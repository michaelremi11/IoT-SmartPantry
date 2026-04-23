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
    print("🥦 Smart Pantry Hub starting...")
    # Connecting to Central API Server on localhost over HTTP
    run()
