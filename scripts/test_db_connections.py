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

def test_influxdb():
    print("\n--- Testing InfluxDB Connection ---")
    
    url = os.getenv("INFLUX_URL")
    org = os.getenv("INFLUX_ORG")
    bucket = os.getenv("INFLUX_BUCKET")
    token = os.getenv("INFLUX_TOKEN")
    
    print(f"INFLUX_URL: {url}")
    print(f"INFLUX_ORG: {org}")
    print(f"INFLUX_BUCKET: {bucket}")
    print(f"INFLUX_TOKEN: {'[SET]' if token else '[MISSING]'}")

    if not all([url, org, bucket, token]):
        print("❌ ERROR: Missing one or more InfluxDB configuration variables in .env.")
        return False

    try:
        import httpx
        health_url = f"{url.rstrip('/')}/health"
        res = httpx.get(health_url, timeout=5.0)
        
        if res.status_code == 200:
            print(f"✅ Successful Connection to InfluxDB! ({health_url} returned 200 OK)")
            return True
        else:
            print(f"❌ ERROR: InfluxDB returned status {res.status_code}: {res.text}")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: Failed to reach InfluxDB: {e}")
        return False

if __name__ == "__main__":
    fb_ok = test_firebase()
    in_ok = test_influxdb()
    
    if not fb_ok or not in_ok:
        print("\n[Tests Failed]")
        sys.exit(1)
    else:
        print("\n[Tests Passed Successfully]")
