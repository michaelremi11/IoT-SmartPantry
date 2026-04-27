from typing import Any

from fastapi import APIRouter

from analytics.firebase import get_db
from analytics.services.firebase_analytics import (
    get_environmental_risk,
    get_historical_sustainability,
    get_live_status,
    get_missions,
    get_popular_categories,
    get_sensor_time_series,
    get_smart_shopping_plan,
    get_sustainability_score,
    get_trending_bounds,
    get_waste_report,
    get_recipe_unlocks,
    refresh_analytics_documents,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/time-series")
def sensor_time_series(hours: int = 24, device_id: str = "hub-rpi4-001") -> list[dict[str, Any]]:
    return get_sensor_time_series(get_db(), hours=hours, device_id=device_id)


@router.get("/sustainability")
def sustainability_score() -> dict:
    return get_sustainability_score(get_db())


@router.get("/status")
def live_status(device_id: str = "hub-rpi4-001") -> dict:
    return get_live_status(get_db(), device_id=device_id)


@router.get("/trending")
def trending_bounds(device_id: str = "hub-rpi4-001") -> dict:
    return get_trending_bounds(get_db(), device_id=device_id)


@router.get("/risk")
def environmental_risk(device_id: str = "hub-rpi4-001") -> dict:
    return get_environmental_risk(get_db(), device_id=device_id)


@router.get("/waste-report")
def waste_report() -> dict:
    return get_waste_report(get_db())


@router.get("/historical-sustainability")
def historical_sustainability() -> dict:
    return get_historical_sustainability(get_db())


@router.get("/popular-categories")
def popular_categories() -> dict:
    return get_popular_categories(get_db())


@router.get("/missions")
def missions() -> dict:
    return get_missions(get_db())


@router.get("/recipe-unlocks")
def recipe_unlocks() -> dict:
    return get_recipe_unlocks(get_db())


@router.get("/smart-shopping-plan")
def smart_shopping_plan() -> dict:
    return get_smart_shopping_plan(get_db())


@router.post("/refresh")
def refresh() -> dict:
    refresh_analytics_documents(get_db())
    return {"status": "success"}
