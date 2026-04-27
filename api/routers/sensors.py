from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
import os

from ..db.firebase_db import get_firebase_db

router = APIRouter(prefix="/sensors", tags=["Sensors"])

class SensorPayload(BaseModel):
    deviceId: str
    temperatureC: float
    humidityPercent: float
    gyro_x: Optional[float] = 0.0
    gyro_y: Optional[float] = 0.0
    gyro_z: Optional[float] = 0.0
    timestamp: Optional[datetime] = None

def calculate_comfort_score(temp: float, hum: float) -> int:
    temp_score = max(0, min(100, 100 - abs(temp - 21.0) * 10))
    hum_score = max(0, min(100, 100 - abs(hum - 45.0) * 3.33))
    return int((temp_score * 0.6) + (hum_score * 0.4))

@router.post("/log")
def log_sensor_data(payload: SensorPayload):
    """
    Compatibility endpoint for Pi telemetry.

    New hub code writes directly to Firestore, but this route is kept for older
    scripts and writes to the same Firebase collection.
    """
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")

    collection_name = os.getenv("FIRESTORE_LOGS_COLLECTION", "environmentLogs")
    reading = {
        "deviceId": payload.deviceId,
        "temperatureC": payload.temperatureC,
        "humidityPercent": payload.humidityPercent,
        "gyro_x": payload.gyro_x,
        "gyro_y": payload.gyro_y,
        "gyro_z": payload.gyro_z,
        "comfort_score": calculate_comfort_score(payload.temperatureC, payload.humidityPercent),
        "timestamp": payload.timestamp or datetime.now(timezone.utc),
    }
    try:
        db.collection(collection_name).document().set(reading)
    except Exception as e:
        print(f"Firestore write error: {e}")
        return {"status": "warning", "msg": str(e)}

    return {"status": "success"}
