"""
hub/sensors/sense_hat_logger.py
Reads temperature and humidity from the Sense HAT and logs
readings to Firestore on a configurable interval.
"""

import os
import time
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
import httpx

load_dotenv()

logger = logging.getLogger(__name__)

# Fallback stub when running off-device (e.g. development on desktop)
try:
    from sense_hat import SenseHat
    _SENSE_AVAILABLE = True
except (ImportError, Exception):
    _SENSE_AVAILABLE = False
    logger.warning("[SenseHAT] sense_hat not available — using simulated values.")


class EnvironmentLogger:
    """Periodically reads Sense HAT sensors and writes to Firestore."""

    COLLECTION = os.getenv("FIRESTORE_LOGS_COLLECTION", "environmentLogs")
    DEVICE_ID = os.getenv("HUB_DEVICE_ID", "hub-rpi4-001")
    INTERVAL = int(os.getenv("HUB_TEMP_LOG_INTERVAL_SECONDS", "300"))

    API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

    def __init__(self):
        self.sense = SenseHat() if _SENSE_AVAILABLE else None

    def _read(self) -> dict:
        if self.sense:
            temp = round(self.sense.get_temperature(), 2)
            humidity = round(self.sense.get_humidity(), 2)
        else:
            # Simulated values for development / testing
            import random
            temp = round(20.0 + random.uniform(-2, 5), 2)
            humidity = round(50.0 + random.uniform(-10, 15), 2)

        return {
            "deviceId": self.DEVICE_ID,
            "temperatureC": temp,
            "humidityPercent": humidity,
            "timestamp": datetime.now(timezone.utc),
        }

    def log_once(self) -> dict:
        """Read sensors and push one record to API. Returns the record."""
        reading = self._read()
        try:
            # Send reading to Central API which routes to InfluxDB
            reading["timestamp"] = reading["timestamp"].isoformat()
            res = httpx.post(f"{self.API_URL}/sensors/log", json=reading, timeout=5.0)
            res.raise_for_status()
            logger.info(
                f"[SenseHAT] API Logged: {reading['temperatureC']}°C / "
                f"{reading['humidityPercent']}% RH"
            )
        except Exception as exc:
            logger.error(f"[SenseHAT] API Error log_once: {exc}")
        return reading

    def run_loop(self):
        """Blocking loop — logs a reading every INTERVAL seconds."""
        logger.info(
            f"[SenseHAT] Starting logger loop — interval: {self.INTERVAL}s"
        )
        while True:
            try:
                self.log_once()
            except Exception as exc:
                logger.error(f"[SenseHAT] Logging error: {exc}")
            time.sleep(self.INTERVAL)
