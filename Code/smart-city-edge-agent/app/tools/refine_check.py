"""Through-the-app check of the early alert + refined re-analysis (HANDBOOK 2.39) and the 12 h checks.

Restarts the sensor clock once (1 s polls, so 1 reading = 1 s), lets 45 readings of history build up so the
12 h checks have >= 8 h, then injects scenarios one after another WITHOUT resetting (a reset starts a new
history and correctly drops pending refinements). For each incident it records every stage
(early -> 1.5 h -> 3 h): severity, title, per-sensor pattern/status, revisions, 12 h findings, NPU time.

  python refine_check.py --out DIR [--scenarios stuck_sensor,tank_leak,pm_spike]
"""
import argparse
import json
import time
from pathlib import Path

import stress_app as S


def snap(iid):
    _, d = S.req(f"/api/incidents/{iid}")
    return d if isinstance(d, dict) else {}


def summary(inc):
    agents = {a.get("ref"): a.get("parsed") or {} for a in inc.get("agents") or []}
    sens = []
    for s in inc.get("sensors") or []:
        if s.get("context"):
            continue
        f = agents.get(s["ref"]) or {}
        sens.append({"ref": s["ref"], "metric": s["metric"], "pattern": f.get("pattern"), "status": f.get("status"),
                     "rule": (s.get("rule") or {}).get("pattern"), "long_range": [l.get("text") for l in s.get("long_range") or []]})
    return {"stage": inc.get("refine_stage"), "state": inc.get("state"), "severity": inc.get("severity"),
            "title": inc.get("title"), "rule_title": inc.get("rule_title"), "note": inc.get("refine_note"),
            "revisions": len(inc.get("revisions") or []), "sensors": sens, "total_ms": inc.get("total_ms")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--scenarios", default="stuck_sensor,tank_leak,pm_spike")
    ap.add_argument("--stage-timeout", type=int, default=300)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log = open(out / "refine_check.jsonl", "a", encoding="utf-8")
    S.reset("10:00")
    S.req("/api/mode", {"mode": 3})
    print("building 45 readings of history ...", flush=True)
    time.sleep(48)
    results = []
    for sc in a.scenarios.split(","):
        before = set(S.incident_ids())
        t0 = time.time()
        code, _ = S.req("/api/inject", {"scenario": sc})
        print(f"\n== {sc}: injected ({code})", flush=True)
        iid = None
        while time.time() - t0 < 240 and not iid:
            new = [i for i in S.incident_ids() if i not in before]
            iid = new[0] if new else None
            time.sleep(2)
        if not iid:
            print("  no incident")
            results.append({"scenario": sc, "incident": None})
            continue
        seen, stages = None, []
        t1 = time.time()
        while time.time() - t1 < a.stage_timeout * 3:
            inc = snap(iid)
            sm = summary(inc)
            key = (sm["stage"], sm["state"], sm["revisions"])
            if key != seen and sm["state"] == "done":
                seen = key
                sm["t_since_inject_s"] = round(time.time() - t0, 1)
                stages.append(sm)
                log.write(json.dumps({"scenario": sc, "incident": iid, **sm}) + "\n")
                log.flush()
                (out / f"{iid}_{sm['stage'] or 'none'}.json").write_text(json.dumps(inc, indent=1))
                print(f"  {sm['t_since_inject_s']:6.1f}s {iid} stage={sm['stage']} sev={sm['severity']} title={sm['title']!r}", flush=True)
                for s in sm["sensors"]:
                    print(f"         {s['ref']} {s['metric']}: agent {s['pattern']}/{s['status']} (rule {s['rule']}) 12h={s['long_range']}", flush=True)
                if sm["note"]:
                    print("         note:", sm["note"], flush=True)
            if sm["stage"] == "3h" or (sm["note"] or "").startswith("Not refined"):
                break
            time.sleep(3)
        results.append({"scenario": sc, "incident": iid, "stages": stages})
    (out / "refine_check_summary.json").write_text(json.dumps(results, indent=1))
    ok = sum(1 for r in results if r.get("stages") and r["stages"][-1]["stage"] == "3h")
    print(f"\n==== {ok}/{len(results)} incidents reached the 3 h refinement ====")


if __name__ == "__main__":
    main()
