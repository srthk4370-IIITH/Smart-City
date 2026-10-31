"""rsn_v3 chat tools on the training store: the 9 rsn_v1 tools (round-1 Executor; list_sensors' status now uses the live
rule below) + the 6 tools of TOOLS_V3_CHAT.md (rank_readings, current_levels, recent_incidents, open_incidents,
faulty_sensors, what_if). The device side is Code/smart-city-edge-agent/app/backend/chat_tools_v3.go; both are checked
on the same fixture by parity_py.py + backend/chat_tools_v3_parity_test.go.

Store: ../data/train_store_v3.sqlite (make_store_v3.py: a copy of the round-1 train store with today's/yesterday's
incidents and realistic per-hour noise). Conventions copied from round 1 (eval/p0/tools_impl.py): sim "now" =
common.NOW (2026-10-22 12:00 IST, naive), reading timestamps are epoch seconds of naive IST wall time, hourly rollups
from READINGS_FROM, 5-min from FIVEMIN_FROM, demo injections excluded, numbers 1 decimal (pf/ph 3), times
"YYYY-MM-DD HH:MM".

Shared rules (the Go side implements the same ones):
- reading window of a period [a, b): readings with a <= t < b and t <= now (5-min rows where the store has them,
  hourly rows before FIVEMIN_FROM; the device has 7 days of 5-min readings).
- live status of a sensor: "sensor_fault" when a non-injected incident created in the last 4 h (the device's 48-reading
  window) flags that sensor as faulty (sensor status or incident severity sensor_fault) - on the device also when the
  engine's own rules say sensor_fault; otherwise the latest reading against the rule limits (backend features.go
  Metrics): high-side metrics warning >= warn, critical >= crit; pf (low side) warning < 0.85, critical < 0.7; pH both
  sides (warning < 6.5 or >= 8.5, critical < 6.0 or >= 9.0); metrics without limits are normal; no reading = no_data.
- rank_readings: one item per sensor (its first extreme in the window); sorted by value, ties by node+metric;
  "sensors" = sensors compared (after include_faulty); faulty_suspect = live sensor_fault or a sensor-fault incident on
  it in the period.
- what_if: driver sensors = every sensor of the driver metric matching `location` (node, location text or building),
  grouped by building; per building the driver series is the mean of its sensors' hourly means (an hour needs >= 6
  readings); no location and several buildings: the building with the most linked targets (ties: alphabetical).
  driver_now = mean of the driver sensors' latest readings; a percent change on a driver that is ~0 now (<= 10% of its
  mean over the hours it was above 0) is applied to that typical in-use level (driver_basis says so).
  driver_after is floored at the metric's physical minimum, not capped (occupancy: the hourly occupied fraction of a
  0/1 presence sensor; above 1 = busier than a fully occupied hour, an extrapolation). Targets: every other-metric
  sensor of the building; linked = >= 24 common hours, r2 >= 0.2 and a latest reading; after = latest + slope * delta,
  clamped to the metric's physical range; estimates sorted by r2 (ties node+metric), at most 5; no_clear_link =
  sorted metrics without any link. location in the result = the building that was fitted.
"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
R1 = os.path.abspath(os.path.join(HERE, "..", "..", "2026-10-25_reasoner_final"))
P0 = os.path.join(R1, "eval", "p0")
for p in (P0, os.path.join(R1, "pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)

import tools_impl as T1  # noqa: E402
from tools_impl import Executor, ToolError, iso, resolve_time, coverage, METRICS  # noqa: E402
from common import NOW, READINGS_FROM, FIVEMIN_FROM, CATALOG, DOMAINS, building_of  # noqa: E402

STORE = os.path.abspath(os.path.join(HERE, "..", "data", "train_store_v3.sqlite"))
STORE_R1 = os.path.join(R1, "data", "train_store.sqlite")
EPOCH0 = dt.datetime(1970, 1, 1)
NEW_TOOLS = ["rank_readings", "current_levels", "recent_incidents", "open_incidents", "faulty_sensors", "what_if"]
CHAT_TOOLS_V4 = list(T1.CHAT_TOOLS) + NEW_TOOLS
FAULT_WINDOW = dt.timedelta(hours=4)     # the device's 48-reading window
MAX_ESTIMATES = 5

# rule thresholds the device uses (backend features.go Metrics + orchestrator.go hvac); keyed (domain, metric)
LIMITS = {
    ("air_quality", "co2"): (1000, 1500), ("air_quality", "pm25"): (60, 120), ("air_quality", "pm10"): (100, 250),
    ("air_quality", "temp"): (30, 34), ("air_quality", "rh"): (70, 85), ("water", "tds"): (500, 1000),
    ("water", "ph"): (8.5, 9.0), ("power", "pf"): (0.85, 0.7), ("weather", "temp"): (38, 42), ("weather", "rh"): (90, 97),
    ("weather", "wind"): (10, 15), ("hvac", "room_temp"): (30, 34),
}
LOW_SIDE = {("power", "pf")}
PH_LOW = (6.5, 6.0)                      # pH warning / critical below (rules.go StatusOf)
# physical range (features.go Metrics Lo/Hi; orchestrator.go hvac) for what_if clamping
PHYS = {
    ("air_quality", "co2"): (250, 5000), ("air_quality", "pm25"): (0, 1000), ("air_quality", "pm10"): (0, 1000),
    ("air_quality", "temp"): (5, 55), ("air_quality", "rh"): (1, 100), ("water", "level"): (0, 500), ("water", "flow"): (0, 40),
    ("water", "tds"): (0, 1000), ("water", "ph"): (0, 14), ("power", "power_kw"): (0, 2000), ("power", "pf"): (0, 1),
    ("weather", "temp"): (5, 50), ("weather", "rh"): (1, 100), ("weather", "wind"): (0, 44), ("occupancy", "occ"): (0, 1),
    ("hvac", "ac_units_on"): (0, 200), ("hvac", "room_temp"): (5, 55),
}
SEV_RANK = {"critical": 0, "sensor_fault": 1, "warning": 2, "normal": 3}
OCC_NOTE = "occupancy is a 0/1 presence sensor: values are the occupied fraction of an hour (above 1 = extrapolated)"


def ep(t):
    return int((t - EPOCH0).total_seconds())


def fromts(x):
    return EPOCH0 + dt.timedelta(seconds=x)


def rnd(metric, x):
    if x is None:
        return None
    return round(float(x), 3 if metric in ("pf", "ph") else 1)


def gofmt(v):
    """a reading as Go's strconv.FormatFloat(v, 'f', -1, 64) writes it (list_sensors "last" on the device)"""
    s = repr(float(v))
    if "e" in s or "E" in s:
        s = ("%.12f" % float(v)).rstrip("0").rstrip(".")
    return s[:-2] if s.endswith(".0") else s


