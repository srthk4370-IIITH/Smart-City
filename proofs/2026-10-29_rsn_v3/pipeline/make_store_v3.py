"""train_store_v3.sqlite = a copy of the round-1 training store (proofs/2026-10-25_reasoner_final/data/train_store.sqlite,
never modified) with three fixes for the rsn_v3 chat data:

1. today/yesterday: the round-1 store has no incident on the sim day (2026-10-22, now 12:00 IST) and one on the day
   before. Added: 8 incidents on 2026-10-21 and 9 on 2026-10-22 (one a demo injection, one still being analysed) in
   the shapes of the round-1 builder (P0/host_bench/build_store.py families: same sensors, patterns, causes, titles,
   steps, events), mixed severities, domains and approval states. Their flagged sensors' readings get the builder's
   event bump (-2.5 h .. +0.5 h around the incident; dips for dip/decrease patterns, erratic values for a noise fault).
2. realistic readings for what_if: the round-1 readings are smooth functions of a weekday-daytime switch, so every
   pair of sensors fits with r2 0.9-1.0. Per sensor and hour an AR(1) offset (seeded) is added to the hourly rollup and
   to every 5-min reading of that hour; occupancy (a 0/1 presence sensor, as on the device: features.go "occupancy/occ"
   unit 0/1, sensors.json min 0 max 1 step 1) gets vacant daytime hours (free periods) and some occupied evening/
   weekend hours, AC units on vary by +-1-2 per hour. Hourly rollups at and after FIVEMIN_FROM are recomputed from the
   5-min rows. Target: what_if fits with r2 spread over ~0.2-0.8 and some no-link cases.
3. occupancy stays a 0/1 presence sensor (no people counts), so the tools and the spec use the hourly occupied
   fraction.

  python3 make_store_v3.py   -> ../data/train_store_v3.sqlite + ../data/store_v3_manifest.json
"""
import datetime as dt
import hashlib
import json
import math
import os
import random
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tools_v3_impl import STORE, STORE_R1, ep, fromts  # noqa: E402
from common import NOW, FIVEMIN_FROM, CATALOG, CAT  # noqa: E402

SEED = 20261029
OPS = ["op_ravi", "op_meena", "op_arjun", "op_sana"]
STEP_TEXT = {"inspect_ventilation": "Inspect ventilation / fresh-air dampers", "monitor": "Monitor the next re-check",
             "review_schedule": "Review the room booking / HVAC schedule", "inspect_hvac": "Inspect the AC units",
             "inspect_water_system": "Inspect tank, valves and pipes", "request_facility_review": "Request a facility review",
             "inspect_electrical": "Inspect the electrical panel", "none": "No action needed",
             "check_sensor": "Check the sensor on site", "recalibrate_sensor": "Recalibrate the sensor",
             "replace_sensor": "Replace the sensor", "restart_or_reconnect_sensor": "Restart / reconnect the sensor"}
PLAYBOOK = {
    "ventilation_issue": ["inspect_ventilation", "monitor"], "occupancy_driven_load": ["review_schedule", "monitor"],
    "hvac_or_thermal_issue": ["inspect_hvac"], "air_pollution_event": ["inspect_ventilation", "monitor"],
    "water_leak_or_overuse": ["inspect_water_system"], "water_supply_issue": ["inspect_water_system"],
    "water_quality_issue": ["inspect_water_system", "request_facility_review"],
    "power_load_anomaly": ["inspect_electrical", "monitor"], "power_quality_issue": ["inspect_electrical"],
    "weather_driven": ["monitor", "review_schedule"], "normal_operation": ["none"], "unknown": ["monitor"],
    "sensor_fault": ["check_sensor", "recalibrate_sensor"],
}

