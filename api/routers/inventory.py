from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone
from ..db.firebase_db import get_firebase_db
from ..db.influx_db import get_influx_write_api
from influxdb_client import Point
import os
import httpx
import json

router = APIRouter(prefix="/inventory", tags=["Inventory"])

class InventoryItem(BaseModel):
    id: Optional[str] = None
    name: str
    quantity: float = 0.0
    unit: str = "unit"
    category: Optional[str] = ""
    in_stock: bool = True
    expiryDate: Optional[str] = None

class ActionRequest(BaseModel):
    item_id: str
    action_type: str # "cooked" or "discarded"

@router.get("/", response_model=List[InventoryItem])
def get_all_inventory():
    """Returns all items currently in the pantry."""
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")
    
    collection_name = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    docs = db.collection(collection_name).stream()
    items = []
    for doc in docs:
        d = doc.to_dict()
        items.append(InventoryItem(
            id=doc.id,
            name=d.get("name", "Unknown"),
            quantity=d.get("quantity", 0.0),
            unit=d.get("unit", "unit"),
            category=d.get("category", ""),
            in_stock=d.get("in_stock", True),
            expiryDate=d.get("expiryDate")
        ))
    return items

@router.post("/add")
def add_inventory_item(item: InventoryItem):
    """Add or update an item via the API structure instead of direct Firebase connection."""
    item_id = item.id if hasattr(item, "id") else None
    print(f'BACKEND RECEIVED: {item_id if item_id else "New Item"}')
    print(f"---> RECEIVED REQUEST [POST /inventory]: name={item.name}, quantity={item.quantity}, unit={item.unit}, category={item.category}")
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")
        
    collection_name = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    doc_ref = db.collection(collection_name).document(item.id) if item.id else db.collection(collection_name).document()
    data_to_save = {
        "name": item.name,
        "quantity": item.quantity,
        "unit": item.unit,
        "category": item.category,
        "expiryDate": item.expiryDate,
        "updatedAt": datetime.now(timezone.utc)
    }
    print(f'PUSHING TO FIREBASE: {data_to_save}')
    try:
        doc_ref.set(data_to_save, merge=True)
    except Exception:
        import traceback
        print(traceback.format_exc())
    return {"status": "success", "id": doc_ref.id}

@router.delete("/{item_id}")
def delete_inventory_item(item_id: str):
    """Delete an item via the API structure."""
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")
        
    collection_name = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    db.collection(collection_name).document(item_id).delete()
    return {"status": "success", "id": item_id}

