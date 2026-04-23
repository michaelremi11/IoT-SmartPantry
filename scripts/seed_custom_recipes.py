import sys
import os
import json
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.db.firebase_db import get_firebase_db

def seed_custom():
    db = get_firebase_db()
    
    file_path = os.path.join(os.path.dirname(__file__), "custom_recipes.json")
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        sys.exit(1)
        
    with open(file_path, "r") as f:
        data = json.load(f)
        
    collection_name = os.getenv("FIRESTORE_RECIPES_COLLECTION", "recipes")
    
    recipes = data.get("recipes", [])
    print(f"Found {len(recipes)} recipes, uploading to Firebase...")
    
    for r in recipes:
        doc_ref = db.collection(collection_name).document()
        doc_data = {
            "title": r.get("title", "Untitled"),
            "ingredients": r.get("ingredients", []),
            "instructions": r.get("instructions", ""),
            "estimated_time": r.get("estimated_time", None),
            "source": "custom",
            "created_at": datetime.now(timezone.utc)
        }
        doc_ref.set(doc_data)
        print(f"Saved: {r['title']}")
        
    print("Done!")

if __name__ == "__main__":
    seed_custom()
