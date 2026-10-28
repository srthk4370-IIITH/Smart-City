"""Build the benchmark's local SQLite incident store (store_schema.sql + APPROVAL_AND_MEMORY 4.1 tables).

Contents (all local, seeded, rebuildable):
  * the real app-test incidents from proofs/ (2026-10-21_v2_app, 2026-10-23_app_ab_v2_vs_3d), with their real
    sensors, agent findings, final reports and wall times. They were demo injections, so injected=1 (the tools
    exclude them by default, exactly as the design says).
  * a synthetic 2026 "field year" (1 Jan .. 22 Oct) of non-injected incidents over the same sensor kinds, with
    checklist steps, outcomes, maintenance rows (replaced / recalibrated / restarted) and recurrences, generated
    from label playbooks; ground truth for every question is computed by SQL over this store.
  * readings: hourly rollups for the last 60 days and raw 5-min for the last 3 days, every catalogue series.

Usage: python3 build_store.py   (writes data/store.sqlite and data/store_manifest.json)
"""
import glob
import hashlib
import json
import math
import os
import random
import sqlite3
import datetime as dt

from common import (HERE, PROOFS, STORE, NOW, YEAR_START, READINGS_FROM, FIVEMIN_FROM, CATALOG, CAT, building_of)

SCHEMA = open(os.path.join(HERE, "..", "..", "store_schema.sql")).read()
EXTRA = """
CREATE TABLE IF NOT EXISTS incident_event (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL, at_wall TEXT NOT NULL,
  actor TEXT NOT NULL, event TEXT NOT NULL, step_id TEXT, outcome TEXT, note TEXT, detail_json TEXT);
CREATE TABLE IF NOT EXISTS incident_step (
  incident_id TEXT NOT NULL, step_id TEXT NOT NULL, source TEXT NOT NULL, action TEXT, target TEXT,
  text TEXT NOT NULL, why TEXT, added_at_stage TEXT, state TEXT NOT NULL DEFAULT 'open',
  by TEXT, at_wall TEXT, note TEXT, PRIMARY KEY (incident_id, step_id));
ALTER TABLE incident ADD COLUMN workflow TEXT;
ALTER TABLE incident ADD COLUMN owner TEXT;
ALTER TABLE incident ADD COLUMN acked_at TEXT;
ALTER TABLE incident ADD COLUMN closed_at TEXT;
ALTER TABLE incident ADD COLUMN outcome TEXT;
ALTER TABLE incident ADD COLUMN outcome_note TEXT;
ALTER TABLE incident ADD COLUMN recurred_by TEXT;
ALTER TABLE incident ADD COLUMN source TEXT;
"""
OPERATORS = ["op_ravi", "op_meena", "op_arjun", "op_sana"]
R = random.Random(20261022)


def epoch(t):
    return int((t - dt.datetime(1970, 1, 1)).total_seconds())


def iso(t):
    return t.strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ label playbooks for the synthetic year
# each: weight, monthly weight multiplier fn, sensors builder -> [(node, metric, pattern, status, likely_cause, fault_kind, context)]
AQ_ROOMS = [("SR-AQ-KH03-03", "AC-KH03", "SR-OC-GW-KH95-01"), ("SR-AQ-KH03-01", "AC-KH03", "SR-OC-GW-KH95-01"),
            ("SR-AQ-VN02-01", "AC-VN02", "SR-OC-GW-VN95-02"), ("SR-AQ-BK01-02", None, "SR-OC-GW-BK95-01")]
TANKS = [("WM-WL-KH98-00", "WM-WF-KH98-40"), ("WM-WL-VN98-00", "WM-WF-VN98-10")]
METERS = ["SR-EM-KH04-01", "SR-EM-VN01-02", "EM-CR-SB00-00"]


def sev_pick(p_crit, p_warn):
    x = R.random()
    return "critical" if x < p_crit else ("warning" if x < p_crit + p_warn else "normal")


