"""
analytics/models/buy_signals.py
Pure-math Buy More / Buy Less signal calculator.

No LLM is used here — this is intentional to conserve RAM on the Pi 4.

Definitions
-----------
BUY MORE  (high consumption frequency)
  An item is consumed faster than a reference rate. Triggered when the
  average daily consumption rate exceeds the item's personal baseline
  OR when the estimated days-until-empty drops below BUY_MORE_THRESHOLD_DAYS.

BUY LESS  (high expiration rate)
  An item is expiring before it is consumed. Triggered when more than
  BUY_LESS_EXPIRY_RATIO of recent restocks expired without being used.

Algorithm
---------
Both signals are derived solely from the `usage_logs` Firestore collection.
Each document in `usage_logs` must follow the schema in docs/firestore_schema.md:

  {
    "sku":         str,           # barcode / product SKU
    "item_id":     str,           # Firestore pantryItems doc ID
    "event_type":  "consumed" | "restocked" | "expired",
    "delta":       float,         # quantity change (always positive)
    "timestamp":   datetime (UTC)
  }

Returns
-------
Both public functions return a list of SignalResult dicts:

  {
    "item_id":     str,
    "name":        str,
    "signal":      "BUY_MORE" | "BUY_LESS",
    "reason":      str,           # human-readable explanation
    "score":       float,         # dimensionless urgency score (higher = more urgent)
    "rate_per_day": float | None,
    "days_until_empty": float | None,
    "expiry_ratio": float | None,
  }
"""

import os
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (overridable via environment)
# ---------------------------------------------------------------------------

#: Days-remaining threshold below which a BUY_MORE signal fires.
BUY_MORE_THRESHOLD_DAYS: float = float(os.getenv("BUY_MORE_THRESHOLD_DAYS", "3"))

#: If actual rate > baseline_rate * this multiplier → BUY_MORE.
BUY_MORE_RATE_MULTIPLIER: float = float(os.getenv("BUY_MORE_RATE_MULTIPLIER", "1.5"))

#: Fraction of restocks that expired before use → BUY_LESS signal.
#: e.g. 0.40 means "40 % of restocks expired"
BUY_LESS_EXPIRY_RATIO: float = float(os.getenv("BUY_LESS_EXPIRY_RATIO", "0.40"))

#: Minimum number of log events required for a signal to be computed.
MIN_EVENTS: int = int(os.getenv("SIGNAL_MIN_EVENTS", "3"))

#: Look-back window in days for usage log queries.
LOOKBACK_DAYS: int = int(os.getenv("SIGNAL_LOOKBACK_DAYS", "30"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _consumption_rate(events: list[dict]) -> Optional[float]:
    """
    Compute average daily consumption rate from a list of 'consumed' events.

    Each event must have:
      - quantity_after (float) — stock level after the event
      - timestamp      (datetime)

    Returns units/day, or None if there are fewer than 2 data points.
    """
    consumed = sorted(
        [e for e in events if e.get("event_type") == "consumed"],
        key=lambda e: e["timestamp"],
    )
    if len(consumed) < 2:
        return None

    total_consumed = sum(e.get("delta", 0) for e in consumed)
    span_days = (
        consumed[-1]["timestamp"] - consumed[0]["timestamp"]
    ).total_seconds() / 86_400

    if span_days <= 0:
        return None

    return round(total_consumed / span_days, 4)


def _expiry_ratio(events: list[dict]) -> float:
    """
    Ratio of expired units to restocked units in the event window.

    expired_qty / restocked_qty  (clamped to [0, 1])
    """
    restocked = sum(e.get("delta", 0) for e in events if e.get("event_type") == "restocked")
    expired   = sum(e.get("delta", 0) for e in events if e.get("event_type") == "expired")

    if restocked <= 0:
        return 0.0
    return round(min(expired / restocked, 1.0), 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_buy_signals(
    items: list[dict],
    usage_logs: list[dict],
) -> list[dict]:
    """
    Compute BUY_MORE / BUY_LESS signals for each item.

    Parameters
    ----------
    items : list of pantryItem dicts.
            Each must have keys: id, name, quantity, baseline_rate_per_day (optional).
    usage_logs : list of usage_log dicts scoped to the look-back window.
                 Each must have: item_id, event_type, delta, timestamp.

    Returns
    -------
    list of signal dicts (see module docstring).  Items with insufficient
    data are silently skipped.
    """
    # Group logs by item_id for O(n) grouping instead of O(n * m) scanning
    logs_by_item: dict[str, list[dict]] = defaultdict(list)
    for log in usage_logs:
        logs_by_item[log["item_id"]].append(log)

    signals = []

    for item in items:
        item_id   = item.get("id") or item.get("item_id")
        name      = item.get("name", "Unknown")
        events    = logs_by_item.get(item_id, [])

        if len(events) < MIN_EVENTS:
            logger.debug("[BuySignals] Skipping %s — insufficient events (%d)", name, len(events))
            continue

        current_qty    = float(item.get("quantity", 0))
        baseline_rate  = item.get("baseline_rate_per_day")  # may be None

        rate       = _consumption_rate(events)
        exp_ratio  = _expiry_ratio(events)
        days_left  = round(current_qty / rate, 1) if (rate and rate > 0) else None

        # ── BUY_LESS check ─────────────────────────────────────────────
        if exp_ratio >= BUY_LESS_EXPIRY_RATIO:
            score = round(exp_ratio * 10, 2)  # 0–10 scale
            signals.append({
                "item_id":         item_id,
                "name":            name,
                "signal":          "BUY_LESS",
                "reason": (
                    f"{int(exp_ratio * 100)}% of restocked quantity expired before use "
                    f"(threshold: {int(BUY_LESS_EXPIRY_RATIO * 100)}%)"
                ),
                "score":           score,
                "rate_per_day":    rate,
                "days_until_empty": days_left,
                "expiry_ratio":    exp_ratio,
            })
            continue  # an item cannot be BUY_MORE and BUY_LESS simultaneously

        # ── BUY_MORE check ────────────────────────────────────────────
        buy_more = False
        reason   = ""
        score    = 0.0

        # Condition A: Low days remaining
        if days_left is not None and days_left <= BUY_MORE_THRESHOLD_DAYS:
            buy_more = True
            score    = round((BUY_MORE_THRESHOLD_DAYS - days_left + 1) * 3, 2)
            reason   = (
                f"Only {days_left} day(s) of stock remain "
                f"(threshold: {BUY_MORE_THRESHOLD_DAYS} days)"
            )

        # Condition B: Consumption rate is unusually high vs baseline
        if (
            not buy_more
            and rate is not None
            and baseline_rate is not None
            and rate >= baseline_rate * BUY_MORE_RATE_MULTIPLIER
        ):
            buy_more = True
            multiplier = round(rate / baseline_rate, 2)
            score    = round((multiplier - 1) * 5, 2)
            reason   = (
                f"Consumption rate {rate:.3f} units/day is {multiplier}× "
                f"the baseline {baseline_rate:.3f} units/day "
                f"(threshold: {BUY_MORE_RATE_MULTIPLIER}×)"
            )

        if buy_more:
            signals.append({
                "item_id":          item_id,
                "name":             name,
                "signal":           "BUY_MORE",
                "reason":           reason,
                "score":            score,
                "rate_per_day":     rate,
                "days_until_empty": days_left,
                "expiry_ratio":     exp_ratio,
            })

    # Sort by urgency (highest score first)
    signals.sort(key=lambda s: s["score"], reverse=True)
    return signals
