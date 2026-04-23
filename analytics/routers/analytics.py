import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (resolves regardless of CWD)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from datetime import datetime

from api.db.influx_db import get_influx_client

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/time-series")
def get_sensor_time_series(hours: int = 24, device_id: str = "hub-rpi4-001") -> List[Dict[str, Any]]:
    """
    Query InfluxDB for time-series environment logs for the given device.
    Used by the Analytics engine to compute Comfort Scores and trending bounds.
    """
    print(f'Fetching data for: /time-series')
    client = get_influx_client()
    query_api = client.query_api()
    bucket = os.getenv("INFLUX_BUCKET", "pantry_sensors")
    
    # Flux query: pull fields from our bucket over the last N hours
    # We use pivot so each row has 'temperature', 'humidity', etc. instead of separate rows per field.
    flux_query = f'''
        from(bucket: "{bucket}")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r._measurement == "environment_logs")
          |> filter(fn: (r) => r.device == "{device_id}")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"], desc: true)
    '''
    
    try:
        tables = query_api.query(query=flux_query)
    except Exception as e:
        print(f"InfluxDB query failed in time-series: {e}")
        return []
        
    results = []
    for table in tables:
        for record in table.records:
            if not record.values:
                continue
            # Flatten the pivoted FluxRecord into a dict
            results.append({
                "time": record.get_time().isoformat() if record.get_time() else None,
                "temperature": record.values.get("temperature"),
                "humidity": record.values.get("humidity"),
                "gyro_x": record.values.get("gyro_x"),
                "gyro_y": record.values.get("gyro_y"),
                "gyro_z": record.values.get("gyro_z"),
            })
            
    return results

@router.get("/sustainability")
def get_sustainability_score():
    """
    Query InfluxDB for inventory_action measurement.
    Calculate cooked vs discarded count.
    """
    print(f'Fetching data for: /sustainability')
    client = get_influx_client()
    query_api = client.query_api()
    bucket = os.getenv("INFLUX_BUCKET", "pantry_sensors")
    
    # Query total cooked and discarded
    flux_query = f'''
        from(bucket: "{bucket}")
          |> range(start: -30d)
          |> filter(fn: (r) => r._measurement == "inventory_action")
          |> filter(fn: (r) => r._field == "quantity_changed")
    '''
    
    try:
        tables = query_api.query(query=flux_query)
    except Exception as e:
        print(f"InfluxDB query failed in sustainability: {e}")
        return {
            "cooked_count": 0,
            "discarded_count": 0,
            "total_actions": 0,
            "sustainability_score": 100
        }
        
    cooked = 0
    discarded = 0
    
    for table in tables:
        for record in table.records:
            if not record.values:
                continue
            t = record.values.get("action_type")
            v = record.get_value()
            if v is None:
                continue
            if t == "cooked":
                cooked += v
            elif t == "discarded":
                discarded += v
                
    total = cooked + discarded
    score = int((cooked / total) * 100) if total > 0 else 100
    
    return {
        "cooked_count": cooked,
        "discarded_count": discarded,
        "total_actions": total,
        "sustainability_score": score
    }

@router.get("/status")
def get_live_status(device_id: str = "pi-client-001"):
    print(f'Fetching data for: /status')
    return {"status": "ok", "data": []}

@router.get("/trending")
def get_trending_bounds(device_id: str = "pi-client-001"):
    print(f'Fetching data for: /trending')
    return {"status": "ok", "data": []}

@router.get("/risk")
def get_environmental_risk(device_id: str = "pi-client-001"):
    print(f'Fetching data for: /risk')
    return {"status": "ok", "data": []}

