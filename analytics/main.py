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
from dotenv import load_dotenv

load_dotenv() # Load variables from .env file

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from analytics.firebase import get_db
from analytics.models import (
    compute_consumption_rate,
    days_until_empty,
    is_buy_soon,
    check_environment,
    compute_buy_signals,
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

from analytics.routers.analytics import router as analytics_router
app.include_router(analytics_router)

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


# ---------------------------------------------------------------------------
# Open Food Facts  ─  /lookup/{sku}
# ---------------------------------------------------------------------------

OFF_BASE = "https://world.openfoodfacts.org/api/v2/product"
OFF_FIELDS = "product_name,quantity,categories_tags,brands,nutriments,image_url"


@app.get("/lookup/{sku}")
def lookup_sku(sku: str):
    """
    Fetch product info from Open Food Facts for `sku` (EAN/UPC barcode),
    then write the result to the Firestore `inventory` collection.

    Returns a flat dict with the most relevant fields for the Kivy UI.
    """
    # ── 1. Fetch from Open Food Facts ──────────────────────────────────
    url = f"{OFF_BASE}/{sku}.json?fields={OFF_FIELDS}"
    try:
        resp = httpx.get(url, timeout=8.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Open Food Facts error: {exc}")

    payload = resp.json()

    if payload.get("status") != 1:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found in Open Food Facts")

    product = payload.get("product", {})
    product_name = product.get("product_name") or "Unknown Product"
    quantity_str  = product.get("quantity") or ""
    categories    = product.get("categories_tags", [])
    brand         = product.get("brands", "")
    image_url     = product.get("image_url", "")

    # ── 2. Parse quantity (e.g. "500 ml" → 500.0) ──────────────────────
    qty_value: Optional[float] = None
    qty_unit: str = "unit"
    if quantity_str:
        parts = quantity_str.strip().split()
        if parts:
            try:
                qty_value = float(parts[0].replace(",", "."))
                qty_unit  = parts[1] if len(parts) > 1 else "unit"
            except ValueError:
                pass  # keep None / 'unit'

    # Pick the most specific category tag (last in list, strip 'en:' prefix)
    category = ""
    if categories:
        category = categories[-1].replace("en:", "").replace("-", " ")

    result = {
        "sku":          sku,
        "product_name": product_name,
        "quantity":     qty_value,
        "unit":         qty_unit,
        "category":     category,
        "brand":        brand,
        "image_url":    image_url,
        "raw_quantity": quantity_str,
    }

    # ── 3. Write to Firestore `inventory` collection ────────────────────
    try:
        db = get_db()
        doc_ref = db.collection("inventory").document(sku)
        doc_ref.set(
            {
                "sku":          sku,
                "name":         product_name,
                "amount":       qty_value,
                "unit":         qty_unit,
                "category":     category,
                "brand":        brand,
                "image_url":    image_url,
                "added_date":   datetime.now(timezone.utc),
                "expiry_date":  None,   # user fills this in on the Kivy form
                "in_stock":     True,
                "source":       "open_food_facts",
            },
            merge=True,   # don't overwrite user-edited fields on re-scan
        )
    except Exception as exc:
        # Don't fail the API call if Firestore write fails — log and continue
        import logging
        logging.getLogger(__name__).error("[lookup] Firestore write error: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Buy Signals  ─  /buy-signals
# ---------------------------------------------------------------------------

@app.get("/buy-signals")
def buy_signals(days: int = 30):
    """
    Compute BUY_MORE / BUY_LESS purchasing signals for all pantry items.

    BUY_MORE  — high consumption frequency (running low soon).
    BUY_LESS  — high expiration rate (buying more than we use).

    Pure math, no LLM — conserves RAM on the Raspberry Pi 4.
    """
    db     = get_db()
    since  = datetime.now(timezone.utc) - timedelta(days=days)

    # Fetch all pantry items
    item_docs = list(db.collection("pantryItems").stream())
    items = []
    for doc in item_docs:
        d = doc.to_dict()
        d["id"] = doc.id
        items.append(d)

    if not items:
        return []

    # Fetch usage logs for the window
    log_docs = (
        db.collection("usage_logs")
        .where("timestamp", ">=", since)
        .order_by("timestamp")
        .stream()
    )
    usage_logs = [log.to_dict() for log in log_docs]

    signals = compute_buy_signals(items, usage_logs)
    return signals


# ---------------------------------------------------------------------------
# Meal Recommendations  ─  /recommendations
# ---------------------------------------------------------------------------

OLLAMA_URL     = os.getenv("OLLAMA_URL",     "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL",   "llama3.2:1b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT_S", "60"))


@app.get("/recommendations")
def meal_recommendations():
    """
    Pull all 'in stock' pantry items and ask the local Ollama model
    (Llama 3.2 1B) for 3 meal ideas that use those ingredients.

    Returns a JSON list of recipe objects.  The prompt is crafted to
    elicit a structured JSON response from the small model reliably.
    """
    db = get_db()

    # ── Gather in-stock items ──────────────────────────────────────────
    docs = db.collection("inventory").where("in_stock", "==", True).stream()
    in_stock = [
        f"{d.to_dict().get('name', 'Unknown')} ({d.to_dict().get('amount', '?')} {d.to_dict().get('unit', 'unit')})"
        for d in docs
    ]

    if not in_stock:
        return {"recipes": [], "message": "No in-stock items found."}

    ingredient_list = ", ".join(in_stock[:20])  # cap to avoid prompt overflow

    # ── Build optimised Llama 3.2 1B prompt ───────────────────────────
    prompt = (
        "You are a helpful kitchen assistant. "
        "Reply with ONLY a minified JSON array — no markdown, no explanation. "
        "The array must contain exactly 3 recipe objects. "
        "Each object must have these keys: "
        '"name" (string), "ingredients" (array of strings), "steps" (array of strings), '
        '"time_minutes" (integer), "difficulty" ("easy"|"medium"|"hard"). '
        "Use only ingredients from this pantry list (you may add basic pantry staples like "
        "salt, oil, water): "
        f"{ingredient_list}. "
        "Output the JSON array now:"
    )

    body = {
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature":  0.7,
            "top_p":        0.9,
            "num_predict":  768,   # keep response tight for 1B model
        },
    }

    # ── Call local Ollama instance ─────────────────────────────────────
    try:
        resp = httpx.post(OLLAMA_URL, json=body, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")

    raw_text = resp.json().get("response", "")

    # ── Parse JSON from model output ───────────────────────────────────
    import json, re
    # Strip any accidental markdown fences the model might emit
    clean = re.sub(r"```(?:json)?|```", "", raw_text).strip()
    try:
        recipes = json.loads(clean)
        if not isinstance(recipes, list):
            recipes = [recipes]
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Model returned invalid JSON: {exc}. Raw: {clean[:300]}",
        )

    return {
        "recipes":     recipes[:3],
        "ingredients": in_stock,
        "model":       OLLAMA_MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

print("--- Analytics Registered Routes ---")
for route in app.routes:
    print(f"Registered: {getattr(route, 'path', 'Unknown')}")
