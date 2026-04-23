import requests
import time
import random
import sys

def run_pi_client(target_ip):
    url = f"http://{target_ip}:8000/pi/telemetry"
    device_id = "pi-client-001"
    
    print(f"Starting Pi Hardware Client...")
    print(f"Target API: {url}")
    print("Reading from i2c/SPI pins... (mocking)")
    
    # Base environments
    temp = 21.0
    hum = 45.0
    
    while True:
        # Simulate slight drift
        temp += random.uniform(-0.5, 0.5)
        hum += random.uniform(-1.0, 1.0)
        
        # Clamp to realistic bounds
        temp = max(15.0, min(30.0, temp))
        hum = max(20.0, min(80.0, hum))
        
        payload = {
            "deviceId": device_id,
            "temperatureC": round(temp, 2),
            "humidityPercent": round(hum, 2),
            "gyro_x": random.uniform(-1, 1),
            "gyro_y": random.uniform(-1, 1),
            "gyro_z": random.uniform(-1, 1)
        }
        
        try:
            res = requests.post(url, json=payload, timeout=5)
            if res.status_code == 200:
                data = res.json()
                print(f"[SUCCESS] Sent Temp: {payload['temperatureC']}C | Hum: {payload['humidityPercent']}% | Comfort Score: {data.get('comfort_score')}")
            else:
                print(f"[ERROR] API returned {res.status_code}: {res.text}")
        except requests.exceptions.RequestException as e:
            print(f"[CONNECTION ERROR] Ensure the backend is running on 0.0.0.0:8000. {e}")
            
        time.sleep(30)

if __name__ == "__main__":
    ip = "127.0.0.1" # Fallback if not specified
    if len(sys.argv) > 1:
        ip = sys.argv[1]
    run_pi_client(ip)
