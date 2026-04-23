import os
import random
import time
from datetime import datetime, timezone
import sys
from pathlib import Path

# Add project root to sys path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

def main():
    url = os.getenv("INFLUX_URL", "http://localhost:8086")
    token = os.getenv("INFLUX_TOKEN", "my-super-secret-auth-token")
    org = os.getenv("INFLUX_ORG", "pantry-org")
    bucket = os.getenv("INFLUX_BUCKET", "pantry_sensors")

    client = InfluxDBClient(url=url, token=token, org=org)
    write_api = client.write_api(write_options=SYNCHRONOUS)

    device_id = "hub-rpi4-001"
    
    print(f"Injecting dummy sensor data into InfluxDB at {url}...")
    print(f"Bucket: {bucket}, Org: {org}, Device: {device_id}")

    # Generate 5 sample points, going back 5 hours
    for i in range(5):
        # Go back `i` hours
        timestamp = int(time.time()) - (i * 3600)
        
        temp = round(random.uniform(20.0, 24.0), 2)
        humidity = round(random.uniform(40.0, 55.0), 2)
        gyro_x = round(random.uniform(-1.0, 1.0), 2)
        gyro_y = round(random.uniform(-1.0, 1.0), 2)
        gyro_z = round(random.uniform(-1.0, 1.0), 2)

        point = Point("environment_logs") \
            .tag("device", device_id) \
            .field("temperature", temp) \
            .field("humidity", humidity) \
            .field("gyro_x", gyro_x) \
            .field("gyro_y", gyro_y) \
            .field("gyro_z", gyro_z) \
            .time(timestamp, write_precision='s')

        write_api.write(bucket=bucket, org=org, record=point)
        print(f"Wrote data - Temp: {temp}C, Hum: {humidity}%, Time: {datetime.fromtimestamp(timestamp, tz=timezone.utc)}")

    print("Success! Dummy data injected.")

if __name__ == "__main__":
    main()
