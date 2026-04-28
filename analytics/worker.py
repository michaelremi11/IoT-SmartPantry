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

_BASIC_STAPLES = {
    "salt",
    "pepper",
    "water",
    "olive oil",
    "vegetable oil",
    "butter",
    "garlic",
    "onion",
    "flour",
    "sugar",
}
_MEASUREMENT_WORDS = {
    "cup",
    "cups",
    "tbsp",
    "tablespoon",
    "tablespoons",
    "tsp",
    "teaspoon",
    "teaspoons",
    "oz",
    "ounce",
    "ounces",
    "lb",
    "lbs",
    "pound",
    "pounds",
    "g",
    "gram",
    "grams",
    "kg",
    "ml",
    "l",
    "liter",
    "liters",
    "slice",
    "slices",
    "piece",
    "pieces",
    "can",
    "cans",
    "clove",
    "cloves",
}
_PREP_WORDS = {
    "fresh",
    "frozen",
    "canned",
    "diced",
    "chopped",
    "minced",
    "sliced",
    "shredded",
    "grated",
    "boneless",
    "skinless",
    "large",
    "medium",
    "small",
    "optional",
    "to",
    "taste",
}


def _json_from_model(text: str) -> Any:
    clean = re.sub(r"```(?:json)?|```", "", text).strip()
    match = re.search(r"\{.*\}|\[.*\]", clean, re.DOTALL)
    if match:
        clean = match.group(0)
    return json.loads(clean)


