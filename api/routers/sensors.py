from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from influxdb_client import Point
import os

from ..db.influx_db import get_influx_write_api

router = APIRouter(prefix="/sensors", tags=["Sensors"])

class SensorPayload(BaseModel):
    deviceId: str
    temperatureC: float
    humidityPercent: float
    gyro_x: Optional[float] = 0.0
    gyro_y: Optional[float] = 0.0
    gyro_z: Optional[float] = 0.0
    timestamp: Optional[datetime] = None

@router.post("/log")
def log_sensor_data(payload: SensorPayload):
    """
    Writes Pi telemetry to InfluxDB, serving as the central funnel 
    so the Pi doesn't write direct to the database.
    """
    write_api = get_influx_write_api()
    bucket = os.getenv("INFLUX_BUCKET", "pantry_sensors")
    
    # Write to Influx time-series!
    p = Point("environment_logs") \
        .tag("device", payload.deviceId) \
        .field("temperature", payload.temperatureC) \
        .field("humidity", payload.humidityPercent) \
        .field("gyro_x", payload.gyro_x) \
        .field("gyro_y", payload.gyro_y) \
        .field("gyro_z", payload.gyro_z) \
        .time(payload.timestamp or datetime.now(timezone.utc))
        
    try:
        write_api.write(bucket=bucket, record=p)
    except Exception as e:
        print(f"Influx write error: {e}")
        # Soft fail if DB isn't running yet locally
        return {"status": "warning", "msg": str(e)}

    return {"status": "success"}
