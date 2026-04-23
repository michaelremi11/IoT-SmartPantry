import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.getcwd(), '.env'))
print(f'DEBUG: Found INFLUX_TOKEN: {str(os.getenv("INFLUX_TOKEN"))[:5]}... (Length: {len(os.getenv("INFLUX_TOKEN") if os.getenv("INFLUX_TOKEN") else "")})')

from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
def get_influx_client() -> InfluxDBClient:
    load_dotenv(os.path.join(os.getcwd(), '.env'))
    url = os.getenv("INFLUX_URL", "http://localhost:8086")
    token = (os.getenv("INFLUX_TOKEN") or "").strip()
    org = (os.getenv("INFLUX_ORG") or "pantry-org").strip()
    
    return InfluxDBClient(url=url, token=token, org=org)

def get_influx_write_api():
    client = get_influx_client()
    return client.write_api(write_options=SYNCHRONOUS)
    
def get_influx_query_api():
    client = get_influx_client()
    return client.query_api()
