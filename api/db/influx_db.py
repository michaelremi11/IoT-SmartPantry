import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (resolves regardless of CWD)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS

# Module-level singleton — created once, reused across requests.
_client: InfluxDBClient | None = None


def get_influx_client() -> InfluxDBClient:
    """Return a reusable InfluxDBClient, lazily initialised on first call."""
    global _client
    if _client is None:
        url   = os.getenv("INFLUX_URL", "http://localhost:8086")
        token = (os.getenv("INFLUX_TOKEN") or "").strip()
        org   = (os.getenv("INFLUX_ORG") or "pantry-org").strip()
        _client = InfluxDBClient(url=url, token=token, org=org)
    return _client


def get_influx_write_api():
    client = get_influx_client()
    return client.write_api(write_options=SYNCHRONOUS)


def get_influx_query_api():
    client = get_influx_client()
    return client.query_api()
