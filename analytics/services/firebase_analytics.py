"""
Firebase-backed analytics for Smart Pantry.

This module is the shared source of server-side "heavy lifting" now that
clients read and write normal app state directly in Firestore.  The FastAPI
routes call these functions for diagnostics, and the background worker writes
their results back to Firestore for web/mobile clients to subscribe to.
"""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from analytics.models import check_environment, compute_buy_signals


PANTRY_COLLECTION = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
USAGE_LOGS_COLLECTION = os.getenv("FIRESTORE_USAGE_LOGS_COLLECTION", "usageLogs")
ENVIRONMENT_COLLECTION = os.getenv("FIRESTORE_LOGS_COLLECTION", "environmentLogs")
RECIPES_COLLECTION = os.getenv("FIRESTORE_RECIPES_COLLECTION", "recipes")
ANALYTICS_COLLECTION = os.getenv("FIRESTORE_ANALYTICS_SUMMARIES_COLLECTION", "analyticsSummaries")
SMART_PLAN_COLLECTION = os.getenv("FIRESTORE_SMART_PLAN_COLLECTION", "smartShoppingPlans")
HOUSEHOLDS_COLLECTION = os.getenv("FIRESTORE_HOUSEHOLDS_COLLECTION", "households")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _date_key(value: Any) -> str:
    ts = _to_datetime(value) or utc_now()
    return ts.date().isoformat()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _usage_value(log: dict, default: float = 1.0) -> float:
    """Prefer true quantity deltas over legacy count-style `quantity_changed` values."""
    delta = _number(log.get("delta"), default)
    quantity_changed = _number(log.get("quantity_changed"), default)
    if delta > 0:
        return delta
    return quantity_changed


