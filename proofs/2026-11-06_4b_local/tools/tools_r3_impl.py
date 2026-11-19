"""r3 chat tools on the training stores: the 15 rsn_v3 tools (tools_v3_impl.ToolsV3 on the DEVICE store) + 4 fog tools with a
deterministic device fallback + 3 local cross-domain tools. The device side is
Code/smart-city-edge-agent/app/backend/chat_fog.go; both run the same fixture in parity_r3.py / chat_fog_parity_test.go.

World (make_store_r3.py): fog store = every incident (2025-11-01 .. now), daily sensor rollups, the knowledge base;
device store = the newest 1000 incidents in full + an index row for every older one (no root cause, notes, close time,
steps, events) + hourly readings for 60 days. `fog` state: "online" | "offline" | "timeout" (the prompt still says
online, the call times out: fog down mid-conversation). The model never chooses the fallback: the tool does.

Fog tools (result `source`: "fog" | "device_fallback" + `fog: "unreachable"`):
  fog_search_history(time*, domain, metric, node, severity, label, text, limit)  incidents + root causes, all history
  fog_analytics(analysis*, time*, bucket, group_by, domain, metric, node, severity, label)
      incident_trend (counts per month/week, zero-filled), resolve_time (hours created -> closed), sensor_monthly (node*, metric*)
  search_knowledge(query*, k)    fog knowledge base (standards, SOPs, manuals, reports); fallback: device cache (cached=true)
  fog_status()                   reachable?, last sync, pending uploads, what the device store holds
  get_incident (existing)        an archived incident's full record comes from the fog; fallback = its index row
Coverage on a fallback: from = oldest full record on the device, incidents = full records, complete = the period starts inside
the device's full-record window (trend counts: inside the index), index_from, counts_exact (false with a text filter: older
incidents are matched on title/label only), note.
Local tools (device store incl. the all-time index, demo injections excluded):
  co_occurring_incidents(id*, window_min=60, other_domains_only=true)  incidents within +-window of an incident
  recurring_issues(time*, min_count=3, by=sensor|node, domain, metric)   sensors/nodes with repeated incidents
  compare_periods(period_a*, period_b*, domain, metric, node, severity, label)  counts, severities, top labels, change
"""
import collections
import datetime as dt
import json
import math
import os
import re
import sqlite3
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
V3P = os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3", "pipeline")
sys.path.insert(0, V3P)
import tools_v3_impl as TV3  # noqa: E402
from tools_v3_impl import ToolsV3, CHAT_TOOLS_V4, iso, resolve_time, ToolError, ep, fromts, EPOCH0  # noqa: E402
import tools_impl as T1  # noqa: E402
from common import NOW, CATALOG  # noqa: E402

STORE_DIR = os.path.abspath(os.path.join(HERE, "..", "data", "store"))
FOG_DB = os.path.join(STORE_DIR, "fog_store_r3.sqlite")
DEV_DB = os.path.join(STORE_DIR, "device_store_r3.sqlite")
KB_PATH = os.path.join(HERE, "knowledge_r3.json")
FOG_TOOLS = ["fog_search_history", "fog_analytics", "search_knowledge", "fog_status"]
LOCAL_TOOLS = ["co_occurring_incidents", "recurring_issues", "compare_periods"]
CHAT_TOOLS_R3 = [t for t in CHAT_TOOLS_V4] + ["fog_search_history", "fog_analytics", "fog_status"] + LOCAL_TOOLS
SEVS = ("critical", "warning", "sensor_fault", "normal")
DOMAINS = ("air_quality", "water", "power", "occupancy", "weather", "hvac")
STOP = set("""a an the and or of to in on for is are was were be been what whats what's does do did say says said about how we our
with me my find show look up please pls per from at it its this that any there should when which who can could you tell give get
search knowledge base docs doc document documents sop sops manual handbook guideline guidelines i us your have has had
is there kya hai batao""".split())
FALLBACK_NOTE_INC = ("fog unreachable: full records for the last %d incidents on this device (since %s); older incidents from the "
                     "all-time index (no root cause or checklist)")

# the device-side round-1 coverage: records (device index and fog) start at the first incident
T1.YEAR_START = dt.datetime(2025, 11, 1)


def tokens(s):
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1]


def r1(x):
    return float("%.1f" % x)


def rnd(metric, x):
    return round(x, 3) if metric in ("pf", "ph") else round(x, 1)