# (time, label, severity, why, sensors [(node, metric, pattern, status, cause, fault_kind, context)], approval, workflow,
#  outcome, state, injected)
NEW = [
    ("2026-10-21 07:55", "occupancy_driven_load", "warning", "CO2 rise from room occupancy",
     [("SR-AQ-KH03-03", "co2", "step_increase", "warning", "occupancy_load", None, 0), ("SR-OC-GW-KH95-01", "occ", "arrival", "normal", "arrival", None, 1)],
     "approved", "closed", "resolved_on_its_own", "done", 0),
    ("2026-10-21 10:20", "power_load_anomaly", "critical", "unexpected load increase",
     [("EM-CR-SB00-00", "power_kw", "step_increase", "critical", "load_surge", None, 0)], "approved", "closed", "fixed_by_action", "done", 0),
    ("2026-10-21 13:05", "water_leak_or_overuse", "warning", "tank draining with high flow",
     [("WM-WL-VN98-00", "level", "gradual_decrease", "warning", "possible_leak", None, 0),
      ("WM-WF-VN98-10", "flow", "step_increase", "warning", "possible_leak", None, 0)], "pending", "needs_decision", None, "done", 0),
    ("2026-10-21 15:30", "hvac_or_thermal_issue", "critical", "room temperature rising while AC units drop out",
     [("AC-VN02", "room_temp", "gradual_increase", "critical", "hvac_cooling_issue", None, 0),
      ("AC-VN02", "ac_units_on", "step_decrease", "warning", "hvac_cooling_issue", None, 0)], "approved", "in_progress", None, "done", 0),
    ("2026-10-21 17:10", "air_pollution_event", "warning", "outdoor PM2.5 entering the building",
     [("SR-AQ-BK01-02", "pm25", "gradual_increase", "warning", "outdoor_pollution_ingress", None, 0),
      ("AQ-KN00-00", "pm25", "gradual_increase", "warning", "outdoor_pollution_ingress", None, 0),
      ("WE-VN04-00", "wind", "stable", "normal", "normal_weather", None, 1)], "approved", "closed", "resolved_on_its_own", "done", 0),
    ("2026-10-21 19:40", "normal_operation", "normal", "normal daily cycle",
     [("WE-VN04-00", "temp", "gradual_decrease", "normal", "normal_conditions", None, 0)], "dismissed", "closed", "no_action_needed", "done", 0),
    ("2026-10-21 21:15", "sensor_fault", "sensor_fault", "sensor reading implausible (noise)",
     [("WM-WQ-KH98-01", "ph", "erratic", "sensor_fault", "sensor_fault", "noise", 0)], "pending", "needs_decision", None, "done", 0),
    ("2026-10-21 23:35", "water_supply_issue", "warning", "inflow stopped, tank level falling",
     [("WM-WL-KH98-00", "level", "gradual_decrease", "warning", "supply_interruption", None, 0),
      ("WM-WF-KH98-40", "flow", "dip", "warning", "supply_interruption", None, 0)], "approved", "in_progress", None, "done", 0),
    ("2026-10-22 02:40", "water_leak_or_overuse", "critical", "tank draining with high flow",
     [("WM-WL-KH98-00", "level", "gradual_decrease", "critical", "possible_leak", None, 0),
      ("WM-WF-KH98-40", "flow", "step_increase", "warning", "possible_leak", None, 0)], "pending", "needs_decision", None, "done", 0),
    ("2026-10-22 07:50", "power_quality_issue", "critical", "power factor dropped",
     [("SR-EM-VN01-02", "pf", "dip", "critical", "power_quality_issue", None, 0)], "pending", "needs_decision", None, "done", 0),
    ("2026-10-22 08:35", "ventilation_issue", "critical", "demo injection: CO2 rising with ventilation reduced",
     [("SR-AQ-KH03-03", "co2", "exponential_increase", "critical", "ventilation_insufficient", None, 0)], "pending", "needs_decision", None, "done", 1),
    ("2026-10-22 09:25", "ventilation_issue", "warning", "CO2 rising with ventilation reduced",
     [("SR-AQ-VN02-01", "co2", "gradual_increase", "warning", "ventilation_insufficient", None, 0),
      ("AC-VN02", "ac_units_on", "step_decrease", "normal", "hvac_context", None, 1),
      ("SR-OC-GW-VN95-02", "occ", "occupied", "normal", "normal_occupancy", None, 1)], "approved", "in_progress", None, "done", 0),
    ("2026-10-22 10:05", "occupancy_driven_load", "critical", "CO2 rise from room occupancy",
     [("SR-AQ-KH03-01", "co2", "exponential_increase", "critical", "occupancy_load", None, 0),
      ("SR-OC-GW-KH95-01", "occ", "arrival", "normal", "arrival", None, 1)], "pending", "needs_decision", None, "done", 0),
    ("2026-10-22 10:40", "sensor_fault", "sensor_fault", "sensor reading implausible (noise)",
     [("SR-AQ-BK01-02", "pm25", "erratic", "sensor_fault", "sensor_fault", "noise", 0)], "pending", "needs_decision", None, "done", 0),
    ("2026-10-22 11:05", "power_load_anomaly", "warning", "unexpected load increase",
     [("SR-EM-KH04-01", "power_kw", "spike", "warning", "equipment_startup", None, 0)], "dismissed", "closed", "false_alarm", "done", 0),
    ("2026-10-22 11:20", "weather_driven", "warning", "heat wave raising cooling load",
     [("WE-VN04-00", "temp", "gradual_increase", "warning", "heat_buildup", None, 0),
      ("SR-EM-VN01-02", "power_kw", "gradual_increase", "warning", "gradual_load_growth", None, 0),
      ("AC-VN02", "ac_units_on", "step_increase", "normal", "hvac_context", None, 1)], "pending", "needs_decision", None, "done", 0),
    ("2026-10-22 11:50", "water_quality_issue", "warning", "water quality out of range",
     [("WM-WQ-KH98-01", "tds", "step_increase", "warning", "water_quality_issue", None, 0)], "pending", "analysing", None, "running", 0),
]

