#!/usr/bin/env python3
"""Critical-breach check through the app (final.sh): the room CO2 slider (/api/ingest, one reading per poll) is set
to 2000 ppm, past the 1500 ppm critical limit, and held. Expect the FAST-PATH incident first (fast_path true, rules preliminary, no NPU), then the
AI update on the SAME incident (domain agents + reasoner report). Prints one JSON line; exit 0 = pass.
Uses chaos2.py helpers (adb shell curl on the board). Board heat pacing: waits for < 60 C before the inject."""
import json, sys, time
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/scripts")
import chaos2 as C

while C.temp_c() >= 60:
    time.sleep(30)
C.reset("10:00")
NODE, METRIC = "SR-AQ-KH03-03", "co2"
want = {NODE}
before = set(C.ids())
t0 = time.time()
C.api("/api/ingest", {"node": NODE, "metric": METRIC, "value": 2000})
fast_id, fast_t, ai_t, inc = None, None, None, None
while time.time() - t0 < 1200:
    for cand in [i for i in C.ids() if i not in before]:
        ci = C.api(f"/api/incidents/{cand}")
        if not isinstance(ci, dict):
            continue
        nodes = {x.get("node") for x in (ci.get("sensors") or [])}
        if want and not (nodes & want):
            continue
        if ci.get("fast_path") and fast_id is None:
            fast_id, fast_t = cand, time.time() - t0
        if fast_id == cand:
            inc = ci
    if inc:
        fin = inc.get("final") or {}
        ran_ai = any("Reasoner v3" in (t.get("msg") or "") for t in inc.get("timeline") or [])
        if fin and not fin.get("preliminary") and ran_ai and inc.get("state") == "done":
            ai_t = time.time() - t0
            break
    time.sleep(5)
fin = (inc or {}).get("final") or {}
res = {"fast_incident": fast_id, "fast_s": round(fast_t, 1) if fast_t else None, "ai_update_s": round(ai_t, 1) if ai_t else None,
       "final_model": fin.get("model"), "valid": fin.get("valid"), "severity": (inc or {}).get("severity"),
       "title": (inc or {}).get("title"), "pass": bool(fast_id and ai_t)}
C.reset("10:00")  # sliders back to their defaults
json.dump({"incident": inc, "result": res}, open(f"{C.P}/raw/fastcheck_{int(t0)}.json", "w"), indent=1)
print(json.dumps(res))
sys.exit(0 if res["pass"] else 1)
