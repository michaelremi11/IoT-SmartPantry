import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add project root to sys path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import firebase_admin
from firebase_admin import credentials, firestore

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
        {"id": "item_salmon_test", "name": "Atlantic Salmon", "quantity": 1.0, "amount": 1.0, "unit": "filet", "category": "protein", "expiryDate": (now + timedelta(days=2)).strftime("%Y-%m-%d")},
        {"id": "item_spinach_test", "name": "Fresh Spinach", "quantity": 1.0, "amount": 1.0, "unit": "bag", "category": "veg", "expiryDate": (now + timedelta(days=3)).strftime("%Y-%m-%d")},
    ]

    print("Injecting test ingredient items...")
    collection_name = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    for item in items:
        db.collection(collection_name).document(item["id"]).set(item)
        print(f"  Inserted: {item['name']} ({item['category']}) with expiry {item['expiryDate']}")

    print("Success! Test ingredients injected.")

if __name__ == "__main__":
    main()
