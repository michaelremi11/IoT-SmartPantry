#!/usr/bin/env python3
"""
Quick Firestore analytics sanity check.

Run from the project root after configuring GOOGLE_APPLICATION_CREDENTIALS.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics.firebase import get_db

db = get_db()
pantry_count = len(list(db.collection(os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")).limit(5).stream()))
usage_count = len(list(db.collection(os.getenv("FIRESTORE_USAGE_LOGS_COLLECTION", "usageLogs")).limit(5).stream()))
env_count = len(list(db.collection(os.getenv("FIRESTORE_LOGS_COLLECTION", "environmentLogs")).limit(5).stream()))

print("Firestore connection OK")
print(f"Sample pantry docs: {pantry_count}")
print(f"Sample usage log docs: {usage_count}")
print(f"Sample environment log docs: {env_count}")
