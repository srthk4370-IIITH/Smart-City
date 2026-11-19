"""Device/training tool parity, Python side.

parity_cases.json (hand-made fixture: 8 sensors in two buildings with 3 days of 5-min readings up to now, 9 incidents,
22 tool calls) is run through tools_v3_impl.ToolsV3 on a throw-away SQLite store built from it; the results go to
parity_out_py.json. backend/chat_tools_v3_parity_test.go runs the same calls on the Go tools (an Engine and a Reasoner
built from the same fixture) and compares field names, types and values (numbers within the written rounding).

  python3 parity_py.py --make     # (re)write parity_cases.json from the spec below, then run
  python3 parity_py.py            # run -> parity_out_py.json
"""
import argparse
import datetime as dt
import json
import math
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tools_v3_impl import ToolsV3, STORE_R1, ep  # noqa: E402
from common import NOW  # noqa: E402

CASES = os.path.join(HERE, "parity_cases.json")
OUT = os.path.join(HERE, "parity_out_py.json")
START = NOW - dt.timedelta(days=3)

SENSORS = [  # node, metric, role, location, unit, building
    ("SR-AQ-KH03-03", "co2", "air_quality", "KH building, level 03, indoor air sensor 03", "ppm", "KH"),
    ("SR-AQ-KH03-03", "temp", "air_quality", "KH building, level 03, indoor air sensor 03", "C", "KH"),
    ("SR-OC-GW-KH95-01", "occ", "occupancy", "KH building, room occupancy sensor 01 (gateway KH95)", "0/1", "KH"),
    ("SR-EM-KH04-01", "power_kw", "power", "KH building, level 04, room energy meter 01", "kW", "KH"),
    ("AC-KH03", "room_temp", "hvac", "KH building, level 03, AC units", "C", "KH"),
    ("WM-WQ-KH98-01", "ph", "water", "KH building, level 98, water quality probe 01", "pH", "KH"),
    ("SR-EM-VN01-02", "pf", "power", "VN building, level 01, room energy meter 02", "", "VN"),
    ("WE-VN04-00", "temp", "weather", "VN building, level 04, rooftop weather station", "C", "VN"),
]


def _jit(i, k):
    """deterministic pseudo-noise in [-1, 1]"""
    x = math.sin(i * 12.9898 + k * 78.233) * 43758.5453
    return 2 * (x - math.floor(x)) - 1


