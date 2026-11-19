"""r4 tool store: the r3 stores (device + fog) plus synthetic CROSS-DOMAIN CLUSTERS with a known causal graph, so cross-domain
chat questions (why / what links / which is the root / chains) have a checkable answer. Incident ids are renumbered by time
(INC-0001 ...), in every table and text column, so ids stay monotonic as on the board.

Clusters (device window 2026-06-25 .. 2026-10-20, all full on the device, same rows in the fog store):
  heat   : weather_driven (rooftop station) -> hvac_or_thermal_issue (AC units, building b) -> power_load_anomaly (room meter, b)
           [-> power_quality_issue (SB00 feeder PF)]
  occ    : occupancy_driven_load (CO2, b) -> power_load_anomaly (room meter, b) [-> hvac_or_thermal_issue (b)]
  leak   : water_leak_or_overuse (tank, b) -> power_load_anomaly (pump meter, b)
  pump   : power_load_anomaly (pump meter power lost, b) -> water_supply_issue (tank level falling, b)
  + decoys (p 0.6): an unrelated sensor_fault / water_quality_issue / air_pollution_event in another building within +-40 min.
The causal rules (graph.py) are applied to ANY incidents (natural store ones too): label pair, time order (<= 90 min) and locality.

  python3 make_store_r4.py [--clusters 280] [--seed 41113]  -> ../build/store_r4/{device,fog}_store_r4.sqlite + manifest
"""
import argparse
import collections
import datetime as dt
import json
import os
import random
import re
import shutil
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "..", "2026-11-06_4b_local", "data", "store"))
OUT = os.path.abspath(os.path.join(HERE, "..", "build", "store_r4"))
BLDS = ["KH", "VN", "BK", "OB", "NB", "KN"]
IDRX = re.compile(r"INC-\d{4}")


def inc(t, sev, label, title, root, sensor, outcome):
    return dict(t=t, sev=sev, label=label, title=title, root=root, sensor=sensor, outcome=outcome)


def sen(node, metric, domain, loc, pattern, status, cause, fault=None):
    return dict(node=node, metric=metric, domain=domain, location=loc, pattern=pattern, status=status, likely_cause=cause, fault_kind=fault)


def loc_em(b, fl, k):
    return "SR-EM-%s%02d-%02d" % (b, fl, k), "%s building, level %02d, room energy meter %02d" % (b, fl, k)


