"""
hub/main.py
Entry point for the Smart Pantry Hub application.
Run with:  python main.py
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

from hub.ui import run

if __name__ == "__main__":
    import os
    from hub.firebase import get_firebase_app

    print("🥦 Smart Pantry Hub starting...")
    
    # Pre-flight check: Firebase credentials
    try:
        get_firebase_app()
    except Exception as e:
        print(f"❌ Initialization Error: {e}")
        print("Please ensure GOOGLE_APPLICATION_CREDENTIALS is set in .env correctly.")
        exit(1)

    run()
