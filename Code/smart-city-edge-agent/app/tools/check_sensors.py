"""Host check of the live-sensor input path (mock LLM): idle -> no alarms; slider changes -> incidents."""
import json, sys, time, urllib.request
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8093"
def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())
def pats(): return {(s["node"], s["metric"]): (s["pattern"], s["status"]) for r in call("/api/live")["roles"].values() for s in r["sensors"]}
ok = True
s = call("/api/sensors"); print("sensors:", len(s["sensors"]), "noise", s["noise_scale"])
call("/api/replay", {"poll_ms": 500}); time.sleep(12)
inc0 = call("/api/incidents"); bad = {k: v for k, v in pats().items() if v[0] not in ("stable", "vacant", "context") or v[1] not in ("normal",)}
print("idle 24 polls: incidents", len(inc0), "| non-steady sensors:", bad or "none"); ok &= not inc0 and not bad
# slider step: CO2 450 -> 1400 (sustained)
call("/api/sensors", {"node": "SR-AQ-KH03-03", "metric": "co2", "value": 1400}); time.sleep(10)
p = pats()[("SR-AQ-KH03-03", "co2")]; incs = call("/api/incidents")
print("CO2 step to 1400: pattern", p, "| incidents", [(i["id"], i["title"][:60]) for i in incs]); ok &= bool(incs)
if incs:
    d = call(f"/api/incidents/{incs[0]['id']}")
    while d["state"] == "running": time.sleep(1); d = call(f"/api/incidents/{incs[0]['id']}")
    print("  sensors:", [(x["ref"], x["role"], x["metric"], "ctx" if x["context"] else "FLAG") for x in d["sensors"]])
# real-device ingest path
r = call("/api/ingest", {"node": "WE-VN04-00", "metric": "temp", "value": 41}); print("ingest:", r)
src = [x for x in call("/api/sensors")["sensors"] if x["metric"] == "temp" and x["role"] == "weather"][0]["source"]; print("  source:", src); ok &= src == "api"
# noise 0 -> exact constant readings -> stuck-sensor (flatline) detection after 16 identical readings
call("/api/sensors", {"reset_values": True, "noise_scale": 0}); time.sleep(12)
p = pats()[("SR-AQ-KH03-03", "temp")]; print("noise 0, 24 polls: room temp ->", p); ok &= p[0] == "flatline"
call("/api/sensors", {"noise_scale": 1})
print("ALL OK" if ok else "FAILED")