def limit_status(domain, metric, v):
    """status of one reading against the rule limits (see the module doc)"""
    if v is None:
        return "no_data"
    lim = LIMITS.get((domain, metric))
    if not lim:
        return "normal"
    w, c = lim
    if metric == "ph":
        if v < PH_LOW[1] or v >= c:
            return "critical"
        if v < PH_LOW[0] or v >= w:
            return "warning"
        return "normal"
    if (domain, metric) in LOW_SIDE:
        return "critical" if v < c else ("warning" if v < w else "normal")
    return "critical" if v >= c else ("warning" if v >= w else "normal")


def limit_obj(domain, metric):
    lim = LIMITS.get((domain, metric))
    if not lim:
        return None
    o = {"warning": lim[0], "critical": lim[1]}
    if (domain, metric) in LOW_SIDE:
        o["alert"] = "below"
    if metric == "ph":
        o["low_warning"], o["low_critical"] = PH_LOW
    return o


def _metric_ok(metric):
    if metric is None:
        return
    if metric not in METRICS:
        raise ToolError("unknown metric %r" % metric)


def _domain_ok(domain):
    if domain is not None and domain not in DOMAINS:
        raise ToolError("unknown domain %r" % domain)


def _match_loc(node, loc, location):
    return not location or str(location).lower() in (node + " " + loc + " " + building_of(node)).lower()


