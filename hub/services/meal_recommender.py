"""
hub/services/meal_recommender.py
Standalone Ollama meal recommendation client for the Smart Pantry Hub.

Can be called directly from the Kivy UI or from the FastAPI service.
Fetches 'in_stock' items from Firestore and returns 3 recipe suggestions
as a Python list of dicts, via the locally running Ollama Llama 3.2 1B.

Optimisation notes for Llama 3.2 1B on Raspberry Pi 4 (4 GB RAM)
------------------------------------------------------------------
* `num_ctx` is capped at 512 tokens — the model context window we actively
  send is < 200 tokens, so this keeps inference fast (< 10 s on Pi 4).
* `num_predict` = 768 gives enough room for 3 recipe JSON objects.
* `temperature` = 0.7 balances creativity vs. output reliability.
* `top_p` = 0.9 keeps the token distribution tight.
* We request pure JSON (`stream: false`) to avoid having to stream-parse
  newline-delimited JSON on a resource-constrained device.

Usage
-----
    from hub.services.meal_recommender import get_meal_recommendations

    recipes = get_meal_recommendations(db)   # blocking call
    for r in recipes:
        print(r["name"], r["time_minutes"], "min")
"""

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

OLLAMA_URL     = os.getenv("OLLAMA_URL",      "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL",    "llama3.2:1b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT_S", "60"))

# ---------------------------------------------------------------------------
# Prompt template — optimised for Llama 3.2 1B instruction-following
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a helpful kitchen assistant. "
    "Reply with ONLY a minified JSON array — no markdown, no explanation, no commentary. "
    "The array must contain exactly 3 recipe objects. "
    "Each object must have these exact keys: "
    '"name" (string), '
    '"ingredients" (array of strings), '
    '"steps" (array of strings with numbered steps), '
    '"time_minutes" (integer), '
    '"difficulty" ("easy"|"medium"|"hard"). '
)

_USER_PART = (
    "Pantry items available: {ingredient_list}. "
    "You may also use basic staples: salt, pepper, olive oil, water, garlic. "
    "Output the JSON array now:"
)

FULL_PROMPT_TEMPLATE = _SYSTEM_PROMPT + _USER_PART


def get_meal_recommendations(db, max_items: int = 20) -> list[dict]:
    """
    Query Firestore for in-stock items, build a structured prompt, call
    Ollama, and return a list of up to 3 recipe dicts.

    Parameters
    ----------
    db        : Firestore client (from hub.firebase.get_db or analytics.firebase.get_db).
    max_items : Cap the ingredient list to avoid prompt overflow.

    Returns
    -------
    list of recipe dicts with keys:
        name, ingredients, steps, time_minutes, difficulty

    Raises
    ------
    RuntimeError  if Ollama is unreachable or returns unparseable output.
    """
    # ── 1. Fetch in-stock inventory ────────────────────────────────────
    docs = db.collection("inventory").where("in_stock", "==", True).stream()
    in_stock_items = []
    for d in docs:
        data = d.to_dict()
        name    = data.get("name", "Unknown")
        amount  = data.get("amount", "?")
        unit    = data.get("unit", "unit")
        in_stock_items.append(f"{name} ({amount} {unit})")

    if not in_stock_items:
        logger.warning("[MealRecommender] No in-stock items found in Firestore.")
        return []

    ingredient_list = ", ".join(in_stock_items[:max_items])
    logger.info("[MealRecommender] Building prompt for %d item(s).", len(in_stock_items[:max_items]))

    # ── 2. Build prompt ────────────────────────────────────────────────
    prompt = FULL_PROMPT_TEMPLATE.format(ingredient_list=ingredient_list)

    payload = {
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "top_p":       0.9,
            "num_predict": 768,   # ~3 recipes in JSON uses ~400–600 tokens
            "num_ctx":     512,   # keep context window minimal for speed
        },
    }

    # ── 3. Call Ollama ─────────────────────────────────────────────────
    try:
        import httpx
        logger.info("[MealRecommender] POST %s model=%s", OLLAMA_URL, OLLAMA_MODEL)
        resp = httpx.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"[MealRecommender] Ollama request failed: {exc}") from exc

    raw_text = resp.json().get("response", "")
    logger.debug("[MealRecommender] Raw response: %s", raw_text[:500])

    # ── 4. Parse JSON from model output ───────────────────────────────
    # Strip accidental markdown fences (some Llama variants add them)
    clean = re.sub(r"```(?:json)?|```", "", raw_text).strip()

    # Find the outermost JSON array if there's surrounding text
    match = re.search(r"\[.*\]", clean, re.DOTALL)
    if match:
        clean = match.group(0)

    try:
        recipes = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"[MealRecommender] Could not parse model output as JSON: {exc}. "
            f"Raw (first 300 chars): {raw_text[:300]}"
        ) from exc

    if not isinstance(recipes, list):
        recipes = [recipes]

    logger.info("[MealRecommender] ✅ Got %d recipe(s).", len(recipes))
    return recipes[:3]
