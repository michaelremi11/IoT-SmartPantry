from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone
import os
import httpx
import json

from ..db.firebase_db import get_firebase_db

router = APIRouter(prefix="/recipes", tags=["Recipes"])

class Recipe(BaseModel):
    id: Optional[str] = None
    title: str
    ingredients: List[str]
    instructions: str
    source: str = "ai-generated" # "common" or "ai-generated"
    estimated_time: Optional[str] = None

@router.get("/", response_model=List[Recipe])
def get_all_recipes():
    """Returns all saved recipes."""
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")
    
    collection_name = os.getenv("FIRESTORE_RECIPES_COLLECTION", "recipes")
    docs = db.collection(collection_name).stream()
    items = []
    for doc in docs:
        d = doc.to_dict()
        items.append(Recipe(
            id=doc.id,
            title=d.get("title", "Unknown"),
            ingredients=d.get("ingredients", []),
            instructions=d.get("instructions", ""),
            source=d.get("source", "unknown"),
            estimated_time=d.get("estimated_time", None)
        ))
    return items

@router.post("/discover", response_model=List[Recipe])
async def discover_recipes():
    """Reads current pantry, sends to Ollama, and saves new recipes to Firebase."""
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")

    # Get pantry items
    pantry_col = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    docs = db.collection(pantry_col).stream()
    ingredients = [doc.to_dict().get("name", "Unknown") for doc in docs]
    
    if not ingredients:
        return []

    ingredients_text = ", ".join(ingredients)
    
    prompt = f"""You are a helpful culinary AI. I have the following ingredients:
{ingredients_text}

Based on these ingredients, suggest 3 new amazing recipes I can make. 
Format them EXACTLY as JSON for our database. Ensure your response is just the JSON structure, nothing else.
Here is the JSON schema:
{{
  "recipes": [
    {{
      "title": "Recipe Name",
      "ingredients": ["1 cup ingredient", "2 tbsp something"],
      "instructions": "Step 1. Step 2. Step 3."
    }}
  ]
}}
"""

    recipesCollection = os.getenv("FIRESTORE_RECIPES_COLLECTION", "recipes")
    new_recipes = []

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("http://localhost:11434/api/generate", json={
                "model": "llama3.2:latest",
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }, timeout=300.0)
            
            if response.status_code == 200:
                data = response.json()
                result = json.loads(data["response"])
                
                # Save each to firebase
                for r in result.get("recipes", []):
                    doc_ref = db.collection(recipesCollection).document()
                    doc_data = {
                        "title": r.get("title", "Untitled"),
                        "ingredients": r.get("ingredients", []),
                        "instructions": r.get("instructions", ""),
                        "source": "ai-generated",
                        "created_at": datetime.now(timezone.utc)
                    }
                    doc_ref.set(doc_data)
                    new_recipes.append(Recipe(id=doc_ref.id, **doc_data))
                    
            else:
                print(f"Ollama returned {response.status_code}: {response.text}")
                raise HTTPException(status_code=502, detail="Ollama error")

    except Exception as e:
        print(f"Error calling Ollama: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
    return new_recipes

import re

def parse_ingredient_amount(ingredient_str: str) -> float:
    if not ingredient_str or not isinstance(ingredient_str, str):
        return 1.0
    match = re.search(r'^([\d\.]+)', ingredient_str)
    if not match:
        return 1.0
    try:
        val = float(match.group(1))
    except ValueError:
        return 1.0
        
    low = ingredient_str.lower()
    if "cup" in low:
        return val * 8.0 
    elif "tbsp" in low or "tablespoon" in low:
        return val * 0.5 
    elif "tsp" in low or "teaspoon" in low:
        return val * 0.16 
    elif "oz" in low or "ounce" in low:
        return val
    elif "lb" in low or "pound" in low:
        return val * 453.59 
    elif "g " in low or "gram" in low:
        return val
    elif "ml" in low or "milliliter" in low:
        return val * 0.0338 
    return val

@router.post("/{recipe_id}/cook")
def cook_recipe(recipe_id: str):
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")
        
    recipes_col = os.getenv("FIRESTORE_RECIPES_COLLECTION", "recipes")
    pantry_col = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    
    recipe_doc = db.collection(recipes_col).document(recipe_id).get()
    if not recipe_doc.exists:
        raise HTTPException(status_code=404, detail="Recipe not found")
        
    recipe_data = recipe_doc.to_dict()
    ingredients = recipe_data.get("ingredients", [])
    
    pantry_docs = db.collection(pantry_col).stream()
    pantry_items = {doc.id: doc.to_dict() for doc in pantry_docs}
    
    deducted = []
    
    for ing_str in ingredients:
        amount_to_deduct = parse_ingredient_amount(ing_str)
        
        for pid, item_data in pantry_items.items():
            db_name = item_data.get("name", "").lower()
            if db_name and (db_name in ing_str.lower() or ing_str.lower() in db_name):
                # Ensure we handle null amounts/quantities gracefully
                amount_val = item_data.get("amount")
                quantity_val = item_data.get("quantity")
                current_qty = float(amount_val if amount_val is not None else (quantity_val if quantity_val is not None else 0.0))
                
                # Ensure we don't go below 0
                new_qty = max(0.0, current_qty - amount_to_deduct)
                
                db.collection(pantry_col).document(pid).set({"amount": new_qty, "quantity": new_qty}, merge=True)
                pantry_items[pid]["amount"] = new_qty
                pantry_items[pid]["quantity"] = new_qty
                
                deducted.append({"item_id": pid, "deducted": amount_to_deduct, "new_amount": new_qty})
                break
                
    return {"status": "success", "message": "Ingredients deducted", "deducted": deducted}

from collections import Counter

@router.get("/unlocker")
def get_recipe_unlocks():
    """
    Finds recipes that are 1 or 2 ingredients away from being 'ready to cook'.
    Returns the top 3 missing ingredients that would unlock the most recipes.
    """
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")
        
    recipes_col = os.getenv("FIRESTORE_RECIPES_COLLECTION", "recipes")
    pantry_col = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    
    recipes_docs = db.collection(recipes_col).stream()
    recipes = [doc.to_dict() for doc in recipes_docs]
    
    pantry_docs = db.collection(pantry_col).stream()
    pantry_items = [doc.to_dict().get("name", "").lower() for doc in pantry_docs]
    
    missing_counter = Counter()
    
    for r in recipes:
        missing_here = []
        for ing in r.get("ingredients", []):
            # check if ingredient string contains any pantry item name
            matched = any(p in ing.lower() or ing.lower() in p for p in pantry_items if p)
            if not matched:
                # normalize the missing ingredient name to avoid duplicates like "1 cup milk" vs "2 tbsp milk"
                # a simple heuristic: remove quantities and use the last word, or just use the whole string
                words = ing.split()
                if len(words) > 1:
                    clean_name = " ".join(words[-2:]) # "cup milk" -> "milk" or "olive oil" -> "olive oil"
                else:
                    clean_name = ing
                missing_here.append(clean_name.lower())
                
        # If the recipe is close to being unlocked
        if 1 <= len(missing_here) <= 2:
            for m in missing_here:
                missing_counter[m] += 1
                
    top_3 = [{"ingredient": k, "unlocks": v} for k, v in missing_counter.most_common(3)]
    
    return {"high_impact_purchases": top_3}
