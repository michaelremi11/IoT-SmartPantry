"""
FastAPI entry point for the Smart Pantry Firebase worker service.

The web/mobile clients no longer depend on this app for normal CRUD.  They
read and write Firestore directly.  This service remains useful for:
  - background Firebase workers that generate recipes and analytics summaries
  - diagnostic/read-only HTTP endpoints
  - optional compatibility endpoints for barcode lookup and recommendations
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from analytics.firebase import get_db
from analytics.models import compute_consumption_rate, days_until_empty, is_buy_soon, check_environment
from analytics.routers.analytics import router as analytics_router
from analytics.services.firebase_analytics import (
    get_buy_signals,
    get_environment_logs,
    get_pantry_items,
    utc_now,
)
from analytics.worker import start_background_worker, stop_background_worker, _generate_recipes

load_dotenv()

app = FastAPI(
    title="Smart Pantry Firebase Worker",
    description="Recipe generation, Firebase analytics summaries, and diagnostics",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analytics_router)


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


@app.on_event("startup")
def startup() -> None:
    start_background_worker()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_background_worker()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "firebase-worker",
        "utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/forecast", response_model=list[ForecastItem])
def forecast_all() -> list[ForecastItem]:
    db = get_db()
    since = utc_now() - timedelta(days=30)
    results = []
    for item in get_pantry_items(db):
        history_docs = (
            db.collection(os.getenv("FIRESTORE_ANALYTICS_COLLECTION", "analyticsEvents"))
            .where("itemId", "==", item["id"])
            .where("timestamp", ">=", since)
            .stream()
        )
        history = [doc.to_dict() for doc in history_docs]
        rate = compute_consumption_rate(history)
        days_left = days_until_empty(item.get("quantity", 0), rate)
        results.append(
            ForecastItem(
                itemId=item["id"],
                name=item.get("name", "Unknown"),
                currentQty=item.get("quantity", 0),
                unit=item.get("unit", "unit"),
                ratePerDay=rate,
                daysUntilEmpty=days_left,
                buySoon=is_buy_soon(days_left),
            )
        )
    return results


@app.get("/forecast/{item_id}", response_model=ForecastItem)
def forecast_one(item_id: str) -> ForecastItem:
    matches = [item for item in get_pantry_items(get_db()) if item["id"] == item_id]
    if not matches:
        raise HTTPException(status_code=404, detail="Item not found")
    item = matches[0]
    db = get_db()
    since = utc_now() - timedelta(days=30)
    history_docs = (
        db.collection(os.getenv("FIRESTORE_ANALYTICS_COLLECTION", "analyticsEvents"))
        .where("itemId", "==", item_id)
        .where("timestamp", ">=", since)
        .stream()
    )
    history = [doc.to_dict() for doc in history_docs]
    rate = compute_consumption_rate(history)
    days_left = days_until_empty(item.get("quantity", 0), rate)
    return ForecastItem(
        itemId=item_id,
        name=item.get("name", "Unknown"),
        currentQty=item.get("quantity", 0),
        unit=item.get("unit", "unit"),
        ratePerDay=rate,
        daysUntilEmpty=days_left,
        buySoon=is_buy_soon(days_left),
    )


@app.get("/anomalies", response_model=list[dict])
def recent_anomalies(hours: int = 24) -> list[dict]:
    flagged = []
    for reading in get_environment_logs(get_db(), hours=hours):
        flags = check_environment(
            reading.get("temperatureC", 20),
            reading.get("humidityPercent", 50),
        )
        if flags:
            flagged.append(
                {
                    "logId": reading["id"],
                    "timestamp": reading.get("timestamp"),
                    "deviceId": reading.get("deviceId"),
                    "temperatureC": reading.get("temperatureC"),
                    "humidityPercent": reading.get("humidityPercent"),
                    "anomalies": flags,
                }
            )
    return flagged


@app.post("/anomalies/check", response_model=list[AnomalyFlag])
def check_anomaly(reading: SensorReading) -> list[AnomalyFlag]:
    return [AnomalyFlag(**flag) for flag in check_environment(reading.temperatureC, reading.humidityPercent)]


OFF_BASE = "https://world.openfoodfacts.org/api/v2/product"
OFF_FIELDS = "product_name,quantity,categories_tags,brands,nutriments,image_url"


@app.get("/lookup/{sku}")
def lookup_sku(sku: str) -> dict:
    """
    Compatibility product lookup endpoint.

    New clients can do this lookup themselves or create request documents, but
    this endpoint is kept for older Pi scripts.  It caches lookup metadata in
    Firestore under productLookups/{sku}; it does not mutate pantry stock.
    """
    url = f"{OFF_BASE}/{sku}.json?fields={OFF_FIELDS}"
    try:
        resp = httpx.get(url, timeout=8.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Open Food Facts error: {exc}") from exc

    payload = resp.json()
    if payload.get("status") != 1:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found in Open Food Facts")

    product = payload.get("product", {})
    quantity_str = product.get("quantity") or ""
    qty_value: Optional[float] = None
    qty_unit = "unit"
    parts = quantity_str.strip().split()
    if parts:
        try:
            qty_value = float(parts[0].replace(",", "."))
            qty_unit = parts[1] if len(parts) > 1 else "unit"
        except ValueError:
            pass

    categories = product.get("categories_tags", [])
    category = categories[-1].replace("en:", "").replace("-", " ") if categories else ""
    result = {
        "sku": sku,
        "product_name": product.get("product_name") or "Unknown Product",
        "quantity": qty_value,
        "unit": qty_unit,
        "category": category,
        "brand": product.get("brands", ""),
        "image_url": product.get("image_url", ""),
        "raw_quantity": quantity_str,
        "updatedAt": utc_now(),
    }
    get_db().collection("productLookups").document(sku).set(result, merge=True)
    return result


@app.get("/buy-signals")
def buy_signals(days: int = 30) -> list[dict]:
    return get_buy_signals(get_db(), days=days)


@app.get("/recommendations")
def meal_recommendations() -> dict:
    items = get_pantry_items(get_db())
    recipes = _generate_recipes(items)
    return {
        "recipes": recipes,
        "ingredients": [f"{item['name']} ({item['quantity']} {item['unit']})" for item in items],
        "model": os.getenv("OLLAMA_MODEL", "llama3.2:1b"),
        "generated_at": utc_now().isoformat(),
    }