def mk_vent():
    aq, ac, oc = R.choice(AQ_ROOMS)
    sev = sev_pick(0.4, 0.55)
    s = [(aq, "co2", R.choice(["exponential_increase", "gradual_increase"]), sev, "ventilation_insufficient", None, 0)]
    if ac:
        s.append((ac, "ac_units_on", "step_decrease", "normal", "hvac_context", None, 1))
    s.append((oc, "occ", "occupied", "normal", "normal_occupancy", None, 1))
    return "ventilation_issue", sev, s, "CO2 rising with ventilation reduced"


def mk_occ():
    aq, ac, oc = R.choice(AQ_ROOMS)
    sev = sev_pick(0.15, 0.7)
    s = [(aq, "co2", R.choice(["spike", "step_increase", "exponential_increase"]), sev, "occupancy_load", None, 0),
         (oc, "occ", "arrival", "normal", "arrival", None, 1)]
    return "occupancy_driven_load", sev, s, "CO2 rise from room occupancy"


def mk_hvac():
    ac = R.choice(["AC-KH03", "AC-VN02"])
    sev = sev_pick(0.3, 0.6)
    s = [(ac, "room_temp", "gradual_increase", sev, "hvac_cooling_issue", None, 0),
         (ac, "ac_units_on", R.choice(["step_decrease", "oscillation"]), "warning", "hvac_cooling_issue", None, 0)]
    return "hvac_or_thermal_issue", sev, s, "room temperature rising while AC units drop out"


def mk_poll():
    aq = R.choice(["SR-AQ-KH03-01", "SR-AQ-BK01-02"])
    sev = sev_pick(0.35, 0.6)
    s = [(aq, "pm25", "gradual_increase", sev, "outdoor_pollution_ingress", None, 0),
         ("AQ-KN00-00", "pm25", "gradual_increase", "warning", "outdoor_pollution_ingress", None, 0),
         ("WE-VN04-00", "wind", "stable", "normal", "normal_weather", None, 1)]
    return "air_pollution_event", sev, s, "outdoor PM2.5 entering the building"


def mk_leak():
    lv, fl = R.choice(TANKS)
    sev = sev_pick(0.5, 0.45)
    s = [(lv, "level", "gradual_decrease", sev, "possible_leak", None, 0),
         (fl, "flow", "step_increase", "warning", "possible_leak", None, 0)]
    return "water_leak_or_overuse", sev, s, "tank draining with high flow"


def mk_supply():
    lv, fl = R.choice(TANKS)
    sev = sev_pick(0.4, 0.5)
    s = [(lv, "level", "gradual_decrease", sev, "supply_interruption", None, 0),
         (fl, "flow", "dip", "warning", "supply_interruption", None, 0)]
    return "water_supply_issue", sev, s, "inflow stopped, tank level falling"


def mk_quality():
    m = R.choice(["tds", "ph"])
    sev = sev_pick(0.35, 0.6)
    s = [("WM-WQ-KH98-01", m, R.choice(["spike", "step_increase"]), sev, "water_quality_issue", None, 0)]
    return "water_quality_issue", sev, s, "water quality out of range"


def mk_pload():
    m = R.choice(METERS)
    sev = sev_pick(0.3, 0.6)
    s = [(m, "power_kw", R.choice(["spike", "step_increase"]), sev, R.choice(["load_surge", "equipment_startup"]), None, 0)]
    return "power_load_anomaly", sev, s, "unexpected load increase"


def mk_pq():
    m = R.choice(["SR-EM-VN01-02", "EM-CR-SB00-00"])
    sev = sev_pick(0.4, 0.55)
    s = [(m, "pf", "dip", sev, "power_quality_issue", None, 0)]
    return "power_quality_issue", sev, s, "power factor dropped"


def mk_weather():
    sev = sev_pick(0.3, 0.6)
    ac = R.choice(["AC-KH03", "AC-VN02"])
    s = [("WE-VN04-00", "temp", "gradual_increase", sev, "heat_buildup", None, 0),
         (R.choice(METERS), "power_kw", "gradual_increase", "warning", "gradual_load_growth", None, 0),
         (ac, "ac_units_on", "step_increase", "normal", "hvac_context", None, 1)]
    return "weather_driven", sev, s, "heat wave raising cooling load"


