import urllib.request
import json
import time

url = 'http://127.0.0.1:8000/api/evaluate'
payload = {
    "co2_ppm": 1500.0,
    "pm25_ug_m3": 150.0,
    "pm10_ug_m3": 250.0
}
data = json.dumps(payload).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

try:
    print("Testing API...")
    t0 = time.time()
    response = urllib.request.urlopen(req)
    result = response.read().decode('utf-8')
    t1 = time.time()
    print(f"Time taken: {t1-t0:.2f}s")
    print(json.dumps(json.loads(result), indent=2))
except Exception as e:
    print(f"Error: {e}")
