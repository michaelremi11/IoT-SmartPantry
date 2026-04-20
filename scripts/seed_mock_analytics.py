#!/usr/bin/env python3
"""
scripts/seed_mock_analytics.py
Populate Firestore with 30 days of realistic mock usage_log data
to immediately validate the /buy-signals endpoint without needing real scans.

Three test profiles
-------------------
  HIGH_TURNOVER  → triggers BUY_MORE  (rapid consumption, stock almost empty)
  HIGH_WASTE     → triggers BUY_LESS  (most restocked stock expires unused)
  STABLE         → no signal          (steady consumption, low waste, ample stock)

Run from project root:
  python scripts/seed_mock_analytics.py [--dry-run] [--wipe]

Flags:
  --dry-run  : Print documents instead of writing to Firestore
  --wipe     : Delete all existing usage_logs and pantryItems before seeding

Requirements: firebase-admin, python-dotenv
"""

import argparse
import json
import os
import random
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Bootstrap path so we can import hub/analytics modules ─────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------------------------------------------------------------------
# Item profiles
# ---------------------------------------------------------------------------

NOW = datetime.now(timezone.utc)

ITEMS = [
    {
        # ── HIGH TURNOVER ─────────────────────────────────────────────────
        # Used almost every day; stock drops fast; days_until_empty < 3.
        # Expected signal: BUY_MORE (Condition A — low days remaining).
        "id":                 "item_high_turnover",
        "name":               "Oat Milk",
        "sku":                "0000000001",
        "quantity":           1.0,       # nearly empty
        "unit":               "carton",
        "baseline_rate_per_day": 0.3,    # expected rate
        "category":           "dairy-alternative",
        # Event recipe:
        #   Week 1: restocked 6, consumed ~2/day
        #   Week 2: restocked 4, consumed ~2.2/day  ← rate > baseline × 1.5
        #   Week 3: restocked 4, consumed ~2/day
        #   Week 4: restocked 2, consumed rest → nearly empty now
        "_profile": "high_turnover",
    },
    {
        # ── HIGH WASTE ────────────────────────────────────────────────────
        # Frequently restocked but barely used; > 40 % of stock expires.
        # Expected signal: BUY_LESS (expiry_ratio >= 0.40).
        "id":                 "item_high_waste",
        "name":               "Greek Yogurt",
        "sku":                "0000000002",
        "quantity":           3.0,
        "unit":               "tub",
        "baseline_rate_per_day": 0.15,
        "category":           "dairy",
        "_profile": "high_waste",
    },
    {
        # ── STABLE ────────────────────────────────────────────────────────
        # Consumed at a predictable, moderate pace. No signal expected.
        "id":                 "item_stable",
        "name":               "Whole Grain Pasta",
        "sku":                "0000000003",
        "quantity":           4.0,
        "unit":               "pack",
        "baseline_rate_per_day": 0.10,
        "category":           "pasta",
        "_profile": "stable",
    },
]


# ---------------------------------------------------------------------------
# Event generators
# ---------------------------------------------------------------------------

def _ts(days_ago: float, jitter_hours: float = 2.0) -> datetime:
    """Create a UTC timestamp `days_ago` days before NOW, with a small jitter."""
    jitter = timedelta(hours=random.uniform(-jitter_hours, jitter_hours))
    return NOW - timedelta(days=days_ago) + jitter


def _event(item_id: str, sku: str, event_type: str, delta: float,
           quantity_after: float, days_ago: float, notes: str = "") -> dict:
    return {
        "item_id":        item_id,
        "sku":            sku,
        "event_type":     event_type,      # "consumed" | "restocked" | "expired"
        "delta":          round(delta, 2),
        "quantity_after": round(quantity_after, 2),
        "timestamp":      _ts(days_ago),
        "notes":          notes,
    }


