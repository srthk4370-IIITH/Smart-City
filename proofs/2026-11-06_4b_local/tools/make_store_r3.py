"""r3 training stores: one campus history seen from the fog and from the board.

fog_store_r3.sqlite    = the rsn_v3 store (proofs/2026-10-29_rsn_v3/data/train_store_v3.sqlite, 748 incidents 2026-01-01 ..
                         2026-10-22 12:00, never modified) + ADD older/denser incidents 2025-11-01 .. 2026-08-22 cloned from
                         its closed incidents (same sensors, titles, causes, steps, events, maintenance rows, time-shifted;
                         month-weighted labels: winter PM, summer heat/AC, monsoon water/RH), IDs renumbered by time
                         (INC-0001 = oldest), + reading_daily (per sensor and day, 2025-11-01 .. 2026-10-22 so far: the hourly
                         rollups where the store has them (from 2026-08-23), seasonal synthesis before) + meta.
device_store_r3.sqlite = what the board keeps (backend store.go retention, DECISIONS.md): the newest 1000 incidents in full;
                         every older incident stays as an index row (id, time, title, severity, label, sensors with
                         pattern/status/fault kind (flagged sensors only), approval, workflow, outcome, injected) with root_cause, notes,
                         ack/close times, steps and events removed (full_on_device = 0); readings as before (hourly
                         from 2026-08-23, 5-min from 2026-10-19), no reading_daily; maintenance log kept (append-only).
  python3 make_store_r3.py   -> ../data/store/{fog,device}_store_r3.sqlite + store_r3_manifest.json
"""
import collections
import datetime as dt
import json
import math
import os
import random
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
V3 = os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3")
SRC = os.path.join(V3, "data", "train_store_v3.sqlite")
OUT = os.path.join(HERE, "..", "data", "store")
FOG = os.path.join(OUT, "fog_store_r3.sqlite")
DEV = os.path.join(OUT, "device_store_r3.sqlite")
sys.path.insert(0, os.path.join(V3, "pipeline"))
from tools_v3_impl import PHYS, EPOCH0  # noqa: E402
from common import CATALOG, NOW  # noqa: E402

SEED = 20261106
WINDOW = 1000
START = dt.datetime(2025, 11, 1)
ADD_END = dt.datetime(2026, 10, 20)          # clones stay before yesterday (today/yesterday incidents and live faults unchanged)
ADD_PER_MONTH = {(2025, 11): 230, (2025, 12): 230, (2026, 1): 190, (2026, 2): 190, (2026, 3): 200, (2026, 4): 230,
                 (2026, 5): 220, (2026, 6): 140, (2026, 7): 150, (2026, 8): 175, (2026, 9): 165, (2026, 10): 110}
# label weight per season (clone base choice)
SEASON = {
    "winter": {"air_pollution_event": 3.0, "ventilation_issue": 1.3, "weather_driven": 0.6, "hvac_or_thermal_issue": 0.4},
    "summer": {"hvac_or_thermal_issue": 2.5, "weather_driven": 2.5, "power_load_anomaly": 1.6, "water_supply_issue": 1.5, "air_pollution_event": 0.6},
    "monsoon": {"water_leak_or_overuse": 2.0, "water_supply_issue": 1.5, "water_quality_issue": 1.8, "air_pollution_event": 0.3, "occupancy_driven_load": 0.6},
}
SEASON_OF = {11: "winter", 12: "winter", 1: "winter", 2: "winter", 3: "summer", 4: "summer", 5: "summer", 6: "monsoon", 7: "monsoon",
             8: "monsoon", 9: "monsoon", 10: "winter"}
TS_COLS = {"incident": ["created_wall", "resolved_at", "acked_at", "closed_at"], "incident_step": ["at_wall"], "incident_event": ["at_wall"],
           "maintenance": ["at_wall"]}
IDRX = re.compile(r"INC-\d+")