def cluster(R, kind, t0):
    b = R.choice(BLDS)
    fl, k = R.randrange(1, 5), R.randrange(1, 4)
    out = []
    oc = lambda: R.choice(["fixed_by_action", "resolved_on_its_own", "no_action_needed"])
    if kind == "heat":
        sev = R.choice(["warning", "critical"])
        out.append(inc(t0, sev, "weather_driven", "temp gradual increase: VN building, level 04, rooftop weather station",
                       "heat wave raising cooling load at VN building, level 04, rooftop weather station",
                       sen("WE-VN04-00", "temp", "weather", "VN building, level 04, rooftop weather station", "gradual_increase", sev, "heat_buildup"), oc()))
        t1 = t0 + dt.timedelta(minutes=R.randrange(15, 41))
        out.append(inc(t1, R.choice(["warning", "critical"]), "hvac_or_thermal_issue", "room temp gradual increase: %s building, level %02d, AC units" % (b, fl),
                       "room temperature rising while the AC units run flat out at %s building, level %02d, AC units" % (b, fl),
                       sen("AC-%s%02d" % (b, fl), "room_temp", "hvac", "%s building, level %02d, AC units" % (b, fl), "gradual_increase", "warning", "high_heat_load"), oc()))
        t2 = t1 + dt.timedelta(minutes=R.randrange(5, 26))
        n, l = loc_em(b, fl, k)
        out.append(inc(t2, "warning", "power_load_anomaly", "power kw step increase: %s" % l, "AC compressors adding load at %s" % l,
                       sen(n, "power_kw", "power", l, "step_increase", "warning", "cooling_load"), oc()))
        if R.random() < 0.45:
            t3 = t2 + dt.timedelta(minutes=R.randrange(5, 21))
            out.append(inc(t3, R.choice(["warning", "critical"]), "power_quality_issue", "PF dip: SB00 substation, 11 kV feeder meter",
                           "inductive AC load pulling the power factor down at SB00 substation, 11 kV feeder meter",
                           sen("EM-CR-SB00-00", "pf", "power", "SB00 substation, 11 kV feeder meter", "gradual_decrease", "warning", "power_quality_issue"), oc()))
    elif kind == "occ":
        sev = R.choice(["warning", "critical"])
        out.append(inc(t0, sev, "occupancy_driven_load", "CO2 gradual increase: %s building, level %02d, indoor air sensor %02d" % (b, fl, k),
                       "people in the room raising CO2 at %s building, level %02d, indoor air sensor %02d" % (b, fl, k),
                       sen("SR-AQ-%s%02d-%02d" % (b, fl, k), "co2", "air_quality", "%s building, level %02d, indoor air sensor %02d" % (b, fl, k),
                           "gradual_increase", sev, "occupancy_load"), oc()))
        t1 = t0 + dt.timedelta(minutes=R.randrange(5, 31))
        n, l = loc_em(b, fl, k)
        out.append(inc(t1, "warning", "power_load_anomaly", "power kw step increase: %s" % l, "room load rising with the occupancy at %s" % l,
                       sen(n, "power_kw", "power", l, "step_increase", "warning", "occupancy_load"), oc()))
        if R.random() < 0.4:
            t2 = t1 + dt.timedelta(minutes=R.randrange(10, 31))
            out.append(inc(t2, "warning", "hvac_or_thermal_issue", "room temp gradual increase: %s building, level %02d, AC units" % (b, fl),
                           "people adding heat faster than the AC removes it at %s building, level %02d, AC units" % (b, fl),
                           sen("AC-%s%02d" % (b, fl), "room_temp", "hvac", "%s building, level %02d, AC units" % (b, fl), "gradual_increase", "warning", "occupancy_heat"), oc()))
    elif kind == "leak":
        sev = R.choice(["warning", "critical"])
        out.append(inc(t0, sev, "water_leak_or_overuse", "level gradual decrease: %s building, level 98, water tank level sensor 00" % b,
                       "tank draining with high flow at %s building, level 98, water tank level sensor 00" % b,
                       sen("WM-WL-%s98-00" % b, "level", "water", "%s building, level 98, water tank level sensor 00" % b, "gradual_decrease", sev, "tank_draining"), oc()))
        t1 = t0 + dt.timedelta(minutes=R.randrange(10, 41))
        l = "%s building, level 98, pump energy meter 07" % b
        out.append(inc(t1, "warning", "power_load_anomaly", "power kw gradual increase: %s" % l, "pump running longer to refill the draining tank at %s" % l,
                       sen("SR-EM-%s98-07" % b, "power_kw", "power", l, "gradual_increase", "warning", "pump_load"), oc()))
    else:  # pump
        l = "%s building, level 98, pump energy meter 07" % b
        out.append(inc(t0, "warning", "power_load_anomaly", "power kw step decrease: %s" % l, "pump lost power at %s" % l,
                       sen("SR-EM-%s98-07" % b, "power_kw", "power", l, "step_decrease", "warning", "equipment_off"), oc()))
        t1 = t0 + dt.timedelta(minutes=R.randrange(10, 41))
        out.append(inc(t1, R.choice(["warning", "critical"]), "water_supply_issue", "level gradual decrease: %s building, level 98, water tank level sensor 00" % b,
                       "no refill: tank level falling with the pump stopped at %s building, level 98, water tank level sensor 00" % b,
                       sen("WM-WL-%s98-00" % b, "level", "water", "%s building, level 98, water tank level sensor 00" % b, "gradual_decrease", "warning", "no_inflow"), oc()))
    if R.random() < 0.6:
        b2 = R.choice([x for x in BLDS if x != b])
        td = t0 + dt.timedelta(minutes=R.randrange(-40, 41))
        d = R.choice(["fault", "wq", "pm"])
        if d == "fault":
            out.append(inc(td, "sensor_fault", "sensor_fault", "pm25 flatline: %s building, level 02, indoor air sensor 03" % b2,
                           "sensor reading implausible (stuck) at %s building, level 02, indoor air sensor 03" % b2,
                           sen("SR-AQ-%s02-03" % b2, "pm25", "air_quality", "%s building, level 02, indoor air sensor 03" % b2, "flatline", "sensor_fault", "sensor_fault", "stuck"), "sensor_repaired"))
        elif d == "wq":
            out.append(inc(td, "warning", "water_quality_issue", "TDS step increase: %s building, level 98, water quality probe 01" % b2,
                           "dissolved solids up after a supply change at %s building, level 98, water quality probe 01" % b2,
                           sen("WM-WQ-%s98-01" % b2, "tds", "water", "%s building, level 98, water quality probe 01" % b2, "step_increase", "warning", "water_quality_issue"), "fixed_by_action"))
        else:
            out.append(inc(td, "warning", "air_pollution_event", "pm25 gradual increase: %s building, outdoor air station" % b2,
                           "outdoor PM2.5 event at %s building, outdoor air station" % b2,
                           sen("AQ-%s00-00" % b2, "pm25", "air_quality", "%s building, outdoor air station" % b2, "gradual_increase", "warning", "outdoor_pollution"), "resolved_on_its_own"))
    return out