def mk_fault():
    node, metric, dom, loc, u = R.choice([c for c in CATALOG if c[2] != "occupancy"])
    fk = R.choice(["stuck", "stuck", "bias", "drift", "noise", "dropout", "saturation", "quantised"])
    pat = {"stuck": "flatline", "dropout": "flatline", "noise": "erratic", "bias": "step_increase",
           "drift": "gradual_increase", "saturation": "flatline", "quantised": "erratic"}[fk]
    s = [(node, metric, pat, "sensor_fault", "sensor_fault", fk, 0)]
    return "sensor_fault", "sensor_fault", s, "sensor reading implausible (%s)" % fk


def mk_normal():
    node, metric, dom, loc, u = R.choice([c for c in CATALOG if c[2] in ("weather", "power", "air_quality")])
    s = [(node, metric, R.choice(["gradual_increase", "oscillation", "gradual_decrease"]), "normal",
          "normal_conditions", None, 0)]
    return "normal_operation", "normal", s, "normal daily cycle"


def mk_unknown():
    node, metric, dom, loc, u = R.choice(CATALOG)
    s = [(node, metric, "erratic", "warning", "unknown", None, 0)]
    return "unknown", "warning", s, "no clear cause"


def season(month, kind):
    if kind == "weather":
        return {3: 1.5, 4: 2.5, 5: 3.0, 6: 2.0}.get(month, 0.4)
    if kind == "poll":
        return {1: 2.5, 2: 2.0, 3: 1.2, 10: 1.5, 11: 2.5, 12: 2.5}.get(month, 0.5)
    if kind == "hvac":
        return {4: 2.0, 5: 2.5, 6: 1.8}.get(month, 0.7)
    return 1.0


GENS = [(mk_vent, 9, None), (mk_occ, 12, None), (mk_hvac, 6, "hvac"), (mk_poll, 5, "poll"), (mk_leak, 6, None),
        (mk_supply, 3, None), (mk_quality, 3, None), (mk_pload, 7, None), (mk_pq, 3, None),
        (mk_weather, 6, "weather"), (mk_fault, 10, None), (mk_normal, 7, None), (mk_unknown, 1, None)]

PLAYBOOK = {
    "ventilation_issue": ["inspect_ventilation", "monitor"], "occupancy_driven_load": ["review_schedule", "monitor"],
    "hvac_or_thermal_issue": ["inspect_hvac"], "air_pollution_event": ["inspect_ventilation", "monitor"],
    "water_leak_or_overuse": ["inspect_water_system"], "water_supply_issue": ["inspect_water_system"],
    "water_quality_issue": ["inspect_water_system", "request_facility_review"],
    "power_load_anomaly": ["inspect_electrical", "monitor"], "power_quality_issue": ["inspect_electrical"],
    "weather_driven": ["monitor", "review_schedule"], "normal_operation": ["none"], "unknown": ["monitor"],
}
STEP_TEXT = {"inspect_ventilation": "Inspect ventilation / fresh-air dampers", "monitor": "Monitor the next re-check",
             "review_schedule": "Review the room booking / HVAC schedule", "inspect_hvac": "Inspect the AC units",
             "inspect_water_system": "Inspect tank, valves and pipes", "request_facility_review": "Request a facility review",
             "inspect_electrical": "Inspect the electrical panel", "none": "No action needed",
             "check_sensor": "Check the sensor on site", "recalibrate_sensor": "Recalibrate the sensor",
             "replace_sensor": "Replace the sensor", "restart_or_reconnect_sensor": "Restart / reconnect the sensor"}

