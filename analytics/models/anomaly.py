"""
analytics/models/anomaly.py
Detects environmental anomalies from Sense HAT sensor logs.
"""

import os
from typing import Optional

TEMP_HIGH = float(os.getenv("ANOMALY_TEMP_HIGH_C", "30"))
TEMP_LOW  = float(os.getenv("ANOMALY_TEMP_LOW_C", "10"))
HUM_HIGH  = float(os.getenv("ANOMALY_HUMIDITY_HIGH_PERCENT", "80"))
HUM_LOW   = float(os.getenv("ANOMALY_HUMIDITY_LOW_PERCENT", "20"))


def check_environment(temp_c: float, humidity_pct: float) -> list[dict]:
    """
    Check a single sensor reading for anomalies.
    Returns a list of anomaly dicts (empty if all clear).

    Each anomaly dict:
      { "type": str, "message": str, "severity": "warning"|"critical" }
    """
    flags = []

    if temp_c > TEMP_HIGH:
        flags.append({
            "type": "TEMP_HIGH",
            "message": f"Temperature {temp_c}°C exceeds threshold {TEMP_HIGH}°C",
            "severity": "critical" if temp_c > TEMP_HIGH + 5 else "warning",
        })
    elif temp_c < TEMP_LOW:
        flags.append({
            "type": "TEMP_LOW",
            "message": f"Temperature {temp_c}°C is below threshold {TEMP_LOW}°C",
            "severity": "critical" if temp_c < TEMP_LOW - 5 else "warning",
        })

    if humidity_pct > HUM_HIGH:
        flags.append({
            "type": "HUMIDITY_HIGH",
            "message": f"Humidity {humidity_pct}% exceeds threshold {HUM_HIGH}%",
            "severity": "warning",
        })
    elif humidity_pct < HUM_LOW:
        flags.append({
            "type": "HUMIDITY_LOW",
            "message": f"Humidity {humidity_pct}% is below threshold {HUM_LOW}%",
            "severity": "warning",
        })

    return flags
