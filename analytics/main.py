"""
analytics/main.py
FastAPI entry point for the Smart Pantry analytics microservice.

Endpoints:
  GET  /health                    — liveness check
  GET  /forecast                  — consumption forecasts for all pantry items
  GET  /forecast/{item_id}        — forecast for a single item
  GET  /anomalies                 — recent environment anomaly flags
  POST /anomalies/check           — check a single sensor reading on-demand
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from analytics.firebase import get_db
from analytics.models import (
    compute_consumption_rate,
    days_until_empty,
    is_buy_soon,
    check_environment,
)

# ---------------------------------------------------------------------------
app = FastAPI(
    title="Smart Pantry Analytics",
    description="Consumption rate forecasting & environmental anomaly detection",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response models

class SensorReading(BaseModel):
    temperatureC: float
    humidityPercent: float


class ForecastItem(BaseModel):
    itemId: str
    name: str
    currentQty: float
    unit: str
    ratePerDay: Optional[float]
    daysUntilEmpty: Optional[float]
    buySoon: bool


class AnomalyFlag(BaseModel):
    type: str
    message: str
    severity: str


# ---------------------------------------------------------------------------
# Routes

@app.get("/health")
def health():
    return {"status": "ok", "service": "analytics", "utc": datetime.now(timezone.utc).isoformat()}


@app.get("/forecast", response_model=list[ForecastItem])
def forecast_all():
    """Compute buy-soon forecasts for every item in the pantry."""
    db = get_db()
    docs = list(db.collection("pantryItems").stream())
    results = []

    for doc in docs:
        item = doc.to_dict()
        item_id = doc.id

        # Fetch the last 30 days of update history from analyticsEvents
        history_docs = (
            db.collection("analyticsEvents")
            .where("itemId", "==", item_id)
            .where("timestamp", ">=", datetime.now(timezone.utc) - timedelta(days=30))
            .order_by("timestamp")
            .stream()
        )
        history = [h.to_dict() for h in history_docs]

        rate = compute_consumption_rate(history)
        current_qty = item.get("quantity", 0)
        days_left = days_until_empty(current_qty, rate)

        results.append(
            ForecastItem(
                itemId=item_id,
                name=item.get("name", "Unknown"),
                currentQty=current_qty,
                unit=item.get("unit", "unit"),
                ratePerDay=rate,
                daysUntilEmpty=days_left,
                buySoon=is_buy_soon(days_left),
            )
        )

    return results


@app.get("/forecast/{item_id}", response_model=ForecastItem)
def forecast_one(item_id: str):
    """Forecast for a single pantry item."""
    db = get_db()
    doc = db.collection("pantryItems").document(item_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Item not found")

    item = doc.to_dict()
    history_docs = (
        db.collection("analyticsEvents")
        .where("itemId", "==", item_id)
        .where("timestamp", ">=", datetime.now(timezone.utc) - timedelta(days=30))
        .order_by("timestamp")
        .stream()
    )
    history = [h.to_dict() for h in history_docs]
    rate = compute_consumption_rate(history)
    current_qty = item.get("quantity", 0)
    days_left = days_until_empty(current_qty, rate)

    return ForecastItem(
        itemId=item_id,
        name=item.get("name", "Unknown"),
        currentQty=current_qty,
        unit=item.get("unit", "unit"),
        ratePerDay=rate,
        daysUntilEmpty=days_left,
        buySoon=is_buy_soon(days_left),
    )


@app.get("/anomalies", response_model=list[dict])
def recent_anomalies(hours: int = 24):
    """Return environment anomalies detected in the last N hours."""
    db = get_db()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    logs = (
        db.collection("environmentLogs")
        .where("timestamp", ">=", since)
        .order_by("timestamp", direction="DESCENDING")
        .limit(500)
        .stream()
    )

    flagged = []
    for log in logs:
        reading = log.to_dict()
        flags = check_environment(
            reading.get("temperatureC", 20),
            reading.get("humidityPercent", 50),
        )
        if flags:
            flagged.append({
                "logId": log.id,
                "timestamp": reading.get("timestamp"),
                "deviceId": reading.get("deviceId"),
                "temperatureC": reading.get("temperatureC"),
                "humidityPercent": reading.get("humidityPercent"),
                "anomalies": flags,
            })

    return flagged


@app.post("/anomalies/check", response_model=list[AnomalyFlag])
def check_anomaly(reading: SensorReading):
    """On-demand anomaly check for a single sensor reading."""
    flags = check_environment(reading.temperatureC, reading.humidityPercent)
    return [AnomalyFlag(**f) for f in flags]