# per-hour AR(1) offset sd per metric (phi 0.75); tuned for what_if r2 ~0.2-0.8
HOUR_SD = {"co2": 55.0, "temp": 0.3, "rh": 2.0, "pm25": 4.0, "pm10": 7.0, "level": 3.0, "flow": 0.28, "tds": 6.0,
           "ph": 0.03, "power_kw": 0.17, "pf": 0.008, "wind": 0.5, "room_temp": 0.22}
REL = {"power_kw"}   # sd relative to the meter's scale


def wall(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")


def copy_store():
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    if os.path.exists(STORE):
        os.remove(STORE)
    src = sqlite3.connect("file:%s?mode=ro" % STORE_R1, uri=True)
    dst = sqlite3.connect(STORE)
    src.backup(dst)
    src.close()
    dst.execute("PRAGMA journal_mode=DELETE")
    return dst


def add_noise(db, R):
    """per sensor/hour AR(1) offsets on hourly rollups and 5-min readings; occupancy and AC schedules made irregular"""
    scale = {"SR-EM-KH04-01": 18, "SR-EM-VN01-02": 30, "EM-CR-SB00-00": 820}
    f0 = ep(FIVEMIN_FROM)
    for node, metric, dom, loc, unit in CATALOG:
        hours = [r[0] for r in db.execute("SELECT t FROM reading_hourly WHERE node=? AND metric=? ORDER BY t", (node, metric))]
        x = 0.0
        for t in hours:
            w = fromts(t)
            day = w.weekday() < 5 and 9 <= w.hour < 18
            if metric == "occ":
                if day:
                    frac = 0.0 if R.random() < 0.2 else R.choice([0.5, 0.75, 0.9, 1.0, 1.0])
                else:
                    frac = R.choice([0.25, 0.5, 0.75]) if R.random() < 0.05 else 0.0
                set_hour(db, node, metric, t, t >= f0, lambda v, k: 1.0 if R.random() < frac else 0.0, frac)
                continue
            if metric == "ac_units_on":
                off = R.choice([-2, -1, -1, 0, 0, 0, 1, 1]) if day else R.choice([-1, 0, 0, 0, 1])
                set_hour(db, node, metric, t, t >= f0, lambda v, k: float(max(0, min(6, round(v + off)))), None)
                continue
            sd = HOUR_SD.get(metric, 0.0) * (scale.get(node, 1) if metric in REL else 1)
            if not sd:
                continue
            x = 0.75 * x + math.sqrt(1 - 0.75 ** 2) * R.gauss(0, sd)
            off = x
            dec = 3 if metric in ("pf", "ph") else 1
            lo = 0.0 if metric not in ("temp", "room_temp") else -50
            set_hour(db, node, metric, t, t >= f0, lambda v, k, o=off: round(max(lo, v + o), dec), None)


def set_hour(db, node, metric, t, five, fn, mean_override):
    """apply fn(v, k) to the 5-min readings of hour t (recomputing the rollup), or to the rollup when no 5-min rows"""
    rows = db.execute("SELECT t, v FROM reading_5min WHERE node=? AND metric=? AND t>=? AND t<? ORDER BY t", (node, metric, t, t + 3600)).fetchall() if five else []
    if rows:
        for k, (tt, v) in enumerate(rows):
            db.execute("UPDATE reading_5min SET v=? WHERE node=? AND metric=? AND t=?", (fn(v, k), node, metric, tt))
        return
    r = db.execute("SELECT n, mean, min, max, last FROM reading_hourly WHERE node=? AND metric=? AND t=?", (node, metric, t)).fetchone()
    n, mean, mn, mx, last = r
    if mean_override is not None:      # occupancy: a fraction of the hour occupied
        k = int(round(mean_override * n))
        db.execute("UPDATE reading_hourly SET mean=?, min=?, max=?, last=? WHERE node=? AND metric=? AND t=?",
                   (round(k / n, 3), 0.0 if k < n else 1.0, 1.0 if k > 0 else 0.0, 1.0 if k == n else 0.0, node, metric, t))
        return
    db.execute("UPDATE reading_hourly SET mean=?, min=?, max=?, last=? WHERE node=? AND metric=? AND t=?",
               (round(fn(mean, 0) if metric != "ac_units_on" else max(0.0, mean + (fn(mx, 0) - mx)), 3), fn(mn, 0), fn(mx, 0), fn(last, 0), node, metric, t))


def bump(db, R, t0, sensors, sev):
    """the round-1 builder's event shape on the flagged sensors' 5-min readings"""
    for node, metric, pat, st, cause, fk, ctx in sensors:
        if ctx:
            continue
        rows = db.execute("SELECT t, v FROM reading_5min WHERE node=? AND metric=? AND t>=? AND t<=? ORDER BY t",
                          (node, metric, ep(t0 - dt.timedelta(hours=2.5)), ep(min(NOW, t0 + dt.timedelta(hours=0.5))))).fetchall()
        for tt, v in rows:
            k = ((fromts(tt) - t0).total_seconds() / 3600 + 2.5) / 3.0
            if st == "sensor_fault" and fk == "noise":
                nv = v * (1 + R.choice([-1, 1]) * R.uniform(0.3, 1.4) * min(1.0, 2 * k))
            elif pat in ("dip", "gradual_decrease", "step_decrease"):
                nv = v * (1 - 0.45 * k)
            else:
                nv = v * (1 + 0.9 * k * (1.4 if st == "critical" else 1.0))
            if metric == "ac_units_on":
                nv = float(round(nv))
            elif metric == "ph" and st == "sensor_fault":
                nv = 7.4 + (nv - 7.4) * 6        # pH noise: wild swings around neutral
            nv = round(max(0.0, nv), 3 if metric in ("pf", "ph") else 1)
            db.execute("UPDATE reading_5min SET v=? WHERE node=? AND metric=? AND t=?", (nv, node, metric, tt))


def rollup(db):
    f0 = ep(FIVEMIN_FROM)
    for node, metric, *_ in CATALOG:
        rows = db.execute("SELECT t, v FROM reading_5min WHERE node=? AND metric=? AND t>=? ORDER BY t", (node, metric, f0)).fetchall()
        by = {}
        for t, v in rows:
            by.setdefault(t - (t % 3600), []).append(v)
        for h, vs in by.items():
            db.execute("UPDATE reading_hourly SET n=?, mean=?, min=?, max=?, last=? WHERE node=? AND metric=? AND t=?",
                       (len(vs), round(sum(vs) / len(vs), 3), min(vs), max(vs), vs[-1], node, metric, h))


def add_incidents(db, R):
    n0 = int(db.execute("SELECT MAX(CAST(substr(id,5) AS INTEGER)) FROM incident").fetchone()[0])
    out = []
    for k, (ts, label, sev, why, sensors, approval, workflow, outcome, state, inj) in enumerate(NEW, 1):
        iid = "INC-%04d" % (n0 + k)
        t = wall(ts)
        age_h = (NOW - t).total_seconds() / 3600
        f0 = next(s for s in sensors if not s[6])
        loc0 = CAT[(f0[0], f0[1])][1]
        mname = f0[1].upper() if f0[1] in ("co2", "pf", "tds") else f0[1].replace("_", " ")
        title = "%s %s: %s" % (mname, f0[2].replace("_", " "), loc0)
        root = None if state == "running" else "%s at %s" % (why, loc0)
        stage = "3h" if age_h > 3.2 else ("1.5h" if age_h > 1.6 else "early")
        op = R.choice(OPS)
        acked = (t + dt.timedelta(minutes=R.randrange(4, 35))) if approval != "pending" else None
        closed = (t + dt.timedelta(hours=R.randrange(2, 9))) if workflow == "closed" else None
        if closed and closed > NOW:
            closed = NOW - dt.timedelta(minutes=R.randrange(5, 30))
        if acked and closed and acked > closed:
            acked = t + dt.timedelta(minutes=3)
        S = lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if x else None  # noqa: E731
        db.execute("INSERT INTO incident (id, version, created_wall, created_sim, state, mode, severity, severity_final,"
                   " rule_severity, label, root_cause, title, refine_stage, resolved_at, approval, approval_note, injected,"
                   " full_on_device, synced_version, workflow, owner, acked_at, closed_at, outcome, outcome_note, source)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (iid, 1 if state == "running" else 3, S(t), ep(t), state, 3 if len(sensors) > 1 else 2, sev, 0 if state == "running" else 1, sev,
                    None if state == "running" else label, root, title, stage, S(closed), approval,
                    "dismissed: harmless" if approval == "dismissed" else "", inj, 1, 3, workflow,
                    op if approval != "pending" else None, S(acked), S(closed), outcome, None,
                    "synthetic_injected" if inj else "synthetic_v3"))
        for j, s in enumerate(sensors, 1):
            node, metric = s[0], s[1]
            dom, loc, _u = CAT[(node, metric)]
            db.execute("INSERT INTO incident_sensor VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (iid, "S%d" % j, node, metric, dom, loc, s[6], "agent", s[2], s[3], s[4], s[5] if s[3] == "sensor_fault" else None,
                        (t - dt.timedelta(minutes=35)).strftime("%H:%M")))
        if state != "running":
            for j, a in enumerate(PLAYBOOK[label], 1):
                st = "open"
                if workflow == "closed":
                    st = "done" if approval == "approved" else "not_needed"
                elif workflow == "in_progress" and j == 1:
                    st = "done"
                db.execute("INSERT INTO incident_step VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (iid, "s%d" % j, "reasoner", a, "%s/%s" % (f0[0], f0[1]), STEP_TEXT[a], why, "early", st,
                            op if st != "open" else None, S(closed or acked) if st != "open" else None, None))
        db.execute("INSERT INTO incident_event (incident_id, at_wall, actor, event) VALUES (?,?,?,?)", (iid, S(t), "system", "created"))
        if acked:
            db.execute("INSERT INTO incident_event (incident_id, at_wall, actor, event) VALUES (?,?,?,?)", (iid, S(acked), op, "ack"))
        if closed:
            db.execute("INSERT INTO incident_event (incident_id, at_wall, actor, event, outcome) VALUES (?,?,?,?,?)",
                       (iid, S(closed), op, "closed" if approval == "approved" else "dismissed", outcome))
        out.append((iid, t, sensors, sev))
    return out


