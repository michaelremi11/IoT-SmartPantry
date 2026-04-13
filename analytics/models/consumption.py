"""
analytics/models/consumption.py
Calculates per-item consumption rates and estimates days-until-empty.
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd


LOW_STOCK_THRESHOLD_DAYS = int(os.getenv("LOW_STOCK_THRESHOLD_DAYS", "3"))


def compute_consumption_rate(history: list[dict]) -> Optional[float]:
    """
    Given a list of inventory update events for a single item, compute the
    average daily consumption rate in `units per day`.

    Each history record must have:
      - `quantity`  (float)  — quantity at that point in time
      - `timestamp` (datetime) — when the record was taken

    Returns None if insufficient data.
    """
    if len(history) < 2:
        return None

    df = pd.DataFrame(history)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp")

    deltas = []
    for i in range(1, len(df)):
        qty_diff = df.iloc[i - 1]["quantity"] - df.iloc[i]["quantity"]
        day_diff = (df.iloc[i]["timestamp"] - df.iloc[i - 1]["timestamp"]).total_seconds() / 86400
        if day_diff > 0 and qty_diff >= 0:
            deltas.append(qty_diff / day_diff)

    if not deltas:
        return None
    return round(sum(deltas) / len(deltas), 4)


def days_until_empty(current_qty: float, rate_per_day: float) -> Optional[float]:
    """Estimate how many days until the item runs out."""
    if rate_per_day is None or rate_per_day <= 0:
        return None
    return round(current_qty / rate_per_day, 1)


def is_buy_soon(days_left: Optional[float]) -> bool:
    """Return True if item needs purchasing within the threshold window."""
    return days_left is not None and days_left <= LOW_STOCK_THRESHOLD_DAYS