def sev_set(v):
    if v is None or v == "" or v == []:
        return set()
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        raise ToolError("severity must be a string or a list")
    bad = [s for s in v if s not in SEVS]
    if bad:
        raise ToolError("unknown severity %s" % bad[0])
    return set(v)


def clamp_int(v, d, lo, hi):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return d
    return max(lo, min(hi, v))


class Store:
    """incidents of one SQLite store as the tools see them"""

    def __init__(self, path):
        self.path = path
        db = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        db.row_factory = sqlite3.Row
        self.db = db
        sens = collections.defaultdict(list)
        for s in db.execute("SELECT * FROM incident_sensor WHERE context=0 ORDER BY incident_id, ref"):
            sens[s["incident_id"]].append(dict(s))
        self.incs = []
        for r in db.execute("SELECT * FROM incident ORDER BY created_wall, id"):
            doms = []
            for s in sens[r["id"]]:
                if s["domain"] not in doms:
                    doms.append(s["domain"])
            self.incs.append({"id": r["id"], "t": dt.datetime.strptime(r["created_wall"][:16], "%Y-%m-%d %H:%M"),
                              "time": r["created_wall"][:16], "title": r["title"], "severity": r["severity"], "label": r["label"],
                              "root": r["root_cause"] or None, "domains": doms, "sensors": sens[r["id"]], "approval": r["approval"],
                              "workflow": r["workflow"], "outcome": r["outcome"], "injected": bool(r["injected"]),
                              "closed": dt.datetime.strptime(r["closed_at"][:16], "%Y-%m-%d %H:%M") if r["closed_at"] else None,
                              "full": bool(r["full_on_device"])})
        self.by_id = {x["id"]: x for x in self.incs}
        full = [x for x in self.incs if x["full"]]
        self.n_full = len(full)
        self.full_from = min(x["t"] for x in full) if full else NOW
        self.index_from = self.incs[0]["t"] if self.incs else NOW
        tabs = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.has_daily = "reading_daily" in tabs

    def filter(self, args, time_key="time", required=True):
        a, b = resolve_time(args.get(time_key), required=required)
        dom, metric, node, label = (str(args.get(k) or "").strip() for k in ("domain", "metric", "node", "label"))
        if dom and dom not in DOMAINS:
            raise ToolError("unknown domain %r" % dom)
        sevs = sev_set(args.get("severity"))
        text = str(args.get("text") or "").lower().split()
        out = []
        for x in self.incs:
            if x["injected"] or x["t"] < a or x["t"] >= b:
                continue
            if sevs and x["severity"] not in sevs:
                continue
            if label and x["label"] != label:
                continue
            if dom or metric or node:
                if not any((not dom or s["domain"] == dom) and (not metric or s["metric"] == metric) and
                           (not node or node in s["node"] or node in s["node"].replace("-", "")) for s in x["sensors"]):
                    continue
            if text:
                hay = ("%s %s %s" % (x["title"] or "", x["root"] or "", x["label"] or "")).lower()
                if not all(w in hay for w in text):
                    continue
            out.append(x)
        out.sort(key=lambda x: (x["t"], x["id"]), reverse=True)
        return out, a, b


def inc_item(x, root=True):
    it = {"id": x["id"], "time": x["time"], "title": x["title"], "severity": x["severity"], "label": x["label"],
          "domains": x["domains"], "outcome": x["outcome"]}
    if root:
        it["root_cause"] = x["root"]
    return it