# Scripted maintenance histories (the "memory" cases): (node, metric, fault_kind, [(date, action, outcome)])
SCRIPTED_FAULTS = [
    ("SR-AQ-VN02-01", "temp", "stuck", [("2026-02-03 10:20", "recalibrate_sensor"), ("2026-02-21 14:05", "recalibrate_sensor"),
                                         ("2026-03-06 09:40", "replace_sensor")]),
    ("WM-WL-VN98-00", "level", "drift", [("2026-06-10 07:15", "recalibrate_sensor"), ("2026-07-01 08:30", "replace_sensor")]),
    ("SR-AQ-BK01-02", "pm25", "noise", [("2026-08-12 16:10", "restart_or_reconnect_sensor"), ("2026-09-02 11:45", "recalibrate_sensor")]),
    ("SR-AQ-KH03-03", "co2", "stuck", [("2026-09-14 13:30", "recalibrate_sensor"), ("2026-10-01 10:05", "recalibrate_sensor"),
                                        ("2026-10-20 15:50", None)]),   # recurred twice; latest still open
    ("EM-CR-SB00-00", "power_kw", "dropout", [("2026-05-19 03:10", "restart_or_reconnect_sensor")]),
    ("WE-VN04-00", "rh", "saturation", [("2026-07-22 06:00", "replace_sensor")]),
]


def load_real():
    """Real app-test incidents: latest stage per (run dir, id)."""
    pats = [os.path.join(PROOFS, "2026-10-21_v2_app", "*", "INC-*.json"),
            os.path.join(PROOFS, "2026-10-23_app_ab_v2_vs_3d", "*", "*", "INC-*.json")]
    files = sorted(set(sum([glob.glob(p) for p in pats], [])))
    order = {"early": 0, "1.5h": 1, "3h": 2}
    best = {}
    for f in files:
        d = json.load(open(f))
        key = (os.path.dirname(f), d["id"])
        rank = order.get(d.get("refine_stage") or "early", 0)
        if key not in best or rank >= best[key][0]:
            best[key] = (rank, f, d)
    out = []
    for (dirn, iid), (rank, f, d) in sorted(best.items(), key=lambda kv: kv[1][2]["created_wall"]):
        out.append((os.path.relpath(f, PROOFS).replace("\\", "/"), d))
    return out


