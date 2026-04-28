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
    get_household_ids,
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
    "extra",
    "virgin",
    "whole",
    "skim",
    "reduced",
    "fat",
    "lowfat",
    "original",
}

_FAMILY_GROUP_KEYWORDS = [
    ("pasta", "long_pasta", ["spaghetti", "linguine", "fettuccine", "angel hair", "capellini", "bucatini", "vermicelli", "pappardelle", "tagliatelle"]),
    ("pasta", "shaped_pasta", ["penne", "rigatoni", "rotini", "fusilli", "macaroni", "elbow macaroni", "cavatappi", "farfalle", "ziti", "gemelli", "shells"]),
    ("pasta", "small_pasta", ["orzo", "ditalini", "stelline", "acini di pepe"]),
    ("pasta", "sheet_pasta", ["lasagna", "lasagne"]),
    ("pasta", "stuffed_pasta", ["ravioli", "tortellini"]),
    ("milk", "oat_milk", ["oat milk"]),
    ("milk", "almond_milk", ["almond milk"]),
    ("milk", "soy_milk", ["soy milk"]),
    ("milk", "coconut_milk", ["coconut milk"]),
    ("milk", "cashew_milk", ["cashew milk"]),
    ("oil", "olive_oil", ["olive oil", "extra virgin olive oil"]),
    ("oil", "vegetable_oil", ["vegetable oil", "canola oil"]),
]

