"""
Background Firebase worker for Smart Pantry.

The worker polls Firestore for lightweight request documents, performs heavy
work locally (analytics, recipe generation, smart shopping plans), then writes
the results back to Firestore for web/mobile/Pi clients to receive in realtime.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any

import httpx

from analytics.firebase import get_db
from analytics.services.firebase_analytics import (
    RECIPES_COLLECTION,
    SMART_PLAN_COLLECTION,
    get_pantry_items,
    get_smart_shopping_plan,
    refresh_analytics_documents,
    utc_now,
)

logger = logging.getLogger(__name__)

WORKER_ENABLED = os.getenv("FIREBASE_WORKER_ENABLED", "true").lower() != "false"
WORKER_INTERVAL = int(os.getenv("FIREBASE_WORKER_INTERVAL_SECONDS", "30"))
RECIPE_REQUESTS_COLLECTION = os.getenv("FIRESTORE_RECIPE_REQUESTS_COLLECTION", "recipeRequests")
SMART_PLAN_REQUESTS_COLLECTION = os.getenv("FIRESTORE_SMART_PLAN_REQUESTS_COLLECTION", "smartPlanRequests")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT_S", "60"))

_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _json_from_model(text: str) -> Any:
    clean = re.sub(r"```(?:json)?|```", "", text).strip()
    match = re.search(r"\{.*\}|\[.*\]", clean, re.DOTALL)
    if match:
        clean = match.group(0)
    return json.loads(clean)


def _fallback_recipes(items: list[dict]) -> list[dict]:
    names = [item.get("name", "Pantry Item") for item in items[:4]] or ["Pantry Staples"]
    main = names[0]
    return [
        {
            "title": f"Simple {main} Bowl",
            "ingredients": names,
            "instructions": "1. Prep the ingredients. 2. Cook or warm everything together. 3. Season to taste and serve.",
            "estimated_time": "20 minutes",
        },
        {
            "title": f"Quick {main} Skillet",
            "ingredients": names[:3],
            "instructions": "1. Heat oil in a pan. 2. Add the pantry ingredients. 3. Cook until tender and finish with salt and pepper.",
            "estimated_time": "15 minutes",
        },
    ]


def _generate_recipes(items: list[dict]) -> list[dict]:
    ingredient_text = ", ".join(
        f"{item.get('name', 'Unknown')} ({item.get('quantity', '?')} {item.get('unit', 'unit')})"
        for item in items[:20]
    )
    if not ingredient_text:
        return []

    prompt = f"""You are a helpful culinary AI. I have the following ingredients:
{ingredient_text}

Suggest 3 useful recipes I can make. Return ONLY valid JSON in this exact shape:
{{
  "recipes": [
    {{
      "title": "Recipe Name",
      "ingredients": ["1 cup ingredient", "2 tbsp ingredient"],
      "instructions": "1. First step. 2. Second step.",
      "estimated_time": "25 minutes"
    }}
  ]
}}
"""

    body = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.7, "top_p": 0.9, "num_predict": 768},
    }
    try:
        response = httpx.post(OLLAMA_URL, json=body, timeout=OLLAMA_TIMEOUT)
        response.raise_for_status()
        parsed = _json_from_model(response.json().get("response", ""))
        recipes = parsed.get("recipes", parsed) if isinstance(parsed, dict) else parsed
        if isinstance(recipes, list):
            return recipes[:3]
    except Exception as exc:
        logger.warning("[Worker] Recipe generation fell back: %s", exc)
    return _fallback_recipes(items)


def process_recipe_requests(db) -> int:
    processed = 0
    pending = (
        db.collection(RECIPE_REQUESTS_COLLECTION)
        .where("status", "==", "pending")
        .limit(3)
        .stream()
    )
    for doc in pending:
        ref = doc.reference
        now = utc_now()
        ref.set({"status": "processing", "startedAt": now}, merge=True)
        try:
            items = get_pantry_items(db)
            recipes = _generate_recipes(items)
            recipe_ids = []
            for recipe in recipes:
                recipe_ref = db.collection(RECIPES_COLLECTION).document()
                estimated_time = recipe.get("estimated_time")
                if not estimated_time and recipe.get("time_minutes"):
                    estimated_time = f"{recipe['time_minutes']} minutes"
                payload = {
                    "title": recipe.get("title") or recipe.get("name") or "Untitled Recipe",
                    "ingredients": recipe.get("ingredients", []),
                    "instructions": recipe.get("instructions")
                    or " ".join(recipe.get("steps", []))
                    or "",
                    "source": "ai-generated",
                    "estimated_time": estimated_time,
                    "created_at": now,
                    "request_id": doc.id,
                }
                recipe_ref.set(payload)
                recipe_ids.append(recipe_ref.id)
            ref.set(
                {
                    "status": "complete",
                    "completedAt": utc_now(),
                    "recipeIds": recipe_ids,
                    "error": None,
                },
                merge=True,
            )
            processed += 1
        except Exception as exc:
            logger.exception("[Worker] Recipe request failed: %s", doc.id)
            ref.set({"status": "error", "error": str(exc), "completedAt": utc_now()}, merge=True)
    return processed


def process_smart_plan_requests(db) -> int:
    processed = 0
    pending = (
        db.collection(SMART_PLAN_REQUESTS_COLLECTION)
        .where("status", "==", "pending")
        .limit(5)
        .stream()
    )
    for doc in pending:
        try:
            plan = get_smart_shopping_plan(db)
            payload = {**plan, "status": "complete", "updatedAt": utc_now(), "requestId": doc.id}
            db.collection(SMART_PLAN_COLLECTION).document(doc.id).set(payload, merge=True)
            db.collection(SMART_PLAN_COLLECTION).document("current").set(payload, merge=True)
            doc.reference.set(
                {"status": "complete", "completedAt": utc_now(), "planId": doc.id},
                merge=True,
            )
            processed += 1
        except Exception as exc:
            logger.exception("[Worker] Smart plan request failed: %s", doc.id)
            doc.reference.set({"status": "error", "error": str(exc), "completedAt": utc_now()}, merge=True)
    return processed


def run_worker_loop() -> None:
    if not WORKER_ENABLED:
        logger.info("[Worker] Firebase worker disabled by FIREBASE_WORKER_ENABLED=false")
        return

    logger.info("[Worker] Firebase worker started; interval=%ss", WORKER_INTERVAL)
    while not _stop_event.is_set():
        try:
            db = get_db()
            refresh_analytics_documents(db)
            recipe_count = process_recipe_requests(db)
            plan_count = process_smart_plan_requests(db)
            if recipe_count or plan_count:
                logger.info(
                    "[Worker] Processed %d recipe request(s), %d smart plan request(s)",
                    recipe_count,
                    plan_count,
                )
        except Exception as exc:
            logger.exception("[Worker] Loop failed: %s", exc)
        _stop_event.wait(WORKER_INTERVAL)


def start_background_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _worker_thread = threading.Thread(target=run_worker_loop, name="firebase-worker", daemon=True)
    _worker_thread.start()


def stop_background_worker() -> None:
    _stop_event.set()