def main():
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    if os.path.exists(STORE):
        os.remove(STORE)
    db = sqlite3.connect(STORE)
    db.executescript(SCHEMA)
    db.executescript(EXTRA)

    incidents = []   # dicts, assigned ids after sorting by time

    # ---------------- synthetic field year
    day = YEAR_START
    while day < NOW.replace(hour=0, minute=0, second=0):
        n = sum(1 for _ in range(6) if R.random() < 0.33)   # ~2 incidents / day
        for _ in range(n):
            ws = [w * (season(day.month, k) if k else 1.0) for _, w, k in GENS]
            gen = R.choices([g for g, _, _ in GENS], weights=ws)[0]
            label, sev, sensors, why = gen()
            t = day + dt.timedelta(minutes=R.randrange(0, 24 * 60))
            if label == "water_leak_or_overuse" and R.random() < 0.6:
                t = day + dt.timedelta(hours=R.choice([1, 2, 3, 4]), minutes=R.randrange(60))
            incidents.append(dict(t=t, label=label, severity=sev, sensors=sensors, why=why, injected=0,
                                  source="synthetic"))
        day += dt.timedelta(days=1)
    # demo injections inside the field year (excluded by default)
    for _ in range(25):
        label, sev, sensors, why = R.choice([mk_vent, mk_leak, mk_fault, mk_occ])()
        t = YEAR_START + dt.timedelta(minutes=R.randrange(0, int((NOW - YEAR_START).total_seconds() // 60) - 600))
        incidents.append(dict(t=t, label=label, severity=sev, sensors=sensors, why="demo injection: " + why,
                              injected=1, source="synthetic_injected"))
    # scripted recurring faults
    scripted = []
    for node, metric, fk, hist in SCRIPTED_FAULTS:
        pat = {"stuck": "flatline", "drift": "gradual_increase", "noise": "erratic", "dropout": "flatline",
               "saturation": "flatline"}[fk]
        for i, (ts, act) in enumerate(hist):
            t = dt.datetime.strptime(ts, "%Y-%m-%d %H:%M") - dt.timedelta(hours=R.choice([2, 3, 5]))
            inc = dict(t=t, label="sensor_fault", severity="sensor_fault",
                       sensors=[(node, metric, pat, "sensor_fault", "sensor_fault", fk, 0)],
                       why="sensor reading implausible (%s)" % fk, injected=0, source="scripted_fault",
                       scripted_action=(ts, act))
            incidents.append(inc)
            scripted.append(inc)

    # ---------------- real app-test incidents
    for rel, d in load_real():
        t = dt.datetime.strptime(d["created_wall"], "%Y-%m-%d %H:%M:%S")
        if t >= NOW:
            t = NOW - dt.timedelta(hours=2)
        fin = ((d.get("final") or {}).get("parsed") or {})
        sensors = []
        for i, s in enumerate(d["sensors"]):
            ag = None
            for a in d.get("agents") or []:
                if a.get("ref") == s["ref"] and a.get("valid") and a.get("parsed"):
                    ag = a["parsed"]
            f = ag or s.get("rule_finding") or {}
            sensors.append((s["node"], s["metric"], f.get("pattern"), f.get("status"), f.get("likely_cause"),
                            f.get("fault_kind"), 1 if s.get("context") else 0, s.get("role"), s.get("location")))
        incidents.append(dict(t=t, label=fin.get("label") or "unknown", severity=d["severity"], sensors=sensors,
                              why=fin.get("root_cause") or d.get("title"), injected=1, source="real:" + rel,
                              title=d.get("title"), root_cause=fin.get("root_cause"),
                              refine_stage=d.get("refine_stage") or "early", approval=d.get("approval") or "pending",
                              approval_note=d.get("approval_note") or "", real=True))

    incidents.sort(key=lambda x: x["t"])
    for i, inc in enumerate(incidents, 1):
        inc["id"] = "INC-%04d" % i

    # ---------------- write incidents, sensors, steps, events, maintenance
    last_fault_close = {}
    for inc in incidents:
        t = inc["t"]
        age_h = (NOW - t).total_seconds() / 3600
        flagged = [s for s in inc["sensors"] if not s[6]]
        f0 = flagged[0] if flagged else inc["sensors"][0]
        n0, m0 = f0[0], f0[1]
        loc0 = CAT.get((n0, m0), ("", f0[8] if len(f0) > 8 else "", ""))[1]
        title = inc.get("title") or "%s %s: %s" % (m0.upper() if m0 in ("co2", "pf", "tds") else m0.replace("_", " "),
                                                    (f0[2] or "event").replace("_", " "), loc0)
        root = inc.get("root_cause") or ("%s at %s" % (inc["why"], loc0))
        if inc.get("real"):
            approval, workflow, outcome = inc["approval"], ("closed" if inc["approval"] != "pending" else "needs_decision"), None
            if inc["approval"] == "dismissed":
                outcome = "no_action_needed"
        elif age_h < 30:
            approval = R.choice(["pending", "pending", "approved"])
            workflow = "needs_decision" if approval == "pending" else "in_progress"
            outcome = None
        else:
            x = R.random()
            approval = "approved" if x < 0.78 else ("dismissed" if x < 0.93 else "pending")
            workflow = "closed" if approval != "pending" else "needs_decision"
            outcome = None
        steps = []
        op = R.choice(OPERATORS)
        if inc["label"] == "sensor_fault" and not inc.get("real"):
            act = inc.get("scripted_action", (None, None))[1] if inc.get("source") == "scripted_fault" else \
                R.choice(["recalibrate_sensor", "recalibrate_sensor", "replace_sensor", "restart_or_reconnect_sensor", "check_sensor"])
            if inc.get("source") == "scripted_fault":
                if act is None:
                    approval, workflow = "pending", "needs_decision"
                else:
                    approval, workflow = "approved", "closed"
            steps = [("check_sensor", "done" if workflow == "closed" else "open")]
            if act and act != "check_sensor":
                steps.append((act, "done" if workflow == "closed" else "open"))
            if workflow == "closed" and approval == "approved":
                outcome = {"replace_sensor": "sensor_replaced", "recalibrate_sensor": "sensor_repaired",
                           "restart_or_reconnect_sensor": "sensor_repaired", "check_sensor": "false_alarm"}.get(act, "sensor_repaired")
            elif approval == "dismissed":
                outcome = "false_alarm"
        elif not inc.get("real"):
            for a in PLAYBOOK.get(inc["label"], ["monitor"]):
                st = "open"
                if workflow == "closed":
                    st = "done" if R.random() < 0.8 else "not_needed"
                elif workflow == "in_progress":
                    st = R.choice(["open", "done"])
                steps.append((a, st))
            if workflow == "closed":
                if approval == "dismissed":
                    outcome = R.choice(["false_alarm", "no_action_needed"])
                elif any(s == "done" and a not in ("monitor", "none") for a, s in steps):
                    outcome = "fixed_by_action"
                else:
                    outcome = "resolved_on_its_own"
        if inc["severity"] == "critical" and workflow == "closed" and approval == "approved" and outcome is None:
            outcome = "fixed_by_action"
        acked = iso(t + dt.timedelta(minutes=R.randrange(3, 40))) if approval != "pending" else None
        closed = iso(t + dt.timedelta(hours=R.randrange(2, 30))) if workflow == "closed" else None
        if inc.get("source") == "scripted_fault" and inc["scripted_action"][1]:
            closed = inc["scripted_action"][0] + ":00"
        stage = inc.get("refine_stage") or ("3h" if age_h > 3.2 else ("1.5h" if age_h > 1.6 else "early"))
        db.execute("INSERT INTO incident (id, version, created_wall, created_sim, state, mode, severity, severity_final,"
                   " rule_severity, label, root_cause, title, refine_stage, resolved_at, approval, approval_note, injected,"
                   " full_on_device, synced_version, workflow, owner, acked_at, closed_at, outcome, outcome_note, source)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (inc["id"], 3, iso(t), epoch(t), "done", 3 if len(inc["sensors"]) > 1 else 2,
                    inc["severity"], 1, inc["severity"], inc["label"], root, title, stage, closed, approval,
                    inc.get("approval_note") or ("dismissed: harmless" if approval == "dismissed" else ""),
                    inc["injected"], 1, 3, workflow, op if approval != "pending" else None, acked, closed, outcome,
                    None, inc["source"]))
        for k, s in enumerate(inc["sensors"], 1):
            node, metric = s[0], s[1]
            dom, loc, _u = CAT.get((node, metric), (s[7] if len(s) > 7 else "unknown", s[8] if len(s) > 8 else "", ""))
            db.execute("INSERT INTO incident_sensor VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (inc["id"], "S%d" % k, node, metric, dom, loc, s[6], "agent", s[2], s[3], s[4],
                        s[5] if s[3] == "sensor_fault" else None, (t - dt.timedelta(minutes=35)).strftime("%H:%M")))
        for k, (a, st) in enumerate(steps, 1):
            db.execute("INSERT INTO incident_step VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (inc["id"], "s%d" % k, "reasoner", a, "%s/%s" % (n0, m0), STEP_TEXT[a], inc["why"], "early", st,
                        op if st != "open" else None, closed if st != "open" else None, None))
            if st == "done" and a in ("replace_sensor", "recalibrate_sensor", "restart_or_reconnect_sensor"):
                mact = {"replace_sensor": "replaced", "recalibrate_sensor": "recalibrated",
                        "restart_or_reconnect_sensor": "repaired"}[a]
                db.execute("INSERT INTO maintenance (at_wall, node, metric, action, incident_id, operator, note) VALUES (?,?,?,?,?,?,?)",
                           (closed, n0, m0, mact, inc["id"], op, STEP_TEXT[a]))
        db.execute("INSERT INTO incident_event (incident_id, at_wall, actor, event) VALUES (?,?,?,?)", (inc["id"], iso(t), "system", "created"))
        if acked:
            db.execute("INSERT INTO incident_event (incident_id, at_wall, actor, event) VALUES (?,?,?,?)", (inc["id"], acked, op, "ack"))
        if closed and workflow == "closed":
            db.execute("INSERT INTO incident_event (incident_id, at_wall, actor, event, outcome) VALUES (?,?,?,?,?)",
                       (inc["id"], closed, op, "closed" if approval == "approved" else "dismissed", outcome))
        # recurrence: same sensor faults again within 7 days of a close
        if inc["label"] == "sensor_fault":
            key = (n0, m0)
            prev = last_fault_close.get(key)
            if prev and (t - prev[1]).total_seconds() < 7 * 86400 + 1 and prev[1] <= t:
                db.execute("UPDATE incident SET recurred_by=? WHERE id=?", (inc["id"], prev[0]))
            if closed:
                last_fault_close[key] = (inc["id"], dt.datetime.strptime(closed[:19], "%Y-%m-%d %H:%M:%S"))
    # a couple of maintenance rows with no incident (routine work)
    db.execute("INSERT INTO maintenance (at_wall, node, metric, action, incident_id, operator, note) VALUES (?,?,?,?,?,?,?)",
               ("2026-04-02 10:00:00", "WM-WQ-KH98-01", "ph", "recalibrated", None, "op_meena", "quarterly calibration"))
    db.execute("INSERT INTO maintenance (at_wall, node, metric, action, incident_id, operator, note) VALUES (?,?,?,?,?,?,?)",
               ("2026-07-02 10:00:00", "WM-WQ-KH98-01", "ph", "recalibrated", None, "op_meena", "quarterly calibration"))
    db.execute("INSERT INTO maintenance (at_wall, node, metric, action, incident_id, operator, note) VALUES (?,?,?,?,?,?,?)",
               ("2026-09-15 12:00:00", "SR-OC-GW-VN95-02", "occ", "installed", None, "op_arjun", "new occupancy sensor"))

    # ---------------- readings
    gen_readings(db, incidents)
    db.commit()
    # manifest
    cnt = {r[0]: r[1] for r in db.execute("SELECT source LIKE 'real:%', COUNT(*) FROM incident GROUP BY 1")}
    man = {"what": "benchmark incident store (store_schema.sql + incident_event/incident_step + workflow columns)",
           "now": NOW.isoformat(), "incidents_total": db.execute("SELECT COUNT(*) FROM incident").fetchone()[0],
           "real_app_test_incidents": cnt.get(1, 0), "synthetic_incidents": cnt.get(0, 0),
           "injected": db.execute("SELECT COUNT(*) FROM incident WHERE injected=1").fetchone()[0],
           "maintenance_rows": db.execute("SELECT COUNT(*) FROM maintenance").fetchone()[0],
           "steps": db.execute("SELECT COUNT(*) FROM incident_step").fetchone()[0],
           "hourly_rows": db.execute("SELECT COUNT(*) FROM reading_hourly").fetchone()[0],
           "fivemin_rows": db.execute("SELECT COUNT(*) FROM reading_5min").fetchone()[0],
           "labels": dict(db.execute("SELECT label, COUNT(*) FROM incident WHERE injected=0 GROUP BY label").fetchall()),
           "seed": 20261022}
    db.close()
    man["sha256"] = hashlib.sha256(open(STORE, "rb").read()).hexdigest()
    json.dump(man, open(os.path.join(os.path.dirname(STORE), "store_manifest.json"), "w"), indent=1)
    print(json.dumps(man, indent=1))