def generate_high_turnover_events(item: dict) -> list[dict]:
    """
    High Turnover profile:
    - 4 restocks over 30 days, each 4–6 units
    - Consumption ≈ 2 units/day → rate well above baseline (0.3/day)
    - Result: stock reaches ~1 unit → BUY_MORE (days_until_empty ≈ 1.7)
    """
    events = []
    stock  = 0.0
    iid    = item["id"]
    sku    = item["sku"]

    # Day 30: initial restock +6
    stock += 6
    events.append(_event(iid, sku, "restocked", 6, stock, 30, "weekly shop"))

    # Days 28–22: consume 2/day
    for day in range(28, 21, -1):
        consumed = round(random.uniform(1.8, 2.2), 2)
        stock    = max(0, stock - consumed)
        events.append(_event(iid, sku, "consumed", consumed, stock, day))

    # Day 21: restock +4
    stock += 4
    events.append(_event(iid, sku, "restocked", 4, stock, 21, "top-up"))

    # Days 20–14: consume 2/day — elevated rate
    for day in range(20, 13, -1):
        consumed = round(random.uniform(2.0, 2.5), 2)
        stock    = max(0, stock - consumed)
        events.append(_event(iid, sku, "consumed", consumed, stock, day))

    # Day 14: restock +4
    stock += 4
    events.append(_event(iid, sku, "restocked", 4, stock, 14, "weekly shop"))

    # Days 13–7: consume 2/day
    for day in range(13, 6, -1):
        consumed = round(random.uniform(1.8, 2.2), 2)
        stock    = max(0, stock - consumed)
        events.append(_event(iid, sku, "consumed", consumed, stock, day))

    # Day 7: restock +2 (small top-up)
    stock += 2
    events.append(_event(iid, sku, "restocked", 2, stock, 7, "corner shop"))

    # Days 6–1: consume ~2/day → nearly empty
    for day in range(6, 0, -1):
        consumed = round(min(stock, random.uniform(1.8, 2.2)), 2)
        stock    = max(0, stock - consumed)
        events.append(_event(iid, sku, "consumed", consumed, stock, day))

    return events


def generate_high_waste_events(item: dict) -> list[dict]:
    """
    High Waste profile:
    - 4 restocks over 30 days, each 4–6 units
    - Only ~1 unit actually consumed per week; rest expires
    - `expired_qty / restocked_qty` well above 0.40 → BUY_LESS
    """
    events = []
    stock  = 0.0
    iid    = item["id"]
    sku    = item["sku"]

    schedules = [
        # (days_ago_restock, restock_qty, days_consumed, consumed_per_event, days_ago_expire, expired_qty)
        (30, 5, [29, 27], 0.5, 24, 4.0),
        (23, 5, [22, 20], 0.5, 17, 4.0),
        (16, 4, [15, 13], 0.5, 10, 3.0),
        (9,  4, [8,  6 ], 0.5, 3,  3.0),
    ]

    for restock_day, qty, consume_days, consume_per, expire_day, expire_qty in schedules:
        stock += qty
        events.append(_event(iid, sku, "restocked", qty, stock, restock_day, "weekly shop"))

        for cd in consume_days:
            stock = max(0, stock - consume_per)
            events.append(_event(iid, sku, "consumed", consume_per, stock, cd, "small portion"))

        stock = max(0, stock - expire_qty)
        events.append(_event(iid, sku, "expired", expire_qty, stock, expire_day, "past use-by"))

    return events


def generate_stable_events(item: dict) -> list[dict]:
    """
    Stable profile:
    - Restock every 10 days, ~3 units each time
    - Consume ~0.3/day steady
    - No expiry events
    - No signal expected
    """
    events = []
    stock  = 0.0
    iid    = item["id"]
    sku    = item["sku"]

    for restock_day in [30, 20, 10]:
        stock += 3
        events.append(_event(iid, sku, "restocked", 3, stock, restock_day, "weekly shop"))

        for day in range(restock_day - 1, restock_day - 10, -1):
            consumed = round(random.uniform(0.08, 0.12), 3)
            stock    = max(0, stock - consumed)
            events.append(_event(iid, sku, "consumed", consumed, stock, day))

    return events


# ---------------------------------------------------------------------------
# Event dispatcher
# ---------------------------------------------------------------------------

_GENERATORS = {
    "high_turnover": generate_high_turnover_events,
    "high_waste":    generate_high_waste_events,
    "stable":        generate_stable_events,
}


def generate_all_events() -> dict[str, list[dict]]:
    """Return {item_id: [events]} for all three test profiles."""
    return {
        item["id"]: _GENERATORS[item["_profile"]](item)
        for item in ITEMS
    }