def _fit(dh, th):
    ts = [t for t in dh if t in th]
    n = len(ts)
    if n < 3:
        return None, 0.0, n
    xs = [dh[t] for t in ts]
    ys = [th[t] for t in ts]
    xm, ym = sum(xs) / n, sum(ys) / n
    sxx = sum((x - xm) ** 2 for x in xs)
    syy = sum((y - ym) ** 2 for y in ys)
    sxy = sum((x - xm) * (y - ym) for x, y in zip(xs, ys))
    if sxx < 1e-12 or syy < 1e-12:
        return None, 0.0, n
    return sxy / sxx, sxy * sxy / (sxx * syy), n


class ToolsV3(Executor):
    def __init__(self, path=STORE, scenario=None, catalog=None, readings_from=None, fivemin_from=None):
        super().__init__(path=path, scenario=scenario)
        cat = catalog or CATALOG
        self.catalog = sorted(cat, key=lambda c: c[0] + c[1])          # device Snapshot order (node+metric)
        self.cat = {(n, m): (d, l, u) for n, m, d, l, u in cat}
        self.readings_from = readings_from or READINGS_FROM
        self.fivemin_from = fivemin_from or FIVEMIN_FROM
        self._last = {}
        self._fault_now = None

    # ---------------------------------------------------------------- helpers
    def rcov(self, a, b):
        k = self.readings_from
        return {"source": "device", "complete": a >= k, "from": iso(max(a, k)), "to": iso(min(b, NOW)),
                "note": "device keeps readings from %s" % k.date()}

    def last_reading(self, node, metric):
        k = (node, metric)
        if k not in self._last:
            r = self.db.execute("SELECT t, v FROM reading_5min WHERE node=? AND metric=? AND t<=? ORDER BY t DESC LIMIT 1",
                                (node, metric, ep(NOW))).fetchone()
            if not r:
                r = self.db.execute("SELECT t, last v FROM reading_hourly WHERE node=? AND metric=? AND t<=? ORDER BY t DESC LIMIT 1",
                                    (node, metric, ep(NOW))).fetchone()
            self._last[k] = (fromts(r["t"]), r["v"]) if r and r["v"] is not None else (None, None)
        return self._last[k]

    def fault_now(self):
        """(node, metric) -> earliest time of a non-injected sensor-fault incident on it in the last 4 h"""
        if self._fault_now is None:
            rows = self.db.execute(
                "SELECT s.node, s.metric, MIN(i.created_wall) FROM incident i JOIN incident_sensor s ON s.incident_id=i.id AND s.context=0"
                " WHERE i.injected=0 AND i.created_wall>=? AND i.created_wall<=? AND (i.severity='sensor_fault' OR s.status='sensor_fault')"
                " GROUP BY s.node, s.metric", (iso(NOW - FAULT_WINDOW), NOW.strftime("%Y-%m-%d %H:%M:%S"))).fetchall()
            self._fault_now = {(r[0], r[1]): r[2][:16] for r in rows}
        return self._fault_now

    def live_status(self, node, metric):
        if (node, metric) in self.fault_now():
            return "sensor_fault"
        d = self.cat.get((node, metric), ("",))[0]
        return limit_status(d, metric, self.last_reading(node, metric)[1])

    def _fault_in_period(self, node, metric, a, b):
        r = self.db.execute(
            "SELECT 1 FROM incident i JOIN incident_sensor s ON s.incident_id=i.id AND s.context=0 WHERE s.node=? AND s.metric=?"
            " AND i.injected=0 AND i.created_wall>=? AND i.created_wall<? AND (i.severity='sensor_fault' OR s.status='sensor_fault') LIMIT 1",
            (node, metric, iso(a), iso(b))).fetchone()
        return bool(r)

    def _sensors(self, metric=None, domain=None, location=None):
        return [(n, m, d, l, u) for n, m, d, l, u in self.catalog
                if (not metric or m == metric) and (not domain or d == domain) and _match_loc(n, l, location)]

    def _readings(self, node, metric, a, b, col="v"):
        """(t, value) in the window: hourly rows (col = mean|min|max) before fivemin_from, 5-min rows after"""
        hi = min(b, NOW + dt.timedelta(seconds=1))
        out = []
        if a < self.fivemin_from:
            hcol = col if col != "v" else "mean"
            out += [(r[0], r[1]) for r in self.db.execute(
                "SELECT t, %s FROM reading_hourly WHERE node=? AND metric=? AND t>=? AND t<? AND %s IS NOT NULL ORDER BY t" % (hcol, hcol),
                (node, metric, ep(a), ep(min(hi, self.fivemin_from))))]
        out += [(r[0], r[1]) for r in self.db.execute(
            "SELECT t, v FROM reading_5min WHERE node=? AND metric=? AND t>=? AND t<? AND v IS NOT NULL ORDER BY t",
            (node, metric, ep(max(a, self.fivemin_from)), ep(hi)))]
        return out

    def _hourly(self, node, metric, a, b):
        """hourly means with >= 6 readings, hours starting in [a, b) and not after now"""
        return {r[0]: r[1] for r in self.db.execute(
            "SELECT t, mean FROM reading_hourly WHERE node=? AND metric=? AND t>=? AND t<? AND t<=? AND n>=6 AND mean IS NOT NULL",
            (node, metric, ep(a), ep(b), ep(NOW)))}

    def _domains_of(self, iid):
        out = []
        for (d,) in self.db.execute("SELECT domain FROM incident_sensor WHERE incident_id=? AND context=0 ORDER BY ref", (iid,)):
            if d not in out:
                out.append(d)
        return out

    # ---------------------------------------------------------------- rsn_v1 list_sensors with the live status
    def t_list_sensors(self, domain=None, location=None, status=None):
        out = []
        for node, metric, dom, loc, unit in self.catalog:
            if domain and dom != domain:
                continue
            if location and location.lower() not in (node + " " + loc).lower():
                continue
            st = self.live_status(node, metric)
            if status and st != status:
                continue
            v = self.last_reading(node, metric)[1]
            out.append({"node": node, "metric": metric, "domain": dom, "location": loc, "status": st,
                        "last": ("%s %s" % (gofmt(v), unit)).strip() if v is not None else None})
        if len(out) > 40:
            return {"sensors": out[:40], "count": len(out), "note": "first 40 shown"}
        return {"sensors": out, "count": len(out)}

    # ---------------------------------------------------------------- 1. rank_readings
    def t_rank_readings(self, metric=None, time=None, order="highest", domain=None, location=None, limit=3, include_faulty=True):
        if not metric:
            raise ToolError("'metric' is required")
        _metric_ok(metric)
        _domain_ok(domain)
        order = order or "highest"
        if order not in ("highest", "lowest"):
            raise ToolError("order must be highest|lowest")
        try:
            limit = max(1, min(5, int(limit or 3)))
        except (TypeError, ValueError):
            limit = 3
        if include_faulty is None:
            include_faulty = True
        a, b = resolve_time(time or {"preset": "today"})
        sens = self._sensors(metric, domain, location)
        if not sens:
            raise ToolError("no %s sensor%s" % (metric, (" matching %r" % location) if location else ""))
        low = order == "lowest"
        items = []
        for node, m, d, loc, unit in sens:
            xs = self._readings(node, m, a, b, "min" if low else "max")
            if not xs:
                continue
            best = xs[0]
            for t, v in xs:
                if (low and v < best[1]) or (not low and v > best[1]):
                    best = (t, v)
            fs = self.live_status(node, m) == "sensor_fault" or self._fault_in_period(node, m, a, b)
            if fs and not include_faulty:
                continue
            items.append({"node": node, "location": loc, "value": rnd(m, best[1]), "unit": unit, "at": iso(fromts(best[0])),
                          "status": self.live_status(node, m), "faulty_suspect": fs, "_v": best[1], "_k": node + m})
        items.sort(key=lambda x: (x["_v"] if low else -x["_v"], x["_k"]))
        for x in items:
            del x["_v"], x["_k"]
        return {"metric": metric, "order": order, "items": items[:limit], "sensors": len(items), "coverage": self.rcov(a, b)}

    # ---------------------------------------------------------------- 2. current_levels
    def t_current_levels(self, metric=None, domain=None, location=None):
        if not (metric or domain or location):
            raise ToolError("give at least one of 'metric', 'domain', 'location'")
        _metric_ok(metric)
        _domain_ok(domain)
        sens = self._sensors(metric, domain, location)
        if not sens:
            raise ToolError("no sensor matches metric=%s domain=%s location=%s" % (metric, domain, location))
        today = NOW.replace(hour=0, minute=0, second=0)
        items = []
        for node, m, d, loc, unit in sens:
            xs = [v for _, v in self._readings(node, m, today, today + dt.timedelta(days=1))]
            last = self.last_reading(node, m)[1]
            items.append({"node": node, "metric": m, "location": loc, "last": rnd(m, last), "unit": unit,
                          "status": self.live_status(node, m),
                          "today": ({"min": rnd(m, min(xs)), "max": rnd(m, max(xs)), "mean": rnd(m, sum(xs) / len(xs))} if xs else None),
                          "limit": limit_obj(d, m)})
        out = {"items": items[:20], "count": len(items), "coverage": self.rcov(today, today + dt.timedelta(days=1))}
        if len(items) > 20:
            out["note"] = "first 20 shown"
        return out

    # ---------------------------------------------------------------- 3. recent_incidents
    def t_recent_incidents(self, limit=5, domain=None, severity=None, metric=None):
        _metric_ok(metric)
        _domain_ok(domain)
        try:
            limit = max(1, min(10, int(limit or 5)))
        except (TypeError, ValueError):
            limit = 5
        w, p, a, b, defn, sw, sp = self._where({"preset": "all"}, domain, metric, None, severity)
        total = self.db.execute("SELECT COUNT(*) FROM incident i WHERE " + w, p).fetchone()[0]
        rows = self.db.execute("SELECT * FROM incident i WHERE %s ORDER BY i.created_wall DESC, i.id DESC LIMIT %d" % (w, limit), p).fetchall()
        items = [{"id": r["id"], "time": r["created_wall"][:16], "title": r["title"], "severity": r["severity"], "label": r["label"],
                  "domains": self._domains_of(r["id"]), "approval": r["approval"], "outcome": r["outcome"]} for r in rows]
        return {"items": items, "total": total, "coverage": coverage(a, b)}

    # ---------------------------------------------------------------- 4. open_incidents
    def t_open_incidents(self, domain=None):
        _domain_ok(domain)
        rows = self.db.execute("SELECT id, severity, created_wall, state, workflow, title FROM incident WHERE injected=0"
                               " AND (state='running' OR workflow IN ('needs_decision','analysing')) ORDER BY created_wall, id").fetchall()
        doms, pending = [], {}
        for d in DOMAINS:
            if domain and d != domain:
                continue
            pend, ana = [], 0
            for r in rows:
                if d not in self._domains_of(r["id"]):
                    continue
                if r["state"] == "running" or r["workflow"] == "analysing":
                    ana += 1
                else:
                    pend.append(r)
                    pending.setdefault(r["id"], (r, d))
            if not pend and not ana and not domain:
                continue
            bs = {}
            for s in ("critical", "warning", "sensor_fault", "normal"):
                c = sum(1 for r in pend if r["severity"] == s)
                if c:
                    bs[s] = c
            doms.append({"domain": d, "pending_review": len(pend), "analysing": ana, "by_severity": bs,
                         "oldest_pending": pend[0]["created_wall"][:16] if pend else None})
        doms.sort(key=lambda x: (-x["pending_review"], x["domain"]))
        top = sorted(pending.values(), key=lambda x: (SEV_RANK.get(x[0]["severity"], 9), x[0]["created_wall"], x[0]["id"]))[:3]
        return {"domains": doms, "total_pending_review": len(pending),
                "top_pending": [{"id": r["id"], "severity": r["severity"], "title": r["title"],
                                 "domain": domain or self._domains_of(r["id"])[0]} for r, _ in top],
                "definition": "pending_review = approval pending (no operator decision yet); analysing = AI still running",
                "coverage": coverage(dt.datetime(2000, 1, 1), NOW)}

    # ---------------------------------------------------------------- 5. faulty_sensors
    def t_faulty_sensors(self, time=None):
        a, b = resolve_time(time or {"preset": "last_7d"})
        live = []
        for node, m, d, loc, unit in self.catalog:
            if self.live_status(node, m) != "sensor_fault":
                continue
            live.append({"node": node, "metric": m, "location": loc, "status": "sensor_fault", "since": self.fault_now().get((node, m))})
        rows = self.db.execute(
            "SELECT s.node, s.metric, s.fault_kind, i.id, i.created_wall FROM incident_sensor s JOIN incident i ON i.id=s.incident_id"
            " WHERE s.context=0 AND s.status='sensor_fault' AND i.injected=0 AND i.created_wall>=? AND i.created_wall<? ORDER BY i.created_wall",
            (iso(a), iso(b))).fetchall()
        agg = {}
        for r in rows:
            k = (r["node"], r["metric"])
            x = agg.setdefault(k, {"node": r["node"], "metric": r["metric"], "location": self.cat.get(k, ("", "", ""))[1],
                                   "incidents": 0, "last": None, "fault_kind": None})
            x["incidents"] += 1
            x["last"] = r["created_wall"][:16]
            if r["fault_kind"]:
                x["fault_kind"] = r["fault_kind"]
        ai = sorted(agg.values(), key=lambda x: (-x["incidents"], x["node"] + x["metric"]))[:10]
        distinct = {(x["node"], x["metric"]) for x in live} | set(agg)
        return {"live": live, "ai_diagnosed": ai, "count_distinct": len(distinct), "coverage": coverage(a, b)}

    # ---------------------------------------------------------------- 6. what_if
    def t_what_if(self, driver=None, change_pct=None, change_abs=None, location=None, time=None):
        if not driver:
            raise ToolError("'driver' is required")
        _metric_ok(driver)
        if change_pct is None and change_abs is None:
            raise ToolError("give 'change_pct' (e.g. 50 or -20) or 'change_abs'")
        try:
            change_pct = None if change_pct is None else float(change_pct)
            change_abs = None if change_abs is None else float(change_abs)
        except (TypeError, ValueError):
            raise ToolError("change_pct/change_abs must be numbers")
        a, b = resolve_time(time or {"preset": "last_7d"})
        drv = self._sensors(driver, None, location)
        if not drv:
            raise ToolError("no %s sensor%s" % (driver, (" matching %r" % location) if location else ""))
        blds = sorted({building_of(s[0]) for s in drv})

        def fit(bl):
            ds = [s for s in drv if building_of(s[0]) == bl]
            hs = {}
            for node, m, d, loc, unit in ds:
                for t, v in self._hourly(node, m, a, b).items():
                    hs.setdefault(t, []).append(v)
            dx = {t: sum(v) / len(v) for t, v in hs.items()}
            nows = [self.last_reading(s[0], s[1])[1] for s in ds]
            nows = [v for v in nows if v is not None]
            now = sum(nows) / len(nows) if nows else (dx[max(dx)] if dx else 0.0)
            use = [v for v in dx.values() if v > 0]
            typical = False
            if change_pct is not None and use and now <= 0.1 * sum(use) / len(use):
                now, typical = sum(use) / len(use), True
            after = now + (now * change_pct / 100.0 if change_pct is not None else change_abs)
            lo = PHYS.get((ds[0][2], driver), (None, None))[0]
            if lo is not None:
                after = max(lo, after)
            delta = after - now
            ests, weak = [], []
            for node, m, d, loc, unit in self.catalog:
                if building_of(node) != bl or m == driver:
                    continue
                slope, r2, n = _fit(dx, self._hourly(node, m, a, b))
                last = self.last_reading(node, m)[1]
                if slope is None or n < 24 or r2 < 0.2 or last is None:
                    weak.append(m)
                    continue
                y = last + slope * delta
                lo2, hi2 = PHYS.get((d, m), (None, None))
                if lo2 is not None and hi2 > lo2:
                    y = max(lo2, min(hi2, y))
                ests.append({"metric": m, "node": node, "now": rnd(m, last), "after": rnd(m, y), "unit": unit,
                             "slope": round(slope, 3), "r2": round(r2, 2), "hours": n, "_r2": r2, "_k": node + m})
            return {"bl": bl, "unit": ds[0][4], "now": now, "after": after, "typical": typical, "ests": ests, "weak": weak}

        best = None
        for bl in blds:
            o = fit(bl)
            if best is None or len(o["ests"]) > len(best["ests"]):
                best = o
        est = sorted(best["ests"], key=lambda e: (-e["_r2"], e["_k"]))
        have = {e["metric"] for e in est}
        ncl = sorted({m for m in best["weak"] if m not in have})
        for e in est:
            del e["_r2"], e["_k"]
        if change_pct is not None:
            chg = "%+g%%" % change_pct
        else:
            chg = ("%+g %s" % (change_abs, best["unit"])).strip()
        out = {"driver": driver, "change": chg, "driver_now": rnd(driver, best["now"]), "driver_after": rnd(driver, best["after"]),
               "driver_basis": "typical in-use level (the current reading is about zero)" if best["typical"] else "current reading",
               "unit": best["unit"], "location": best["bl"], "estimates": est[:MAX_ESTIMATES], "no_clear_link": ncl,
               "method": "linear fit of hourly means over the window; association, not a controlled experiment",
               "coverage": self.rcov(a, b)}
        if driver == "occ":
            out["note"] = OCC_NOTE
        return out


