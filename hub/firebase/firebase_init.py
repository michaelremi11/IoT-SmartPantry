"""
hub/firebase/firebase_init.py
Firebase Admin SDK initialization for the Raspberry Pi hub.
Uses GOOGLE_APPLICATION_CREDENTIALS (service account JSON) for server-side auth.
"""

import os
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

_app = None
_db = None


def get_firebase_app() -> firebase_admin.App:
    """Initialize and return the Firebase Admin app (singleton)."""
    global _app
    if _app is not None:
        return _app

    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./serviceAccountKey.json")
    project_id = os.getenv("FIREBASE_PROJECT_ID")

    if not os.path.exists(cred_path):
        raise FileNotFoundError(
            f"Service account key not found at '{cred_path}'. "
            "Download it from Firebase Console → Project Settings → Service accounts."
        )

    cred = credentials.Certificate(cred_path)
    _app = firebase_admin.initialize_app(cred, {"projectId": project_id})
    print(f"[Firebase] Initialized hub app for project: {project_id}")
    return _app


def get_db() -> firestore.client:
    """Return a Firestore client (singleton)."""
    global _db
    if _db is None:
        get_firebase_app()
        _db = firestore.client()
    return _db
