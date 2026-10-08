"""Host check (mock LLM): rest -> no incidents; air + water alarming 2 polls apart -> ONE incident with both;
return to normal -> no new incident; sustained alarm -> no repeat incident."""
import json, sys, time, urllib.request
B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8094"
def call(p, b=None):
    r = urllib.request.Request(B + p, data=json.dumps(b).encode() if b is not None else None, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=20).read())
ok = True
call("/api/replay", {"poll_ms": 400}); time.sleep(12)
n0 = len(call("/api/incidents")); print("rest, 30 polls: incidents", n0); ok &= n0 == 0
call("/api/sensors", {"node": "SR-AQ-KH03-03", "metric": "co2", "value": 1600}); time.sleep(0.8)
call("/api/sensors", {"node": "WM-WD-KH98-00", "metric": "tds", "value": 800}); time.sleep(10)
inc = call("/api/incidents"); print("air + water alarm:", [(i["id"], i["title"]) for i in inc]); ok &= len(inc) == 1
if inc:
    d = call(f"/api/incidents/{inc[0]['id']}")
    while d["state"] == "running": time.sleep(0.5); d = call(f"/api/incidents/{inc[0]['id']}")
    fl = [(s["role"], s["metric"]) for s in d["sensors"] if not s["context"]]
    print("  flagged:", fl, "| NPU agents:", sum(1 for a in d["agents"] if not a["model"].startswith("context"))); ok &= len(fl) == 2
time.sleep(10); n1 = len(call("/api/incidents")); print("sustained alarm 25 more polls: incidents", n1); ok &= n1 == 1
call("/api/sensors", {"reset_values": True}); time.sleep(12); n2 = len(call("/api/incidents")); print("back to normal: incidents", n2); ok &= n2 == 1
print("ALL OK" if ok else "FAILED")
