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
def sensor_time_series(
    household_id: str,
    hours: int = 24,
    device_id: str = "hub-rpi4-001",
) -> list[dict[str, Any]]:
    return get_sensor_time_series(get_db(), hours=hours, device_id=device_id, household_id=household_id)


@router.get("/sustainability")
def sustainability_score(household_id: str) -> dict:
    return get_sustainability_score(get_db(), household_id=household_id)


@router.get("/status")
def live_status(household_id: str, device_id: str = "hub-rpi4-001") -> dict:
    return get_live_status(get_db(), device_id=device_id, household_id=household_id)


@router.get("/trending")
def trending_bounds(household_id: str, device_id: str = "hub-rpi4-001") -> dict:
    return get_trending_bounds(get_db(), device_id=device_id, household_id=household_id)


@router.get("/risk")
def environmental_risk(household_id: str, device_id: str = "hub-rpi4-001") -> dict:
    return get_environmental_risk(get_db(), device_id=device_id, household_id=household_id)


@router.get("/waste-report")
def waste_report(household_id: str) -> dict:
    return get_waste_report(get_db(), household_id=household_id)


@router.get("/historical-sustainability")
def historical_sustainability(household_id: str) -> dict:
    return get_historical_sustainability(get_db(), household_id=household_id)


@router.get("/popular-categories")
def popular_categories(household_id: str) -> dict:
    return get_popular_categories(get_db(), household_id=household_id)


@router.get("/missions")
def missions(household_id: str) -> dict:
    return get_missions(get_db(), household_id=household_id)


@router.get("/recipe-unlocks")
def recipe_unlocks(household_id: str) -> dict:
    return get_recipe_unlocks(get_db(), household_id=household_id)


@router.get("/smart-shopping-plan")
def smart_shopping_plan(household_id: str) -> dict:
    return get_smart_shopping_plan(get_db(), household_id=household_id)


@router.post("/refresh")
def refresh(household_id: str) -> dict:
    refresh_analytics_documents(get_db(), household_id)
    return {"status": "success"}