class ToolsR3:
    def __init__(self, fog="online", last_sync=None, fog_path=FOG_DB, dev_path=DEV_DB, kb_path=KB_PATH):
        assert fog in ("online", "offline", "timeout")
        self.fog = fog
        self.last_sync = last_sync
        self.dev = ToolsV3(path=dev_path)
        self.fogx = ToolsV3(path=fog_path)
        self.D = Store(dev_path)
        self.F = Store(fog_path)
        kb = json.load(open(kb_path, encoding="utf-8"))
        self.kb = kb
        self.cache = [p for p in kb if p.get("cached")]
        self.qid = 0

    @property
    def online(self):
        return self.fog == "online"

    # ---------------------------------------------------------------- dispatch
    def run(self, name, args):
        if not isinstance(args, dict):
            try:
                args = json.loads(args)
            except Exception:
                return {"error": "arguments must be a JSON object"}
        self.qid += 1
        try:
            if name in FOG_TOOLS:
                res = self.fog_tool(name, args)
            elif name in LOCAL_TOOLS:
                res = getattr(self, "t_" + name)(**args)
            elif name == "get_incident":
                res = self.get_incident(args)
            elif name in CHAT_TOOLS_V4:
                res = self.dev.run(name, args)
                if isinstance(res, dict) and "error" not in res:
                    self.patch_notes(res)
            else:
                return {"error": "unknown tool %r" % name}
        except ToolError as e:
            return {"error": str(e)}
        except TypeError as e:
            return {"error": "bad arguments: %s" % e}
        if isinstance(res, dict) and "error" not in res:
            res.pop("query_id", None)
            res["query_id"] = "q%d" % self.qid
        return res

    def patch_notes(self, o):
        """device tools' coverage notes follow the live fog state (Go: chatCoverage)"""
        if isinstance(o, dict):
            for k, v in list(o.items()):
                if k == "note" and isinstance(v, str) and self.online:
                    o[k] = v.replace("device store, fog offline", "device store").replace(", which is unreachable (offline)", "").replace(" (offline)", "")
                elif isinstance(v, (dict, list)):
                    self.patch_notes(v)
        elif isinstance(o, list):
            for x in o:
                self.patch_notes(x)

    def fog_tool(self, name, args):
        if self.online:
            res = getattr(self, "q_" + name)(args, self.F, True)
            if "error" not in res:
                res = dict({"source": "fog"}, **res)
            return res
        res = getattr(self, "q_" + name)(args, self.D, False)
        if "error" not in res:
            res = dict({"source": "device_fallback", "fog": "unreachable"}, **res)
        return res

    # ---------------------------------------------------------------- coverage
    def cov(self, S, on_fog, a, b, counts_exact=True, index=False):
        to = iso(min(b, NOW))
        if on_fog:
            return {"from": S.index_from.strftime("%Y-%m-%d"), "to": to, "incidents": len(S.incs), "complete": True}
        start = S.index_from if index else S.full_from
        return {"from": S.full_from.strftime("%Y-%m-%d"), "to": to, "incidents": S.n_full, "complete": a >= start or (index and a.year == 2000),
                "index_from": S.index_from.strftime("%Y-%m-%d"), "counts_exact": counts_exact,
                "note": FALLBACK_NOTE_INC % (S.n_full, S.full_from.strftime("%Y-%m-%d"))}

    # ---------------------------------------------------------------- fog queries (same code on fog and device stores)
    def q_fog_search_history(self, args, S, on_fog):
        bad = set(args) - {"time", "domain", "metric", "node", "severity", "label", "text", "limit"}
        if bad:
            raise ToolError("unknown argument %s" % sorted(bad)[0])
        incs, a, b = S.filter(args)
        limit = clamp_int(args.get("limit", 5), 5, 1, 10)
        cov = self.cov(S, on_fog, a, b, counts_exact=not str(args.get("text") or "").strip())
        return {"total": len(incs), "items": [inc_item(x) for x in incs[:limit]], "coverage": cov}

    def q_fog_analytics(self, args, S, on_fog):
        an = args.get("analysis")
        if an not in ("incident_trend", "resolve_time", "sensor_monthly"):
            raise ToolError("analysis must be incident_trend|resolve_time|sensor_monthly")
        if an == "sensor_monthly":
            return self.sensor_monthly(args, S, on_fog)
        incs, a, b = S.filter(args)
        if an == "incident_trend":
            bucket = args.get("bucket") or "month"
            if bucket not in ("month", "week"):
                raise ToolError("bucket must be month|week")
            start, end = max(a, S.index_from), min(b, NOW)
            keyf = (lambda t: t.strftime("%Y-%m")) if bucket == "month" else (lambda t: "%d-W%02d" % t.isocalendar()[:2])
            keys, t = [], (start.replace(day=1, hour=0, minute=0, second=0) if bucket == "month" else
                           (start - dt.timedelta(days=start.weekday())).replace(hour=0, minute=0, second=0))
            while t < end:
                keys.append(keyf(t))
                t = (t + dt.timedelta(days=32)).replace(day=1) if bucket == "month" else t + dt.timedelta(days=7)
            cnt = collections.Counter(keyf(x["t"]) for x in incs)
            buckets = [{"key": k, "count": cnt.get(k, 0)} for k in keys]
            peak = max(buckets, key=lambda x: x["count"]) if buckets else None
            res = {"analysis": an, "bucket": bucket, "total": len(incs), "buckets": buckets,
                   "peak": peak, "mean_per_bucket": r1(len(incs) / len(buckets)) if buckets else 0.0}
            res["coverage"] = self.cov(S, on_fog, a, b, index=True)
            if not on_fog:
                res["coverage"]["note"] = "fog unreachable: counted on this device from its all-time incident index (counts exact)"
            return res
        g = args.get("group_by") or "label"
        if g not in ("label", "domain"):
            raise ToolError("group_by must be label|domain")
        hrs = collections.defaultdict(list)
        allh = []
        for x in incs:
            if not x["closed"] or x["workflow"] != "closed":
                continue
            h = (x["closed"] - x["t"]).total_seconds() / 3600
            allh.append(h)
            for k in ([x["label"] or "none"] if g == "label" else x["domains"]):
                hrs[k].append(h)
        groups = [{"key": k, "closed": len(v), "mean_h": r1(sum(v) / len(v)), "median_h": r1(statistics.median(v))} for k, v in hrs.items()]
        groups.sort(key=lambda x: (-x["closed"], x["key"]))
        res = {"analysis": an, "group_by": g, "closed": len(allh),
               "mean_h": r1(sum(allh) / len(allh)) if allh else None, "median_h": r1(statistics.median(allh)) if allh else None,
               "groups": groups[:8], "coverage": self.cov(S, on_fog, a, b)}
        if not on_fog:
            res["coverage"]["note"] = "fog unreachable: only incidents with full records on this device (since %s)" % S.full_from.strftime("%Y-%m-%d")
            res["coverage"]["counts_exact"] = res["coverage"]["complete"]
        return res

    def sensor_monthly(self, args, S, on_fog):
        node, metric = str(args.get("node") or "").strip(), str(args.get("metric") or "").strip()
        if not node or not metric:
            raise ToolError("'node' and 'metric' are required for sensor_monthly")
        cat = {(n, m): u for n, m, d, l, u in self.dev.catalog}
        if (node, metric) not in cat:
            cands = [m for (n, m) in cat if n == node]
            raise ToolError("unknown sensor %s/%s%s" % (node, metric, ("; this node has " + ", ".join(cands)) if cands else ""))
        a, b = resolve_time(args.get("time"))
        b2 = min(b, NOW)
        months = collections.OrderedDict()
        if on_fog and S.has_daily:
            for r in S.db.execute("SELECT day, n, mean, min, max FROM reading_daily WHERE node=? AND metric=? AND day>=? AND day<=? ORDER BY day",
                                  (node, metric, a.strftime("%Y-%m-%d"), b2.strftime("%Y-%m-%d"))):
                if dt.datetime.strptime(r["day"], "%Y-%m-%d") >= b2:     # a day row covers [day, day+1): keep it if it starts before b
                    continue
                m = months.setdefault(r["day"][:7], {"means": [], "min": r["min"], "max": r["max"], "days": set()})
                m["means"].append((r["mean"], r["n"] or 1))
                m["min"], m["max"] = min(m["min"], r["min"]), max(m["max"], r["max"])
                m["days"].add(r["day"])
            first = S.db.execute("SELECT MIN(day) FROM reading_daily WHERE node=? AND metric=?", (node, metric)).fetchone()[0]
        else:
            for r in S.db.execute("SELECT t, n, mean, min, max FROM reading_hourly WHERE node=? AND metric=? AND t>=? AND t<? ORDER BY t",
                                  (node, metric, ep(a), ep(b2))):
                t = fromts(r["t"])
                m = months.setdefault(t.strftime("%Y-%m"), {"means": [], "min": r["min"], "max": r["max"], "days": set()})
                m["means"].append((r["mean"], r["n"] or 1))
                m["min"], m["max"] = min(m["min"], r["min"]), max(m["max"], r["max"])
                m["days"].add(t.strftime("%Y-%m-%d"))
            f = S.db.execute("SELECT MIN(t) FROM reading_hourly WHERE node=? AND metric=?", (node, metric)).fetchone()[0]
            first = fromts(f).strftime("%Y-%m-%d") if f is not None else None
        out = [{"month": k, "mean": rnd(metric, sum(x * n for x, n in v["means"]) / sum(n for _, n in v["means"])), "min": rnd(metric, v["min"]), "max": rnd(metric, v["max"]),
                "days": len(v["days"])} for k, v in months.items()]
        first = first or NOW.strftime("%Y-%m-%d")
        cov = {"from": first, "to": iso(b2), "complete": a >= dt.datetime.strptime(first, "%Y-%m-%d") or on_fog}
        if not on_fog:
            cov["note"] = "fog unreachable: monthly values from the readings still on this device (since %s)" % first
        return {"analysis": "sensor_monthly", "sensor": "%s %s" % (node, metric), "unit": cat[(node, metric)], "months": out, "coverage": cov}

    def q_search_knowledge(self, args, S, on_fog):
        q = str(args.get("query") or "").strip()
        if not q:
            raise ToolError("'query' is required")
        k = clamp_int(args.get("k", 3), 3, 1, 5)
        qt = set(tokens(q))
        docs = self.kb if on_fog else self.cache
        scored = []
        for i, p in enumerate(docs):
            pt = set(tokens(p["id"] + " " + p["title"] + " " + p["text"]))
            s = len(qt & pt)
            if s > 0:
                scored.append((-s, i, p))
        scored.sort(key=lambda x: (x[0], x[1]))
        ps = [{"id": p["id"], "title": p["title"], "source": p["source"], "text": p["text"]} for _, _, p in scored[:k]]
        res = {"available": bool(ps), "passages": ps}
        if not on_fog:
            res["coverage"] = {"passages": len(self.cache), "complete": False,
                               "note": "fog unreachable: searched only the device cache of key limits and SOPs"}
        return res

    def q_fog_status(self, args, S, on_fog):
        d = self.D
        ls = (NOW - dt.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M") if on_fog else self.last_sync
        pend = 0
        if not on_fog:
            pend = sum(1 for x in d.incs if ls is None or x["time"] > ls)
        res = {"fog": "reachable" if on_fog else "unreachable", "last_sync": ls, "pending_uploads": pend,
               "device_store": {"full_incidents": d.n_full, "since": d.full_from.strftime("%Y-%m-%d"), "index_rows": len(d.incs),
                                "index_from": d.index_from.strftime("%Y-%m-%d")}}
        if on_fog:
            res["fog_incidents"] = len(S.incs)
        return res

    # ---------------------------------------------------------------- get_incident: archived -> fog / index row
    def get_incident(self, args):
        res = self.dev.run("get_incident", args)
        if not isinstance(res, dict) or "error" in res:
            return res
        x = self.D.by_id.get(res["id"])
        if x is None or x["full"]:
            return res
        if self.online:
            f = self.fogx.run("get_incident", args)
            f.pop("query_id", None)
            return dict({"source": "fog"}, **f)
        res.pop("query_id", None)
        return dict({"source": "device_fallback", "fog": "unreachable",
                     "note": "full record archived off the device (it keeps the last %d incidents in full); fog unreachable: index row only, "
                             "no root cause or checklist" % self.D.n_full}, **res)

    # ---------------------------------------------------------------- local cross-domain tools (device store + index)
    def t_co_occurring_incidents(self, id=None, window_min=60, other_domains_only=True):
        if not id:
            raise ToolError("'id' is required")
        x0 = self.D.by_id.get(str(id).strip().upper())
        if x0 is None:
            return {"error": "no incident %s on this device" % str(id).strip().upper()}
        w = clamp_int(window_min, 60, 10, 240)
        other = other_domains_only is not False
        items = []
        for x in self.D.incs:
            if x["id"] == x0["id"] or x["injected"]:
                continue
            d = (x["t"] - x0["t"]).total_seconds()
            if abs(d) > w * 60:
                continue
            if other and not (set(x["domains"]) - set(x0["domains"])):
                continue
            it = inc_item(x, root=False)
            it.pop("outcome")
            it["offset_min"] = int(math.floor(d / 60))
            items.append(it)
        items.sort(key=lambda it: (abs(it["offset_min"]), it["id"]))
        return {"anchor": {"id": x0["id"], "time": x0["time"], "title": x0["title"], "domains": x0["domains"]}, "window_min": w,
                "other_domains_only": other, "total": len(items), "items": items[:8]}

    def t_recurring_issues(self, time=None, min_count=3, by="sensor", domain=None, metric=None):
        a, b = resolve_time(time)
        if by not in ("sensor", "node"):
            raise ToolError("by must be sensor|node")
        if domain and domain not in DOMAINS:
            raise ToolError("unknown domain %r" % domain)
        mc = clamp_int(min_count, 3, 2, 50)
        g = collections.OrderedDict()
        for x in sorted(self.D.incs, key=lambda x: (x["t"], x["id"])):
            if x["injected"] or x["t"] < a or x["t"] >= b:
                continue
            keys = []
            for s in x["sensors"]:
                if (domain and s["domain"] != domain) or (metric and s["metric"] != metric):
                    continue
                k = s["node"] + " " + s["metric"] if by == "sensor" else s["node"]
                if k not in keys:
                    keys.append(k)
            for k in keys:
                e = g.setdefault(k, {"n": 0, "first": x["time"], "last": x["time"], "labels": collections.Counter(), "outcomes": collections.Counter(), "open": 0})
                e["n"] += 1
                e["last"] = x["time"]
                e["labels"][x["label"] or "none"] += 1
                if x["outcome"]:
                    e["outcomes"][x["outcome"]] += 1
                if x["workflow"] != "closed":
                    e["open"] += 1
        rows = [(k, e) for k, e in g.items() if e["n"] >= mc]
        rows.sort(key=lambda r: (-r[1]["n"], r[0]))
        items = []
        for k, e in rows[:8]:
            top = sorted(e["labels"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            items.append({by: k, "count": e["n"], "first": e["first"], "last": e["last"], "top_label": top,
                          "outcomes": dict(sorted(e["outcomes"].items())), "open": e["open"]})
        return {"by": by, "min_count": mc, "groups": len(rows), "items": items,
                "coverage": {"source": "device", "from": a.strftime("%Y-%m-%d"), "to": iso(min(b, NOW)), "complete": True}}

    def t_compare_periods(self, period_a=None, period_b=None, domain=None, metric=None, node=None, severity=None, label=None):
        if period_a is None or period_b is None:
            raise ToolError("'period_a' and 'period_b' are required")
        out = {}
        base = {"domain": domain, "metric": metric, "node": node, "severity": severity, "label": label}
        for key, per in (("a", period_a), ("b", period_b)):
            incs, a, b = self.D.filter(dict(base, time=per))
            sev = collections.Counter(x["severity"] for x in incs)
            lab = collections.Counter(x["label"] or "none" for x in incs)
            out[key] = {"from": iso(a), "to": iso(min(b, NOW)), "count": len(incs),
                        "by_severity": {s: sev[s] for s in SEVS if sev[s]},
                        "top_labels": [{"label": k, "count": v} for k, v in sorted(lab.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]}
        na, nb = out["a"]["count"], out["b"]["count"]
        out["b_minus_a"] = nb - na
        out["change_pct"] = r1((nb - na) / na * 100) if na else None
        return out


if __name__ == "__main__":
    for st in ("online", "offline"):
        ex = ToolsR3(fog=st, last_sync="2026-10-22 08:40")
        for name, args in [("fog_search_history", {"time": {"from": "2026-01-01", "to": "2026-02-01"}, "domain": "water", "limit": 2}),
                           ("fog_search_history", {"time": {"preset": "this_year"}, "text": "leak", "limit": 1}),
                           ("fog_analytics", {"analysis": "incident_trend", "time": {"preset": "this_year"}}),
                           ("fog_analytics", {"analysis": "resolve_time", "time": {"preset": "this_year"}, "group_by": "domain"}),
                           ("fog_analytics", {"analysis": "sensor_monthly", "node": "WE-VN04-00", "metric": "temp", "time": {"preset": "this_year"}}),
                           ("search_knowledge", {"query": "drinking water pH limit"}), ("search_knowledge", {"query": "AC service contract"}),
                           ("fog_status", {}), ("get_incident", {"id": "INC-0100"}),
                           ("co_occurring_incidents", {"id": "INC-2600", "window_min": 120}),
                           ("recurring_issues", {"time": {"preset": "last_30d"}}),
                           ("compare_periods", {"period_a": {"preset": "last_month"}, "period_b": {"preset": "this_month"}}),
                           ("count_incidents", {"time": {"preset": "all"}})]:
            print(st, name, json.dumps(ex.run(name, args))[:400])
