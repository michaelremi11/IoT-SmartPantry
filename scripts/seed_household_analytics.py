#!/usr/bin/env python3
"""
Seed realistic household-scoped Firestore data for analytics testing.

This script seeds upstream source collections only:
  - pantryItems
  - usageLogs
  - environmentLogs
  - recipes

It then refreshes worker-owned analytics documents so the current dashboard and
smart shopping plan reflect the seeded source data.

Run from project root:
  python scripts/seed_household_analytics.py --household-id <HOUSEHOLD_ID>

Examples:
  python scripts/seed_household_analytics.py --household-id abc123 --reset
  python scripts/seed_household_analytics.py --household-id abc123 --days 60 --scenario waste-heavy
  python scripts/seed_household_analytics.py --household-id abc123 --dry-run
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from analytics.firebase import get_db
from analytics.services.firebase_analytics import calculate_comfort_score, refresh_analytics_documents


PANTRY_COLLECTION = "pantryItems"
SHOPPING_COLLECTION = "shoppingList"
USAGE_LOGS_COLLECTION = "usageLogs"
ENVIRONMENT_COLLECTION = "environmentLogs"
RECIPES_COLLECTION = "recipes"
RECIPE_REQUESTS_COLLECTION = "recipeRequests"
SMART_PLAN_REQUESTS_COLLECTION = "smartPlanRequests"
ANALYTICS_COLLECTION = "analyticsSummaries"
SMART_PLAN_COLLECTION = "smartShoppingPlans"
HOUSEHOLDS_COLLECTION = "households"

SCENARIOS = ("demo", "waste-heavy", "low-stock")


@dataclass(frozen=True)
class ItemProfile:
    key: str
    name: str
    unit: str
    category: str
    barcode: str
    brand: str
    image_url: str
    profile: str
    baseline_rate_per_day: float
    expiry_days: int | None = None


ITEMS: list[ItemProfile] = [
    ItemProfile(
        key="milk",
        name="Whole Milk",
        unit="fl oz",
        category="liquid",
        barcode="012345678901",
        brand="Great Value",
        image_url="",
        profile="high_turnover",
        baseline_rate_per_day=6.0,
        expiry_days=5,
    ),
    ItemProfile(
        key="eggs",
        name="Eggs",
        unit="unit",
        category="protein",
        barcode="012345678902",
        brand="Happy Farms",
        image_url="",
        profile="high_turnover",
        baseline_rate_per_day=0.9,
        expiry_days=8,
    ),
    ItemProfile(
        key="spinach",
        name="Baby Spinach",
        unit="g",
        category="veg",
        barcode="012345678903",
        brand="Fresh Express",
        image_url="",
        profile="high_waste",
        baseline_rate_per_day=18.0,
        expiry_days=2,
    ),
    ItemProfile(
        key="yogurt",
        name="Greek Yogurt",
        unit="unit",
        category="dairy",
        barcode="012345678904",
        brand="Chobani",
        image_url="",
        profile="high_waste",
        baseline_rate_per_day=0.15,
        expiry_days=1,
    ),
    ItemProfile(
        key="spaghetti",
        name="Barilla Spaghetti",
        unit="oz",
        category="carb",
        barcode="012345678905",
        brand="Barilla",
        image_url="",
        profile="steady",
        baseline_rate_per_day=0.7,
    ),
    ItemProfile(
        key="rotini",
        name="Rotini Pasta",
        unit="oz",
        category="carb",
        barcode="012345678906",
        brand="Great Value",
        image_url="",
        profile="steady",
        baseline_rate_per_day=0.5,
    ),
    ItemProfile(
        key="olive_oil",
        name="Great Value Olive Oil",
        unit="fl oz",
        category="sauce",
        barcode="012345678907",
        brand="Great Value",
        image_url="",
        profile="steady",
        baseline_rate_per_day=0.2,
    ),
    ItemProfile(
        key="tomatoes",
        name="Canned Tomatoes",
        unit="unit",
        category="veg",
        barcode="012345678908",
        brand="Hunt's",
        image_url="",
        profile="steady",
        baseline_rate_per_day=0.1,
    ),
    ItemProfile(
        key="cheddar",
        name="Shredded Cheddar Cheese",
        unit="oz",
        category="dairy",
        barcode="012345678909",
        brand="Sargento",
        image_url="",
        profile="steady",
        baseline_rate_per_day=0.35,
        expiry_days=12,
    ),
    ItemProfile(
        key="broth",
        name="Chicken Broth",
        unit="fl oz",
        category="liquid",
        barcode="012345678910",
        brand="Swanson",
        image_url="",
        profile="high_turnover",
        baseline_rate_per_day=2.0,
        expiry_days=20,
    ),
    ItemProfile(
        key="rice",
        name="White Rice",
        unit="oz",
        category="carb",
        barcode="012345678911",
        brand="Mahatma",
        image_url="",
        profile="steady",
        baseline_rate_per_day=0.4,
    ),
    ItemProfile(
        key="chicken",
        name="Chicken Breast",
        unit="unit",
        category="protein",
        barcode="012345678912",
        brand="Tyson",
        image_url="",
        profile="steady",
        baseline_rate_per_day=0.12,
        expiry_days=3,
    ),
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def slugify(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


def pantry_doc_id(household_id: str, item: ItemProfile) -> str:
    return f"seed_{slugify(household_id)}_{item.key}"


def recipe_doc_id(household_id: str, key: str) -> str:
    return f"seed_recipe_{slugify(household_id)}_{key}"


def make_timestamp(days_ago: float, rng: random.Random, jitter_hours: float = 4.0) -> datetime:
    jitter = timedelta(hours=rng.uniform(-jitter_hours, jitter_hours))
    return utc_now() - timedelta(days=days_ago) + jitter


def quantity_for_profile(item: ItemProfile, profile: str, scenario: str, rng: random.Random) -> tuple[float, list[dict[str, Any]]]:
    stock = 0.0
    events: list[dict[str, Any]] = []

    def restock(days_ago: float, delta: float, note: str) -> None:
        nonlocal stock
        stock += delta
        events.append(
            {
                "event_type": "restocked",
                "action_type": "restocked",
                "delta": round(delta, 3),
                "quantity_changed": round(delta, 3),
                "quantity_after": round(stock, 3),
                "timestamp": make_timestamp(days_ago, rng),
                "notes": note,
            }
        )

    def consume(days_ago: float, delta: float, note: str) -> None:
        nonlocal stock
        actual = min(stock, delta)
        if actual <= 0:
            return
        stock -= actual
        events.append(
            {
                "event_type": "consumed",
                "action_type": "cooked",
                "delta": round(actual, 3),
                "quantity_changed": round(actual, 3),
                "quantity_after": round(stock, 3),
                "timestamp": make_timestamp(days_ago, rng),
                "notes": note,
            }
        )

    def expire(days_ago: float, delta: float, note: str) -> None:
        nonlocal stock
        actual = min(stock, delta)
        if actual <= 0:
            return
        stock -= actual
        events.append(
            {
                "event_type": "expired",
                "action_type": "discarded",
                "delta": round(actual, 3),
                "quantity_changed": round(actual, 3),
                "quantity_after": round(stock, 3),
                "timestamp": make_timestamp(days_ago, rng),
                "notes": note,
            }
        )

    if profile == "high_turnover":
        scenario_multiplier = 1.0
        if scenario == "low-stock":
            scenario_multiplier = 1.35
        elif scenario == "waste-heavy":
            scenario_multiplier = 0.9

        cycle_length = 7
        restock_floor = {
            "fl oz": 12.0,
            "unit": 4.0,
            "oz": 8.0,
            "g": 100.0,
        }.get(item.unit, 6.0)
        restock_size = max(item.baseline_rate_per_day * 6.0, restock_floor)

        cycle_starts = [42, 35, 28, 21, 14, 7]
        for cycle_start in cycle_starts:
            restock(cycle_start, restock_size * rng.uniform(0.85, 1.05), "weekly restock")
            consume_points = [cycle_start - 5, cycle_start - 3, cycle_start - 1]
            avg_portion = (item.baseline_rate_per_day * cycle_length / len(consume_points)) * scenario_multiplier
            for consume_day in consume_points:
                consume(consume_day, avg_portion * rng.uniform(0.85, 1.15), "used in meals")

        if scenario == "low-stock":
            consume(0.6, max(0.25, item.baseline_rate_per_day * 1.2), "used at the end of the week")
        else:
            consume(1.2, max(0.2, item.baseline_rate_per_day * 0.7), "recent use")

    elif profile == "high_waste":
        waste_multiplier = 1.0 if scenario != "waste-heavy" else 1.35
        cycle_length = 8
        restock_floor = {"g": 100.0, "unit": 2.0}.get(item.unit, 3.0)
        base_restock = max(item.baseline_rate_per_day * 8.0, restock_floor)
        cycle_starts = [40, 32, 24, 16, 8]
        for cycle_start in cycle_starts:
            restock(cycle_start, base_restock * rng.uniform(0.9, 1.1), "weekly restock")
            consume(cycle_start - 5, max(0.15, item.baseline_rate_per_day * cycle_length * 0.35), "small use")
            expire(cycle_start - 1, base_restock * 0.78 * waste_multiplier, "expired before use")

    else:
        scenario_multiplier = 1.0 if scenario != "low-stock" else 1.15
        cycle_length = 10
        restock_floor = {
            "fl oz": 6.0,
            "unit": 2.0,
            "oz": 4.0,
            "g": 60.0,
        }.get(item.unit, 3.0)
        base_restock = max(item.baseline_rate_per_day * cycle_length * 1.15, restock_floor)
        cycle_starts = [40, 30, 20, 10]
        for cycle_start in cycle_starts:
            restock(cycle_start, base_restock * rng.uniform(0.9, 1.1), "regular grocery trip")
            consume_points = [cycle_start - 7, cycle_start - 4, cycle_start - 1]
            avg_portion = (item.baseline_rate_per_day * cycle_length / len(consume_points)) * scenario_multiplier
            for consume_day in consume_points:
                consume(consume_day, avg_portion * rng.uniform(0.85, 1.15), "normal use")

    events.sort(key=lambda event: event["timestamp"])
    return round(max(stock, 0.0), 3), events


def expiry_date_for_item(item: ItemProfile) -> str | None:
    if item.expiry_days is None:
        return None
    return (utc_now().date() + timedelta(days=item.expiry_days)).isoformat()


def trim_events_to_days(events: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    cutoff = utc_now() - timedelta(days=max(days, 1))
    filtered = [event for event in events if event["timestamp"] >= cutoff]
    return filtered or events


def seed_pantry_and_usage(
    household_id: str,
    scenario: str,
    seed: int,
    days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(seed)
    pantry_docs: list[dict[str, Any]] = []
    usage_logs: list[dict[str, Any]] = []

    for index, item in enumerate(ITEMS):
        item_seed = seed + index * 17
        final_qty, events = quantity_for_profile(item, item.profile, scenario, random.Random(item_seed))
        events = trim_events_to_days(events, days)
        doc_id = pantry_doc_id(household_id, item)
        pantry_docs.append(
            {
                "id": doc_id,
                "householdId": household_id,
                "name": item.name,
                "barcode": item.barcode,
                "quantity": final_qty,
                "amount": final_qty,
                "unit": item.unit,
                "category": item.category,
                "brand": item.brand,
                "image_url": item.image_url,
                "expiryDate": expiry_date_for_item(item),
                "in_stock": final_qty > 0,
                "source": "analytics-seed",
                "baseline_rate_per_day": item.baseline_rate_per_day,
                "addedAt": make_timestamp(min(max(days, 7), 45), rng),
                "updatedAt": utc_now(),
            }
        )

        for event in events:
            usage_logs.append(
                {
                    "householdId": household_id,
                    "item_id": doc_id,
                    "item_name": item.name,
                    "sku": item.barcode,
                    "source": "analytics-seed",
                    **event,
                }
            )

    usage_logs.sort(key=lambda event: event["timestamp"])
    return pantry_docs, usage_logs


def build_environment_logs(household_id: str, device_id: str, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    now = utc_now()
    docs: list[dict[str, Any]] = []
    for index in range(16):
        hours_ago = 45 - (index * 3)
        temp = 20.5 + rng.uniform(-1.3, 2.0)
        humidity = 43.0 + rng.uniform(-8.0, 12.0)
        if index >= 13:
            temp = 30.5 + rng.uniform(-0.2, 1.0)
            humidity = 82.0 + rng.uniform(-1.5, 3.5)
        if index == 15:
            temp = 31.2
            humidity = 84.5

        docs.append(
            {
                "id": f"seed_env_{slugify(household_id)}_{index:02d}",
                "householdId": household_id,
                "deviceId": device_id,
                "temperatureC": round(temp, 2),
                "humidityPercent": round(humidity, 2),
                "comfort_score": calculate_comfort_score(temp, humidity),
                "timestamp": now - timedelta(hours=hours_ago),
            }
        )
    return docs


def ingredient(
    name: str,
    amount: float,
    unit: str,
    canonical: str | None = None,
    family: str | None = None,
    group: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "amount": amount,
        "unit": unit,
        "canonical": canonical or name.lower(),
        "family": family,
        "group": group,
        "display": f"{amount:g} {unit} {name}",
    }


def build_recipes(household_id: str) -> list[dict[str, Any]]:
    now = utc_now()
    return [
        {
            "id": recipe_doc_id(household_id, "creamy_chicken_spaghetti"),
            "householdId": household_id,
            "title": "Creamy Chicken Spaghetti",
            "ingredients": [
                ingredient("chicken breast", 1, "unit", family="protein"),
                ingredient("spaghetti", 8, "oz", family="pasta", group="long_pasta"),
                ingredient("milk", 1, "cup", family="milk", group="dairy_milk"),
                ingredient("cheddar cheese", 4, "oz"),
                ingredient("olive oil", 1, "tbsp", family="oil", group="olive_oil"),
                ingredient("garlic", 2, "cloves"),
            ],
            "instructions": "Cook the chicken and pasta, then stir everything together with milk and cheese.",
            "source": "seeded-demo",
            "estimated_time": "25 minutes",
            "created_at": now,
        },
        {
            "id": recipe_doc_id(household_id, "tomato_rotini_bake"),
            "householdId": household_id,
            "title": "Tomato Rotini Bake",
            "ingredients": [
                ingredient("rotini pasta", 8, "oz", family="pasta", group="shaped_pasta"),
                ingredient("canned tomatoes", 1, "unit"),
                ingredient("cheddar cheese", 3, "oz"),
                ingredient("olive oil", 1, "tbsp", family="oil", group="olive_oil"),
                ingredient("onion", 1, "unit"),
            ],
            "instructions": "Boil the pasta, simmer the tomatoes, then bake with cheese until bubbly.",
            "source": "seeded-demo",
            "estimated_time": "30 minutes",
            "created_at": now,
        },
        {
            "id": recipe_doc_id(household_id, "spinach_rice_bowl"),
            "householdId": household_id,
            "title": "Spinach Rice Bowl",
            "ingredients": [
                ingredient("white rice", 8, "oz"),
                ingredient("chicken broth", 2, "cup"),
                ingredient("baby spinach", 60, "g"),
                ingredient("olive oil", 1, "tbsp", family="oil", group="olive_oil"),
            ],
            "instructions": "Cook the rice in broth, wilt in the spinach, and finish with olive oil.",
            "source": "seeded-demo",
            "estimated_time": "20 minutes",
            "created_at": now,
        },
        {
            "id": recipe_doc_id(household_id, "breakfast_scramble"),
            "householdId": household_id,
            "title": "Breakfast Scramble",
            "ingredients": [
                ingredient("eggs", 3, "unit"),
                ingredient("milk", 0.25, "cup", family="milk", group="dairy_milk"),
                ingredient("cheddar cheese", 2, "oz"),
                ingredient("baby spinach", 30, "g"),
            ],
            "instructions": "Whisk the eggs and milk, cook gently, then fold in cheese and spinach.",
            "source": "seeded-demo",
            "estimated_time": "12 minutes",
            "created_at": now,
        },
        {
            "id": recipe_doc_id(household_id, "pantry_pasta_primavera"),
            "householdId": household_id,
            "title": "Pantry Pasta Primavera",
            "ingredients": [
                ingredient("rotini pasta", 8, "oz", family="pasta", group="shaped_pasta"),
                ingredient("canned tomatoes", 1, "unit"),
                ingredient("olive oil", 1, "tbsp", family="oil", group="olive_oil"),
                ingredient("bell pepper", 1, "unit"),
                ingredient("onion", 1, "unit"),
            ],
            "instructions": "Cook the pasta, saute the vegetables, and toss with tomatoes and olive oil.",
            "source": "seeded-demo",
            "estimated_time": "28 minutes",
            "created_at": now,
        },
    ]


def chunked(seq: list[Any], size: int) -> list[list[Any]]:
    return [seq[index : index + size] for index in range(0, len(seq), size)]


def delete_household_docs(db, collection_name: str, household_id: str) -> int:
    deleted = 0
    docs = list(db.collection(collection_name).where("householdId", "==", household_id).stream())
    for group in chunked(docs, 400):
        batch = db.batch()
        for doc in group:
            batch.delete(doc.reference)
            deleted += 1
        batch.commit()
    return deleted


def delete_by_id_prefix(db, collection_name: str, doc_ids: list[str]) -> int:
    deleted = 0
    for group in chunked(doc_ids, 400):
        batch = db.batch()
        for doc_id in group:
            batch.delete(db.collection(collection_name).document(doc_id))
            deleted += 1
        batch.commit()
    return deleted


def ensure_household_exists(db, household_id: str) -> None:
    snap = db.collection(HOUSEHOLDS_COLLECTION).document(household_id).get()
    if not snap.exists:
        raise SystemExit(
            f"Household '{household_id}' does not exist. Create an account first or use a real householdId."
        )


def reset_household_seed_data(db, household_id: str) -> dict[str, int]:
    summary = {
        PANTRY_COLLECTION: delete_household_docs(db, PANTRY_COLLECTION, household_id),
        SHOPPING_COLLECTION: delete_household_docs(db, SHOPPING_COLLECTION, household_id),
        USAGE_LOGS_COLLECTION: delete_household_docs(db, USAGE_LOGS_COLLECTION, household_id),
        ENVIRONMENT_COLLECTION: delete_household_docs(db, ENVIRONMENT_COLLECTION, household_id),
        RECIPES_COLLECTION: delete_household_docs(db, RECIPES_COLLECTION, household_id),
        RECIPE_REQUESTS_COLLECTION: delete_household_docs(db, RECIPE_REQUESTS_COLLECTION, household_id),
        SMART_PLAN_REQUESTS_COLLECTION: delete_household_docs(db, SMART_PLAN_REQUESTS_COLLECTION, household_id),
        ANALYTICS_COLLECTION: delete_household_docs(db, ANALYTICS_COLLECTION, household_id),
        SMART_PLAN_COLLECTION: delete_household_docs(db, SMART_PLAN_COLLECTION, household_id),
    }
    summary[f"{ANALYTICS_COLLECTION}_well_known"] = delete_by_id_prefix(
        db,
        ANALYTICS_COLLECTION,
        [
            f"{household_id}_sustainability",
            f"{household_id}_wasteReport",
            f"{household_id}_historicalSustainability",
            f"{household_id}_popularCategories",
            f"{household_id}_missions",
            f"{household_id}_liveStatus",
            f"{household_id}_liveTrend",
            f"{household_id}_risk",
            f"{household_id}_recipeUnlocks",
            f"{household_id}_buySignals",
        ],
    )
    summary[f"{SMART_PLAN_COLLECTION}_current"] = delete_by_id_prefix(
        db,
        SMART_PLAN_COLLECTION,
        [f"{household_id}_current"],
    )
    return summary


def commit_documents(db, collection_name: str, docs: list[dict[str, Any]]) -> int:
    written = 0
    for group in chunked(docs, 400):
        batch = db.batch()
        for doc_data in group:
            payload = dict(doc_data)
            doc_id = payload.pop("id")
            batch.set(db.collection(collection_name).document(doc_id), payload)
            written += 1
        batch.commit()
    return written


def commit_add_documents(db, collection_name: str, docs: list[dict[str, Any]]) -> int:
    written = 0
    for group in chunked(docs, 200):
        batch = db.batch()
        for payload in group:
            batch.set(db.collection(collection_name).document(), payload)
            written += 1
        batch.commit()
    return written


def print_plan(
    household_id: str,
    pantry_docs: list[dict[str, Any]],
    usage_logs: list[dict[str, Any]],
    environment_logs: list[dict[str, Any]],
    recipes: list[dict[str, Any]],
    scenario: str,
    days: int,
    dry_run: bool,
) -> None:
    print("🌱 Smart Pantry analytics seed")
    print(f"   Household: {household_id}")
    print(f"   Scenario:  {scenario}")
    print(f"   Window:    {days} days")
    print(f"   Mode:      {'DRY RUN' if dry_run else 'LIVE WRITE'}")
    print(f"   Pantry:    {len(pantry_docs)} items")
    print(f"   Usage:     {len(usage_logs)} usage log events")
    print(f"   Sensors:   {len(environment_logs)} environment logs")
    print(f"   Recipes:   {len(recipes)} recipes")
    print()

    for item in pantry_docs[:5]:
        expiry = item.get("expiryDate") or "none"
        print(f"   - {item['name']}: {item['quantity']} {item['unit']} (expires {expiry})")
    if len(pantry_docs) > 5:
        print(f"   ... and {len(pantry_docs) - 5} more pantry items")
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed household-scoped Firestore data for Smart Pantry analytics."
    )
    parser.add_argument(
        "--household-id",
        required=True,
        help="Existing householdId to seed.",
    )
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="demo",
        help="Seed profile to generate.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=45,
        help="How many trailing days of generated usage history to keep.",
    )
    parser.add_argument(
        "--device-id",
        default="hub-rpi4-001",
        help="Device ID to attach to seeded environment logs.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic output.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete only this household's seeded app data before writing new data.",
    )
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Write source collections but do not rebuild analytics summaries afterward.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without writing anything to Firestore.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    household_id = args.household_id.strip()
    if not household_id:
        raise SystemExit("--household-id is required.")

    pantry_docs, usage_logs = seed_pantry_and_usage(household_id, args.scenario, args.seed, args.days)
    environment_logs = build_environment_logs(household_id, args.device_id, args.seed + 900)
    recipes = build_recipes(household_id)

    print_plan(
        household_id,
        pantry_docs,
        usage_logs,
        environment_logs,
        recipes,
        args.scenario,
        args.days,
        args.dry_run,
    )

    if args.dry_run:
        print("Dry run complete. No data was written.")
        return

    db = get_db()
    ensure_household_exists(db, household_id)

    if args.reset:
        print("🧹 Resetting this household's existing app data...")
        reset_summary = reset_household_seed_data(db, household_id)
        for collection_name, count in reset_summary.items():
            print(f"   {collection_name}: {count}")
        print()

    print("📦 Writing pantryItems...")
    pantry_count = commit_documents(db, PANTRY_COLLECTION, pantry_docs)
    print(f"   Wrote {pantry_count} pantry items")

    print("📊 Writing usageLogs...")
    usage_count = commit_add_documents(db, USAGE_LOGS_COLLECTION, usage_logs)
    print(f"   Wrote {usage_count} usage log events")

    print("🌡️  Writing environmentLogs...")
    env_count = commit_documents(db, ENVIRONMENT_COLLECTION, environment_logs)
    print(f"   Wrote {env_count} environment logs")

    print("🍽️  Writing recipes...")
    recipe_count = commit_documents(db, RECIPES_COLLECTION, recipes)
    print(f"   Wrote {recipe_count} recipes")

    if not args.skip_refresh:
        print("🧠 Refreshing analytics summaries and smart shopping plan...")
        refresh_analytics_documents(db, household_id)
        print("   Analytics refresh complete")
    else:
        print("⏭️  Skipped analytics refresh by request")

    print()
    print("✅ Seed complete")
    print("   Open the web app for this household and check:")
    print("   - inventory analytics tabs")
    print("   - sustainability / waste report")
    print("   - buy signals")
    print("   - smart shopping plan")


if __name__ == "__main__":
    main()