def _normalize_text(value: str) -> str:
    cleaned = re.sub(r"\([^)]*\)", " ", value.lower())
    cleaned = re.sub(r"[^a-z0-9\s/-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _singularize(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 3 and word.endswith("es") and not word.endswith("ses"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _canonical_food_name(value: str) -> str:
    cleaned = _normalize_text(value)
    cleaned = re.sub(r"^\d+[\/\d.\s-]*", "", cleaned).strip()
    tokens: list[str] = []
    for raw in cleaned.split():
        token = _singularize(raw)
        if token in _MEASUREMENT_WORDS or token in _PREP_WORDS:
            continue
        if re.fullmatch(r"[\d./-]+", token):
            continue
        tokens.append(token)
    return " ".join(tokens).strip()


def _build_pantry_profiles(items: list[dict]) -> list[dict]:
    profiles: list[dict] = []
    for item in items:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        quantity = item.get("quantity", item.get("amount", 0))
        try:
            numeric_quantity = float(quantity)
        except (TypeError, ValueError):
            numeric_quantity = 0.0
        if numeric_quantity <= 0:
            continue
        canonical = _canonical_food_name(name)
        if not canonical:
            continue
        profiles.append(
            {
                "display_name": name,
                "canonical": canonical,
                "quantity": numeric_quantity,
                "unit": item.get("unit", "unit"),
                "category": str(item.get("category", "")).strip().lower(),
            }
        )
    return profiles


def _matches_pantry(ingredient_name: str, pantry_profiles: list[dict]) -> bool:
    if not ingredient_name:
        return False
    if ingredient_name in _BASIC_STAPLES:
        return True

    ingredient_tokens = set(ingredient_name.split())
    for pantry_item in pantry_profiles:
        pantry_name = pantry_item["canonical"]
        pantry_tokens = set(pantry_name.split())
        if ingredient_name == pantry_name:
            return True
        if ingredient_name in pantry_name or pantry_name in ingredient_name:
            return True
        if ingredient_tokens and pantry_tokens and ingredient_tokens.issubset(pantry_tokens):
            return True
        if ingredient_tokens and pantry_tokens and pantry_tokens.issubset(ingredient_tokens):
            return True
    return False


def _format_pantry_for_prompt(pantry_profiles: list[dict]) -> str:
    return "\n".join(
        f"- {item['display_name']} ({item['quantity']:g} {item['unit']})"
        for item in pantry_profiles[:20]
    )


def _build_recipe_prompt(pantry_profiles: list[dict]) -> str:
    pantry_text = _format_pantry_for_prompt(pantry_profiles)
    staples_text = ", ".join(sorted(_BASIC_STAPLES))
    return f"""You are a practical home cook planning realistic meals from a real pantry.

Available pantry items:
{pantry_text}

You may also assume these basic staples are available: {staples_text}.

Rules:
- Return exactly 3 recipe objects.
- Use pantry items as the primary ingredients. Do not invent extra produce, meat, dairy, sauces, or grains unless they appear above or are in the basic staples list.
- Keep recipes realistic for an ordinary home kitchen.
- Prefer 4 to 8 ingredients and 3 to 6 steps.
- If the pantry is sparse, suggest simple meals instead of forcing complex dishes.
- Each ingredient string should clearly refer to a pantry item or a basic staple.
- Avoid duplicate recipe ideas.
- Return ONLY valid JSON.

Return this exact shape:
{{
  "recipes": [
    {{
      "title": "Recipe Name",
      "ingredients": ["2 eggs", "1 tomato", "salt"],
      "steps": ["Beat the eggs.", "Cook them with the tomato.", "Season and serve."],
      "time_minutes": 15,
      "difficulty": "easy"
    }}
  ]
}}
"""


def _normalize_steps(recipe: dict) -> list[str]:
    steps = recipe.get("steps")
    if isinstance(steps, list):
        normalized_steps = [str(step).strip() for step in steps if str(step).strip()]
        if normalized_steps:
            return normalized_steps[:6]

    instructions = str(recipe.get("instructions", "")).strip()
    if not instructions:
        return []

    parts = re.split(r"\s*(?:\d+\.\s+|\n+)\s*", instructions)
    normalized_steps = [part.strip() for part in parts if part.strip()]
    return normalized_steps[:6]


def _normalize_recipe(recipe: dict, pantry_profiles: list[dict], seen_titles: set[str]) -> dict | None:
    title = str(recipe.get("title") or recipe.get("name") or "").strip()
    if not title:
        return None

    title_key = _normalize_text(title)
    if not title_key or title_key in seen_titles:
        return None

    raw_ingredients = recipe.get("ingredients")
    if not isinstance(raw_ingredients, list):
        return None

    steps = _normalize_steps(recipe)
    if len(steps) < 2:
        return None

    normalized_ingredients: list[str] = []
    matched_pantry_count = 0
    for ingredient in raw_ingredients[:10]:
        ingredient_text = str(ingredient).strip()
        if not ingredient_text:
            continue
        normalized_name = _canonical_food_name(ingredient_text)
        if not normalized_name:
            continue
        if not _matches_pantry(normalized_name, pantry_profiles):
            return None
        if normalized_name not in _BASIC_STAPLES:
            matched_pantry_count += 1
        normalized_ingredients.append(ingredient_text)

    minimum_matches = 1 if len(pantry_profiles) <= 2 else 2
    if len(normalized_ingredients) < minimum_matches or matched_pantry_count < minimum_matches:
        return None

    time_minutes = recipe.get("time_minutes")
    if not isinstance(time_minutes, int):
        try:
            time_minutes = int(str(time_minutes).strip())
        except (TypeError, ValueError):
            time_minutes = None
    if not time_minutes or time_minutes <= 0:
        time_minutes = 20

    seen_titles.add(title_key)
    return {
        "title": title,
        "ingredients": normalized_ingredients,
        "instructions": " ".join(f"{index}. {step}" for index, step in enumerate(steps, start=1)),
        "estimated_time": f"{time_minutes} minutes",
        "source": "ai-generated",
    }


def _make_recipe(
    title: str,
    ingredients: list[str],
    steps: list[str],
    estimated_time: str,
    seen_titles: set[str],
) -> dict | None:
    title_key = _normalize_text(title)
    if title_key in seen_titles:
        return None
    seen_titles.add(title_key)
    return {
        "title": title,
        "ingredients": ingredients,
        "instructions": " ".join(f"{index}. {step}" for index, step in enumerate(steps, start=1)),
        "estimated_time": estimated_time,
        "source": "template-generated",
    }


def _fallback_recipes(items: list[dict]) -> list[dict]:
    pantry_profiles = _build_pantry_profiles(items)
    if not pantry_profiles:
        return []

    names = [item["display_name"] for item in pantry_profiles]
    canonicals = {item["canonical"] for item in pantry_profiles}
    non_bread_names = [
        item["display_name"] for item in pantry_profiles if "bread" not in item["canonical"]
    ]
    seen_titles: set[str] = set()
    fallback: list[dict] = []

    def add_recipe(recipe: dict | None) -> None:
        if recipe and len(fallback) < 3:
            fallback.append(recipe)

    if "egg" in canonicals or "eggs" in canonicals:
        mix_ins = [
            name
            for name in non_bread_names
            if _canonical_food_name(name) not in {"egg", "eggs"}
        ][:3]
        add_recipe(
            _make_recipe(
                "Pantry Egg Scramble",
                ["Eggs", *mix_ins, "Salt", "Pepper"],
                [
                    "Prep the pantry vegetables or proteins into bite-size pieces.",
                    "Whisk the eggs with salt and pepper.",
                    "Cook the mix-ins in a lightly oiled skillet, then add the eggs and stir until just set.",
                    "Serve warm.",
                ],
                "12 minutes",
                seen_titles,
            )
        )

    if any("bread" in canonical for canonical in canonicals):
        toppings = non_bread_names[:3]
        add_recipe(
            _make_recipe(
                "Loaded Pantry Toast",
                ["Bread", *toppings, "Olive Oil", "Salt", "Pepper"],
                [
                    "Toast or warm the bread until crisp.",
                    "Cook or warm the toppings as needed in a skillet with a little oil.",
                    "Pile the toppings onto the toast and season to taste.",
                ],
                "10 minutes",
                seen_titles,
            )
        )

    core = non_bread_names[:4] or names[:4]
    if core:
        add_recipe(
            _make_recipe(
                f"{core[0]} and Pantry Skillet",
                [*core, "Olive Oil", "Salt", "Pepper"],
                [
                    "Prep the pantry ingredients so they cook evenly.",
                    "Heat a skillet with oil and cook the firmest items first.",
                    "Add the remaining items, season well, and cook until everything is hot and tender.",
                    "Serve right away.",
                ],
                "18 minutes",
                seen_titles,
            )
        )

    if len(core) >= 2:
        add_recipe(
            _make_recipe(
                "Pantry Bowl",
                [*core, "Olive Oil", "Salt", "Pepper"],
                [
                    "Warm or cook the pantry ingredients separately as needed.",
                    "Combine them in a bowl with a little oil, salt, and pepper.",
                    "Toss well and serve as a quick meal bowl.",
                ],
                "15 minutes",
                seen_titles,
            )
        )

    if len(core) >= 3:
        add_recipe(
            _make_recipe(
                f"{core[0]} Supper Plate",
                [*core[:3], "Butter", "Salt", "Pepper"],
                [
                    "Cook the main pantry ingredient until hot and ready to serve.",
                    "Warm the supporting ingredients in the same pan with butter and seasoning.",
                    "Plate everything together and finish with a final pinch of salt and pepper.",
                ],
                "20 minutes",
                seen_titles,
            )
        )

    return fallback[:3]


def _extract_recipe_candidates(payload: Any) -> list[dict]:
    recipes = payload.get("recipes", payload) if isinstance(payload, dict) else payload
    return recipes if isinstance(recipes, list) else []


def _generate_recipes(items: list[dict]) -> list[dict]:
    pantry_profiles = _build_pantry_profiles(items)
    if not pantry_profiles:
        return []

    body = {
        "model": OLLAMA_MODEL,
        "prompt": _build_recipe_prompt(pantry_profiles),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.4, "top_p": 0.9, "num_predict": 768, "num_ctx": 768},
    }
    try:
        response = httpx.post(OLLAMA_URL, json=body, timeout=OLLAMA_TIMEOUT)
        response.raise_for_status()
        parsed = _json_from_model(response.json().get("response", ""))
        candidates = _extract_recipe_candidates(parsed)
        normalized: list[dict] = []
        seen_titles: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            recipe = _normalize_recipe(candidate, pantry_profiles, seen_titles)
            if recipe:
                normalized.append(recipe)
            if len(normalized) == 3:
                break
        if normalized:
            return normalized
        logger.warning("[Worker] Recipe generation returned no valid recipes; using fallback templates.")
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