def renumber(db, mapping):
    sub = lambda s: IDRX.sub(lambda m: mapping.get(m.group(0), m.group(0)), s) if isinstance(s, str) else s
    for (tab,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'reading_%'").fetchall():
        cols = [r[1] for r in db.execute("PRAGMA table_info(%s)" % tab)]
        rows = db.execute("SELECT * FROM %s" % tab).fetchall()
        if not rows or not any(isinstance(v, str) and "INC-" in v for r in rows for v in r):
            continue
        db.execute("DELETE FROM %s" % tab)
        db.executemany("INSERT INTO %s (%s) VALUES (%s)" % (tab, ",".join(cols), ",".join("?" * len(cols))), [tuple(sub(v) for v in r) for r in rows])


def build(src, dst, clusters, fog):
    shutil.copyfile(src, dst + ".part")
    db = sqlite3.connect(dst + ".part")
    db.row_factory = sqlite3.Row
    tpl = dict(db.execute("SELECT * FROM incident WHERE closed_at IS NOT NULL AND full_on_device=1 ORDER BY created_wall DESC LIMIT 1").fetchone())
    t_wall = dt.datetime.strptime(tpl["created_wall"][:19], "%Y-%m-%d %H:%M:%S")
    sim0 = tpl["created_sim"] - int(t_wall.timestamp())
    cols = list(tpl.keys())
    scol = [r[1] for r in db.execute("PRAGMA table_info(incident_sensor)")]
    n = 0
    for ci, cl in enumerate(clusters):
        for j, x in enumerate(cl):
            n += 1
            iid = "INC-T%04d" % n
            row = dict(tpl)
            closed = x["t"] + dt.timedelta(hours=random.Random(n).randrange(2, 30))
            row.update(id=iid, version=3, created_wall=x["t"].strftime("%Y-%m-%d %H:%M:%S"), created_sim=int(x["t"].timestamp()) + sim0, state="done",
                       severity=x["sev"], rule_severity=x["sev"], label=x["label"], root_cause=x["root"], title=x["title"], refine_stage="early",
                       approval="approved", approval_note="", injected=0, full_on_device=1, workflow="closed", closed_at=closed.strftime("%Y-%m-%d %H:%M:%S"),
                       resolved_at=closed.strftime("%Y-%m-%d %H:%M:%S"), outcome=x["outcome"], outcome_note=None, recurred_by=None, source="synthetic_r4_cluster")
            db.execute("INSERT INTO incident (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))), [row[c] for c in cols])
            s = dict(incident_id=iid, ref="S1", context=0, source="agent", onset=x["t"].strftime("%H:%M"), **x["sensor"])
            db.execute("INSERT INTO incident_sensor (%s) VALUES (%s)" % (",".join(scol), ",".join("?" * len(scol))), [s.get(c) for c in scol])
    allr = db.execute("SELECT id, created_wall FROM incident ORDER BY created_wall, id").fetchall()
    mapping = {r["id"]: "INC-%04d" % (i + 1) for i, r in enumerate(allr)}
    tmap = {k: v for k, v in mapping.items() if k.startswith("INC-T")}
    old = {k: v for k, v in mapping.items() if not k.startswith("INC-T")}
    # two-step to avoid collisions: real ids -> INC-Xnnnn, then all -> final
    db.row_factory = None
    tmp = {k: "INC-X" + v[4:] for k, v in mapping.items()}
    renumber_any(db, tmp)
    renumber_any(db, {v: mapping[k] for k, v in tmp.items()})
    db.commit()
    db.execute("VACUUM")
    db.close()
    os.replace(dst + ".part", dst)
    return mapping, len(allr)


def renumber_any(db, mp):
    rx = re.compile(r"INC-[TX]?\d{4}")
    sub = lambda s: rx.sub(lambda m: mp.get(m.group(0), m.group(0)), s) if isinstance(s, str) else s
    for (tab,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'reading_%'").fetchall():
        cols = [r[1] for r in db.execute("PRAGMA table_info(%s)" % tab)]
        rows = db.execute("SELECT * FROM %s" % tab).fetchall()
        if not rows or not any(isinstance(v, str) and "INC-" in v for r in rows for v in r):
            continue
        db.execute("DELETE FROM %s" % tab)
        db.executemany("INSERT INTO %s (%s) VALUES (%s)" % (tab, ",".join(cols), ",".join("?" * len(cols))), [tuple(sub(v) for v in r) for r in rows])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clusters", type=int, default=280)
    ap.add_argument("--seed", type=int, default=41113)
    a = ap.parse_args()
    R = random.Random(a.seed)
    os.makedirs(OUT, exist_ok=True)
    start, end = dt.datetime(2026, 6, 25), dt.datetime(2026, 10, 20, 20, 0)
    span = int((end - start).total_seconds() // 300)
    cl, kinds = [], collections.Counter()
    for i in range(a.clusters):
        kind = R.choices(["heat", "occ", "leak", "pump"], [0.4, 0.3, 0.15, 0.15])[0]
        t0 = start + dt.timedelta(minutes=5 * R.randrange(span))
        if kind == "heat":
            t0 = t0.replace(hour=R.randrange(11, 16))
        cl.append(cluster(R, kind, t0))
        kinds[kind] += 1
    m1, n1 = build(os.path.join(SRC, "device_store_r3.sqlite"), os.path.join(OUT, "device_store_r4.sqlite"), cl, False)
    m2, n2 = build(os.path.join(SRC, "fog_store_r3.sqlite"), os.path.join(OUT, "fog_store_r4.sqlite"), cl, True)
    assert m1 == m2, "device/fog id mapping differs"
    man = {"clusters": a.clusters, "kinds": dict(kinds), "incidents_added": sum(len(c) for c in cl), "incidents_total": n1, "seed": a.seed,
           "source": "proofs/2026-11-06_4b_local/data/store (r3) + clusters; ids renumbered by time"}
    json.dump(man, open(os.path.join(OUT, "store_r4_manifest.json"), "w"), indent=1)
    print(json.dumps(man))


if __name__ == "__main__":
    main()