_UNIT_DEFINITIONS = {
    "unit": ("count", 1.0),
    "units": ("count", 1.0),
    "count": ("count", 1.0),
    "piece": ("count", 1.0),
    "pieces": ("count", 1.0),
    "item": ("count", 1.0),
    "items": ("count", 1.0),
    "egg": ("count", 1.0),
    "eggs": ("count", 1.0),
    "clove": ("count", 1.0),
    "cloves": ("count", 1.0),
    "slice": ("count", 1.0),
    "slices": ("count", 1.0),
    "cup": ("volume", 8.0),
    "cups": ("volume", 8.0),
    "tbsp": ("volume", 0.5),
    "tablespoon": ("volume", 0.5),
    "tablespoons": ("volume", 0.5),
    "tsp": ("volume", 1.0 / 6.0),
    "teaspoon": ("volume", 1.0 / 6.0),
    "teaspoons": ("volume", 1.0 / 6.0),
    "fl oz": ("volume", 1.0),
    "floz": ("volume", 1.0),
    "ml": ("volume", 0.033814),
    "l": ("volume", 33.814),
    "oz": ("weight", 28.3495),
    "ounce": ("weight", 28.3495),
    "ounces": ("weight", 28.3495),
    "lb": ("weight", 453.592),
    "lbs": ("weight", 453.592),
    "pound": ("weight", 453.592),
    "pounds": ("weight", 453.592),
    "g": ("weight", 1.0),
    "gram": ("weight", 1.0),
    "grams": ("weight", 1.0),
    "kg": ("weight", 1000.0),
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


def _normalize_unit(unit: str | None) -> str:
    return _normalize_text(unit or "")


def _unit_definition(unit: str | None) -> tuple[str, float]:
    normalized = _normalize_unit(unit)
    if not normalized:
        return ("count", 1.0)
    return _UNIT_DEFINITIONS.get(normalized, ("unknown", 1.0))


def _to_comparable_amount(amount: float, unit: str | None) -> float:
    _dimension, factor = _unit_definition(unit)
    return amount * factor


def _from_comparable_amount(amount: float, unit: str | None) -> float:
    _dimension, factor = _unit_definition(unit)
    return amount / factor if factor else amount


def _classify_food_key(value: str) -> tuple[str | None, str | None]:
    normalized = _normalize_text(value)
    for family, group, keywords in _FAMILY_GROUP_KEYWORDS:
        for keyword in keywords:
            if _normalize_text(keyword) in normalized:
                return family, group
    if "milk" in normalized:
        return "milk", "dairy_milk"
    if "pasta" in normalized or "noodle" in normalized:
        return "pasta", None
    if "oil" in normalized:
        return "oil", None
    return None, None


def _token_overlap(left: set[str], right: set[str]) -> int:
    return len(left.intersection(right))


def _ingredient_match_score(ingredient: dict, pantry_item: dict) -> int:
    ingredient_name = ingredient.get("canonical", "")
    pantry_name = pantry_item.get("canonical", "")
    if not ingredient_name or not pantry_name:
        return 0

    if ingredient_name == pantry_name or ingredient_name in pantry_name or pantry_name in ingredient_name:
        return 5

    if ingredient.get("family") and ingredient.get("family") == pantry_item.get("family"):
        if ingredient.get("group") and pantry_item.get("group"):
            return 4 if ingredient.get("group") == pantry_item.get("group") else 0
        if ingredient.get("group") and not pantry_item.get("group"):
            return 1
        return 3

    ingredient_tokens = set(ingredient_name.split())
    pantry_tokens = set(pantry_name.split())
    overlap = _token_overlap(ingredient_tokens, pantry_tokens)
    if overlap >= 2:
        return 2
    if overlap == 1:
        return 1
    return 0


def _parse_numeric(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if parsed > 0 else None
    text = str(value or "").strip()
    if not text:
        return None
    if "/" in text:
        numerator, _, denominator = text.partition("/")
        try:
            left = float(numerator)
            right = float(denominator)
            if right != 0:
                return left / right
        except ValueError:
            return None
    try:
        parsed = float(text)
        return parsed if parsed > 0 else None
    except ValueError:
        return None


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
        family, group = _classify_food_key(canonical)
        unit = str(item.get("unit", "unit") or "unit")
        profiles.append(
            {
                "id": item.get("id"),
                "display_name": name,
                "canonical": canonical,
                "quantity": numeric_quantity,
                "unit": unit,
                "comparable_quantity": _to_comparable_amount(numeric_quantity, unit),
                "category": str(item.get("category", "")).strip().lower(),
                "family": family,
                "group": group,
            }
        )
    return profiles


def _best_pantry_matches(ingredient: dict, pantry_profiles: list[dict]) -> list[dict]:
    return sorted(
        [
            {**pantry_item, "match_score": _ingredient_match_score(ingredient, pantry_item)}
            for pantry_item in pantry_profiles
            if _ingredient_match_score(ingredient, pantry_item) > 0
        ],
        key=lambda item: (-item["match_score"], item.get("comparable_quantity", 0.0)),
    )


def _matches_pantry(ingredient_name: str, pantry_profiles: list[dict]) -> bool:
    if not ingredient_name:
        return False
    if ingredient_name in _BASIC_STAPLES:
        return True
    family, group = _classify_food_key(ingredient_name)
    ingredient = {
        "canonical": ingredient_name,
        "family": family,
        "group": group,
    }
    return bool(_best_pantry_matches(ingredient, pantry_profiles))


def _format_pantry_for_prompt(pantry_profiles: list[dict]) -> str:
    return "\n".join(
        f"- {item['display_name']} | canonical: {item['canonical']} | available: {item['quantity']:g} {item['unit']}"
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
- For every non-staple ingredient, set `item` to the exact pantry item name from the list above.
- Every ingredient must include a numeric `amount` and a `unit`.
- Keep amounts realistic and modest relative to the available pantry quantity.
- Keep recipes realistic for an ordinary home kitchen.
- Prefer 4 to 8 ingredients and 3 to 6 steps.
- If the pantry is sparse, suggest simple meals instead of forcing complex dishes.
- Prefer exact pantry names over generic ingredient labels when possible.
- Avoid duplicate recipe ideas.
- Return ONLY valid JSON.

Return this exact shape:
{{
  "recipes": [
    {{
      "title": "Recipe Name",
      "ingredients": [
        {{
          "item": "Great Value Olive Oil",
          "name": "olive oil",
          "amount": 2,
          "unit": "tbsp",
          "optional": false
        }}
      ],
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


def _coerce_recipe_ingredient(raw_ingredient: Any) -> dict | None:
    if isinstance(raw_ingredient, dict):
        pantry_item_name = str(
            raw_ingredient.get("item")
            or raw_ingredient.get("pantry_item")
            or raw_ingredient.get("pantryItem")
            or ""
        ).strip()
        name = str(
            raw_ingredient.get("name")
            or raw_ingredient.get("ingredient")
            or pantry_item_name
            or ""
        ).strip()
        if not name:
            return None
        amount = _parse_numeric(raw_ingredient.get("amount"))
        unit = str(raw_ingredient.get("unit") or "").strip() or "unit"
        canonical = _canonical_food_name(name or pantry_item_name)
        family, group = _classify_food_key(canonical)
        return {
            "item": pantry_item_name or None,
            "name": name,
            "amount": amount or 1.0,
            "unit": unit,
            "canonical": canonical,
            "family": family,
            "group": group,
            "optional": bool(raw_ingredient.get("optional", False)),
        }

    ingredient_text = str(raw_ingredient or "").strip()
    if not ingredient_text:
        return None

    match = re.match(r"^(\d+(?:\.\d+)?(?:\/\d+(?:\.\d+)?)?|\d+\/\d+)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)\s+(.+)$", ingredient_text)
    if match:
        amount = _parse_numeric(match.group(1)) or 1.0
        unit = match.group(2).strip()
        name = match.group(3).strip()
    else:
        amount = 1.0
        unit = "unit"
        name = ingredient_text

    canonical = _canonical_food_name(name)
    family, group = _classify_food_key(canonical)
    return {
        "item": None,
        "name": name,
        "amount": amount,
        "unit": unit,
        "canonical": canonical,
        "family": family,
        "group": group,
        "optional": False,
    }


def _ingredient_display(ingredient: dict) -> str:
    amount = ingredient.get("amount")
    unit = ingredient.get("unit") or "unit"
    name = ingredient.get("name") or ingredient.get("item") or "ingredient"
    if amount is None:
        return str(name)
    amount_text = int(amount) if float(amount).is_integer() else round(float(amount), 2)
    if _normalize_unit(unit) == "unit":
        return f"{amount_text} {name}"
    return f"{amount_text} {unit} {name}"


def _merge_duplicate_ingredients(ingredients: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: dict[str, int] = {}
    for ingredient in ingredients:
        key = str(ingredient.get("canonical") or ingredient.get("name") or "").strip().lower()
        if key in seen:
            existing = merged[seen[key]]
            existing_amount = _to_comparable_amount(float(existing.get("amount") or 0.0), existing.get("unit"))
            incoming_amount = _to_comparable_amount(float(ingredient.get("amount") or 0.0), ingredient.get("unit"))
            total_amount = existing_amount + incoming_amount
            existing["amount"] = round(_from_comparable_amount(total_amount, existing.get("unit")), 2)
            existing["display"] = _ingredient_display(existing)
        else:
            normalized = {**ingredient}
            normalized["display"] = _ingredient_display(normalized)
            seen[key] = len(merged)
            merged.append(normalized)
    return merged


def _is_cooking_fat(item: dict) -> bool:
    canonical = item.get("canonical", "")
    family = item.get("family")
    return family == "oil" or canonical in {"butter", "olive oil", "vegetable oil"}


def _is_breakfast_cereal(item: dict) -> bool:
    canonical = item.get("canonical", "")
    return "cereal" in canonical or "granola" in canonical


def _is_savory_main(item: dict) -> bool:
    canonical = item.get("canonical", "")
    category = item.get("category", "")
    family = item.get("family")
    if canonical in _BASIC_STAPLES or _is_cooking_fat(item):
        return False
    if _is_breakfast_cereal(item):
        return False
    if family == "milk":
        return False
    if any(token in category for token in {"protein", "meat", "veg", "vegetable", "carb", "grain"}):
        return True
    return any(token in canonical for token in {"chicken", "beef", "rice", "pasta", "bean", "tomato", "pepper", "onion", "bread", "egg", "cheese"})


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

    normalized_ingredients: list[dict] = []
    matched_pantry_count = 0
    remaining_quantities = {
        str(profile.get("id") or profile["display_name"]): float(profile.get("comparable_quantity", 0.0))
        for profile in pantry_profiles
    }
    for ingredient in raw_ingredients[:10]:
        normalized_ingredient = _coerce_recipe_ingredient(ingredient)
        if not normalized_ingredient:
            continue
        normalized_name = normalized_ingredient["canonical"]
        if not normalized_name:
            continue
        amount = normalized_ingredient.get("amount") or 1.0
        unit = normalized_ingredient.get("unit") or "unit"
        comparable_needed = _to_comparable_amount(float(amount), unit)

        if normalized_name in _BASIC_STAPLES:
            normalized_ingredients.append(
                {
                    **normalized_ingredient,
                    "item": normalized_ingredient.get("item") or normalized_ingredient.get("name"),
                    "display": _ingredient_display(normalized_ingredient),
                }
            )
            continue

        exact_item_name = str(normalized_ingredient.get("item") or "").strip()
        matched_profile = None
        if exact_item_name:
            matched_profile = next(
                (profile for profile in pantry_profiles if profile["display_name"].strip().lower() == exact_item_name.lower()),
                None,
            )

        if matched_profile is None:
            matches = _best_pantry_matches(normalized_ingredient, pantry_profiles)
            matched_profile = matches[0] if matches else None

        if matched_profile is None:
            return None

        profile_key = str(matched_profile.get("id") or matched_profile["display_name"])
        if remaining_quantities.get(profile_key, 0.0) + 1e-6 < comparable_needed:
            return None

        matched_pantry_count += 1
        remaining_quantities[profile_key] = remaining_quantities.get(profile_key, 0.0) - comparable_needed
        normalized_ingredients.append(
            {
                **normalized_ingredient,
                "item": matched_profile["display_name"],
                "family": matched_profile.get("family") or normalized_ingredient.get("family"),
                "group": matched_profile.get("group") or normalized_ingredient.get("group"),
                "canonical": matched_profile.get("canonical") or normalized_name,
                "display": _ingredient_display(
                    {
                        **normalized_ingredient,
                        "name": normalized_ingredient.get("name") or matched_profile["canonical"],
                    }
                ),
            }
        )

    normalized_ingredients = _merge_duplicate_ingredients(normalized_ingredients)

    minimum_matches = 1 if len(pantry_profiles) <= 2 else 2
    if len(normalized_ingredients) < minimum_matches or matched_pantry_count < minimum_matches:
        return None

    non_staple_unique = {
        str(ingredient.get("item") or ingredient.get("canonical") or "").strip().lower()
        for ingredient in normalized_ingredients
        if ingredient.get("canonical") not in _BASIC_STAPLES
    }
    if len(non_staple_unique) < minimum_matches:
        return None

    if any(
        _is_breakfast_cereal(ingredient) and any(_is_savory_main(other) for other in normalized_ingredients if other is not ingredient)
        for ingredient in normalized_ingredients
    ):
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
    ingredients: list[dict],
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
    savory_items = [item for item in pantry_profiles if _is_savory_main(item)]
    non_bread_names = [
        item["display_name"] for item in pantry_profiles if "bread" not in item["canonical"]
    ]
    seen_titles: set[str] = set()
    fallback: list[dict] = []

    def add_recipe(recipe: dict | None) -> None:
        if recipe and len(fallback) < 3:
            fallback.append(recipe)

    pasta_item = next((item for item in pantry_profiles if item.get("family") == "pasta"), None)
    milk_item = next((item for item in pantry_profiles if item.get("family") == "milk"), None)
    olive_oil_item = next(
        (
            item
            for item in pantry_profiles
            if item.get("group") == "olive_oil" or item.get("canonical") == "olive oil"
        ),
        None,
    )
    tomato_item = next((item for item in pantry_profiles if "tomato" in item.get("canonical", "")), None)
    cheese_item = next(
        (item for item in pantry_profiles if "cheese" in item.get("canonical", "")),
        None,
    )
    cereal_item = next((item for item in pantry_profiles if _is_breakfast_cereal(item)), None)

    if cereal_item and milk_item:
        add_recipe(
            _make_recipe(
                f"{cereal_item['display_name']} with Milk",
                [
                    {"item": cereal_item["display_name"], "name": "cereal", "amount": 1, "unit": "cup", "canonical": cereal_item["canonical"]},
                    {"item": milk_item["display_name"], "name": "milk", "amount": 1, "unit": "cup", "canonical": milk_item["canonical"], "family": milk_item.get("family"), "group": milk_item.get("group")},
                ],
                [
                    "Pour the cereal into a bowl.",
                    "Add the milk and serve immediately.",
                ],
                "2 minutes",
                seen_titles,
            )
        )

    if pasta_item and olive_oil_item:
        add_recipe(
            _make_recipe(
                f"{pasta_item['display_name']} with Garlic Oil",
                [
                    {"item": pasta_item["display_name"], "name": "pasta", "amount": 8, "unit": "oz", "canonical": pasta_item["canonical"], "family": pasta_item.get("family"), "group": pasta_item.get("group")},
                    {"item": olive_oil_item["display_name"], "name": "olive oil", "amount": 2, "unit": "tbsp", "canonical": olive_oil_item["canonical"], "family": olive_oil_item.get("family"), "group": olive_oil_item.get("group")},
                    {"item": "Garlic", "name": "garlic", "amount": 2, "unit": "cloves", "canonical": "garlic"},
                    {"item": "Salt", "name": "salt", "amount": 0.5, "unit": "tsp", "canonical": "salt"},
                    {"item": "Pepper", "name": "pepper", "amount": 0.25, "unit": "tsp", "canonical": "pepper"},
                ],
                [
                    "Boil the pasta in salted water until tender.",
                    "Warm the olive oil with minced garlic in a skillet just until fragrant.",
                    "Toss the drained pasta with the garlic oil, then season with salt and pepper before serving.",
                ],
                "20 minutes",
                seen_titles,
            )
        )

    if pasta_item and milk_item and cheese_item:
        add_recipe(
            _make_recipe(
                f"Creamy {pasta_item['display_name']}",
                [
                    {"item": pasta_item["display_name"], "name": "pasta", "amount": 8, "unit": "oz", "canonical": pasta_item["canonical"], "family": pasta_item.get("family"), "group": pasta_item.get("group")},
                    {"item": milk_item["display_name"], "name": "milk", "amount": 1, "unit": "cup", "canonical": milk_item["canonical"], "family": milk_item.get("family"), "group": milk_item.get("group")},
                    {"item": cheese_item["display_name"], "name": "cheese", "amount": 4, "unit": "oz", "canonical": cheese_item["canonical"]},
                    {"item": "Butter", "name": "butter", "amount": 1, "unit": "tbsp", "canonical": "butter"},
                    {"item": "Salt", "name": "salt", "amount": 0.5, "unit": "tsp", "canonical": "salt"},
                    {"item": "Pepper", "name": "pepper", "amount": 0.25, "unit": "tsp", "canonical": "pepper"},
                ],
                [
                    "Cook the pasta until just tender and reserve a splash of cooking water.",
                    "Warm the milk and butter in a skillet, then stir in the cheese until melted.",
                    "Add the pasta, loosen with a little cooking water if needed, and season with salt and pepper.",
                ],
                "25 minutes",
                seen_titles,
            )
        )

    if pasta_item and tomato_item:
        add_recipe(
            _make_recipe(
                f"Tomato {pasta_item['display_name']}",
                [
                    {"item": pasta_item["display_name"], "name": "pasta", "amount": 8, "unit": "oz", "canonical": pasta_item["canonical"], "family": pasta_item.get("family"), "group": pasta_item.get("group")},
                    {"item": tomato_item["display_name"], "name": "tomato", "amount": 2, "unit": "unit", "canonical": tomato_item["canonical"]},
                    *(
                        [{"item": olive_oil_item["display_name"], "name": "olive oil", "amount": 1, "unit": "tbsp", "canonical": olive_oil_item["canonical"], "family": olive_oil_item.get("family"), "group": olive_oil_item.get("group")}]
                        if olive_oil_item
                        else []
                    ),
                    {"item": "Garlic", "name": "garlic", "amount": 2, "unit": "cloves", "canonical": "garlic"},
                    {"item": "Salt", "name": "salt", "amount": 0.5, "unit": "tsp", "canonical": "salt"},
                ],
                [
                    "Cook the pasta until tender.",
                    "Saute the garlic and chopped tomatoes in olive oil until they soften into a quick sauce.",
                    "Toss the pasta with the sauce, season with salt, and serve hot.",
                ],
                "22 minutes",
                seen_titles,
            )
        )

    if "egg" in canonicals or "eggs" in canonicals:
        mix_ins = [
            name
            for name in non_bread_names
            if _canonical_food_name(name) not in {"egg", "eggs"}
        ][:3]
        add_recipe(
            _make_recipe(
                "Pantry Egg Scramble",
                [
                    {"item": "Eggs", "name": "eggs", "amount": 2, "unit": "unit", "canonical": "egg"},
                    *[
                        {"item": name, "name": _canonical_food_name(name), "amount": 1, "unit": "unit", "canonical": _canonical_food_name(name)}
                        for name in mix_ins
                    ],
                    {"item": "Salt", "name": "salt", "amount": 0.5, "unit": "tsp", "canonical": "salt"},
                    {"item": "Pepper", "name": "pepper", "amount": 0.25, "unit": "tsp", "canonical": "pepper"},
                ],
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
        toppings = [item["display_name"] for item in savory_items if "bread" not in item["canonical"]][:3]
        add_recipe(
            _make_recipe(
                "Loaded Pantry Toast",
                [
                    {"item": "Bread", "name": "bread", "amount": 2, "unit": "slices", "canonical": "bread"},
                    *[
                        {"item": name, "name": _canonical_food_name(name), "amount": 1, "unit": "unit", "canonical": _canonical_food_name(name)}
                        for name in toppings
                    ],
                    *(
                        [{"item": olive_oil_item["display_name"], "name": "olive oil", "amount": 1, "unit": "tbsp", "canonical": olive_oil_item["canonical"], "family": olive_oil_item.get("family"), "group": olive_oil_item.get("group")}]
                        if olive_oil_item
                        else []
                    ),
                    {"item": "Salt", "name": "salt", "amount": 0.25, "unit": "tsp", "canonical": "salt"},
                    {"item": "Pepper", "name": "pepper", "amount": 0.25, "unit": "tsp", "canonical": "pepper"},
                ],
                [
                    "Toast or warm the bread until crisp.",
                    "Cook or warm the toppings as needed in a skillet with a little oil.",
                    "Pile the toppings onto the toast and season to taste.",
                ],
                "10 minutes",
                seen_titles,
            )
        )

    core = [item["display_name"] for item in savory_items][:4]
    if len(core) >= 2:
        add_recipe(
            _make_recipe(
                f"{core[0]} and Pantry Skillet",
                [
                    *[
                        {"item": name, "name": _canonical_food_name(name), "amount": 1, "unit": "unit", "canonical": _canonical_food_name(name)}
                        for name in core
                    ],
                    *(
                        [{"item": olive_oil_item["display_name"], "name": "olive oil", "amount": 1, "unit": "tbsp", "canonical": olive_oil_item["canonical"], "family": olive_oil_item.get("family"), "group": olive_oil_item.get("group")}]
                        if olive_oil_item and olive_oil_item["display_name"] not in core
                        else []
                    ),
                    {"item": "Salt", "name": "salt", "amount": 0.5, "unit": "tsp", "canonical": "salt"},
                    {"item": "Pepper", "name": "pepper", "amount": 0.25, "unit": "tsp", "canonical": "pepper"},
                ],
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
                [
                    *[
                        {"item": name, "name": _canonical_food_name(name), "amount": 1, "unit": "unit", "canonical": _canonical_food_name(name)}
                        for name in core
                    ],
                    *(
                        [{"item": olive_oil_item["display_name"], "name": "olive oil", "amount": 1, "unit": "tbsp", "canonical": olive_oil_item["canonical"], "family": olive_oil_item.get("family"), "group": olive_oil_item.get("group")}]
                        if olive_oil_item and olive_oil_item["display_name"] not in core
                        else []
                    ),
                    {"item": "Salt", "name": "salt", "amount": 0.5, "unit": "tsp", "canonical": "salt"},
                    {"item": "Pepper", "name": "pepper", "amount": 0.25, "unit": "tsp", "canonical": "pepper"},
                ],
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
                [
                    *[
                        {"item": name, "name": _canonical_food_name(name), "amount": 1, "unit": "unit", "canonical": _canonical_food_name(name)}
                        for name in core[:3]
                    ],
                    {"item": "Butter", "name": "butter", "amount": 1, "unit": "tbsp", "canonical": "butter"},
                    {"item": "Salt", "name": "salt", "amount": 0.5, "unit": "tsp", "canonical": "salt"},
                    {"item": "Pepper", "name": "pepper", "amount": 0.25, "unit": "tsp", "canonical": "pepper"},
                ],
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
            household_id = (doc.to_dict() or {}).get("householdId")
            if not household_id:
                raise ValueError("Recipe request is missing householdId.")
            items = get_pantry_items(db, household_id=household_id)
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
                    "ingredient_summary": [
                        _ingredient_display(ingredient)
                        for ingredient in recipe.get("ingredients", [])
                        if isinstance(ingredient, dict)
                    ],
                    "instructions": recipe.get("instructions")
                    or " ".join(recipe.get("steps", []))
                    or "",
                    "source": recipe.get("source", "ai-generated"),
                    "estimated_time": estimated_time,
                    "created_at": now,
                    "request_id": doc.id,
                    "householdId": household_id,
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
            household_id = (doc.to_dict() or {}).get("householdId")
            if not household_id:
                raise ValueError("Smart plan request is missing householdId.")
            plan = get_smart_shopping_plan(db, household_id=household_id)
            payload = {
                **plan,
                "status": "complete",
                "updatedAt": utc_now(),
                "requestId": doc.id,
                "householdId": household_id,
            }
            db.collection(SMART_PLAN_COLLECTION).document(doc.id).set(payload, merge=True)
            db.collection(SMART_PLAN_COLLECTION).document(f"{household_id}_current").set(payload, merge=True)
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
            for household_id in get_household_ids(db):
                refresh_analytics_documents(db, household_id)
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