def main():
    R = random.Random(SEED)
    db = copy_store()
    add_noise(db, R)
    new = add_incidents(db, R)
    for iid, t, sensors, sev in new:
        bump(db, R, t, sensors, sev)
    rollup(db)
    db.commit()
    q = lambda s, *p: db.execute(s, p).fetchall()  # noqa: E731
    man = {"what": "rsn_v3 chat training store: copy of the round-1 train store + today/yesterday incidents + per-hour noise "
                   "(make_store_v3.py)", "source": os.path.relpath(STORE_R1, os.path.dirname(STORE)), "now": NOW.isoformat(), "seed": SEED,
           "incidents_total": q("SELECT COUNT(*) FROM incident")[0][0], "added": [x[0] for x in new],
           "per_day": dict(q("SELECT substr(created_wall,1,10), COUNT(*) FROM incident WHERE created_wall>='2026-10-20' GROUP BY 1")),
           "today_by_severity": dict(q("SELECT severity, COUNT(*) FROM incident WHERE created_wall>='2026-10-22' AND injected=0 GROUP BY 1")),
           "today_by_workflow": dict(q("SELECT workflow, COUNT(*) FROM incident WHERE created_wall>='2026-10-22' AND injected=0 GROUP BY 1")),
           "hourly_rows": q("SELECT COUNT(*) FROM reading_hourly")[0][0], "fivemin_rows": q("SELECT COUNT(*) FROM reading_5min")[0][0]}
    db.close()
    man["sha256"] = hashlib.sha256(open(STORE, "rb").read()).hexdigest()
    with open(os.path.join(os.path.dirname(STORE), "store_v3_manifest.json"), "w") as f:
        json.dump(man, f, indent=1)
    print(json.dumps(man))


if __name__ == "__main__":
    main()
