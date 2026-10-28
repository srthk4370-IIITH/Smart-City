"""E1 board stories (2026-10-25 domain plan, P1 deploy): leak starts below the node high mark and drains 3/step; AC rises 0.15 C/step; agent prompts + repairs + claim_flags saved.
mixA50 deployed (2026-10-25): hand-made real-world sensor stories pushed through the app's /api/ingest,
gradual + noisy (not canned scenarios). Prints each incident's agent answers + report for a qualitative read."""
import json, random, sys, time
sys.path.insert(0, "C:/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/tools")
import stress_app as S
random.seed(7)
OUT = __import__("os").environ.get("SIM_OUT", "C:/Users/hp/Desktop/qidk/proofs/2026-10-25_mixA50_realworld")
def put(n, m, v): S.req("/api/ingest", {"node": n, "metric": m, "value": round(v, 2)})
STORIES = {  # name: (steps, fn(step) -> list of (node, metric, value))
  "class_fills_up": (14, lambda i: [("SR-AQ-KH03-03", "co2", 450 + 70 * i + random.gauss(0, 15)), ("SR-OC-GW-KH95-01", "occ", 1),
                                    ("SR-AQ-KH03-03", "temp", 25 + 0.12 * i + random.gauss(0, .1)), ("SR-EM-KH04-01", "power_kw", 3 + 0.25 * i + random.gauss(0, .1))]),
  "slow_tank_leak": (40, lambda i: [("WM-WL-KH98-00", "level", 160 - 1.0 * i + random.gauss(0, 0.5)), ("WM-WF-KH98-40", "flow", 5 + random.gauss(0, .3))]),
  "dust_storm_ingress": (12, lambda i: [("AQ-KN00-00", "pm25", 25 + 11 * i + random.gauss(0, 4)), ("AQ-KN00-00", "pm10", 45 + 25 * i + random.gauss(0, 8)),
                                       ("WE-VN04-00", "wind", 3 + 0.9 * i + random.gauss(0, .5))]),
  "acidic_water": (10, lambda i: [("WM-WD-KH98-00", "ph", 7.2 - 0.17 * i + random.gauss(0, .03)), ("WM-WD-KH98-00", "tds", 150 + 4 * i + random.gauss(0, 3))]),
  "ac_fails_hot_day": (14, lambda i: [("SR-AC-KH02-24", "room_temp", 25.3 + 0.15 * i + random.gauss(0, .05)), ("SR-AC-KH02-24", "ac_on", 1),
                                     ("WE-VN04-00", "temp", 34 + random.gauss(0, .3))]),
  "co2_sensor_glitch": (6, lambda i: [("SR-AQ-KH03-03", "co2", 2900 if i % 2 else 230)]),
}
res = []
for name, (steps, fn) in STORIES.items():
    S.reset("10:00"); time.sleep(40)
    before = set(S.incident_ids())
    for i in range(1, steps + 1):
        for n, m, v in fn(i): put(n, m, v)
        time.sleep(4)
    iid, _ = S.wait_new_incident(before, timeout=180)
    if not iid: print(f"## {name}: NO INCIDENT", flush=True); res.append({"story": name, "incident": None}); continue
    inc = S.wait_done(iid, timeout=240) or S.req(f"/api/incidents/{iid}")[1]
    S.INCIDENTS.clear(); S.record(name, inc); r = S.INCIDENTS[0]; r["agent_prompts"] = [{"ref": a.get("ref"), "prompt": a.get("prompt"), "repairs": a.get("repairs"), "claim_flags": a.get("claim_flags"), "parsed": a.get("parsed")} for a in (inc.get("agents") or [])]; res.append(r)
    print(f"## {name}: {iid} title={r['title']!r} {r['total_ms']}ms", flush=True)
    for a in r["agents"]: print(f"  {a['ref']}: {a['pattern']}/{a['status']} cause={a['cause']} | {str(a['observations'])[:160]}", flush=True)
    rp = r["report"]; print(f"  REPORT {rp['label']} root={rp['root_cause']} action={str(rp['action'])[:150]}\n  {str(rp['explanation'])[:300]}", flush=True)
json.dump(res, open(f"{OUT}/sim_results.json", "w"), indent=1)
S.reset("10:00"); print("done")
