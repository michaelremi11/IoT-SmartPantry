import os
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

_app = None
_db = None

def get_firebase_app() -> firebase_admin.App:
    global _app
    if _app is not None:
        return _app

    # Try resolving relative to root workspace instead of api/ folder
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "../serviceAccountKey.json")
    project_id = os.getenv("FIREBASE_PROJECT_ID")

    if not os.path.exists(cred_path):
        # Fallback to local
        cred_path = "./serviceAccountKey.json"
        if not os.path.exists(cred_path):
            print(f"[Warning] Service account key not found. Firebase will fail.")
            return None

    cred = credentials.Certificate(cred_path)
    _app = firebase_admin.initialize_app(cred, {"projectId": project_id})
    print(f"[Firebase] Initialized api app for project: {project_id}")
    return _app

def get_firebase_db() -> firestore.client:
    global _db
    if _db is None:
        app = get_firebase_app()
        if app:
            _db = firestore.client()
    return _db
