import json, sys, time, urllib.request
B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8096"
def call(p, b=None):
    r = urllib.request.Request(B + p, data=json.dumps(b).encode() if b is not None else None, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=20).read())
def titles(): return [i["title"] for i in reversed(call("/api/incidents"))]
ok = True
call("/api/replay", {"poll_ms": 300}); time.sleep(5)
call("/api/sensors", {"node": "SR-AQ-KH03-03", "metric": "co2", "value": 1600}); time.sleep(6)
call("/api/sensors", {"reset_values": True}); time.sleep(6)
call("/api/sensors", {"node": "WM-WD-KH98-00", "metric": "tds", "value": 800}); time.sleep(7)
t = titles(); print("after CO2 alarm, reset, then TDS alarm:", t); ok &= len(t) == 2 and "CO2" not in t[1]
call("/api/sensors", {"reset_values": True}); time.sleep(4)
call("/api/sensors", {"node": "SR-AQ-KH03-03", "metric": "co2", "value": 1700}); time.sleep(7)
t = titles(); print("CO2 raised again:", t[-1:]); ok &= len(t) == 3 and "CO2" in t[2]
print("ALL OK" if ok else "FAILED")
