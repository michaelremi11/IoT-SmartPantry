from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
import os

from ..db.firebase_db import get_firebase_db

router = APIRouter(prefix="/pi", tags=["Raspberry Pi"])

class TelemetryPayload(BaseModel):
    deviceId: str
    temperatureC: float
    humidityPercent: float
    gyro_x: Optional[float] = 0.0
    gyro_y: Optional[float] = 0.0
    gyro_z: Optional[float] = 0.0
    timestamp: Optional[datetime] = None

def calculate_comfort_score(temp: float, hum: float) -> int:
    """
    Weighted average of temperature and humidity stability.
    Ideal Temp: ~21°C.
    Ideal Humidity: ~45%.
    """
    # 0 deviation = 100 points. 10 deg deviation = 0 points.
    temp_dev = abs(temp - 21.0)
    temp_score = 100 - (temp_dev * 10)
    temp_score = max(0, min(100, temp_score))
    
    # Humidity: 0 deviation = 100 points. 30% deviation = 0 points.
    hum_dev = abs(hum - 45.0)
    hum_score = 100 - (hum_dev * 3.33)
    hum_score = max(0, min(100, hum_score))
    
    return int((temp_score * 0.6) + (hum_score * 0.4))

@router.post("/telemetry")
def log_telemetry(payload: TelemetryPayload):
    """
    Receives raw sensor readings from the Pi, calculates Comfort Score,
    and logs all data to Firestore.
    """
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="Database not configured")
    
    comfort = calculate_comfort_score(payload.temperatureC, payload.humidityPercent)

    collection_name = os.getenv("FIRESTORE_LOGS_COLLECTION", "environmentLogs")
    reading = {
        "deviceId": payload.deviceId,
        "temperatureC": payload.temperatureC,
        "humidityPercent": payload.humidityPercent,
        "gyro_x": payload.gyro_x,
        "gyro_y": payload.gyro_y,
        "gyro_z": payload.gyro_z,
        "comfort_score": comfort,
        "timestamp": payload.timestamp or datetime.now(timezone.utc),
    }
        
    try:
        db.collection(collection_name).document().set(reading)
    except Exception as e:
        print(f"Firestore write error: {e}")
        return {"status": "warning", "msg": str(e)}

    return {"status": "success", "comfort_score": comfort}
