import os
import sys
from pathlib import Path

# Add project root to sys path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone, timedelta

def main():
    print("Connecting to Firebase...")
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./serviceAccountKey.json")
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            "projectId": os.getenv("FIREBASE_PROJECT_ID"),
        })
    
    db = firestore.client()

    now = datetime.now(timezone.utc)
    
    items = [
        {"id": "item_1", "name": "Broccoli", "quantity": 2.0, "unit": "heads", "category": "veg", "expiryDate": (now + timedelta(days=2)).strftime("%Y-%m-%d")},
        {"id": "item_2", "name": "Apples", "quantity": 5.0, "unit": "pcs", "category": "fruit", "expiryDate": (now + timedelta(days=10)).strftime("%Y-%m-%d")},
        {"id": "item_3", "name": "Chicken Breast", "quantity": 1.5, "unit": "lbs", "category": "protein", "expiryDate": (now + timedelta(days=1)).strftime("%Y-%m-%d")},
        {"id": "item_4", "name": "White Rice", "quantity": 10.0, "unit": "lbs", "category": "carb", "expiryDate": (now + timedelta(days=365)).strftime("%Y-%m-%d")},
        {"id": "item_5", "name": "Hot Sauce", "quantity": 1.0, "unit": "bottle", "category": "sauce", "expiryDate": (now + timedelta(days=180)).strftime("%Y-%m-%d")},
        {"id": "item_6", "name": "Coffee Beans", "quantity": 1.0, "unit": "bag", "category": "misc", "expiryDate": (now + timedelta(days=30)).strftime("%Y-%m-%d")},
    ]

    print("Injecting mock inventory items...")
    for item in items:
        # Save to the pantryItems collection
        db.collection("pantryItems").document(item["id"]).set(item)
        print(f"  Inserted: {item['name']} ({item['category']})")

    print("Success! Dummy inventory data injected.")

if __name__ == "__main__":
    main()