# daily synthesis: weather temperature monthly normals (Hyderabad, C), outdoor RH (%), PM factor; others multiplicative
T_NORM = {11: 23.5, 12: 21.5, 1: 22.0, 2: 24.5, 3: 28.0, 4: 31.0, 5: 32.5, 6: 28.5, 7: 26.5, 8: 26.0, 9: 26.0, 10: 25.0}
RH_NORM = {11: 60, 12: 55, 1: 52, 2: 45, 3: 38, 4: 37, 5: 40, 6: 65, 7: 75, 8: 76, 9: 73, 10: 65}
PM_F = {11: 1.6, 12: 1.9, 1: 1.9, 2: 1.5, 3: 1.2, 4: 1.0, 5: 0.9, 6: 0.6, 7: 0.5, 8: 0.55, 9: 0.6, 10: 0.9}
MULT = {
    "co2": {5: 0.88, 6: 0.78, 7: 0.86}, "occ": {5: 0.8, 6: 0.6, 7: 0.75},
    "power_kw": {11: 0.9, 12: 0.85, 1: 0.85, 2: 0.95, 3: 1.1, 4: 1.25, 5: 1.2, 6: 0.9, 7: 0.95},
    "ac_units_on": {11: 0.6, 12: 0.4, 1: 0.4, 2: 0.7, 3: 1.2, 4: 1.5, 5: 1.5},
    "wind": {6: 1.5, 7: 1.6, 8: 1.35, 9: 1.1}, "tds": {3: 1.08, 4: 1.1, 5: 1.12, 6: 0.94, 7: 0.9, 8: 0.92},
    "flow": {3: 1.08, 4: 1.12, 5: 1.1, 6: 0.85, 7: 0.9},
}


def p(s):
    return dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S") if len(s) > 16 else dt.datetime.strptime(s, "%Y-%m-%d %H:%M")


def fmt(t, like):
    return t.strftime("%Y-%m-%d %H:%M:%S") if len(like) > 16 else t.strftime("%Y-%m-%d %H:%M")


def shift(s, d):
    return None if s is None else fmt(p(s) + d, s)


def rows(db, t):
    cur = db.execute("SELECT * FROM %s" % t)
    cols = [c[0] for c in cur.description]
    return cols, [dict(zip(cols, r)) for r in cur.fetchall()]


