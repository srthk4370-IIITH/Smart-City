"""Through-the-app check of automatic rechecking at 1.5 h and 3 h: does a refinement CURB a warning when the
event has cleared and ELEVATE it when the event got worse? (refine.go curbTo / keep-worst, 2026-10-21)

For each case: reset, build history, inject the scenario, wait for the early analysis; then either clear the
injection right away ("improve": readings go back to normal well before the 1.5 h window) or keep it held
("hold": the event continues/grows). Records severity, per-sensor status and the revision notes at every
stage, plus the SSE change flag ("elevated"/"curbed").
  python recheck_check.py --out DIR [--cases improve:ventilation_failure,hold:ventilation_failure,...]
"""
import argparse, json, threading, time, urllib.request
from pathlib import Path
import stress_app as S

DEFAULT = ("improve:ventilation_failure,improve:tank_leak,improve:power_throttling,improve:stuck_sensor,"
           "improve:pm_spike,hold:ventilation_failure,hold:tank_leak,hold:power_throttling,hold:heat_buildup")
RANK = {"critical": 3, "warning": 2, "sensor_fault": 1, "normal": 0, "fine": 0}
changes = {}

def sse():
    try:
        r = urllib.request.urlopen(S.B + "/api/events", timeout=3600)
        ev = None
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: ") and ev == "incident":
                d = json.loads(line[6:])
                if d.get("refined"):
                    changes[(d["id"], d["refined"])] = d.get("change", "same")
    except Exception:
        pass

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--cases", default=DEFAULT)
    ap.add_argument("--stage-timeout", type=int, default=600); a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=sse, daemon=True).start()
    S.req("/api/mode", {"mode": 3})
    results = []
    for case in a.cases.split(","):
        kind, sc = case.split(":")
        S.reset("10:00"); S.req("/api/mode", {"mode": 3}); time.sleep(48)
        before = set(S.incident_ids()); t0 = time.time()
        S.req("/api/inject", {"scenario": sc})
        iid = None
        while time.time() - t0 < 240 and not iid:
            new = [i for i in S.incident_ids() if i not in before]; iid = new[0] if new else None; time.sleep(2)
        if not iid:
            print(f"{case}: no incident", flush=True); results.append({"case": case, "incident": None}); continue
        while time.time() - t0 < 400:
            _, d = S.req(f"/api/incidents/{iid}")
            if isinstance(d, dict) and d.get("state") != "running":
                break
            time.sleep(2)
        if kind == "improve":
            S.req("/api/inject", {"scenario": "clear"})
        stages, seen = [], set()
        while time.time() - t0 < a.stage_timeout * 2:
            _, d = S.req(f"/api/incidents/{iid}")
            if isinstance(d, dict):
                st = d.get("refine_stage") or "early"
                if d.get("state") != "running" and st not in seen:
                    seen.add(st)
                    revs = d.get("revisions") or []
                    rv = revs[-1] if revs else {}
                    stages.append({"stage": st, "severity": d.get("severity"), "title": d.get("title"),
                                   "sensors": [{k: s.get(k) for k in ("ref", "metric", "pattern", "status", "kept", "curbed", "note")} for s in rv.get("sensors", [])],
                                   "sse_change": changes.get((iid, st))})
                    (out / f"{iid}_{st}.json").write_text(json.dumps(d, indent=1))
                    print(f"{case} {iid} {st:5} sev={d.get('severity'):12} change={changes.get((iid, st))} "
                          + "; ".join(f"{s.get('metric')} {s.get('pattern')}/{s.get('status')} {'CURBED ' if s.get('curbed') else ''}{'KEPT ' if s.get('kept') else ''}{(s.get('note') or '')[:90]}"
                                      for s in rv.get("sensors", [])), flush=True)
                if st == "3h" or (d.get("refine_note") or "").startswith("Not refined"):
                    break
            time.sleep(3)
        sev = [RANK.get(x["severity"], 0) for x in stages]
        verdict = ("curbed" if sev and sev[-1] < sev[0] else "elevated" if sev and sev[-1] > sev[0] else "same")
        results.append({"case": case, "incident": iid, "stages": stages, "verdict": verdict})
        print(f"== {case}: {' -> '.join(x['severity'] for x in stages)} ({verdict})", flush=True)
        S.req("/api/inject", {"scenario": "clear"})
    (out / "recheck_summary.json").write_text(json.dumps(results, indent=1))

if __name__ == "__main__":
    main()
