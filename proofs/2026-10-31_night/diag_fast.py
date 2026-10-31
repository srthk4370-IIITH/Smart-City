import json, sys, time
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/scripts")
import chaos2 as C
mode = sys.argv[1]; node, metric, val = sys.argv[2], sys.argv[3], float(sys.argv[4])
print("temp", C.temp_c(), flush=True)
C.api("/api/inject", {"scenario": "clear"})
if mode == "restart":
    C.api("/api/replay", {"restart": True, "clock": "10:00", "poll_ms": 1000})
else:
    C.api("/api/replay", {"poll_ms": 1000})
d = C.api("/api/sensors")
for s in d["sensors"]: C.api("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": s["default"]})
time.sleep(int(sys.argv[5]) if len(sys.argv) > 5 else 0)
st = C.api("/api/status"); print("status", {k: st.get(k) for k in ("poll_ms", "speed", "clock", "sim")} if isinstance(st, dict) else st, flush=True)
before = set(C.ids()); t0 = time.time()
C.api("/api/ingest", {"node": node, "metric": metric, "value": val})
while time.time() - t0 < 120:
    for c in [i for i in C.ids() if i not in before]:
        ci = C.api(f"/api/incidents/{c}")
        if isinstance(ci, dict) and ci.get("fast_path"):
            print("fast", c, round(time.time() - t0, 1), ci.get("title")); before.add(c); t0 = -1; break
    if t0 < 0: break
    time.sleep(1)
C.api("/api/ingest", {"node": node, "metric": metric, "value": [s for s in d["sensors"] if s["node"] == node and s["metric"] == metric][0]["default"]})