def _expiry_days(expiry: Any) -> Optional[int]:
    if not expiry:
        return None
    if isinstance(expiry, datetime):
        exp_dt = expiry.astimezone(timezone.utc)
    else:
        try:
            exp_dt = datetime.strptime(str(expiry), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return (exp_dt.date() - utc_now().date()).days


def get_household_ids(db) -> list[str]:
    ids = [doc.id for doc in db.collection(HOUSEHOLDS_COLLECTION).stream() if doc.id]
    return sorted(set(ids))


def get_pantry_items(db, household_id: str | None = None) -> list[dict]:
    items = []
    query = db.collection(PANTRY_COLLECTION)
    if household_id:
        query = query.where("householdId", "==", household_id)
    for doc in query.stream():
        data = doc.to_dict() or {}
        qty = _number(data.get("quantity", data.get("amount", 0)))
        data.update(
            {
                "id": doc.id,
                "quantity": qty,
                "amount": _number(data.get("amount", qty)),
                "unit": data.get("unit", "unit"),
                "name": data.get("name", "Unknown"),
                "category": data.get("category", "misc") or "misc",
                "in_stock": data.get("in_stock", qty > 0),
            }
        )
        items.append(data)
    return items


def get_usage_logs(db, days: int = 30, household_id: str | None = None) -> list[dict]:
    since = utc_now() - timedelta(days=days)
    logs = []
    query = db.collection(USAGE_LOGS_COLLECTION)
    if household_id:
        query = query.where("householdId", "==", household_id)
    for doc in query.stream():
        data = doc.to_dict() or {}
        ts = _to_datetime(data.get("timestamp"))
        if ts is None or ts < since:
            continue
        data["id"] = doc.id
        data["timestamp"] = ts
        logs.append(data)
    logs.sort(key=lambda item: item["timestamp"])
    return logs


def get_item_quantity_history(db, item_id: str, days: int = 30, household_id: str | None = None) -> list[dict]:
    history = []
    for log in get_usage_logs(db, days=days, household_id=household_id):
        current_item_id = log.get("item_id") or log.get("itemId")
        if current_item_id != item_id:
            continue
        quantity_after = log.get("quantity_after")
        if quantity_after is None:
            continue
        history.append(
            {
                "quantity": _number(quantity_after),
                "timestamp": log["timestamp"],
            }
        )
    return history


def get_environment_logs(
    db,
    hours: int = 24,
    device_id: Optional[str] = None,
    household_id: str | None = None,
) -> list[dict]:
    since = utc_now() - timedelta(hours=hours)
    logs = []
    query = db.collection(ENVIRONMENT_COLLECTION)
    if household_id:
        query = query.where("householdId", "==", household_id)
    for doc in query.stream():
        data = doc.to_dict() or {}
        ts = _to_datetime(data.get("timestamp"))
        if ts is None or ts < since:
            continue
        if device_id and data.get("deviceId") != device_id:
            continue
        data["id"] = doc.id
        data["timestamp"] = ts
        logs.append(data)
    logs.sort(key=lambda item: item["timestamp"], reverse=True)
    return logs


def calculate_comfort_score(temp: float, humidity: float) -> int:
    temp_score = max(0, min(100, 100 - abs(temp - 21.0) * 10))
    hum_score = max(0, min(100, 100 - abs(humidity - 45.0) * 3.33))
    return int((temp_score * 0.6) + (hum_score * 0.4))


def get_sensor_time_series(
    db,
    hours: int = 24,
    device_id: str = "hub-rpi4-001",
    household_id: str | None = None,
) -> list[dict]:
    return [
        {
            "time": item["timestamp"].isoformat(),
            "temperature": item.get("temperatureC"),
            "humidity": item.get("humidityPercent"),
            "gyro_x": item.get("gyro_x", 0.0),
            "gyro_y": item.get("gyro_y", 0.0),
            "gyro_z": item.get("gyro_z", 0.0),
            "comfort_score": item.get("comfort_score"),
        }
        for item in get_environment_logs(db, hours=hours, device_id=device_id, household_id=household_id)
    ]


def get_sustainability_score(db, household_id: str | None = None) -> dict:
    cooked = 0.0
    discarded = 0.0
    for log in get_usage_logs(db, days=30, household_id=household_id):
        action = log.get("action_type")
        event_type = log.get("event_type")
        value = _usage_value(log, 1.0)
        if action == "cooked" or event_type == "consumed":
            cooked += value
        elif action == "discarded" or event_type in {"expired", "discarded"}:
            discarded += value

    total = cooked + discarded
    score = int((cooked / total) * 100) if total > 0 else 100
    return {
        "cooked_count": cooked,
        "discarded_count": discarded,
        "total_actions": total,
        "sustainability_score": score,
    }


def get_live_status(db, device_id: str = "hub-rpi4-001", household_id: str | None = None) -> dict:
    logs = get_environment_logs(db, hours=24, device_id=device_id, household_id=household_id)
    if not logs:
        return {"status": "empty", "data": []}
    latest = logs[0]
    temp = _number(latest.get("temperatureC"))
    humidity = _number(latest.get("humidityPercent"))
    return {
        "status": "ok",
        "deviceId": latest.get("deviceId", device_id),
        "time": latest["timestamp"].isoformat(),
        "temperature": temp,
        "humidity": humidity,
        "comfort_score": latest.get("comfort_score", calculate_comfort_score(temp, humidity)),
    }


def get_trending_bounds(db, device_id: str = "hub-rpi4-001", household_id: str | None = None) -> dict:
    logs = list(reversed(get_environment_logs(db, hours=1, device_id=device_id, household_id=household_id)))
    if len(logs) < 2:
        return {"status": "empty", "trend": "Not enough data yet"}
    first = logs[0]
    latest = logs[-1]
    temp_delta = _number(latest.get("temperatureC")) - _number(first.get("temperatureC"))
    hum_delta = _number(latest.get("humidityPercent")) - _number(first.get("humidityPercent"))
    if abs(temp_delta) < 0.5 and abs(hum_delta) < 2:
        trend = "Stable over the last hour"
    else:
        trend = f"Temp {temp_delta:+.1f}C, humidity {hum_delta:+.1f}% in the last hour"
    return {
        "status": "ok",
        "trend": trend,
        "temperature_delta": round(temp_delta, 2),
        "humidity_delta": round(hum_delta, 2),
    }


def get_environmental_risk(db, device_id: str = "hub-rpi4-001", household_id: str | None = None) -> dict:
    logs = get_environment_logs(db, hours=1, device_id=device_id, household_id=household_id)
    if not logs:
        return {"status": "empty", "high_risk_active": False}
    latest = logs[0]
    humidity = _number(latest.get("humidityPercent"))
    temp = _number(latest.get("temperatureC"))
    flags = check_environment(temp, humidity)
    recent_humidity = [_number(log.get("humidityPercent")) for log in logs[:5]]
    high_risk = bool(flags) or humidity >= 60
    return {
        "status": "ok",
        "high_risk_active": high_risk,
        "temperature": temp,
        "humidity": humidity,
        "min_humidity_5m": min(recent_humidity) if recent_humidity else humidity,
        "anomalies": flags,
    }


def get_waste_report(db, household_id: str | None = None) -> dict:
    item_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"cooked": 0.0, "discarded": 0.0})
    name_map = {item["id"]: item["name"] for item in get_pantry_items(db, household_id=household_id)}
    for log in get_usage_logs(db, days=30, household_id=household_id):
        item_id = log.get("item_id") or log.get("itemId") or "unknown"
        action = log.get("action_type")
        event_type = log.get("event_type")
        value = _usage_value(log, 1.0)
        if action == "cooked" or event_type == "consumed":
            item_stats[item_id]["cooked"] += value
        elif action == "discarded" or event_type in {"expired", "discarded"}:
            item_stats[item_id]["discarded"] += value
        if log.get("item_name"):
            name_map[item_id] = log["item_name"]

    report = []
    for item_id, stats in item_stats.items():
        total = stats["cooked"] + stats["discarded"]
        waste_rate = (stats["discarded"] / total) * 100 if total > 0 else 0
        report.append(
            {
                "item_id": name_map.get(item_id, item_id),
                "raw_item_id": item_id,
                "cooked": stats["cooked"],
                "discarded": stats["discarded"],
                "waste_rate": round(waste_rate, 2),
                "suggestion": "Buy Less" if waste_rate > 30 else "Good",
            }
        )
    report.sort(key=lambda item: item["waste_rate"], reverse=True)
    return {"waste_report": report}


