#!/usr/bin/env python3
"""deploy22 app checks through /api/ingest (chaos2 helpers, adb shell curl on the board).
weather: outdoor temp 45 C (WE-VN04-00, weather-only critical) -> the reasoner report must be accepted (INC-0564 case).
gap: all sensors held at defaults, then silent > 15 min (held api values stop after apiHoldSec = 15 min), then a
critical CO2 2000 ppm -> fast_s (deploy21: 44-46 s after a 17-min silence; expect ~3 s).
usage: python3 verify22.py weather|gap [silent_min]"""
import json, sys, time
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/scripts")
import chaos2 as C
OUT = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_validator"

def cool():
    while C.temp_c() >= 60:
        time.sleep(30)

def watch(node, before, t0, need_ai, limit=1200):
    fast_t = ai_t = None; inc = None; iid = None
    while time.time() - t0 < limit:
        for cand in [i for i in C.ids() if i not in before]:
            ci = C.api(f"/api/incidents/{cand}")
            if not isinstance(ci, dict) or node not in {x.get("node") for x in (ci.get("sensors") or [])}:
                continue
            if iid is None:
                iid = cand
                if ci.get("fast_path"):
                    fast_t = time.time() - t0
            if cand == iid:
                inc = ci
        if inc:
            fin = inc.get("final") or {}
            ran = any("Reasoner v3" in (t.get("msg") or "") or "reasoner" in (t.get("msg") or "").lower() for t in inc.get("timeline") or [])
            if (not need_ai and fast_t) or (fin and not fin.get("preliminary") and inc.get("state") == "done" and ran):
                ai_t = time.time() - t0 if fin and not fin.get("preliminary") else None
                break
        time.sleep(2 if not need_ai else 5)
    return iid, fast_t, ai_t, inc

mode = sys.argv[1]
cool()
if mode == "weather":
    C.reset("10:00")
    time.sleep(10)
    before = set(C.ids()); t0 = time.time()
    if len(sys.argv) > 2 and sys.argv[2] == "ramp":  # gradual heat (a one-step jump reads as a sensor fault)
        for v in (36, 37.5, 39, 40.5, 42, 43.5):
            C.api("/api/ingest", {"node": "WE-VN04-00", "metric": "temp", "value": v}); time.sleep(3)
    C.api("/api/ingest", {"node": "WE-VN04-00", "metric": "temp", "value": 45})
    iid, fast_t, ai_t, inc = watch("WE-VN04-00", before, t0, True)
    fin = (inc or {}).get("final") or {}
    res = {"check": "weather_only_critical", "incident": iid, "roles": (inc or {}).get("roles"), "severity": (inc or {}).get("severity"),
           "fast_s": round(fast_t, 1) if fast_t else None, "ai_update_s": round(ai_t, 1) if ai_t else None,
           "final_model": fin.get("model"), "valid": fin.get("valid"), "errors": fin.get("errors"),
           "first_action": ((fin.get("parsed") or {}).get("action")), "title": (inc or {}).get("title")}
    res["pass"] = bool(iid and "qwen" in str(fin.get("model")) and fin.get("valid") and not fin.get("errors"))
else:
    silent = float(sys.argv[2]) if len(sys.argv) > 2 else 17
    NODE, MET, VAL = (sys.argv[3], sys.argv[4], float(sys.argv[5])) if len(sys.argv) > 5 else ("SR-AQ-KH03-03", "co2", 2000)
    need_ai = NODE.startswith("WE-")  # weather after a silence = the INC-0564 story: also check the AI report
    C.api("/api/inject", {"scenario": "clear"}); C.api("/api/replay", {"poll_ms": 1000})
    d = C.api("/api/sensors")
    for s in d["sensors"]:
        C.api("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": s["default"]})
    time.sleep(15 * 60 + silent * 60)  # 15 min held, then `silent` min with no readings
    cool()
    st = C.api("/api/sensors")
    co2 = [s for s in st["sensors"] if s["node"] == NODE and s["metric"] == MET][0]
    before = set(C.ids()); t0 = time.time()
    C.api("/api/ingest", {"node": NODE, "metric": MET, "value": VAL})
    iid, fast_t, ai_t, inc = watch(NODE, before, t0, need_ai, 900 if need_ai else 300)
    fin = (inc or {}).get("final") or {}
    res = {"check": "critical_after_silence", "silent_min": silent, "sensor_before": {k: co2.get(k) for k in ("status", "quality", "quality_why", "coverage")},
           "sensor": f"{NODE}/{MET}={VAL}", "incident": iid, "fast_s": round(fast_t, 1) if fast_t else None, "ai_update_s": round(ai_t, 1) if ai_t else None, "roles": (inc or {}).get("roles"), "final_model": fin.get("model"), "valid": fin.get("valid"), "errors": fin.get("errors"), "first_action": (fin.get("parsed") or {}).get("action"), "severity": (inc or {}).get("severity"), "title": (inc or {}).get("title")}
    res["pass"] = bool(fast_t and fast_t < 15)
    C.reset("10:00")
json.dump({"result": res, "incident": inc}, open(f"{OUT}/verify_{mode}_{int(time.time())}.json", "w"), indent=1)
print(json.dumps(res))
sys.exit(0 if res["pass"] else 1)