def _series():
    n = 3 * 288 + 1
    out = {}
    occ = []
    for i in range(n):
        t = START + dt.timedelta(minutes=5 * i)
        h = t.hour + t.minute / 60
        busy = 9 <= h < 18 and not (t.day == 20 and 13 <= h < 15)      # a free period on Tuesday afternoon
        occ.append(1.0 if (busy and _jit(i, 1) > -0.7) or (not busy and _jit(i, 2) > 0.93) else 0.0)
    for node, metric, role, loc, unit, bl in SENSORS:
        vs = []
        for i in range(n):
            t = START + dt.timedelta(minutes=5 * i)
            h = t.hour + t.minute / 60
            diurnal = math.sin((h - 9) / 24 * 2 * math.pi)
            o = sum(occ[max(0, i - 6):i + 1]) / len(occ[max(0, i - 6):i + 1])
            if metric == "co2":
                v = 440 + 420 * o + 60 * _jit(i, 3)
            elif metric == "temp" and role == "air_quality":
                v = 24.5 + 1.2 * o + 0.6 * diurnal + 0.4 * _jit(i, 4)
            elif metric == "occ":
                v = occ[i]
            elif metric == "power_kw":
                v = 18 + 12 * o + 4 * _jit(i, 5)
            elif metric == "room_temp":
                v = 25.5 + 0.8 * diurnal + 0.9 * _jit(i, 6)
            elif metric == "ph":
                v = 7.3 + 0.05 * _jit(i, 7)
            elif metric == "pf":
                v = 0.93 + 0.01 * _jit(i, 8) - 0.02 * max(0.0, diurnal)
            else:                                   # weather temp
                v = 28 + 4.5 * diurnal + 0.5 * _jit(i, 9)
            vs.append(v)
        out["%s|%s" % (node, metric)] = vs
    # hand-placed events
    T = lambda s: int((dt.datetime.strptime(s, "%Y-%m-%d %H:%M") - START).total_seconds() // 300)  # noqa: E731
    s = out["SR-AQ-KH03-03|temp"]
    s[T("2026-10-21 14:20")] = 33.8                                      # yesterday's peak
    s[T("2026-10-22 10:05")] = 31.4                                      # today's peak
    s = out["SR-AQ-KH03-03|co2"]
    s[-3:] = [1060, 1095, 1120]                                          # warning now
    s[T("2026-10-22 09:50")] = 1640                                      # today's peak (critical level, passed)
    s = out["AC-KH03|room_temp"]
    s[-4:] = [30.2, 30.6, 31.0, 31.2]                                    # warning now
    s = out["SR-EM-VN01-02|pf"]
    for k in range(T("2026-10-21 07:00"), T("2026-10-21 08:30")):
        s[k] = 0.66 + 0.002 * (k % 5)                                      # yesterday's critical dip
    s[-2:] = [0.83, 0.82]                                                # warning now (low side)
    s = out["WM-WQ-KH98-01|ph"]
    for k in range(T("2026-10-22 05:30"), T("2026-10-22 07:00")):
        s[k] = 5.9                                                       # critical pH this morning
    s[-1] = 6.3                                                          # warning now (low side)
    s = out["WE-VN04-00|temp"]
    for k in range(T("2026-10-22 09:30"), len(s)):
        s[k] = 30.0                                                      # stuck since 09:30
    for key, vs in out.items():
        dec = 3 if key.endswith(("|pf", "|ph")) else 1
        out[key] = [round(v, dec) for v in vs]
    return out


def _inc(iid, at, sev, title, label, root, approval, workflow, state, outcome, injected, sensors):
    return {"id": iid, "at": at, "severity": sev, "title": title, "label": label, "root_cause": root, "approval": approval,
            "workflow": workflow, "state": state, "outcome": outcome, "injected": injected,
            "sensors": [dict(zip(("ref", "node", "metric", "role", "status", "pattern", "fault_kind", "context"), s)) for s in sensors]}


INCIDENTS = [
    _inc("INC-0101", "2026-10-20 09:10", "warning", "CO2 step increase: KH building, level 03, indoor air sensor 03", "occupancy_driven_load",
         "CO2 rise from room occupancy", "approved", "in_progress", "done", "", False,
         [("S1", "SR-AQ-KH03-03", "co2", "air_quality", "warning", "step_increase", "", False),
          ("S2", "SR-OC-GW-KH95-01", "occ", "occupancy", "normal", "arrival", "", True)]),
    _inc("INC-0102", "2026-10-20 15:00", "sensor_fault", "temp gradual increase: VN building, level 04, rooftop weather station", "sensor_fault",
         "sensor reading implausible (drift)", "approved", "closed", "done", "sensor_repaired", False,
         [("S1", "WE-VN04-00", "temp", "weather", "sensor_fault", "gradual_increase", "drift", False)]),
    _inc("INC-0103", "2026-10-21 07:20", "critical", "PF dip: VN building, level 01, room energy meter 02", "power_quality_issue",
         "power factor dropped", "pending", "needs_decision", "done", "", False,
         [("S1", "SR-EM-VN01-02", "pf", "power", "critical", "dip", "", False)]),
    _inc("INC-0104", "2026-10-21 14:30", "warning", "power kw step increase: KH building, level 04, room energy meter 01", "hvac_or_thermal_issue",
         "cooling load rising", "pending", "needs_decision", "done", "", False,
         [("S1", "SR-EM-KH04-01", "power_kw", "power", "warning", "step_increase", "", False),
          ("S2", "AC-KH03", "room_temp", "hvac", "warning", "gradual_increase", "", False)]),
    _inc("INC-0105", "2026-10-21 20:00", "warning", "occ off hours presence: KH building, room occupancy sensor 01 (gateway KH95)", "unknown",
         "presence after hours", "dismissed", "closed", "done", "false_alarm", False,
         [("S1", "SR-OC-GW-KH95-01", "occ", "occupancy", "warning", "off_hours_presence", "", False)]),
    _inc("INC-0106", "2026-10-22 06:15", "critical", "pH dip: KH building, level 98, water quality probe 01", "water_quality_issue",
         "water quality out of range", "pending", "needs_decision", "done", "", False,
         [("S1", "WM-WQ-KH98-01", "ph", "water", "critical", "dip", "", False)]),
    _inc("INC-0107", "2026-10-22 09:40", "sensor_fault", "temp flatline: VN building, level 04, rooftop weather station", "sensor_fault",
         "sensor reading implausible (stuck)", "pending", "needs_decision", "done", "", False,
         [("S1", "WE-VN04-00", "temp", "weather", "sensor_fault", "flatline", "stuck", False)]),
    _inc("INC-0108", "2026-10-22 10:00", "critical", "CO2 spike: KH building, level 03, indoor air sensor 03", "ventilation_issue",
         "demo injection", "pending", "needs_decision", "done", "", True,
         [("S1", "SR-AQ-KH03-03", "co2", "air_quality", "critical", "spike", "", False)]),
    _inc("INC-0109", "2026-10-22 11:40", "warning", "temp step increase: KH building, level 03, indoor air sensor 03", "",
         "", "pending", "analysing", "running", "", False,
         [("S1", "SR-AQ-KH03-03", "temp", "air_quality", "warning", "step_increase", "", False)]),
]

CALLS = [
    ("rank_readings", {"metric": "co2"}),
    ("rank_readings", {"metric": "temp", "time": {"preset": "last_7d"}, "order": "lowest", "include_faulty": False}),
    ("rank_readings", {"metric": "temp", "time": {"preset": "yesterday"}}),
    ("rank_readings", {"metric": "room_temp", "location": "KH", "limit": 5}),
    ("current_levels", {"metric": "co2"}),
    ("current_levels", {"location": "KH"}),
    ("current_levels", {"domain": "power"}),
    ("current_levels", {"metric": "ph"}),
    ("recent_incidents", {}),
    ("recent_incidents", {"severity": ["sensor_fault"], "limit": 3}),
    ("recent_incidents", {"domain": "power"}),
    ("open_incidents", {}),
    ("open_incidents", {"domain": "hvac"}),
    ("open_incidents", {"domain": "weather"}),
    ("faulty_sensors", {}),
    ("faulty_sensors", {"time": {"preset": "last_30d"}}),
    ("what_if", {"driver": "occ", "change_pct": 50}),
    ("what_if", {"driver": "occ", "change_pct": -30, "location": "KH"}),
    ("what_if", {"driver": "room_temp", "change_abs": 2, "location": "KH03"}),
    ("what_if", {"driver": "temp", "change_abs": 3, "location": "VN"}),
    ("list_sensors", {}),
    ("list_sensors", {"status": "warning"}),
]


def make():
    case = {"about": "device/training chat-tool parity fixture (parity_py.py --make); times IST, readings every 5 min from start "
                     "to now inclusive; last reading = the sensor's live value; every engine status normal",
            "now": NOW.strftime("%Y-%m-%d %H:%M"), "start": START.strftime("%Y-%m-%d %H:%M"), "step_min": 5,
            "sensors": [dict(zip(("node", "metric", "role", "location", "unit", "building"), s)) for s in SENSORS],
            "readings": _series(), "incidents": INCIDENTS, "calls": [{"name": n, "args": a} for n, a in CALLS]}
    with open(CASES, "w", encoding="utf-8") as f:
        json.dump(case, f, separators=(",", ":"))
    print("wrote", CASES, os.path.getsize(CASES), "bytes")


def build_db(case, path):
    src = sqlite3.connect("file:%s?mode=ro" % STORE_R1, uri=True)
    ddl = [r[0] for r in src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name IN "
                                     "('incident','incident_sensor','incident_step','maintenance','reading_5min','reading_hourly')")]
    src.close()
    db = sqlite3.connect(path)
    for s in ddl:
        db.execute(s)
    loc = {(s["node"], s["metric"]): s["location"] for s in case["sensors"]}
    for x in case["incidents"]:
        t = dt.datetime.strptime(x["at"], "%Y-%m-%d %H:%M")
        db.execute("INSERT INTO incident (id, version, created_wall, created_sim, state, mode, severity, severity_final, label, root_cause,"
                   " title, approval, injected, workflow, outcome) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (x["id"], 1, t.strftime("%Y-%m-%d %H:%M:%S"), ep(t), x["state"], 3, x["severity"], 1, x["label"] or None,
                    x["root_cause"] or None, x["title"], x["approval"], int(x["injected"]), x["workflow"], x["outcome"] or None))
        for s in x["sensors"]:
            db.execute("INSERT INTO incident_sensor VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (x["id"], s["ref"], s["node"], s["metric"], s["role"], loc[(s["node"], s["metric"])], int(s["context"]), "agent",
                        s["pattern"], s["status"], None, s["fault_kind"] or None, None))
    start = dt.datetime.strptime(case["start"], "%Y-%m-%d %H:%M")
    for k, vs in case["readings"].items():
        node, metric = k.split("|")
        hours = {}
        for i, v in enumerate(vs):
            t = ep(start) + i * 300
            db.execute("INSERT INTO reading_5min VALUES (?,?,?,?)", (node, metric, t, v))
            hours.setdefault(t - t % 3600, []).append(v)
        for h, xs in hours.items():
            db.execute("INSERT INTO reading_hourly VALUES (?,?,?,?,?,?,?,?)", (node, metric, h, len(xs), sum(xs) / len(xs), min(xs), max(xs), xs[-1]))
    db.commit()
    db.close()


def run():
    case = json.load(open(CASES, encoding="utf-8"))
    assert case["now"] == NOW.strftime("%Y-%m-%d %H:%M"), "fixture now must equal the store's NOW"
    cat = [(s["node"], s["metric"], s["role"], s["location"], s["unit"]) for s in case["sensors"]]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "parity.sqlite")
        build_db(case, p)
        ex = ToolsV3(path=p, catalog=cat, readings_from=NOW - dt.timedelta(days=7), fivemin_from=NOW - dt.timedelta(days=7))
        res = []
        for c in case["calls"]:
            r = ex.run(c["name"], json.loads(json.dumps(c["args"])))
            r.pop("query_id", None)
            res.append({"name": c["name"], "args": c["args"], "result": r})
        ex.db.close()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"cases": os.path.basename(CASES), "results": res}, f, indent=1, ensure_ascii=False)
    print("parity_py: %d calls -> %s (%d errors)" % (len(res), OUT, sum(1 for r in res if "error" in r["result"])))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    a = ap.parse_args()
    if a.make or not os.path.exists(CASES):
        make()
    run()
