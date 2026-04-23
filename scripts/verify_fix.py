import sys
sys.path.insert(0, '.')
from api.db.influx_db import get_influx_client
import os

client = get_influx_client()
health = client.health()
print(f'Health: {health.status}')

q = client.query_api()
bucket = os.getenv('INFLUX_BUCKET', 'pantry_sensors')
tables = q.query(f'from(bucket: "{bucket}") |> range(start: -24h) |> limit(n: 5)')
total = sum(len(t.records) for t in tables)
print(f'Query succeeded: {total} records returned')

# Print a sample record
for t in tables:
    for r in t.records:
        print(f'  Sample: time={r.get_time()}, field={r.get_field()}, value={r.get_value()}')
        break
    break

client.close()
print('ALL GOOD - InfluxDB 401 is FIXED')