def base_value(node, metric, t, rr):
    h = t.hour + t.minute / 60.0
    wk = t.weekday() < 5
    day = 1.0 if (wk and 9 <= h < 18) else 0.0
    diurnal = math.sin((h - 9) / 24 * 2 * math.pi)
    if metric == "co2":
        return 440 + day * (280 + 120 * math.sin((h - 9) / 9 * math.pi)) + rr.gauss(0, 12)
    if metric == "temp" and node.startswith("WE"):
        return 27.5 + 4.5 * diurnal + rr.gauss(0, 0.3)
    if metric in ("temp", "room_temp"):
        return 24.5 + 0.8 * diurnal + day * 0.6 + rr.gauss(0, 0.15)
    if metric == "rh":
        return (68 if node.startswith("WE") else 55) - 9 * diurnal + rr.gauss(0, 1.0)
    if metric == "pm25":
        return (48 if node.startswith("AQ") else 22) + 10 * math.cos(h / 24 * 2 * math.pi) + rr.gauss(0, 2)
    if metric == "pm10":
        return 85 + 18 * math.cos(h / 24 * 2 * math.pi) + rr.gauss(0, 4)
    if metric == "level":
        return 45 + 40 * ((h % 12) / 12.0 if (h % 12) < 6 else (1 - (h % 12) / 12.0)) + rr.gauss(0, 0.5)
    if metric == "flow":
        return max(0.0, 0.6 + 1.6 * day + rr.gauss(0, 0.1))
    if metric == "tds":
        return 310 + rr.gauss(0, 4)
    if metric == "ph":
        return 7.4 + rr.gauss(0, 0.03)
    if metric == "power_kw":
        scale = {"SR-EM-KH04-01": 18, "SR-EM-VN01-02": 30, "EM-CR-SB00-00": 820}[node]
        return scale * (1 + 0.9 * day + 0.15 * max(diurnal, 0)) + rr.gauss(0, scale * 0.02)
    if metric == "pf":
        return 0.93 + rr.gauss(0, 0.005)
    if metric == "occ":
        return 1.0 if day and rr.random() < 0.9 else 0.0
    if metric == "wind":
        return max(0.0, 2.5 + 1.5 * diurnal + rr.gauss(0, 0.4))
    if metric == "ac_units_on":
        return float(4 if day else 1)
    return 0.0