def get_historical_sustainability(db, household_id: str | None = None) -> dict:
    daily: dict[str, dict[str, float]] = defaultdict(lambda: {"cooked": 0.0, "discarded": 0.0})
    for log in get_usage_logs(db, days=7, household_id=household_id):
        key = _date_key(log.get("timestamp"))
        action = log.get("action_type")
        event_type = log.get("event_type")
        value = _usage_value(log, 1.0)
        if action == "cooked" or event_type == "consumed":
            daily[key]["cooked"] += value
        elif action == "discarded" or event_type in {"expired", "discarded"}:
            daily[key]["discarded"] += value

    trend = []
    for key in sorted(daily):
        cooked = daily[key]["cooked"]
        discarded = daily[key]["discarded"]
        total = cooked + discarded
        trend.append({"date": key, "score": int((cooked / total) * 100) if total else 100})
    return {"trend": trend}


def get_popular_categories(db, household_id: str | None = None) -> dict:
    counts = Counter((item.get("category") or "misc").lower() for item in get_pantry_items(db, household_id=household_id))
    categories = [{"category": key, "count": value} for key, value in counts.most_common()]
    return {"categories": categories}


def get_recipe_unlocks(db, household_id: str | None = None) -> dict:
    pantry_names = [item["name"].lower() for item in get_pantry_items(db, household_id=household_id) if item.get("name")]
    missing_counter: Counter[str] = Counter()
    query = db.collection(RECIPES_COLLECTION)
    if household_id:
        query = query.where("householdId", "==", household_id)
    for doc in query.stream():
        recipe = doc.to_dict() or {}
        missing_here = []
        for ingredient in recipe.get("ingredients", []):
            if isinstance(ingredient, dict):
                ingredient_text = str(
                    ingredient.get("item")
                    or ingredient.get("name")
                    or ingredient.get("display")
                    or ""
                ).strip()
            else:
                ingredient_text = str(ingredient)
            ingredient_lower = ingredient_text.lower()
            matched = any(
                pantry_name in ingredient_lower or ingredient_lower in pantry_name
                for pantry_name in pantry_names
            )
            if matched:
                continue
            words = ingredient_text.split()
            clean_name = " ".join(words[-2:]) if len(words) > 1 else ingredient_text
            missing_here.append(clean_name.lower())
        if 1 <= len(missing_here) <= 2:
            missing_counter.update(missing_here)

    return {
        "high_impact_purchases": [
            {"ingredient": key, "unlocks": value}
            for key, value in missing_counter.most_common(3)
        ]
    }


