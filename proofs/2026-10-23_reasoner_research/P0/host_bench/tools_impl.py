"""Read-only tool executor for the benchmark: tools.json (draft-1) + get_action_history (APPROVAL_AND_MEMORY 4.2).

The model only chooses tools and arguments; every number comes from the SQL here. Offline mode: the fog is
unreachable, so search_knowledge returns available=false and coverage notes say "device".
"""
import copy
import datetime as dt
import json
import os
import sqlite3

from common import (HERE, STORE, NOW, YEAR_START, READINGS_FROM, FIVEMIN_FROM, CATALOG, CAT, DOMAINS,
                    PATTERN_SYNONYMS, FAULT_KINDS)

TOOLS_JSON = json.load(open(os.path.join(HERE, "..", "..", "tools.json")))
METRICS = TOOLS_JSON["common_types"]["metric"]["enum"]
PRESETS = TOOLS_JSON["common_types"]["time_range"]["properties"]["preset"]["enum"]
EPOCH0 = dt.datetime(1970, 1, 1)


def _resolve_refs(o):
    ct = TOOLS_JSON["common_types"]
    if isinstance(o, dict):
        if "$ref" in o:
            return _resolve_refs(copy.deepcopy(ct[o["$ref"].split("/")[-1]]))
        return {k: _resolve_refs(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_resolve_refs(x) for x in o]
    return o


ACTION_HISTORY_TOOL = {
    "name": "get_action_history",
    "description": "Past checklist steps, outcomes (sensor_replaced, sensor_repaired, fixed_by_action, resolved_on_its_own, false_alarm, no_action_needed) and maintenance rows (replaced, recalibrated, repaired) for a sensor, location or domain. Use for 'what did we do last time' and replaced/repaired questions.",
    "parameters": {"type": "object", "properties": {
        "node": {"type": "string", "description": "Sensor node id or location prefix such as KH03"},
        "metric": {"$ref": "#/common_types/metric"},
        "domain": {"$ref": "#/common_types/domain"},
        "time": {"$ref": "#/common_types/time_range"},
        "outcome": {"type": "string", "enum": ["sensor_replaced", "sensor_repaired", "fixed_by_action",
                                                "resolved_on_its_own", "false_alarm", "no_action_needed"]}}},
}


def openai_tools(names):
    by = {t["name"]: t for t in TOOLS_JSON["tools"]}
    by["get_action_history"] = ACTION_HISTORY_TOOL
    out = []
    for n in names:
        t = _resolve_refs(by[n])
        out.append({"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                     "parameters": t["parameters"]}})
    return out


CHAT_TOOLS = ["count_incidents", "find_incidents", "get_incident", "sensor_faults", "get_sensor_history",
              "list_sensors", "domain_health", "get_action_history", "search_knowledge"]
INCIDENT_TOOLS = ["related_context", "get_sensor_history", "get_action_history", "find_incidents"]


class ToolError(Exception):
    pass


def iso(t):
    return t.strftime("%Y-%m-%d %H:%M")


def parse_date(s):
    s = str(s).strip().replace(" ", "T")
    for f in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%Y-%m"):
        try:
            return dt.datetime.strptime(s, f)
        except ValueError:
            pass
    raise ToolError("bad date %r (use YYYY-MM-DD or YYYY-MM-DDTHH:MM)" % s)


def resolve_time(tr, required=True):
    if tr is None or tr == {}:
        if required:
            raise ToolError("'time' is required, e.g. {\"preset\": \"this_year\"}")
        tr = {"preset": "all"}
    if isinstance(tr, str):
        tr = {"preset": tr}
    if not isinstance(tr, dict):
        raise ToolError("'time' must be an object")
    p = tr.get("preset")
    today = NOW.replace(hour=0, minute=0, second=0)
    if p:
        if p not in PRESETS:
            raise ToolError("unknown preset %r; allowed: %s" % (p, ", ".join(PRESETS)))
        if p == "today":
            a, b = today, today + dt.timedelta(days=1)
        elif p == "yesterday":
            a, b = today - dt.timedelta(days=1), today
        elif p == "last_24h":
            a, b = NOW - dt.timedelta(hours=24), NOW
        elif p == "last_7d":
            a, b = NOW - dt.timedelta(days=7), NOW
        elif p == "this_week":
            a, b = today - dt.timedelta(days=today.weekday()), NOW
        elif p == "last_30d":
            a, b = NOW - dt.timedelta(days=30), NOW
        elif p == "this_month":
            a, b = today.replace(day=1), NOW
        elif p == "last_month":
            first = today.replace(day=1)
            a, b = (first - dt.timedelta(days=1)).replace(day=1), first
        elif p == "this_year":
            a, b = today.replace(month=1, day=1), NOW
        elif p == "last_year":
            a, b = dt.datetime(today.year - 1, 1, 1), dt.datetime(today.year, 1, 1)
        else:
            a, b = dt.datetime(2000, 1, 1), NOW
        return a, b
    a = parse_date(tr["from"]) if tr.get("from") else dt.datetime(2000, 1, 1)
    b = parse_date(tr["to"]) if tr.get("to") else NOW
    if tr.get("to") and len(str(tr["to"]).strip()) == 7:     # "2026-03" as an exclusive month end
        b = (b + dt.timedelta(days=32)).replace(day=1)
    if b <= a:
        raise ToolError("'to' must be after 'from' (to is exclusive)")
    return a, b


def coverage(a, b, kind="incidents"):
    start = YEAR_START if kind == "incidents" else READINGS_FROM
    complete = a >= start or (kind == "incidents" and a == dt.datetime(2000, 1, 1))
    note = "device store, fog offline"
    if not complete:
        note = ("device incident index starts %s; older data is only on the fog, which is unreachable (offline)" % start.date()
                if kind == "incidents" else
                "device keeps hourly readings from %s only; older readings are on the fog (offline)" % start.date())
    return {"source": "device", "complete": complete, "from": iso(max(a, start) if not complete else a)[:10],
            "to": iso(min(b, NOW)), "note": note}


class Executor:
    def __init__(self, path=STORE, scenario=None):
        self.db = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        self.db.row_factory = sqlite3.Row
        self.scenario = scenario or {}
        self.qid = 0

    # -------------------------------------------------------------- dispatch
    def run(self, name, args):
        if not isinstance(args, dict):
            try:
                args = json.loads(args)
            except Exception:
                return {"error": "arguments must be a JSON object"}
        fn = getattr(self, "t_" + str(name), None)
        if fn is None:
            return {"error": "unknown tool %r" % name}
        try:
            self.qid += 1
            res = fn(**args)
            if isinstance(res, dict) and "error" not in res:
                res["query_id"] = "q%d" % self.qid
            return res
        except ToolError as e:
            return {"error": str(e)}
        except TypeError as e:
            return {"error": "bad arguments: %s" % e}

    # -------------------------------------------------------------- filters
    def _where(self, time=None, domain=None, metric=None, node=None, severity=None, pattern=None, label=None,
               approval=None, include_injected=False, text=None, time_required=True):
        a, b = resolve_time(time, required=time_required)
        w = ["i.created_wall >= ?", "i.created_wall < ?"]
        p = [iso(a), iso(b)]
        if not include_injected:
            w.append("i.injected = 0")
        if severity:
            if isinstance(severity, str):
                severity = [severity]
            bad = [s for s in severity if s not in ("critical", "warning", "sensor_fault", "normal")]
            if bad:
                raise ToolError("unknown severity %s" % bad)
            w.append("i.severity IN (%s)" % ",".join("?" * len(severity)))
            p += list(severity)
        if label:
            w.append("i.label = ?")
            p.append(label)
        if approval:
            if approval not in ("pending", "approved", "dismissed"):
                raise ToolError("approval must be pending|approved|dismissed")
            w.append("i.approval = ?")
            p.append(approval)
        sw, sp = [], []
        if domain:
            if domain not in DOMAINS:
                raise ToolError("unknown domain %r" % domain)
            sw.append("s.domain = ?")
            sp.append(domain)
        if metric:
            if metric not in METRICS:
                raise ToolError("unknown metric %r" % metric)
            sw.append("s.metric = ?")
            sp.append(metric)
        if node:
            sw.append("instr(s.node, ?) > 0")
            sp.append(str(node))
        defn = []
        if pattern:
            pats = PATTERN_SYNONYMS.get(pattern, [pattern])
            sw.append("s.pattern IN (%s)" % ",".join("?" * len(pats)))
            sp += pats
            defn.append("pattern %s = %s" % (pattern, "|".join(pats)))
        if sw:
            w.append("EXISTS (SELECT 1 FROM incident_sensor s WHERE s.incident_id = i.id AND s.context = 0 AND %s)" % " AND ".join(sw))
            p += sp
            defn.append("flagged sensor filters")
        if text:
            for tok in str(text).lower().split():
                w.append("lower(coalesce(i.title,'') || ' ' || coalesce(i.root_cause,'') || ' ' || coalesce(i.approval_note,'') || ' ' || i.label) LIKE ?")
                p.append("%" + tok + "%")
        if not include_injected:
            defn.append("demo injections excluded")
        return " AND ".join(w), p, a, b, "; ".join(defn), sw, sp

    # -------------------------------------------------------------- tools
    def t_count_incidents(self, time=None, domain=None, metric=None, node=None, severity=None, pattern=None, label=None,
                          approval=None, include_injected=False, group_by="none"):
        w, p, a, b, defn, sw, sp = self._where(time, domain, metric, node, severity, pattern, label, approval, include_injected)
        res = {"coverage": coverage(a, b), "definition": defn or "all incidents"}
        if not group_by or group_by == "none":
            res["count"] = self.db.execute("SELECT COUNT(*) FROM incident i WHERE " + w, p).fetchone()[0]
            return res
        keys = {"day": "substr(i.created_wall,1,10)", "week": "strftime('%Y-W%W', i.created_wall)",
                "month": "substr(i.created_wall,1,7)", "severity": "i.severity", "label": "i.label"}
        if group_by in keys:
            q = "SELECT %s k, COUNT(*) c FROM incident i WHERE %s GROUP BY k ORDER BY c DESC, k" % (keys[group_by], w)
            rows = self.db.execute(q, p).fetchall()
        elif group_by in ("domain", "metric", "node", "pattern"):
            extra = (" AND " + " AND ".join(sw)) if sw else ""
            q = ("SELECT s.%s k, COUNT(DISTINCT i.id) c FROM incident i JOIN incident_sensor s ON s.incident_id = i.id"
                 " AND s.context = 0 WHERE %s%s GROUP BY k ORDER BY c DESC, k") % (group_by, w, extra)
            rows = self.db.execute(q, p + sp).fetchall()
        else:
            raise ToolError("unknown group_by %r" % group_by)
        res["groups"] = [{"key": r["k"], "count": r["c"]} for r in rows]
        res["total"] = self.db.execute("SELECT COUNT(*) FROM incident i WHERE " + w, p).fetchone()[0]
        return res

    def t_find_incidents(self, time=None, domain=None, metric=None, node=None, severity=None, label=None, text=None,
                         limit=5, pattern=None, include_injected=False, approval=None):
        w, p, a, b, defn, sw, sp = self._where(time, domain, metric, node, severity, pattern, label, approval,
                                               include_injected, text)
        try:
            limit = max(1, min(10, int(limit or 5)))
        except (TypeError, ValueError):
            limit = 5
        total = self.db.execute("SELECT COUNT(*) FROM incident i WHERE " + w, p).fetchone()[0]
        rows = self.db.execute("SELECT * FROM incident i WHERE %s ORDER BY i.created_wall DESC LIMIT %d" % (w, limit), p).fetchall()
        items = []
        for r in rows:
            doms = [x[0] for x in self.db.execute("SELECT DISTINCT domain FROM incident_sensor WHERE incident_id=? AND context=0", (r["id"],))]
            items.append({"id": r["id"], "time": r["created_wall"][:16], "title": r["title"], "severity": r["severity"],
                          "label": r["label"], "domains": doms, "approval": r["approval"], "outcome": r["outcome"]})
        return {"items": items, "total": total, "coverage": coverage(a, b)}

    def t_get_incident(self, id=None, detail="summary"):
        if not id:
            raise ToolError("'id' is required")
        r = self.db.execute("SELECT * FROM incident WHERE id = ?", (str(id).upper(),)).fetchone()
        if not r:
            return {"error": "no incident %s on this device" % id}
        sens = [{"ref": s["ref"], "node": s["node"], "metric": s["metric"], "domain": s["domain"],
                 "flagged": not s["context"], "pattern": s["pattern"], "status": s["status"],
                 **({"fault_kind": s["fault_kind"]} if s["fault_kind"] else {})}
                for s in self.db.execute("SELECT * FROM incident_sensor WHERE incident_id=? ORDER BY ref", (r["id"],))]
        steps = [{"action": s["action"], "state": s["state"], "by": s["by"]}
                 for s in self.db.execute("SELECT * FROM incident_step WHERE incident_id=? ORDER BY step_id", (r["id"],))]
        out = {"id": r["id"], "time": r["created_wall"][:16], "title": r["title"], "severity": r["severity"],
               "label": r["label"], "root_cause": r["root_cause"], "sensors": sens, "approval": r["approval"],
               "workflow": r["workflow"], "outcome": r["outcome"], "steps": steps, "injected": bool(r["injected"]),
               "refine_stage": r["refine_stage"]}
        if r["recurred_by"]:
            out["recurred_by"] = r["recurred_by"]
        return out

    def t_sensor_faults(self, time=None, basis=None, domain=None, distinct_sensors=True, fault_kind=None):
        a, b = resolve_time(time)
        if basis not in ("ai", "confirmed", "replaced"):
            raise ToolError("basis must be ai|confirmed|replaced")
        if fault_kind and fault_kind not in FAULT_KINDS:
            raise ToolError("unknown fault_kind %r" % fault_kind)
        if distinct_sensors is None:
            distinct_sensors = True
        if basis == "replaced":
            q = "SELECT m.node, m.metric, m.at_wall, m.incident_id FROM maintenance m WHERE m.action='replaced' AND m.at_wall >= ? AND m.at_wall < ?"
            p = [iso(a), iso(b)]
            rows = self.db.execute(q + " ORDER BY m.at_wall", p).fetchall()
            if domain:
                rows = [r for r in rows if CAT.get((r["node"], r["metric"]), ("",))[0] == domain]
            sensors = {}
            for r in rows:
                k = (r["node"], r["metric"])
                d = sensors.setdefault(k, {"node": r["node"], "metric": r["metric"], "replaced_at": [], "incidents": []})
                d["replaced_at"].append(r["at_wall"][:16])
                if r["incident_id"]:
                    d["incidents"].append(r["incident_id"])
            cnt = len(sensors) if distinct_sensors else len(rows)
            return {"count": cnt, "basis": "replaced (maintenance log)", "counted": "sensors" if distinct_sensors else "replacements",
                    "sensors": list(sensors.values())[:10], "coverage": coverage(a, b)}
        w = ["s.status = 'sensor_fault'", "i.injected = 0", "i.created_wall >= ?", "i.created_wall < ?"]
        p = [iso(a), iso(b)]
        if basis == "confirmed":
            w.append("i.approval = 'approved'")
        if domain:
            w.append("s.domain = ?")
            p.append(domain)
        if fault_kind:
            w.append("s.fault_kind = ?")
            p.append(fault_kind)
        rows = self.db.execute("SELECT s.node, s.metric, i.id, i.created_wall FROM incident_sensor s JOIN incident i ON i.id = s.incident_id"
                               " WHERE %s ORDER BY i.created_wall" % " AND ".join(w), p).fetchall()
        sensors = {}
        for r in rows:
            k = (r["node"], r["metric"])
            d = sensors.setdefault(k, {"node": r["node"], "metric": r["metric"], "first": r["created_wall"][:16], "incidents": []})
            d["last"] = r["created_wall"][:16]
            d["incidents"].append(r["id"])
        incs = sorted(set(r["id"] for r in rows))
        cnt = len(sensors) if distinct_sensors else len(incs)
        sl = sorted(sensors.values(), key=lambda d: -len(d["incidents"]))
        for d in sl:
            d["incident_count"] = len(d["incidents"])
            d["incidents"] = d["incidents"][-5:]
        return {"count": cnt, "basis": basis, "counted": "distinct sensors" if distinct_sensors else "incidents",
                "sensors": sl[:10], "coverage": coverage(a, b)}

    def t_get_sensor_history(self, node=None, metric=None, time=None, agg="hourly", stats_only=True):
        sc = self.scenario.get("history", {})
        if (node, metric) in [tuple(k.split("|")) for k in sc]:
            return copy.deepcopy(sc["%s|%s" % (node, metric)])
        if self.scenario.get("mode") == "incident" and sc.get("*"):
            return copy.deepcopy(sc["*"])
        if not node or not metric:
            raise ToolError("'node' and 'metric' are required")
        if (node, metric) not in CAT:
            cands = [m for (n, m) in CAT if n == node]
            raise ToolError("unknown sensor %s/%s%s" % (node, metric, ("; this node has " + ", ".join(cands)) if cands else ""))
        a, b = resolve_time(time)
        unit = CAT[(node, metric)][2]
        ep = lambda t: int((t - EPOCH0).total_seconds())
        fromts = lambda x: EPOCH0 + dt.timedelta(seconds=x)
        if agg == "5min":
            rows = self.db.execute("SELECT t, v, v mn, v mx, v lst FROM reading_5min WHERE node=? AND metric=? AND t>=? AND t<? ORDER BY t",
                                   (node, metric, ep(a), ep(b))).fetchall()
            pts = [(fromts(r[0]), r[1], r[2], r[3]) for r in rows]
            res_name, cov_start = "5min", FIVEMIN_FROM
        else:
            rows = self.db.execute("SELECT t, mean, min, max, last FROM reading_hourly WHERE node=? AND metric=? AND t>=? AND t<? ORDER BY t",
                                   (node, metric, ep(a), ep(b))).fetchall()
            pts = [(fromts(r[0]), r[1], r[2], r[3]) for r in rows]
            res_name, cov_start = "hourly", READINGS_FROM
            if agg == "daily":
                byday = {}
                for t, mean, mn, mx in pts:
                    byday.setdefault(t.date(), []).append((t, mean, mn, mx))
                pts = [(dt.datetime.combine(d, dt.time()), sum(x[1] for x in v) / len(v), min(x[2] for x in v), max(x[3] for x in v))
                       for d, v in sorted(byday.items())]
                res_name = "daily"
        cov = {"source": "device", "complete": a >= cov_start, "from": iso(max(a, cov_start)), "to": iso(min(b, NOW)),
               "note": "device keeps %s readings from %s" % ("raw 5-min" if agg == "5min" else "hourly", cov_start.date())}
        if not pts:
            return {"summary": [{"id": "H1", "text": "no readings stored for %s %s in this period" % (node, metric)}],
                    "resolution": res_name, "coverage": cov}
        dec = 3 if metric in ("pf", "ph") else 1
        r_ = lambda x: round(x, dec)
        mean_all = sum(p[1] for p in pts) / len(pts)
        mn = min(pts, key=lambda p: p[2])
        mx = max(pts, key=lambda p: p[3])
        n = len(pts)
        xs = [(p[0] - pts[0][0]).total_seconds() / 86400 for p in pts]
        ys = [p[1] for p in pts]
        if n > 2 and xs[-1] > 0:
            xm = sum(xs) / n
            ym = sum(ys) / n
            slope = sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / max(1e-9, sum((x - xm) ** 2 for x in xs))
        else:
            slope = 0.0
        jumps = [(abs(ys[i] - ys[i - 1]), ys[i] - ys[i - 1], pts[i][0]) for i in range(1, n)]
        jmax = max(jumps) if jumps else (0, 0, pts[0][0])
        lines = [
            "%d %s points from %s to %s" % (n, res_name, iso(pts[0][0]), iso(pts[-1][0])),
            "mean = %s %s" % (r_(mean_all), unit),
            "min = %s %s at %s" % (r_(mn[2]), unit, iso(mn[0])),
            "max = %s %s at %s" % (r_(mx[3]), unit, iso(mx[0])),
            "last = %s %s (%s)" % (r_(pts[-1][1]), unit, iso(pts[-1][0])),
            "trend = %+.*f %s/day" % (dec, slope, unit),
            "largest step between points = %+.*f %s at %s" % (dec, jmax[1], unit, iso(jmax[2])),
        ]
        out = {"sensor": "%s %s" % (node, metric), "summary": [{"id": "H%d" % (i + 1), "text": t} for i, t in enumerate(lines)],
               "resolution": res_name, "coverage": cov}
        if stats_only is False:
            out["points"] = [[iso(p[0]), r_(p[1])] for p in pts[-48:]]
            if n > 48:
                out["points_note"] = "last 48 of %d points" % n
        return out

    def t_list_sensors(self, domain=None, location=None, status=None):
        out = []
        for node, metric, dom, loc, unit in CATALOG:
            if domain and dom != domain:
                continue
            if location and location.lower() not in (node + " " + loc).lower():
                continue
            worst = self.db.execute(
                "SELECT i.severity FROM incident i JOIN incident_sensor s ON s.incident_id=i.id AND s.context=0"
                " WHERE s.node=? AND s.metric=? AND i.workflow != 'closed' AND i.injected=0"
                " ORDER BY CASE i.severity WHEN 'critical' THEN 0 WHEN 'sensor_fault' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END LIMIT 1",
                (node, metric)).fetchone()
            st = worst[0] if worst else "normal"
            if status and st != status:
                continue
            last = self.db.execute("SELECT t, v FROM reading_5min WHERE node=? AND metric=? ORDER BY t DESC LIMIT 1", (node, metric)).fetchone()
            out.append({"node": node, "metric": metric, "domain": dom, "location": loc, "status": st,
                        "last": ("%s %s" % (last[1], unit)).strip() if last else None})
        return {"sensors": out, "count": len(out)}

    def t_domain_health(self, domain=None):
        out = []
        for d in DOMAINS:
            if domain and d != domain:
                continue
            rows = self.db.execute(
                "SELECT DISTINCT i.id, i.severity, i.workflow FROM incident i JOIN incident_sensor s ON s.incident_id=i.id AND s.context=0"
                " WHERE s.domain=? AND i.workflow != 'closed' AND i.injected=0 ORDER BY i.created_wall DESC", (d,)).fetchall()
            sevs = [r["severity"] for r in rows]
            worst = next((s for s in ("critical", "sensor_fault", "warning") if s in sevs), "normal")
            out.append({"domain": d, "worst_status": worst, "open_incidents": len(rows),
                        "needs_decision": sum(1 for r in rows if r["workflow"] == "needs_decision"),
                        "open_ids": [r["id"] for r in rows[:5]]})
        return {"domains": out}

    def t_related_context(self, ref=None, hours=4):
        rc = self.scenario.get("related")
        if self.scenario.get("mode") != "incident":
            raise ToolError("related_context is only available during incident analysis")
        if rc is None:
            return {"related": [], "note": "no causally related sensors beyond those already in the prompt"}
        if isinstance(rc, dict):
            return copy.deepcopy(rc.get(str(ref), rc.get("*", {"related": [], "note": "no related sensors for %s" % ref})))
        return copy.deepcopy(rc)

    def t_search_knowledge(self, query=None, k=5):
        return {"available": False, "passages": [],
                "note": "search_knowledge runs on the fog server, which is unreachable (device offline). No documents are available."}

    def t_get_action_history(self, node=None, metric=None, domain=None, time=None, outcome=None, location=None):
        if self.scenario.get("mode") == "incident" and "action_history" in self.scenario:
            return copy.deepcopy(self.scenario["action_history"])
        node = node or location
        a, b = resolve_time(time, required=False)
        w = ["i.injected = 0", "i.created_wall >= ?", "i.created_wall < ?"]
        p = [iso(a), iso(b)]
        sw, sp = [], []
        if node:
            sw.append("instr(s.node, ?) > 0")
            sp.append(node)
        if metric:
            sw.append("s.metric = ?")
            sp.append(metric)
        if domain:
            sw.append("s.domain = ?")
            sp.append(domain)
        if sw:
            w.append("EXISTS (SELECT 1 FROM incident_sensor s WHERE s.incident_id=i.id AND s.context=0 AND %s)" % " AND ".join(sw))
            p += sp
        w2 = list(w)
        p2 = list(p)
        if outcome:
            w2.append("i.outcome = ?")
            p2.append(outcome)
        counts = {r[0]: r[1] for r in self.db.execute(
            "SELECT i.outcome, COUNT(*) FROM incident i WHERE %s AND i.outcome IS NOT NULL GROUP BY i.outcome" % " AND ".join(w), p)}
        rows = self.db.execute("SELECT * FROM incident i WHERE %s AND (i.outcome IS NOT NULL OR i.workflow != 'closed')"
                               " ORDER BY i.created_wall DESC LIMIT 8" % " AND ".join(w2), p2).fetchall()
        items = []
        for r in rows:
            f = self.db.execute("SELECT node, metric FROM incident_sensor WHERE incident_id=? AND context=0 ORDER BY ref LIMIT 1", (r["id"],)).fetchone()
            steps = ["%s:%s" % (s["action"], s["state"]) for s in self.db.execute(
                "SELECT action, state FROM incident_step WHERE incident_id=? ORDER BY step_id", (r["id"],))]
            it = {"id": r["id"], "time": r["created_wall"][:16], "sensor": "%s/%s" % (f[0], f[1]) if f else None,
                  "label": r["label"], "steps": steps, "outcome": r["outcome"], "workflow": r["workflow"]}
            if r["recurred_by"]:
                it["recurred_by"] = r["recurred_by"]
            items.append(it)
        mw = ["at_wall >= ?", "at_wall < ?"]
        mp = [iso(a), iso(b)]
        if node:
            mw.append("instr(node, ?) > 0")
            mp.append(node)
        if metric:
            mw.append("metric = ?")
            mp.append(metric)
        mrows = self.db.execute("SELECT * FROM maintenance WHERE %s ORDER BY at_wall" % " AND ".join(mw), mp).fetchall()
        if domain:
            mrows = [m for m in mrows if CAT.get((m["node"], m["metric"]), ("",))[0] == domain]
        mcounts = {}
        for m in mrows:
            mcounts[m["action"]] = mcounts.get(m["action"], 0) + 1
        return {"outcome_counts": counts, "maintenance_counts": mcounts,
                "maintenance": [{"at": m["at_wall"][:16], "node": m["node"], "metric": m["metric"], "action": m["action"],
                                 "incident": m["incident_id"]} for m in mrows[-8:]],
                "items": items, "coverage": coverage(a, b)}


if __name__ == "__main__":
    ex = Executor()
    for name, args in [("count_incidents", {"time": {"preset": "this_year"}, "metric": "co2", "pattern": "spike"}),
                       ("count_incidents", {"time": {"preset": "this_year"}, "group_by": "month"}),
                       ("sensor_faults", {"time": {"preset": "this_year"}, "basis": "ai"}),
                       ("sensor_faults", {"time": {"preset": "this_year"}, "basis": "replaced"}),
                       ("get_sensor_history", {"node": "SR-AQ-KH03-03", "metric": "co2", "time": {"preset": "yesterday"}}),
                       ("get_action_history", {"node": "SR-AQ-KH03-03", "metric": "co2"}),
                       ("domain_health", {}), ("find_incidents", {"time": {"preset": "last_7d"}, "severity": ["critical"]})]:
        print(name, json.dumps(ex.run(name, args))[:700])