# ---------------------------------------------------------------------------
# Firestore helpers
# ---------------------------------------------------------------------------

def init_firestore():
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./serviceAccountKey.json")
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            "projectId": os.getenv("FIREBASE_PROJECT_ID"),
        })
    return firestore.client()


def wipe_collections(db):
    print("🗑️  Wiping existing usage_logs and test pantryItems…")
    for doc in db.collection("usage_logs").stream():
        doc.reference.delete()
    for item in ITEMS:
        db.collection("pantryItems").document(item["id"]).delete()
    print("   Done.\n")


def seed_pantry_items(db, dry_run: bool):
    print("📦 Seeding pantryItems…")
    for item in ITEMS:
        doc = {k: v for k, v in item.items() if not k.startswith("_")}
        doc["addedAt"]   = NOW - timedelta(days=31)
        doc["updatedAt"] = NOW
        if dry_run:
            print(f"   [DRY RUN] pantryItems/{item['id']}:", json.dumps(doc, default=str, indent=4))
        else:
            db.collection("pantryItems").document(item["id"]).set(doc)
            print(f"   ✅ pantryItems/{item['id']} ({item['name']})")
    print()


def seed_usage_logs(db, events_by_item: dict[str, list[dict]], dry_run: bool):
    print("📊 Seeding usage_logs…")
    total = 0
    for item_id, events in events_by_item.items():
        item_name = next(i["name"] for i in ITEMS if i["id"] == item_id)
        print(f"   [{item_name}] → {len(events)} events")
        for evt in events:
            if dry_run:
                print("   [DRY RUN]", json.dumps(evt, default=str))
            else:
                db.collection("usage_logs").add(evt)
            total += 1
    print(f"\n   Total events written: {total}\n")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(events_by_item: dict[str, list[dict]]):
    print("=" * 60)
    print("SEED SUMMARY — Expected /buy-signals output")
    print("=" * 60)
    for item in ITEMS:
        iid    = item["id"]
        events = events_by_item[iid]
        consumed  = sum(e["delta"] for e in events if e["event_type"] == "consumed")
        restocked = sum(e["delta"] for e in events if e["event_type"] == "restocked")
        expired   = sum(e["delta"] for e in events if e["event_type"] == "expired")
        expiry_ratio = round(expired / restocked, 2) if restocked else 0
        profile  = item["_profile"]

        expected = {
            "high_turnover": "BUY_MORE  ✅",
            "high_waste":    "BUY_LESS  ✅",
            "stable":        "No signal ✅",
        }[profile]

        print(f"\n  [{item['name']}]")
        print(f"    Profile:       {profile}")
        print(f"    Restocked:     {restocked:.1f} units")
        print(f"    Consumed:      {consumed:.1f} units")
        print(f"    Expired:       {expired:.1f} units")
        print(f"    Expiry ratio:  {expiry_ratio:.0%}")
        print(f"    Current stock: {item['quantity']} {item['unit']}")
        print(f"    Expected:      {expected}")
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Seed Firestore with 30-day mock analytics data."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print events without writing to Firestore.")
    parser.add_argument("--wipe", action="store_true",
                        help="Delete existing test data before seeding.")
    args = parser.parse_args()

    random.seed(42)  # deterministic for reproducibility

    print("🌱 Smart Pantry — mock analytics seed script")
    print(f"   Mode: {'DRY RUN' if args.dry_run else 'LIVE WRITE'}")
    print(f"   Target project: {os.getenv('FIREBASE_PROJECT_ID', '(not set)')}\n")

    events_by_item = generate_all_events()
    print_summary(events_by_item)

    if args.dry_run:
        seed_pantry_items(None, dry_run=True)
        seed_usage_logs(None, events_by_item, dry_run=True)
        print("Dry run complete. No data was written.")
        return

    db = init_firestore()

    if args.wipe:
        wipe_collections(db)

    seed_pantry_items(db, dry_run=False)
    seed_usage_logs(db, events_by_item, dry_run=False)

    print("✅ Seeding complete!")
    print("   Test now:  curl http://localhost:8000/buy-signals")


if __name__ == "__main__":
    main()