def get_smart_shopping_plan(db, household_id: str | None = None) -> dict:
    items = get_pantry_items(db, household_id=household_id)
    staples = []
    at_risk = []
    buy_more_signals = [signal for signal in get_buy_signals(db, household_id=household_id) if signal.get("signal") == "BUY_MORE"]
    seen_staples: set[str] = set()

    for signal in buy_more_signals:
        name = str(signal.get("name", "")).strip()
        if not name:
            continue
        key = name.lower()
        if key in seen_staples:
            continue
        staples.append({"item": name, "reason": signal.get("reason", "Running low soon")})
        seen_staples.add(key)

    for item in items:
        if _number(item.get("quantity")) <= 0:
            key = item["name"].lower()
            if key not in seen_staples:
                staples.append({"item": item["name"], "reason": "Out of stock"})
                seen_staples.add(key)
        days = _expiry_days(item.get("expiryDate") or item.get("expiry_date"))
        if days is not None and 0 <= days <= 3:
            at_risk.append({"item": item["name"], "reason": f"Expires in {days} days"})

    if not staples:
        for item in sorted(items, key=lambda pantry_item: _number(pantry_item.get("quantity"), 0.0)):
            if item["name"].lower() in seen_staples:
                continue
            staples.append({"item": item["name"], "reason": "Lowest stock in pantry right now"})
            if len(staples) == 3:
                break

    unlock_doc = get_recipe_unlocks(db, household_id=household_id)
    unlocks = [
        {"item": entry["ingredient"].title(), "reason": f"Unlocks {entry['unlocks']} recipes"}
        for entry in unlock_doc["high_impact_purchases"]
    ]

    return {
        "staples": staples[:5],
        "unlocks": unlocks[:5],
        "waste_prevention": at_risk[:5],
    }


def get_buy_signals(db, days: int = 30, household_id: str | None = None) -> list[dict]:
    return compute_buy_signals(
        get_pantry_items(db, household_id=household_id),
        get_usage_logs(db, days=days, household_id=household_id),
    )


def get_missions(db, household_id: str | None = None) -> dict:
    score = get_sustainability_score(db, household_id=household_id)["sustainability_score"]
    risk = get_environmental_risk(db, household_id=household_id)
    missions = []
    if score < 80:
        missions.append("Cook at least two pantry items before discarding anything this week.")
    else:
        missions.append("Keep the current low-waste streak going for another week.")
    if risk.get("high_risk_active"):
        missions.append("Prioritize bread, leafy greens, and soft produce while humidity is high.")
    else:
        missions.append("Use the oldest expiring item in one meal before the weekend.")
    missions.append("Add one high-impact missing ingredient that unlocks multiple recipes.")
    return {"missions": missions[:3]}


def refresh_analytics_documents(db, household_id: str) -> dict:
    """Compute current analytics and write client-readable summary documents."""
    now = utc_now()
    docs = {
        "sustainability": get_sustainability_score(db, household_id=household_id),
        "wasteReport": get_waste_report(db, household_id=household_id),
        "historicalSustainability": get_historical_sustainability(db, household_id=household_id),
        "popularCategories": get_popular_categories(db, household_id=household_id),
        "missions": get_missions(db, household_id=household_id),
        "liveStatus": get_live_status(db, household_id=household_id),
        "liveTrend": get_trending_bounds(db, household_id=household_id),
        "risk": get_environmental_risk(db, household_id=household_id),
        "recipeUnlocks": get_recipe_unlocks(db, household_id=household_id),
        "buySignals": {"signals": get_buy_signals(db, household_id=household_id)},
    }
    for doc_id, payload in docs.items():
        db.collection(ANALYTICS_COLLECTION).document(f"{household_id}_{doc_id}").set(
            {**payload, "updatedAt": now, "householdId": household_id},
            merge=True,
        )

    plan = get_smart_shopping_plan(db, household_id=household_id)
    db.collection(SMART_PLAN_COLLECTION).document(f"{household_id}_current").set(
        {**plan, "updatedAt": now, "householdId": household_id},
        merge=True,
    )
    return docs
