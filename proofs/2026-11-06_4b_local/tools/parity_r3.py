"""Device/training parity of the r3 fog + local tools, Python side.

Fixture (written by --make): 90 incidents sampled evenly from the r3 fog store (the oldest 40 archived on the device: index
rows only), the 8 sensors with 3 days of 5-min readings of the rsn_v3 parity fixture, the knowledge base, and ~45 tool calls
each run with the fog online and offline. Python runs them through tools_r3_impl.ToolsR3 on throw-away fog/device SQLite
stores built from the fixture -> parity_r3_out_py.json. backend/chat_fog_parity_test.go runs the same calls on the Go tools
(a device Reasoner with an incidents.archive.jsonl, and a fake fog = FogHandler over a Reasoner holding every incident) and
compares field names, JSON types and values.

  python3 parity_r3.py --make   # write parity_r3_cases.json from the r3 store, then run
  python3 parity_r3.py          # run -> parity_r3_out_py.json
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tools_r3_impl as TR  # noqa: E402
from tools_v3_impl import ep  # noqa: E402

CASES = os.path.join(HERE, "parity_r3_cases.json")
OUT = os.path.join(HERE, "parity_r3_out_py.json")
V3CASES = os.path.join(TR.V3P, "parity_cases.json")


def make():
    db = sqlite3.connect("file:%s?mode=ro" % TR.FOG_DB, uri=True)
    db.row_factory = sqlite3.Row
    ids = [r[0] for r in db.execute("SELECT id FROM incident ORDER BY created_wall, id")]
    pick = ids[::len(ids) // 90][:90]
    incs = []
    for iid in pick:
        r = db.execute("SELECT * FROM incident WHERE id=?", (iid,)).fetchone()
        sens = [{"ref": s["ref"], "node": s["node"], "metric": s["metric"], "role": s["domain"], "status": s["status"] or "",
                 "pattern": s["pattern"] or "", "fault_kind": s["fault_kind"] or "", "context": bool(s["context"])}
                for s in db.execute("SELECT * FROM incident_sensor WHERE incident_id=? ORDER BY ref", (iid,))]
        steps = [{"action": s["action"], "state": s["state"], "by": s["by"] or ""}
                 for s in db.execute("SELECT * FROM incident_step WHERE incident_id=? ORDER BY step_id", (iid,))]
        incs.append({"id": r["id"], "at": r["created_wall"][:16], "severity": r["severity"], "title": r["title"], "label": r["label"] or "",
                     "root_cause": r["root_cause"] or "", "approval": r["approval"] or "", "workflow": r["workflow"] or "", "state": r["state"],
                     "outcome": r["outcome"] or "", "injected": bool(r["injected"]), "refine_stage": r["refine_stage"] or "",
                     "closed_at": (r["closed_at"] or "")[:16], "sensors": sens, "steps": steps})
    archived = [x["id"] for x in incs[:40]]
    v3 = json.load(open(V3CASES, encoding="utf-8"))
    old, new, mid = incs[5]["id"], incs[-3]["id"], incs[60]["id"]
    T = lambda p: {"preset": p}
    rng = lambda a, b: {"from": a, "to": b}
    calls = [
        ("fog_search_history", {"time": T("all")}), ("fog_search_history", {"time": T("all"), "limit": 10}),
        ("fog_search_history", {"time": rng("2025-11-01", "2026-03-01"), "domain": "air_quality"}),
        ("fog_search_history", {"time": T("this_year"), "severity": ["critical"], "limit": 8}),
        ("fog_search_history", {"time": T("all"), "text": "tank"}), ("fog_search_history", {"time": T("all"), "text": "leak", "domain": "water"}),
        ("fog_search_history", {"time": T("last_30d"), "metric": "co2"}), ("fog_search_history", {"time": rng("2026-01-01", "2026-07-01"), "node": "KH03"}),
        ("fog_search_history", {"time": T("all"), "label": "sensor_fault", "severity": "sensor_fault"}),
        ("fog_search_history", {"time": T("all"), "domain": "sky"}), ("fog_search_history", {}),
        ("fog_analytics", {"analysis": "incident_trend", "time": T("all")}),
        ("fog_analytics", {"analysis": "incident_trend", "time": T("this_year"), "domain": "power"}),
        ("fog_analytics", {"analysis": "incident_trend", "time": T("last_30d"), "bucket": "week"}),
        ("fog_analytics", {"analysis": "incident_trend", "time": rng("2026-06-01", "2026-10-01"), "severity": ["critical", "warning"]}),
        ("fog_analytics", {"analysis": "resolve_time", "time": T("all")}),
        ("fog_analytics", {"analysis": "resolve_time", "time": T("this_year"), "group_by": "domain"}),
        ("fog_analytics", {"analysis": "resolve_time", "time": T("last_30d"), "domain": "water"}),
        ("fog_analytics", {"analysis": "sensor_monthly", "time": T("this_month"), "node": "SR-AQ-KH03-03", "metric": "co2"}),
        ("fog_analytics", {"analysis": "sensor_monthly", "time": T("all"), "node": "SR-AQ-KH03-03", "metric": "temp"}),
        ("fog_analytics", {"analysis": "sensor_monthly", "time": T("this_year"), "node": "SR-AQ-KH03-03", "metric": "pm25"}),
        ("fog_analytics", {"analysis": "forecast", "time": T("all")}),
        ("search_knowledge", {"query": "drinking water pH limit"}), ("search_knowledge", {"query": "PM2.5 standard 24 hour", "k": 5}),
        ("search_knowledge", {"query": "AC service contract"}), ("search_knowledge", {"query": "CO2 alarm SOP"}),
        ("search_knowledge", {"query": "room temperature sensor fault vs AC failure"}), ("search_knowledge", {"query": "zzz qqq"}),
        ("search_knowledge", {}),
        ("get_incident", {"id": old}), ("get_incident", {"id": new}), ("get_incident", {"id": mid}), ("get_incident", {"id": "INC-9999"}),
        ("co_occurring_incidents", {"id": new}), ("co_occurring_incidents", {"id": new, "window_min": 240}),
        ("co_occurring_incidents", {"id": old, "window_min": 240, "other_domains_only": False}),
        ("co_occurring_incidents", {"id": "INC-9999"}),
        ("recurring_issues", {"time": T("all")}), ("recurring_issues", {"time": T("all"), "by": "node", "min_count": 2}),
        ("recurring_issues", {"time": T("this_year"), "domain": "air_quality", "min_count": 2}),
        ("recurring_issues", {"time": T("all"), "by": "room"}),
        ("compare_periods", {"period_a": T("last_month"), "period_b": T("this_month")}),
        ("compare_periods", {"period_a": rng("2025-11-01", "2026-01-01"), "period_b": rng("2026-01-01", "2026-03-01"), "domain": "air_quality"}),
        ("compare_periods", {"period_a": rng("2025-01-01", "2025-02-01"), "period_b": T("this_year"), "severity": ["critical"]}),
        ("compare_periods", {"period_a": T("last_month")}),
        ("fog_status", {}),
    ]
    case = {"about": "r3 fog/local tool parity fixture (parity_r3.py --make); times IST", "now": v3["now"], "start": v3["start"],
            "step_min": v3["step_min"], "sensors": v3["sensors"], "readings": v3["readings"], "incidents": incs, "archived": archived,
            "calls": [{"name": n, "args": a, "fog": f} for n, a in calls for f in ("online", "offline")]}
    json.dump(case, open(CASES, "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def build(case, d):
    src = sqlite3.connect("file:%s?mode=ro" % TR.FOG_DB, uri=True)
    ddl = [r[0] for r in src.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name != 'meta'")]
    arch = set(case["archived"])
    start = dt.datetime.strptime(case["start"], "%Y-%m-%d %H:%M")
    paths = {}
    for which in ("fog", "device"):
        p = os.path.join(d, which + ".sqlite")
        db = sqlite3.connect(p)
        for s in ddl:
            if which == "device" and "reading_daily" in s:
                continue
            db.execute(s)
        for x in case["incidents"]:
            a = which == "device" and x["id"] in arch
            db.execute("INSERT INTO incident (id, version, created_wall, created_sim, state, mode, severity, severity_final, label, root_cause, title,"
                       " refine_stage, approval, injected, full_on_device, workflow, outcome, closed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (x["id"], 1, x["at"] + ":00", 0, x["state"], 2, x["severity"], 1, x["label"] or None,
                        None if a else (x["root_cause"] or None), x["title"], x["refine_stage"] or None, x["approval"] or None, int(x["injected"]),
                        0 if a else 1, x["workflow"] or None, x["outcome"] or None, None if a else (x["closed_at"] or None)))
            for s in x["sensors"]:
                if a and s["context"]:
                    continue
                db.execute("INSERT INTO incident_sensor (incident_id, ref, node, metric, domain, location, context, source, pattern, status, fault_kind)"
                           " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (x["id"], s["ref"], s["node"], s["metric"], s["role"], "", int(s["context"]), "agent",
                                                            s["pattern"] or None, s["status"] or None, s["fault_kind"] or None))
            if not a:
                for i, s in enumerate(x["steps"]):
                    db.execute("INSERT INTO incident_step (incident_id, step_id, source, action, text, added_at_stage, state, by) VALUES (?,?,?,?,?,?,?,?)",
                               (x["id"], "s%d" % (i + 1), "reasoner", s["action"], s["action"], "early", s["state"], s["by"] or None))
        days = {}
        for k, xs in case["readings"].items():
            node, metric = k.split("|") if "|" in k else k.split("/")
            hours = {}
            for i, v in enumerate(xs):
                t = start + dt.timedelta(minutes=i * case["step_min"])
                db.execute("INSERT INTO reading_5min VALUES (?,?,?,?)", (node, metric, ep(t), v))
                hours.setdefault(t.replace(minute=0), []).append(v)
                days.setdefault((node, metric, t.strftime("%Y-%m-%d")), []).append(v)
            for h, v in hours.items():
                db.execute("INSERT INTO reading_hourly VALUES (?,?,?,?,?,?,?,?)", (node, metric, ep(h), len(v), sum(v) / len(v), min(v), max(v), v[-1]))
        if which == "fog":
            for (node, metric, day), v in days.items():
                db.execute("INSERT INTO reading_daily VALUES (?,?,?,?,?,?,?)", (node, metric, day, len(v), sum(v) / len(v), min(v), max(v)))
        db.commit()
        db.close()
        paths[which] = p
    return paths


def run():
    case = json.load(open(CASES, encoding="utf-8"))
    out = []
    with tempfile.TemporaryDirectory() as d:
        p = build(case, d)
        ex = {f: TR.ToolsR3(fog=f, last_sync=None, fog_path=p["fog"], dev_path=p["device"]) for f in ("online", "offline")}
        for c in case["calls"]:
            e = ex[c["fog"]]
            e.qid = 0
            r = e.run(c["name"], json.loads(json.dumps(c["args"])))
            if isinstance(r, dict):
                r.pop("query_id", None)
            out.append({"name": c["name"], "args": c["args"], "fog": c["fog"], "result": r})
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("parity r3 py: %d calls, %d errors" % (len(out), sum(1 for o in out if "error" in o["result"])))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    a = ap.parse_args()
    if a.make:
        make()
    run()
