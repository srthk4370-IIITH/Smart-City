#!/usr/bin/env python3
"""2026-11-02 measure-only: realistic sensor stories through the running app (/api/ingest sliders = the user is the sensor),
live 2B reasoner. Per story: board <= 60 C first, reset (clear + replay restart + sliders to default), apply the ramp,
then follow every new incident on the story's nodes until the AI report is in (state done, final not preliminary,
'Reasoner v3' in the timeline) or 900 s. Saves raw incident JSON + new htpd.log lines per story; prints one JSON line each.
usage (WSL): python3 -I stories.py [story ...]"""
import json, os, sys, time
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/scripts")
import chaos2 as C
O = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-02_2b_board/app"
os.makedirs(O + "/raw", exist_ok=True)
CO2, RT, OCC = ("SR-AQ-KH03-03", "co2"), ("SR-AQ-KH03-03", "temp"), ("SR-OC-GW-KH95-01", "occ")
WT = ("WE-VN04-00", "temp"); PH = ("WM-WD-KH98-00", "ph"); PM = ("AQ-KN00-00", "pm25")
# (name, expectation, steps [(seconds to wait before, [(node, metric, value)])], nodes to follow, settle_s)
S = {
 "normal_drift": ("no incident: CO2 450->780 ppm as people arrive, outdoor 30->33 C (all inside limits)",
   [(0, [(*OCC, 1)]), (10, [(*CO2, 520)]), (10, [(*CO2, 590), (*WT, 31)]), (10, [(*CO2, 660)]), (10, [(*CO2, 720), (*WT, 32)]), (10, [(*CO2, 780), (*WT, 33)])],
   {CO2[0], WT[0]}, 300),
 "co2_real_rise": ("real event: occupied room, CO2 climbs 700->1700 ppm over ~1 min, room 25->27 C -> warning/critical, NOT sensor_fault",
   [(0, [(*OCC, 1), (*CO2, 700)]), (8, [(*CO2, 850)]), (8, [(*CO2, 1000), (*RT, 25.8)]), (8, [(*CO2, 1150)]), (8, [(*CO2, 1300), (*RT, 26.4)]),
    (8, [(*CO2, 1450)]), (8, [(*CO2, 1600), (*RT, 27)]), (8, [(*CO2, 1700)])], {CO2[0]}, 900),
 "temp_sensor_fault": ("sensor fault: room temp sensor jumps 25->44 C while the AC sensor and the AC room sensor stay at 24-25 C, room empty",
   [(0, [(*OCC, 0)]), (5, [(*RT, 44)])], {RT[0]}, 900),
 "ph_critical_spike": ("critical real: drinking-water pH spikes 7.2->9.6 (alkaline dosing fault) -> critical water quality, inspect_water_system",
   [(0, [(*PH, 9.6)])], {PH[0]}, 900),
 "weather_heat": ("weather-only heat: outdoor temp 34->41->46 C, indoor fine -> weather critical/warning, no indoor fault, no sensor fault",
   [(0, [(*WT, 34)]), (10, [(*WT, 38)]), (10, [(*WT, 41)]), (10, [(*WT, 44)]), (10, [(*WT, 46)])], {WT[0]}, 900),
}
def htpd_lines(): return C.log_lines()
def run(name):
    exp, steps, nodes, settle = S[name]
    w0 = time.time()
    while C.temp_c() > 60 and time.time() - w0 < 1200: time.sleep(15)
    t_board = C.temp_c()
    C.reset("10:00"); time.sleep(5)
    before = set(C.ids()); l0 = htpd_lines(); t0 = time.time()
    for wait, sets in steps:
        time.sleep(wait)
        for n, m, v in sets: C.api("/api/ingest", {"node": n, "metric": m, "value": v})
    t_last = time.time()
    seen = {}; done = {}
    while time.time() - t0 < settle:
        for cand in [i for i in C.ids() if i not in before]:
            ci = C.api(f"/api/incidents/{cand}")
            if not isinstance(ci, dict) or not ({x.get("node") for x in ci.get("sensors") or []} & nodes): continue
            seen.setdefault(cand, round(time.time() - t0, 1)); fin = ci.get("final") or {}
            ran = any("Reasoner v3" in (t.get("msg") or "") for t in ci.get("timeline") or [])
            if cand not in done and ((fin and not fin.get("preliminary") and ran and ci.get("state") == "done") or ci.get("state") == "failed"):
                done[cand] = (round(time.time() - t0, 1), ci)
        if name != "normal_drift" and seen and all(c in done for c in seen) and time.time() - t_last > 60: break
        time.sleep(3)
    incs = []
    for cand in seen:
        ci = done[cand][1] if cand in done else C.api(f"/api/incidents/{cand}")
        fin = (ci or {}).get("final") or {}; rep = {}
        try: rep = json.loads(fin.get("raw") or "{}")
        except Exception: pass
        incs.append(dict(id=cand, first_seen_s=seen[cand], ai_done_s=done[cand][0] if cand in done else None, fast_path=ci.get("fast_path"),
                         state=ci.get("state"), severity=ci.get("severity"), title=ci.get("title"), label=rep.get("label"),
                         model=fin.get("model"), valid=fin.get("valid"), errors=fin.get("errors"), reasoner_ms=fin.get("latency_ms"),
                         checklist=[c.get("action") for c in rep.get("checklist") or [] if isinstance(c, dict)],
                         root_cause=rep.get("root_cause"), explanation=rep.get("explanation"),
                         timeline=[(t.get("msg") or "")[:160] for t in ci.get("timeline") or []]))
        json.dump(ci, open(f"{O}/raw/{name}_{cand}.json", "w"), indent=1)
    hl = C.sh(f"tail -n +{l0 + 1} {C.D}/state/htpd.log | grep -E 'reasoner loaded|reason stream|reasoner unloaded|agents. model back|exiting|failed'")
    open(f"{O}/raw/{name}_htpd.log", "w").write(hl)
    C.reset("10:00")
    r = dict(story=name, expect=exp, board_c_start=t_board, incidents=incs, n_incidents=len(incs),
             reasoner_loads=[l[l.find("loaded in"):][:140] for l in hl.splitlines() if "reasoner loaded" in l])
    with open(f"{O}/stories.jsonl", "a") as f: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({k: r[k] for k in ("story", "n_incidents")} | {"incs": [(i["id"], i["first_seen_s"], i["ai_done_s"], i["severity"], i["label"], i["valid"], i["title"]) for i in incs]}), flush=True)
for n in (sys.argv[1:] or list(S)): run(n); time.sleep(20)
print("STORIES DONE", flush=True)
