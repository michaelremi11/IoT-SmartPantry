"""
diagnose_influx_auth.py
Diagnostic script to isolate the exact cause of the InfluxDB 401.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

url    = os.getenv("INFLUX_URL", "http://localhost:8086")
token  = os.getenv("INFLUX_TOKEN", "").strip()
bucket = os.getenv("INFLUX_BUCKET", "pantry_sensors")
org_name = os.getenv("INFLUX_ORG", "pantry-org").strip()
org_id   = "12797cddf2af8ed3"   # from user's manual verification

print("=" * 60)
print("InfluxDB 401 Diagnostic")
print("=" * 60)
print(f"URL:      {url}")
print(f"Token:    {token[:8]}...{token[-4:]}")
print(f"Org Name: '{org_name}'")
print(f"Org ID:   '{org_id}'")
print(f"Bucket:   '{bucket}'")
print(f"Token repr: {repr(token[:20])}")
print(f"Token len:  {len(token)}")
print()

# --- Test 1: Raw HTTP (replicates the PowerShell test) -----------------------
print("-" * 60)
print("TEST 1: Raw HTTP request (same as PowerShell)")
print("-" * 60)
import httpx

headers = {"Authorization": f"Token {token}"}

# Health endpoint (no auth needed)
try:
    r = httpx.get(f"{url}/health", timeout=5)
    print(f"  /health -> {r.status_code} {r.json()}")
except Exception as e:
    print(f"  /health -> FAILED: {e}")

# Buckets with org NAME
try:
    r = httpx.get(f"{url}/api/v2/buckets", headers=headers, params={"org": org_name}, timeout=5)
    print(f"  /api/v2/buckets?org={org_name} -> {r.status_code}")
    if r.status_code != 200:
        print(f"    Body: {r.text[:200]}")
except Exception as e:
    print(f"  /api/v2/buckets?org={org_name} -> FAILED: {e}")

# Buckets with org ID
try:
    r = httpx.get(f"{url}/api/v2/buckets", headers=headers, params={"orgID": org_id}, timeout=5)
    print(f"  /api/v2/buckets?orgID={org_id} -> {r.status_code}")
    if r.status_code != 200:
        print(f"    Body: {r.text[:200]}")
except Exception as e:
    print(f"  /api/v2/buckets?orgID={org_id} -> FAILED: {e}")

# Query endpoint with org NAME
flux_query = f'from(bucket: "{bucket}") |> range(start: -1h) |> limit(n: 1)'
try:
    r = httpx.post(
        f"{url}/api/v2/query",
        headers={**headers, "Content-Type": "application/vnd.flux", "Accept": "application/csv"},
        params={"org": org_name},
        content=flux_query,
        timeout=10,
    )
    print(f"  POST /api/v2/query?org={org_name} -> {r.status_code}")
    if r.status_code != 200:
        print(f"    Body: {r.text[:200]}")
except Exception as e:
    print(f"  POST /api/v2/query?org={org_name} -> FAILED: {e}")

# Query endpoint with org ID
try:
    r = httpx.post(
        f"{url}/api/v2/query",
        headers={**headers, "Content-Type": "application/vnd.flux", "Accept": "application/csv"},
        params={"org": org_id},
        content=flux_query,
        timeout=10,
    )
    print(f"  POST /api/v2/query?org={org_id} (as name param) -> {r.status_code}")
    if r.status_code != 200:
        print(f"    Body: {r.text[:200]}")
except Exception as e:
    print(f"  POST /api/v2/query?org={org_id} -> FAILED: {e}")

print()

# --- Test 2: influxdb-client with org NAME -----------------------------------
print("-" * 60)
print("TEST 2: influxdb-client with org NAME ('pantry-org')")
print("-" * 60)
from influxdb_client import InfluxDBClient

try:
    client = InfluxDBClient(url=url, token=token, org=org_name)
    # Check health
    health = client.health()
    print(f"  health() -> status={health.status}, message={health.message}")
    # Try query
    query_api = client.query_api()
    tables = query_api.query(flux_query)
    print(f"  query() -> SUCCESS ({sum(len(t.records) for t in tables)} records)")
    client.close()
except Exception as e:
    print(f"  query() -> FAILED: {e}")
    try:
        client.close()
    except:
        pass

print()

# --- Test 3: influxdb-client with org ID -------------------------------------
print("-" * 60)
print("TEST 3: influxdb-client with org ID ('12797cddf2af8ed3')")
print("-" * 60)
try:
    client = InfluxDBClient(url=url, token=token, org=org_id)
    health = client.health()
    print(f"  health() -> status={health.status}, message={health.message}")
    query_api = client.query_api()
    tables = query_api.query(flux_query)
    print(f"  query() -> SUCCESS ({sum(len(t.records) for t in tables)} records)")
    client.close()
except Exception as e:
    print(f"  query() -> FAILED: {e}")
    try:
        client.close()
    except:
        pass

print()

# --- Test 4: Check what the client actually sends ----------------------------
print("-" * 60)
print("TEST 4: Inspect the actual HTTP request the client builds")
print("-" * 60)
try:
    client = InfluxDBClient(url=url, token=token, org=org_name, debug=False)
    conf = client.api_client.configuration
    print(f"  Client host:           {conf.host}")
    print(f"  Auth header present:   {'Authorization' in (client.api_client.default_headers or {})}")
    print(f"  Default headers:       {client.api_client.default_headers}")
    
    auth_header = client.api_client.default_headers.get("Authorization", "")
    print(f"  Authorization value:   '{auth_header[:20]}...'")
    print(f"  Token starts with 'Token ': {auth_header.startswith('Token ')}")
    
    client.close()
except Exception as e:
    print(f"  Inspection failed: {e}")

print()

# --- Test 5: Check org listing to find the REAL org name ---------------------
print("-" * 60)
print("TEST 5: List all orgs via raw API to find the actual org name")
print("-" * 60)
try:
    r = httpx.get(f"{url}/api/v2/orgs", headers=headers, timeout=5)
    print(f"  /api/v2/orgs -> {r.status_code}")
    if r.status_code == 200:
        orgs = r.json().get("orgs", [])
        for o in orgs:
            print(f"    Org name='{o.get('name')}', id='{o.get('id')}'")
    else:
        print(f"    Body: {r.text[:300]}")
except Exception as e:
    print(f"  /api/v2/orgs -> FAILED: {e}")

print()
print("=" * 60)
print("DIAGNOSIS COMPLETE")
print("=" * 60)
