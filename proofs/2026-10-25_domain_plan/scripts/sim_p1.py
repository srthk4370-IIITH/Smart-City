"""Board proof for P1 (2026-10-25): two realistic stories through the live app, 1 step = 1 s = one 5-min bucket.
 leak: tank level read from /api/series; if it sits above the node's high mark, it first settles at 80% of the high
       mark for 12 steps (1 h), then drains -1.5 per step for 48 steps (4 h), no refill. Rooftop untouched.
 ac:   SR-AC-KH02-24 setpoint 24, ac_on 1, room 24.5 for 24 steps (2 h), then +0.12 C per step (1.4 C/h) for 30 steps with
       the AC still on (no cooling effect). Rooftop temperature left at its default.
Saves every agent call (prompt, parsed, repairs, claim_flags) + report to SIM_OUT/sim_p1.json."""
import json, os, random, sys, time
sys.path.insert(0, "C:/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/tools")
import stress_app as S
random.seed(11)
OUT = os.environ.get("SIM_OUT", "C:/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/board_p1")
HIGH = 186.5  # NodeLimitsV2 WM-WL-KH98-00 high mark (PLAN.md section 2)


def put(n, m, v):
    S.req("/api/ingest", {"node": n, "metric": m, "value": round(v, 2)})


def leak_steps():
    _, d = S.req("/api/series?node=WM-WL-KH98-00&metric=level&hours=1")
    cur = d["points"][-1][1]
    start = cur if cur < HIGH else 0.8 * HIGH
    if cur >= HIGH:   # settle below the high mark first (60 buckets, before the incident baseline is taken)
        for _ in range(60):
            put("WM-WL-KH98-00", "level", start + random.gauss(0, 0.3)); time.sleep(1)
    steps = [start - 1.5 * (i + 1) for i in range(48)]
    return cur, [[("WM-WL-KH98-00", "level", v + random.gauss(0, 0.3))] for v in steps]


def ac_steps():
    st = [[("SR-AC-KH02-24", "setpoint", 24), ("SR-AC-KH02-24", "ac_on", 1), ("SR-AC-KH02-24", "room_temp", 24.5 + random.gauss(0, .05))] for _ in range(24)]
    st += [[("SR-AC-KH02-24", "ac_on", 1), ("SR-AC-KH02-24", "room_temp", 24.5 + 0.12 * (i + 1) + random.gauss(0, .05))] for i in range(30)]
    return st


res = []
STORIES = [x for x in (("leak_from_tank_level", leak_steps), ("ac_not_cooling_on", ac_steps)) if x[0] in os.environ.get("ONLY", "leak_from_tank_level,ac_not_cooling_on")]
for name, mk in STORIES:
    S.reset("10:00"); time.sleep(40)
    if name.startswith("leak"):
        r = mk(); time.sleep(5)
        before = set(S.incident_ids())
    else:
        before = set(S.incident_ids()); r = mk()
    start, steps = r if name.startswith("leak") else (None, r)
    for vals in steps:
        for n, m, v in vals:
            put(n, m, v)
        time.sleep(1)
    iid, _ = S.wait_new_incident(before, timeout=180)
    if not iid:
        print(f"## {name}: NO INCIDENT", flush=True); res.append({"story": name, "incident": None, "tank_level_read": start}); continue
    inc = S.wait_done(iid, timeout=240) or S.req(f"/api/incidents/{iid}")[1]
    rec = {"story": name, "incident": iid, "tank_level_read": start, "title": inc.get("title"), "severity": inc.get("severity"),
           "agents": [{"ref": a.get("ref"), "role": a.get("role"), "parsed": a.get("parsed"), "repairs": a.get("repairs"),
                       "claim_flags": a.get("claim_flags"), "valid": a.get("valid"), "prompt": a.get("prompt")} for a in inc.get("agents") or []],
           "report": (inc.get("final") or {}).get("parsed")}
    res.append(rec)
    print(f"## {name}: {iid} title={rec['title']!r} sev={rec['severity']}", flush=True)
    for a in rec["agents"]:
        p = a["parsed"] or {}
        rp = [x for x in (a["repairs"] or []) if "post-rule" in x]
        print(f"  {a['ref']} {a['role']}: {p.get('pattern')}/{p.get('status')} cause={p.get('likely_cause')} rules={rp} flags={a['claim_flags']}", flush=True)
json.dump(res, open(f"{OUT}/sim_p1_{os.environ.get('ONLY', 'all')}.json", "w"), indent=1)
S.reset("10:00"); print("done")