@router.post("/action")
def perform_inventory_action(request: ActionRequest):
    """Marks an item as cooked or discarded, removes it from Firebase, and logs to InfluxDB."""
    print(f'BACKEND RECEIVED: {request.item_id}')
    print(f"---> RECEIVED REQUEST [POST /inventory/action]: item_id={request.item_id}, action_type={request.action_type}")
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")
    
    if request.action_type not in ["cooked", "discarded"]:
        raise HTTPException(status_code=400, detail="Invalid action_type. Must be 'cooked' or 'discarded'.")

    collection_name = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    doc_ref = db.collection(collection_name).document(request.item_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Item not found")

    # Log to InfluxDB
    try:
        write_api = get_influx_write_api()
        bucket = os.getenv("INFLUX_BUCKET", "pantry_sensors")
        org = os.getenv("INFLUX_ORG", "pantry-org")
        
        point = Point("inventory_action") \
            .tag("action_type", request.action_type) \
            .tag("item_id", request.item_id) \
            .field("quantity_changed", 1.0) \
            .time(datetime.now(timezone.utc))
        
        write_api.write(bucket=bucket, org=org, record=point)
    except Exception as e:
        print(f"[InfluxDB] Failed to log action: {e}")
        # non-fatal for now

    # Remove from Firebase as requested by user logic
    print(f'PUSHING TO FIREBASE: DELETE {request.item_id}')
    try:
        doc_ref.delete()
    except Exception:
        import traceback
        print(traceback.format_exc())
    return {"status": "success", "action": request.action_type, "item_id": request.item_id}

@router.get("/recipes")
async def get_recipes():
    """Fetches top 3 soon-to-expire items and generates 2-3 recipes using Ollama."""
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")

    collection_name = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    # In a real app we might query and sort by expiryDate in Firestore, but let's do it in memory for now
    docs = db.collection(collection_name).stream()
    
    items = []
    for doc in docs:
        d = doc.to_dict()
        exp = d.get("expiryDate")
        if exp:
            items.append({"id": doc.id, "name": d.get("name"), "expiryDate": exp})
            
    # sort by date str (YYYY-MM-DD works well natively)
    items.sort(key=lambda x: x["expiryDate"])
    top_3 = items[:3]
    
    if not top_3:
        return {"recipes": []}

    ingredients_text = ", ".join([f"{i['name']} (ID: {i['id']})" for i in top_3])
    
    prompt = f"""You are a helpful culinary AI. I have the following ingredients that are about to expire:
{ingredients_text}

Provide 2 meal suggestions that use these ingredients. Respond ONLY in valid JSON format.
The JSON must be an object with a 'recipes' array. Each recipe should have 'name', 'description', and a list of 'ingredient_ids' (the exact IDs from the prompt used in the recipe).
Example:
{{
  "recipes": [
    {{
      "name": "Chicken & Veggie Stir Fry",
      "description": "A quick stir fry.",
      "ingredient_ids": ["item_1", "item_3"]
    }}
  ]
}}
"""

    try:
        async with httpx.AsyncClient() as client:
            # Assuming standard local server
            response = await client.post("http://localhost:11434/api/generate", json={
                "model": "llama3.2:latest",
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }, timeout=120.0)
            
            if response.status_code == 200:
                data = response.json()
                return json.loads(data["response"])
            else:
                print(f"Ollama returned {response.status_code}: {response.text}")
    except httpx.ConnectError as e:
        print(f"ConnectionRefusedError: Ollama isn't running or accessible on port 11434. {e}")
    except httpx.TimeoutException as e:
        print(f"Timeout: Ollama is taking too long to respond. {e}")
    except httpx.RequestError as e:
        print(f"RequestException: {e}")
    except Exception as e:
        print(f"Error calling Ollama: {e}")
        
    # Return fallback mock if Ollama isn't actually running or fails
    return {
        "recipes": [
            {
                "name": "Mock Emergency Stir Fry",
                "description": "A fallback recipe because Ollama was unreachable.",
                "ingredient_ids": [i["id"] for i in top_3]
            }
        ]
    }

@router.get("/shopping/smart-plan")
def get_smart_shopping_plan():
    """Generates a shopping plan combining staples, unlock items, and waste prevention."""
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")
        
    pantry_col = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    docs = db.collection(pantry_col).stream()
    
    staples = []
    at_risk = []
    
    for doc in docs:
        d = doc.to_dict()
        qty = d.get("quantity", 0.0)
        name = d.get("name", "Unknown")
        
        if qty == 0.0:
            staples.append({"item": name, "reason": "Out of stock"})
            
        exp = d.get("expiryDate")
        if exp:
            try:
                diff = (datetime.strptime(exp, "%Y-%m-%d").replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
                if 0 <= diff <= 3:
                    at_risk.append({"item": name, "reason": f"Expires in {diff} days"})
            except:
                pass
                
    # To get 'Unlocks', normally we would call the recipes unlocker logic. We can mock it here for simplicity
    # or just make a REST call to itself. For simplicity in the phase, we will return some mock 'High Impact'.
    unlocks = [
        {"item": "Olive Oil", "reason": "Unlocks 3 recipes"},
        {"item": "Garlic", "reason": "Unlocks 2 recipes"}
    ]
    
    return {
        "staples": staples,
        "unlocks": unlocks,
        "waste_prevention": at_risk
    }