def gen_readings(db, incidents):
    rr = random.Random(7)
    # event bumps from incidents inside the readings window (flagged sensors only)
    bumps = {}
    for inc in incidents:
        if inc["t"] < READINGS_FROM:
            continue
        for s in inc["sensors"]:
            if s[6]:
                continue
            bumps.setdefault((s[0], s[1]), []).append((inc["t"], s[2], s[3]))
    step = dt.timedelta(minutes=5)
    for node, metric, dom, loc, u in CATALOG:
        t = READINGS_FROM
        hour_acc = []
        evs = bumps.get((node, metric), [])
        while t < NOW:
            v = base_value(node, metric, t, rr)
            for (et, pat, st) in evs:
                dtm = (t - et).total_seconds() / 3600
                if -2.5 <= dtm <= 0.5:
                    k = (dtm + 2.5) / 3.0
                    if st == "sensor_fault" and pat == "flatline":
                        v = round(base_value(node, metric, et - dt.timedelta(hours=3), random.Random(1)), 1)
                    elif pat in ("dip", "gradual_decrease", "step_decrease"):
                        v = v * (1 - 0.45 * k)
                    else:
                        v = v * (1 + 0.9 * k * (1.4 if st == "critical" else 1.0))
            if metric == "occ":
                v = float(v >= 0.5)
            elif metric == "ac_units_on":
                v = float(round(v))
            elif metric in ("pf", "ph"):
                v = round(v, 3)
            else:
                v = round(v, 1)
            if t >= FIVEMIN_FROM:
                db.execute("INSERT INTO reading_5min VALUES (?,?,?,?)", (node, metric, epoch(t), v))
            hour_acc.append(v)
            t += step
            if t.minute == 0:
                h0 = t - dt.timedelta(hours=1)
                db.execute("INSERT INTO reading_hourly VALUES (?,?,?,?,?,?,?,?)",
                           (node, metric, epoch(h0), len(hour_acc), round(sum(hour_acc) / len(hour_acc), 3),
                            min(hour_acc), max(hour_acc), hour_acc[-1]))
                hour_acc = []


if __name__ == "__main__":
    main()