if __name__ == "__main__":
    ex = ToolsV3()
    for name, args in [("rank_readings", {"metric": "co2"}), ("rank_readings", {"metric": "co2", "time": {"preset": "last_7d"}, "order": "lowest"}),
                       ("current_levels", {"metric": "co2"}), ("current_levels", {"location": "KH98"}), ("list_sensors", {"domain": "air_quality"}),
                       ("recent_incidents", {"limit": 3}), ("open_incidents", {}), ("faulty_sensors", {}),
                       ("count_incidents", {"time": {"preset": "today"}, "group_by": "severity"}),
                       ("what_if", {"driver": "occ", "change_pct": 50, "location": "KH"}),
                       ("what_if", {"driver": "occ", "change_pct": -30, "location": "VN"}),
                       ("what_if", {"driver": "occ", "change_pct": 50, "location": "BK"}),
                       ("what_if", {"driver": "ac_units_on", "change_pct": 50, "location": "KH03"}),
                       ("what_if", {"driver": "ac_units_on", "change_abs": -1, "location": "VN02"}),
                       ("what_if", {"driver": "temp", "change_abs": 3, "location": "WE-VN04"}),
                       ("what_if", {"driver": "room_temp", "change_abs": 2, "location": "KH03"}),
                       ("what_if", {"driver": "power_kw", "change_pct": 20, "location": "KH"})]:
        print(name, json.dumps(args), "->", json.dumps(ex.run(name, args))[:900])