@router.get("/waste-report")
def get_waste_report():
    print(f'Fetching data for: /waste-report')
    client = get_influx_client()
    query_api = client.query_api()
    bucket = os.getenv("INFLUX_BUCKET", "pantry_sensors")
    
    flux = f'''
        from(bucket: "{bucket}")
          |> range(start: -30d)
          |> filter(fn: (r) => r._measurement == "inventory_action")
          |> filter(fn: (r) => r._field == "quantity_changed")
    '''
    try:
        tables = query_api.query(query=flux)
    except Exception as e:
        print(f"InfluxDB query failed in waste-report: {e}")
        return {"waste_report": []}
        
    item_stats = {}
    
    for table in tables:
        for record in table.records:
            if not record.values:
                continue
            item_id = record.values.get("item_id", "unknown")
            action = record.values.get("action_type")
            val = record.get_value()
            if val is None:
                continue
            
            if item_id not in item_stats:
                item_stats[item_id] = {"cooked": 0, "discarded": 0}
            
            if action in ["cooked", "discarded"]:
                item_stats[item_id][action] += val
                
    result = []
    
    from api.db.firebase_db import get_firebase_db
    db = get_firebase_db()
    pantry_col = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    
    name_map = {}
    if db:
        docs = db.collection(pantry_col).stream()
        for doc in docs:
            d = doc.to_dict()
            name_map[doc.id] = d.get("name", doc.id)

    for item_id, stats in item_stats.items():
        total = stats["cooked"] + stats["discarded"]
        waste_rate = (stats["discarded"] / total) * 100 if total > 0 else 0
        if waste_rate > 30:
            suggestion = "Buy Less"
        else:
            suggestion = "Good"
            
        # resolving name
        resolved_name = name_map.get(item_id, item_id)
            
        result.append({
            "item_id": resolved_name, # replaced raw id with name
            "cooked": stats["cooked"],
            "discarded": stats["discarded"],
            "waste_rate": round(waste_rate, 2),
            "suggestion": suggestion
        })
        
    # Sort by waste rate descending
    result.sort(key=lambda x: x["waste_rate"], reverse=True)
    return {"waste_report": result}


@router.get("/historical-sustainability")
def get_historical_sustainability():
    print(f'Fetching data for: /historical-sustainability')
    client = get_influx_client()
    query_api = client.query_api()
    bucket = os.getenv("INFLUX_BUCKET", "pantry_sensors")
    
    # query aggregated by day
    flux = f'''
        from(bucket: "{bucket}")
          |> range(start: -7d)
          |> filter(fn: (r) => r._measurement == "inventory_action")
          |> filter(fn: (r) => r._field == "quantity_changed")
          |> aggregateWindow(every: 1d, fn: sum, createEmpty: false)
    '''
    try:
        tables = query_api.query(query=flux)
    except Exception as e:
        print(f"InfluxDB query failed in historical-sustainability: {e}")
        return {"trend": []} # graceful fallback
        
    daily_stats = {}
    for table in tables:
        for record in table.records:
            if not record.values or not record.get_time():
                continue
            date_str = record.get_time().strftime("%Y-%m-%d")
            action = record.values.get("action_type")
            val = record.get_value()
            if val is None:
                continue
            if date_str not in daily_stats:
                daily_stats[date_str] = {"cooked": 0, "discarded": 0}
            if action in ["cooked", "discarded"]:
                daily_stats[date_str][action] += val
                
    trend = []
    for date_str in sorted(daily_stats.keys()):
        cooked = daily_stats[date_str]["cooked"]
        discarded = daily_stats[date_str]["discarded"]
        total = cooked + discarded
        score = int((cooked / total) * 100) if total > 0 else 100
        trend.append({
            "date": date_str,
            "score": score
        })
        
    return {"trend": trend}


@router.get("/popular-categories")
def get_popular_categories():
    print(f'Fetching data for: /popular-categories')
    # Proxying from Firebase items count to show popular categories 
    from api.db.firebase_db import get_firebase_db
    db = get_firebase_db()
    if not db:
        raise HTTPException(status_code=500, detail="DB not configured")
        
    pantry_col = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
    docs = db.collection(pantry_col).stream()
    
    cats = {}
    for doc in docs:
        c = doc.to_dict().get("category", "misc").lower()
        if not c: c = "misc"
        cats[c] = cats.get(c, 0) + 1
        
    chart_data = [{"category": k, "count": v} for k, v in cats.items()]
    chart_data.sort(key=lambda x: x["count"], reverse=True)
    return {"categories": chart_data}


import httpx
import json

@router.get("/missions")
async def get_missions():
    print(f'Fetching data for: /missions')
    # Basic logic to generate missions
    s_score = get_sustainability_score().get("sustainability_score", 100)
    
    prompt = f"""You are a helpful culinary AI. My current kitchen sustainability score is {s_score}%.
Please generate exactly 3 weekly goals/missions to help me reduce waste and cook better.
Return ONLY valid JSON:
{{
  "missions": [
    "Goal 1",
    "Goal 2",
    "Goal 3"
  ]
}}
"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("http://localhost:11434/api/generate", json={
                "model": "llama3.2:latest",
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }, timeout=30.0)
            
            if response.status_code == 200:
                data = response.json()
                result = json.loads(data["response"])
                return result
    except:
        pass
    
    return {
        "missions": [
            "Use remaining perishables before Friday.",
            "Try 1 new High Impact Purchase recipe.",
            "Keep humidity under 60% to save bread."
        ]
    }