def schema(db):
    return [r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")]


def main():
    R = random.Random(SEED)
    os.makedirs(OUT, exist_ok=True)
    src = sqlite3.connect("file:%s?mode=ro" % SRC, uri=True)
    ddl = schema(src)
    tabs = {t: rows(src, t) for t in ("incident", "incident_sensor", "incident_step", "incident_event", "maintenance")}
    inc = tabs["incident"][1]
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for t in ("incident_sensor", "incident_step", "incident_event", "maintenance"):
        for r in tabs[t][1]:
            if r.get("incident_id"):
                by[t][r["incident_id"]].append(r)
    bases = [r for r in inc if r["workflow"] == "closed" and not r["injected"] and r["created_wall"] < "2026-10-21"]
    # ---- clones
    new_inc, extra = [], collections.defaultdict(list)
    k = 0
    for (y, m), n in sorted(ADD_PER_MONTH.items()):
        a = dt.datetime(y, m, 1)
        b = min(dt.datetime(y + (m == 12), m % 12 + 1, 1), ADD_END)
        wts = [SEASON[SEASON_OF[m]].get(x["label"], 1.0) for x in bases]
        for _ in range(n):
            base = R.choices(bases, wts)[0]
            t0 = p(base["created_wall"])
            tn = a + dt.timedelta(seconds=R.randrange(int((b - a).total_seconds()) - 3 * 86400))
            tn = tn.replace(second=0)
            d = tn - t0
            k += 1
            nid = "NEW-%05d" % k
            r = dict(base)
            r["id"] = nid
            for c in TS_COLS["incident"]:
                r[c] = shift(r[c], d)
            r["created_sim"] = base["created_sim"] + int(d.total_seconds())
            r["recurred_by"] = None
            r["source"] = "r3_clone:" + base["id"]
            new_inc.append(r)
            for t in ("incident_sensor", "incident_step", "incident_event", "maintenance"):
                for x in by[t].get(base["id"], []):
                    y2 = dict(x)
                    y2["incident_id"] = nid
                    for c in TS_COLS.get(t, []):
                        y2[c] = shift(y2[c], d)
                    if "seq" in y2:
                        y2["seq"] = None
                    extra[t].append(y2)
    allinc = inc + new_inc
    allinc.sort(key=lambda r: (r["created_wall"], r["id"]))
    idmap = {r["id"]: "INC-%04d" % (i + 1) for i, r in enumerate(allinc)}
    remap = lambda s: None if s is None else IDRX.sub(lambda m: idmap.get(m.group(0), m.group(0)), s) if isinstance(s, str) else s
    for r in allinc:
        r["id"] = idmap[r["id"]]
        for c in ("recurred_by", "title", "root_cause", "approval_note", "outcome_note"):
            r[c] = remap(r[c])
    child = {}
    for t in ("incident_sensor", "incident_step", "incident_event", "maintenance"):
        lst = [dict(x) for x in tabs[t][1]] + extra[t]
        for x in lst:
            if x.get("incident_id"):
                x["incident_id"] = idmap.get(x["incident_id"], x["incident_id"])
            if "note" in x:
                x["note"] = remap(x["note"])
        if t in ("incident_event", "maintenance"):
            lst.sort(key=lambda x: (x["at_wall"], x.get("incident_id") or ""))
            for i, x in enumerate(lst):
                x["seq"] = i + 1
        child[t] = lst
    # ---- write fog store
    for path in (FOG, DEV):
        if os.path.exists(path):
            os.remove(path)
    fog = sqlite3.connect(FOG)
    for s in ddl:
        fog.execute(s)
    def put(db, t, lst):
        if not lst:
            return
        cols = list(lst[0].keys())
        db.executemany("INSERT INTO %s (%s) VALUES (%s)" % (t, ",".join(cols), ",".join("?" * len(cols))), [[x[c] for c in cols] for x in lst])
    put(fog, "incident", allinc)
    for t, lst in child.items():
        put(fog, t, lst)
    for t in ("reading_5min", "reading_hourly"):
        cur = src.execute("SELECT * FROM %s" % t)
        cols = [c[0] for c in cur.description]
        fog.executemany("INSERT INTO %s (%s) VALUES (%s)" % (t, ",".join(cols), ",".join("?" * len(cols))), cur.fetchall())
    # ---- reading_daily (fog only)
    fog.execute("CREATE TABLE reading_daily (node TEXT NOT NULL, metric TEXT NOT NULL, day TEXT NOT NULL, n INTEGER, mean REAL, min REAL, max REAL,"
                " PRIMARY KEY (node, metric, day)) WITHOUT ROWID")
    ep = lambda t: int((t - EPOCH0).total_seconds())
    last_day = NOW.replace(hour=0, minute=0, second=0) + dt.timedelta(days=1)   # through today (its rows so far, as the fog's hourly sync)
    daily = []
    for node, metric, dom, loc, unit in CATALOG:
        hs = src.execute("SELECT t, n, mean, min, max FROM reading_hourly WHERE node=? AND metric=? AND t < ? ORDER BY t",
                         (node, metric, ep(NOW))).fetchall()
        days = collections.defaultdict(list)
        for t, n, mean, mn, mx in hs:
            days[(EPOCH0 + dt.timedelta(seconds=t)).date()].append((n, mean, mn, mx))
        real = {}
        for d, v in days.items():
            real[d] = (sum(x[0] for x in v), sum(x[1] for x in v) / len(v), min(x[2] for x in v), max(x[3] for x in v))
        B = sum(x[1] for x in real.values()) / len(real)
        span = sum(x[3] - x[2] for x in real.values()) / len(real)
        dec = 3 if metric in ("pf", "ph") else 1
        lo, hi = PHYS[(dom, metric)]
        tnB = sum(T_NORM[m] for m in (8, 9, 10)) / 3
        rhB = sum(RH_NORM[m] for m in (8, 9, 10)) / 3
        pmB = sum(PM_F[m] for m in (8, 9, 10)) / 3
        ar = 0.0
        d = START.date()
        while d < last_day.date():
            if d in real:
                n, mean, mn, mx = real[d]
            else:
                m = d.month
                ar = 0.7 * ar + R.gauss(0, 1)
                if metric in ("temp", "room_temp"):
                    k_ = 1.0 if dom == "weather" else 0.4
                    mean = B + k_ * (T_NORM[m] - tnB) + 0.6 * ar
                elif metric == "rh":
                    k_ = 1.0 if dom == "weather" else 0.6
                    mean = B + k_ * (RH_NORM[m] - rhB) + 2.0 * ar
                elif metric in ("pm25", "pm10"):
                    mean = B * PM_F[m] / pmB * (1 + 0.08 * ar)
                elif metric in ("ph", "pf"):
                    mean = B + (0.02 if metric == "ph" else 0.004) * ar
                else:
                    mean = B * MULT.get(metric, {}).get(m, 1.0) * (1 + 0.04 * ar)
                if d.weekday() >= 5 and metric in ("co2", "occ", "power_kw", "ac_units_on"):
                    mean *= 0.8
                sp = span * (mean / B if B and metric not in ("temp", "room_temp", "rh", "ph", "pf") else 1.0) * R.uniform(0.85, 1.15)
                mn, mx = mean - sp * R.uniform(0.35, 0.55), mean + sp * R.uniform(0.45, 0.65)
                mean, mn, mx = min(max(mean, lo), hi), max(mn, lo), min(mx, hi)
                n = 288
            daily.append((node, metric, d.isoformat(), n, round(mean, dec), round(min(mn, mean), dec), round(max(mx, mean), dec)))
            d += dt.timedelta(days=1)
    fog.executemany("INSERT INTO reading_daily VALUES (?,?,?,?,?,?,?)", daily)
    # ---- device view
    order = sorted(allinc, key=lambda r: (r["created_wall"], r["id"]))
    keep = {r["id"] for r in order[-WINDOW:]}
    arch = [r["id"] for r in order[:-WINDOW]]
    meta = {"now": NOW.strftime("%Y-%m-%d %H:%M"), "index_from": order[0]["created_wall"][:10], "device_from": order[-WINDOW]["created_wall"][:16],
            "device_full_incidents": WINDOW, "fog_incidents": len(allinc), "readings_hourly_from": "2026-08-23", "readings_5min_from": "2026-10-19",
            "fog_daily_from": START.date().isoformat()}
    fog.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    fog.executemany("INSERT INTO meta VALUES (?,?)", [(k_, str(v)) for k_, v in meta.items()])
    fog.commit()
    fog.execute("VACUUM INTO ?", (DEV,))
    fog.close()
    dev = sqlite3.connect(DEV)
    dev.execute("DROP TABLE reading_daily")
    q = ",".join("?" * len(arch))
    dev.execute("UPDATE incident SET full_on_device=0, root_cause=NULL, approval_note=NULL, outcome_note=NULL, owner=NULL, acked_at=NULL,"
                " closed_at=NULL, resolved_at=NULL, recurred_by=NULL WHERE id IN (%s)" % q, arch)
    dev.execute("DELETE FROM incident_sensor WHERE context=1 AND incident_id IN (%s)" % q, arch)
    dev.execute("DELETE FROM incident_step WHERE incident_id IN (%s)" % q, arch)
    dev.execute("DELETE FROM incident_event WHERE incident_id IN (%s)" % q, arch)
    dev.commit()
    dev.execute("VACUUM")
    dev.close()
    lab = collections.Counter(r["label"] for r in allinc)
    mon = collections.Counter(r["created_wall"][:7] for r in allinc)
    man = dict(meta, source_store=os.path.relpath(SRC, OUT), seed=SEED, cloned=len(new_inc), v3_incidents=len(inc),
               archived_on_device=len(arch), labels=dict(lab.most_common()), per_month=dict(sorted(mon.items())), daily_rows=len(daily))
    json.dump(man, open(os.path.join(OUT, "store_r3_manifest.json"), "w"), indent=1)
    print(json.dumps({k_: man[k_] for k_ in ("fog_incidents", "device_from", "index_from", "archived_on_device", "daily_rows")}))


if __name__ == "__main__":
    main()
