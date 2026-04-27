import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()

def test_firebase():
    print("--- Testing Firebase Connection ---")
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./serviceAccountKey.json")
        print(f"Using Google Application Credentials: {cred_path}")
        
        if not os.path.exists(cred_path):
            print(f"❌ ERROR: serviceAccountKey.json not found at {cred_path}")
            return False

        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            
        db = firestore.client()
        
        collection_name = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
        print(f"Target Collection: {collection_name}")
        
        # Check simple read
        # Convert generator to list to force read
        docs = list(db.collection(collection_name).limit(1).stream())
        print(f"✅ Successful Connection to Firebase! Read access confirmed for '{collection_name}'.")
        return True
    except Exception as e:
        print(f"❌ ERROR: Failed to connect to Firebase: {e}")
        return False

if __name__ == "__main__":
    fb_ok = test_firebase()
    
    if not fb_ok:
        print("\n[Tests Failed]")
        sys.exit(1)
    else:
        print("\n[Firebase Test Passed Successfully]")
