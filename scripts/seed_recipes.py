import sys
import os
import json
import requests
from datetime import datetime, timezone

# Add parent directory to path so we can import api modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.db.firebase_db import get_firebase_db

def seed_recipes():
    print("Starting bulk seed process...")
    db = get_firebase_db()
    if not db:
        print("Failed to initialize Firebase app. Check your environment/credentials.")
        sys.exit(1)
        
    prompt = """You are a helpful culinary AI. Generate exactly 10 super common household recipes.
Some examples could be Grilled Cheese, Pasta Marinara, Chicken Noodle Soup, PB&J, etc.

Format them EXACTLY as JSON for our database. Ensure your response is just the JSON structure, nothing else.
Here is the JSON schema:
{
  "recipes": [
    {
      "title": "Recipe Name",
      "ingredients": ["1 cup ingredient", "2 tbsp something"],
      "instructions": "Step 1. Step 2. Step 3."
    }
  ]
}
"""
    print("Requesting 10 recipes from Ollama (llama3.2:latest). This might take a minute...")
    try:
        response = requests.post("http://localhost:11434/api/generate", json={
            "model": "llama3.2:latest",
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }, timeout=600.0)
        response.raise_for_status()
        data = response.json()
        result = json.loads(data["response"])
        
        recipes = result.get("recipes", [])
        if not recipes:
            print("No recipes found in Ollama output.")
            sys.exit(1)
            
        print(f"Successfully generated {len(recipes)} recipes. Saving to Firebase...")
        collection_name = os.getenv("FIRESTORE_RECIPES_COLLECTION", "recipes")
        
        for r in recipes:
            doc_ref = db.collection(collection_name).document()
            doc_data = {
                "title": r.get("title", "Untitled"),
                "ingredients": r.get("ingredients", []),
                "instructions": r.get("instructions", ""),
                "source": "common",
                "created_at": datetime.now(timezone.utc)
            }
            doc_ref.set(doc_data)
            print(f"Saved: {doc_data['title']}")
            
        print("Done seeding recipes.")
        
    except Exception as e:
        print(f"Error seeding recipes: {e}")
        sys.exit(1)

if __name__ == "__main__":
    seed_recipes()
