"""gen_tools.py: reasoner full run, tool-coverage rows (family gen5_<tool> / gen5_agentic, src_real=false, English, chat_r5 protocol).
Results are executed by the Python twins on the campus world: tools_r3_impl.ToolsR3 (device + fog stores, all 21 chat tools incl. the fog
fallback), gen_chat_v4.SiteTools (real campus site tree + status overlay), twins of the two router-only tools (forecast_crossing,
data_health). Single-tool rows reuse the r3 kind generators (verified phrasing banks, last 2 phrasings of each bank held out) with the r5
system prompt; get_site_tree / nodes_under / forecast_crossing / data_health have their own kinds; agentic rows are 2-4 call chains
(plan on the first call only, ids only from earlier results, ~20% recover from an empty / error / not-found result, finals templated
from results, optional "two lines" / "one sentence" format honoured).
  python3 gen_tools.py [--n-single 240] [--n-agentic 1500] [--seed 2111]  ->  ../data/gen5_tools.jsonl + ../data/gen5_stats.json"""
import argparse
import collections
import datetime as dt
import json
import math
import os
import random
import re
import sys

P = "/mnt/c/Users/hp/Desktop/qidk/proofs/"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, P + "2026-11-20_rsn_big/build")
sys.path.insert(0, P + "2026-11-06_4b_local/tools")
import big_chat as BC  # noqa: E402
import build_rsn as B  # noqa: E402
import gen_chat_r3 as GR  # noqa: E402
import gen_chat_v3 as G  # noqa: E402
import gen_chat_v4 as C  # noqa: E402
import tools_r3_impl as TR  # noqa: E402

OUT = os.path.abspath(os.path.join(HERE, "..", "data"))
NOW = dt.datetime(2026, 10, 22, 12, 0)
SINCE = "2026-06-24"
EXS = {s: TR.ToolsR3(fog=s) for s in ("online", "offline", "timeout")}
SITE_TOOLS = BC.SITE_TOOLS
DN = BC.DOMS
MN = {"co2": "CO2", "temp": "temperature", "rh": "humidity", "pm25": "PM2.5", "pm10": "PM10", "power_kw": "power", "pf": "power factor", "occ": "occupancy"}
FMT_SUF = {"two_lines": [" Answer in two lines.", " Two lines please.", " Keep it to two lines."],
           "one_sentence": [" One sentence only.", " Answer in a single sentence.", " In one sentence please."]}
STATS = collections.Counter()
CO2RX = re.compile(r"(?i)co2[^.0-9:]{0,14}[0-9]+(?:[.][0-9]+)?(?![0-9])(?!s*ppm)")


def co2_bad(r):
    """check_big rule: a CO2 number needs ppm in the final (applied to every row: drop, never filter silently later)"""
    fin = r["messages"][-1]["content"]
    return bool(CO2RX.search(re.sub(r"(?i)co2[^.]*?(building|sensor)[^.]*", "", fin))) and "ppm" not in fin


def gate(r):
    e = BC.check(r)
    if not e and co2_bad(r):
        e = ["co2:ppm"]
    return e


# ---------------------------------------------------------------------------------------------------------- builder
def cap(t):
    return t[:1].upper() + t[1:]


def assemble(parts, fmt):
    ps = [re.sub(r"\s+", " ", p).strip().rstrip(".") for p in parts if p]
    if fmt == "one_sentence":
        return ps[0] + "."
    if fmt == "two_lines":
        return ps[0] + ".\n" + (ps[1] if len(ps) > 1 else ps[0]) + "."
    return ". ".join(ps[:3]) + "."


def pickfmt(R):
    return R.choices([None, "two_lines", "one_sentence"], [86, 7, 7])[0]


def with_fmt(R, q, fmt):
    return q + R.choice(FMT_SUF[fmt]) if fmt else q


class RB2(BC.RB):
    """BC.RB over ToolsR3 (per fog state), the campus site twin with a status overlay, and the router-tool twins"""

    def __init__(s, R, state=None):
        s.R, s.W, s.split = R, BC.world(), "train"
        s.fog = state or R.choices(["online", "offline", "timeout"], [45, 45, 10])[0]
        s.ls = GR.last_sync_for(R) if s.fog == "offline" else None
        EXS["offline"].last_sync = s.ls
        EXS["timeout"].last_sync = (NOW - dt.timedelta(minutes=R.randrange(2, 12))).strftime("%Y-%m-%d %H:%M")
        s.ex = EXS[s.fog]
        s.ex.qid = 0
        s.ST = C.SiteTools(s.W["site"], *C.overlay(R, s.W["site"]))
        s.msgs = [{"role": "system", "content": B.r5_system(GR.system_r3(s.fog, s.ls, SINCE), s.W["site"])}]
        s.k, s.gold, s.res, s.hist, s.q, s.stale = 0, [], [], None, "", None

    def peek(s, name, args):
        q = s.ex.qid
        r = s.ex.run(name, dict(args))
        s.ex.qid = q
        return r

    def call(s, name, args, plan=None):
        try:
            if name in SITE_TOOLS:
                res = s.ST.call(name, dict(args))
            elif name == "forecast_crossing":
                res = twin_forecast(s.ex, args)
            elif name == "data_health":
                res = twin_health(s)
            else:
                res = s.ex.run(name, dict(args))
        except Exception as e:  # malformed call = tool error, as in the app
            res = {"error": "bad call: %s" % str(e)[:100]}
        s.k += 1
        a = {"role": "assistant", "content": "", "tool_calls": [C.tc(s.k, name, args)]}
        if plan and s.k == 1:
            a["reasoning_content"] = plan
        s.msgs += [a, {"role": "tool", "tool_call_id": "call_%d" % s.k, "content": json.dumps(res, ensure_ascii=False)}]
        s.gold.append({"name": name, "args": args})
        s.res.append(res)
        return res

    def fin(s, fam, kind, parts, fmt=None, **kw):
        if fmt == "two_lines" and len([p for p in parts if p]) < 2:
            return None
        text = assemble(parts, fmt)
        if len(text) > 640:
            return None
        s.msgs.append({"role": "assistant", "content": text})
        r = {"id": "x", "family": fam, "tools": "chat_r5", "think": True, "hard": len(s.gold) >= 2, "fog": s.fog, "hinglish": False, "site_id": "iiith",
             "reasoning_type": "none", "hops": 0, "messages": s.msgs, "gold_calls": s.gold, "multi_turn": False, "kind": kind, "src_real": False,
             "last_sync": s.ls, "since": SINCE}
        if fmt:
            r["fmt"] = fmt
        if any("error" in x for x in s.res if isinstance(x, dict)):
            r["allow_error"] = True
        r.update(kw)
        return r


# ---------------------------------------------------------------------------------------------------------- router-tool twins
def _unit(ex, node, metric):
    return ex.dev.cat.get((node, metric), ("", "", ""))[2]


def twin_forecast(ex, args):
    """forecast_crossing as chat_polish.go chatForecast: least squares on the last 2 h of 5-min readings; state eta|already|steady|wrong_way|no_data.
    Go records state/last/slope_per_h; the twin adds `at` (time of the crossing) and `unit` so the model never computes a time itself."""
    node, metric, target = args["node"], args["metric"], float(args["target"])
    if (node, metric) not in ex.dev.cat:
        return {"error": "unknown sensor %s/%s" % (node, metric)}
    rows = ex.dev._readings(node, metric, NOW - dt.timedelta(hours=2), NOW + dt.timedelta(seconds=1))
    unit = _unit(ex, node, metric)
    if len(rows) < 6:
        return {"state": "no_data", "last": 0, "slope_per_h": 0, "unit": unit}
    xs = [(t - rows[0][0]) / 60.0 for t, _ in rows]
    ys = [v for _, v in rows]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    r2 = sxy * sxy / (sxx * syy) if sxx and syy else 0.0
    last, per_h = ys[-1], slope * 60
    rise = target >= last
    hours = 0.0
    if (rise and last >= target) or (not rise and last <= target):
        state = "already"
    elif r2 < 0.2 or abs(per_h) < 1e-6 or (rise and per_h <= 0) or (not rise and per_h >= 0):
        state = "wrong_way" if (r2 >= 0.2 and abs(per_h) > 1e-6) else "steady"
    else:
        hours = (target - last) / per_h
        state = "steady" if hours > 72 else "eta"
    res = {"state": state, "last": round(last, 1), "slope_per_h": round(per_h, 2), "unit": unit}
    if state == "eta":
        res["at"] = (NOW + dt.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
    return res


def twin_health(rb):
    """data_health (chat_polish.go chatNotSending): counts of sensors silent for > stale_after_min or never reported. The twin simulates a
    small outage scenario on the real catalog (0-3 stale, 0-1 missing) and adds the sensor lists (Go records counts only)."""
    cat = sorted(rb.ex.dev.cat)
    R = rb.R
    k = R.choice([0, 0, 1, 1, 2, 3])
    pick = R.sample(cat, k + R.choice([0, 0, 1]))
    stale = [{"node": n, "metric": m, "age_min": R.randrange(35, 600)} for n, m in pick[:k]]
    missing = [{"node": n, "metric": m} for n, m in pick[k:]]
    return {"stale": len(stale), "missing": len(missing), "checked": len(cat), "stale_after_min": 30, "stale_sensors": stale, "missing_sensors": missing}


# ---------------------------------------------------------------------------------------------------------- single-tool kinds (r3 generators)
R3KINDS = {"compare_periods": ["compare_tool"], "sensor_faults": ["faults"], "domain_health": ["health"], "search_knowledge": ["knowledge"],
           "faulty_sensors": ["faulty_list", "faulty_explain"], "recurring_issues": ["recurring"], "fog_status": ["fog_status", "fu_fog_status"],
           "what_if": ["whatif_occ", "whatif_temp", "whatif_ac", "followup_whatif"], "recent_incidents": ["recent", "recent_filtered"],
           "open_incidents": ["open_all", "open_domain"], "get_action_history": ["actions"]}


def r3_rows(tool, n, R, seen):
    g = GR.GenR3(R, EXS, "train", SINCE)
    out, tries, why = [], 0, collections.Counter()
    while len(out) < n and tries < n * 40:
        tries += 1
        kind = R.choice(R3KINDS[tool])
        state = "offline" if kind == "fu_fog_status" else R.choices(["online", "offline", "timeout"], [45, 45, 10])[0]
        ls = GR.last_sync_for(R) if state == "offline" else None
        g.use(state)
        EXS["offline"].last_sync = ls
        EXS["timeout"].last_sync = (NOW - dt.timedelta(minutes=R.randrange(2, 12))).strftime("%Y-%m-%d %H:%M")
        t = getattr(g, "k_" + kind)()
        if not t:
            why["nokind"] += 1
            continue
        t["q"] = G.noisy(R, t["q"])
        sol = g.solve(t)
        if not sol:
            why["nosolve"] += 1
            continue
        key = (G.norm(t["q"]), state, json.dumps([c for rd in t["rounds"] for c in rd], sort_keys=True), json.dumps(t.get("history", [])))
        if key in seen:
            why["dup"] += 1
            continue
        rec = G.build_record(g, t, sol, "train", len(out), kind, [])
        names = [c["name"] for c in rec["gold_calls"]]
        if tool not in names:
            why["tool_absent"] += 1
            continue
        r = {"id": "x", "family": "gen5_" + tool, "tools": "chat_r5", "think": True, "hard": len(names) >= 2, "fog": state, "hinglish": False, "site_id": "iiith",
             "reasoning_type": "none", "hops": 0, "messages": rec["messages"], "gold_calls": rec["gold_calls"], "multi_turn": any(m["role"] == "user" for m in rec["messages"][1:-1]),
             "kind": "r3_" + kind.replace("faulty", "flt"), "src_real": False, "last_sync": ls, "since": SINCE}
        r["messages"][0]["content"] = B.r5_system(GR.system_r3(state, ls, SINCE))
        if rec["messages"][-1]["role"] != "assistant" or rec["messages"][-1].get("tool_calls"):
            r["messages"].append({"role": "assistant", "content": rec["reference_answer"]})
        if r["hard"]:
            r["messages"][next(i for i, m in enumerate(r["messages"]) if m.get("tool_calls"))]["reasoning_content"] = "Call the first tool, read its result, then the next one."
        e = gate(r)
        if e:
            why["check:" + e[0].split(":")[0]] += 1
            continue
        seen.add(key)
        out.append(r)
    STATS.update({"drop:%s:%s" % (tool, k): v for k, v in why.items()})
    return out


# ---------------------------------------------------------------------------------------------------------- custom single kinds
def pnode(rb, nid):
    """how a user names a site node: its unique name, else its id"""
    nme = rb.ST.ix.name(nid)
    return nme if rb.ST.find(nme) == nid and rb.R.random() < 0.6 else nid


def kidnames(items, k=4):
    return C.fmt_list([i["name"] for i in items], k)


def k_tree(R):
    rb = RB2(R)
    ST, ix = rb.ST, rb.ST.ix
    mode = R.choices(["campus", "node", "deep", "missing"], [2, 6, 2, 1])[0]
    fmt = pickfmt(R)
    if mode == "campus":
        qs = ["What is on the campus map?", "Show me the top level of the site tree.", "What buildings and areas does the site map have?", "give me an overview of the campus layout",
              "List the main parts of the campus.", "What does the site map start with?", "Show the campus tree.", "What are the top-level areas on the map?"]
        rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
        r = rb.call("get_site_tree", {})
        bad = [c for c in r["children"] if c["status"] != "normal"]
        parts = ["The campus map has %d top-level items: %s" % (r["children_total"], kidnames(r["children"], 5)),
                 ("Not normal right now: %s" % ", ".join("%s (%s)" % (c["name"], c["status"].replace("_", " ")) for c in bad)) if bad else "All of them are normal right now"]
        return rb.fin("gen5_get_site_tree", "tree_campus", parts, fmt)
    if mode == "missing":
        x = R.choice(["Block 7", "ZZ-%d" % R.randrange(100, 999), "Annex B", "QQ%d" % R.randrange(10, 99), "Hostel 3", "the sky tower"])
        qs = ["What is under %s?" % x, "Show me the tree of %s." % x, "What sensors are in %s?" % x, "open %s on the site map" % x, "what's inside %s" % x, "List what %s contains." % x]
        rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
        r = rb.call("get_site_tree", {"node": x, "depth": 1})
        if r.get("found") is not False:
            return None
        return rb.fin("gen5_get_site_tree", "tree_missing", ["I cannot find %s in the site map on this device" % x, "Name a building, floor or room, or ask for the campus tree and I will list what exists"], fmt)
    cands = [n["id"] for n in rb.W["site"]["nodes"] if n["kind"] in ("building", "floor", "wing", "room", "zone") and ix.children.get(n["id"])]
    nid = R.choice(cands)
    x = pnode(rb, nid)
    depth = 2 if mode == "deep" else 1
    qs = ["What is in %s?" % x, "Show me what is under %s." % x, "list the children of %s" % x, "What does %s contain?" % x, "Give me the layout of %s." % x, "What is inside %s?" % x,
          "Show the site tree for %s." % x, "what's in %s" % x]
    if depth == 2:
        qs = ["Show %s two levels deep." % x, "Give me %s with its sub-parts." % x, "Expand %s one more level." % x, "What is in %s and what is in each of those?" % x,
              "Layout of %s, two levels." % x, "show %s and the next level down" % x]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    args = {"node": x} if depth == 1 and R.random() < 0.5 else {"node": x, "depth": depth}
    r = rb.call("get_site_tree", args)
    if r.get("found") is False or not r.get("children"):
        return None
    ch = r["children"]
    bad = [c for c in ch if c["status"] != "normal"]
    parts = ["%s (%s) has %d children: %s" % (r["name"], r["kind"], r["children_total"], kidnames(ch, 4))]
    if depth == 2:
        sub = next((c for c in ch if c.get("children")), None)
        if sub:
            parts.append("Under %s: %s" % (sub["name"], kidnames(sub["children"], 4)))
    parts.append(("Not normal: %s" % ", ".join("%s (%s)" % (c["name"], c["status"].replace("_", " ")) for c in bad[:3])) if bad else "All are normal right now")
    return rb.fin("gen5_get_site_tree", "tree_%s" % ("deep" if depth == 2 else "node"), parts, fmt)


def k_nodes(R):
    rb = RB2(R)
    ST, ix = rb.ST, rb.ST.ix
    fmt = pickfmt(R)
    kind = R.choice(["sensor", "sensor", "room", "equipment", "floor", None])
    status = R.choice([None, "critical", "warning", "data_issue", "normal"])
    metric = R.choice(["co2", "temp", "rh", "pm25", "power_kw", "occ", None]) if kind == "sensor" else None
    pool = [n["id"] for n in rb.W["site"]["nodes"] if n["kind"] in ("building", "floor", "wing") and ix.children.get(n["id"])]
    if status and status != "normal" and R.random() < 0.5:   # nodes that really hold a flagged sensor
        hot = [s for s in ST.status if ST.status[s] == status]
        if hot:
            pool = [x for x in pool if any(h in ix.sensors_under(x) for h in hot)] or pool
    nid = R.choice(pool)
    x = pnode(rb, nid)
    kw = {"critical": "critical", "warning": "in warning", "data_issue": "with a data problem", "normal": "normal"}
    kn = {"sensor": "sensors", "room": "rooms", "equipment": "equipment", "floor": "floors", None: "nodes"}[kind]
    mw = (MN.get(metric, metric) + " ") if metric else ""
    qs = ["Which %s are %s under %s?" % (kn, kw.get(status, "there"), x) if status else "List the %s under %s." % (kn, x),
          "Any %s %s on %s?" % (kn, kw[status], x) if status else "What %s does %s have?" % (kn, x),
          "Show %s %s in %s." % (kn, kw[status] if status else "", x), "%s under %s%s" % (cap(kn), x, (": " + kw[status] + " ones") if status else ""),
          "Find the %s%s in %s." % (mw, kn, x), "Check %s %s %s." % (kn, kw[status] if status else "inside", x),
          "How many %s%s are under %s?" % (mw, kn, x), "%s: %s%s?" % (x, mw, kn)]
    rb.ask(with_fmt(R, re.sub(r"\s+", " ", BC.pick(R, qs, "train")).replace(" ?", "?").replace(" .", "."), fmt))
    args = {"node": x}
    for k, v in (("kind", kind), ("metric", metric), ("status", status)):
        if v:
            args[k] = v
    if len(args) == 1:
        args["kind"] = "room"
    r = rb.call("nodes_under", args)
    if r.get("found") is False:
        return None
    it = r["items"]
    desc = " ".join(w for w in ((args.get("status") or "").replace("_", " "), MN.get(args.get("metric"), args.get("metric") or ""), (args.get("kind") or "node") + "s") if w)
    if r["total"] == 0:
        parts = ["No %s under %s right now" % (desc, r["name"]), "I looked through everything below it in the site map"]
    else:
        parts = ["%s %s under %s: %s" % (r["total"], desc if r["total"] != 1 else desc.rstrip("s"), r["name"], kidnames(it, 4))]
        if r["total"] > len(it):
            parts.append("Only the first %d are listed" % len(it))
        else:
            bad = [i for i in it if i["status"] != "normal"]
            parts.append(("Not normal: " + ", ".join("%s (%s)" % (i["name"], i["status"].replace("_", " ")) for i in bad[:3])) if bad else "None of them has an open problem")
    return rb.fin("gen5_nodes_under", "nodes_" + ("empty" if r["total"] == 0 else "list"), parts, fmt)


def nice_up(v, step):
    return math.ceil(v / step) * step


def k_forecast(R):
    rb = RB2(R)
    ex = rb.ex
    m = R.choices(["co2", "pm25", "temp", "rh", "power_kw"], [4, 2, 2, 1, 1])[0]
    node = R.choice([k for k in sorted(ex.dev.cat) if k[1] == m])[0]
    rows = ex.dev._readings(node, m, NOW - dt.timedelta(minutes=30), NOW + dt.timedelta(seconds=1))
    if not rows:
        return None
    last = rows[-1][1]
    step = {"co2": 100, "pm25": 10, "temp": 1, "rh": 5, "power_kw": 5}[m]
    fall = R.random() < 0.18
    target = nice_up(last * 1.05 + step, step) if not fall else max(step, math.floor(last * 0.9 / step) * step)
    if R.random() < 0.15:
        target = max(step, math.floor(last / step) * step)  # already past
    target = int(target)
    nm = MN[m]
    fmt = pickfmt(R)
    if fall and target < last:
        qs = ["When will %s at %s drop below %s?" % (nm, node, target), "How long until %s on %s falls under %s?" % (nm, node, target), "Will %s at %s get below %s soon?" % (nm, node, target),
              "estimate when %s %s goes under %s" % (node, nm, target), "At this rate, when is %s at %s below %s?" % (nm, node, target), "When does %s on %s fall to %s?" % (nm, node, target)]
    else:
        qs = ["When will %s at %s cross %s?" % (nm, node, target), "How long until %s on %s reaches %s?" % (nm, node, target), "Will %s at %s go above %s today?" % (nm, node, target),
              "estimate when %s %s hits %s" % (node, nm, target), "At this rate, when does %s at %s pass %s?" % (nm, node, target), "When will %s on %s exceed %s?" % (nm, node, target)]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    r = rb.call("forecast_crossing", {"node": node, "metric": m, "target": target})
    if "error" in r:
        return None
    st, u = r["state"], r["unit"]
    cav = "This is a straight line through the last couple of hours of readings, not a forecast"
    if st == "eta":
        parts = ["%s at %s is %s %s now, moving about %s %s per hour, so it would reach %s around %s" % (nm, node, r["last"], u, abs(r["slope_per_h"]), u, target, r["at"][11:]), cav]
    elif st == "already":
        parts = ["%s at %s is already at %s %s, past %s" % (nm, node, r["last"], u, target), "There is no crossing to wait for"]
    elif st == "wrong_way":
        parts = ["%s at %s is %s %s now and moving away from %s" % (nm, node, r["last"], u, target), cav]
    elif st == "steady":
        parts = ["%s at %s is %s %s now and shows no clear trend towards %s in the last couple of hours" % (nm, node, r["last"], u, target), cav]
    else:
        parts = ["There are not enough readings from %s in the last couple of hours to estimate a crossing" % node, "Try again once it has reported for a while"]
    return rb.fin("gen5_forecast_crossing", "forecast_" + st, parts, fmt)


def k_health(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    qs = ["Which sensors are not sending data right now?", "Is any sensor silent?", "Are all sensors reporting?", "Any sensor offline or stale?", "Which meters stopped reporting?",
          "Check the data health of the sensors.", "Are there sensors that have not sent anything lately?", "Is every sensor sending data?", "Which sensors have gone quiet?", "Did any sensor stop reporting?", "Are all the meters still sending readings?", "Is any device silent at the moment?", "sensor data health, anything missing?", "Which sensors are overdue for data?", "Has any sensor lost its link?", "Any gaps in reporting right now?", "Are there silent sensors on campus?", "Check whether all sensors are alive and reporting.", "List sensors that are not reporting."]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    r = rb.call("data_health", {})
    st, ms = r["stale"], r["missing"]
    if not st and not ms:
        parts = ["Every one of the %d sensors checked has sent data within the last %d minutes" % (r["checked"], r["stale_after_min"]), "No sensor looks silent"]
    else:
        parts = []
        if st:
            lst = ", ".join("%s %s (last data %d min ago)" % (x["node"], x["metric"], x["age_min"]) for x in r["stale_sensors"][:3])
            parts.append("%d sensor%s stopped sending new data: %s" % (st, " has" if st == 1 else "s have", lst))
        if ms:
            parts.append("%d sensor%s never reported since this device started: %s" % (ms, " has" if ms == 1 else "s have", ", ".join("%s %s" % (x["node"], x["metric"]) for x in r["missing_sensors"][:3])))
        parts.append("Their last values may be out of date")
    return rb.fin("gen5_data_health", "health_" + ("ok" if not st and not ms else "silent"), parts, fmt)


def single_custom(tool, fn, n, R, seen):
    out, tries, why = [], 0, collections.Counter()
    while len(out) < n and tries < n * 30:
        tries += 1
        r = fn(R)
        if r is None:
            why["nokind"] += 1
            continue
        key = (next(m["content"] for m in r["messages"] if m["role"] == "user"), r["fog"], json.dumps(r["gold_calls"], sort_keys=True), r["messages"][-1]["content"])
        if key in seen:
            why["dup"] += 1
            continue
        e = gate(r)
        if e:
            why["check:" + e[0].split(":")[0]] += 1
            continue
        seen.add(key)
        out.append(r)
    STATS.update({"drop:%s:%s" % (tool, k): v for k, v in why.items()})
    return out


# ---------------------------------------------------------------------------------------------------------- agentic chains
PLANS = {
    "drill": ["Find the incident first, then open its report, then check what was done on that sensor.", "List the matching incidents, open the newest one, then read the action history."],
    "health": ["Check which domain is worst, then open its top incident.", "Read the domain health first, then the incident that needs attention most."],
    "recur": ["Find the repeat offender, read its recent history, then what was done before.", "List the recurring sensors, check the worst one's readings, then its past actions."],
    "compare": ["Compare the two periods, then list the critical incidents of the busier one.", "Count both periods first, then look into the worse one."],
    "tree": ["Open the building, pick a part of it, then list the flagged sensors there.", "Read the site tree first, then narrow to one part and check its status."],
    "faulty": ["List the faulty sensors, then read the readings of the first one.", "Check which sensors are faulty, then look at one of them in detail."],
    "know": ["Look up the limits first, then read the current peak.", "Search the knowledge base, then compare with the latest reading."],
    "whatif": ["Run the estimate, then read the current level of the most affected sensor.", "Estimate the change first, then check that sensor now."],
    "fog": ["Check the fog link first, then search the older incidents.", "Read the fog status, then ask for the month."],
    "cooccur": ["Find the latest incident, read its report, then what happened around it.", "List the recent incidents, open one, then check the incidents nearby in time."],
    "open": ["See what is open, open the most urgent incident, then the past actions on its sensor.", "Read the open incidents, then the top one, then what was done before."],
    "faults": ["List the faulty sensors, open the latest incident on the worst one, then its action history.", "Find the sensors with faults, then the newest incident and maintenance on the worst one."],
    "recover": ["That may not match anything, so I will look up what exists and retry.", "If the first lookup fails, I will check the list and try again with a valid name."],
}


def plan(R, k):
    return R.choice(PLANS[k])


def outcomes_txt(ah):
    oc = ah.get("outcome_counts") or {}
    if not oc:
        return None
    return ", ".join("%s %d" % (k.replace("_", " "), v) for k, v in sorted(oc.items(), key=lambda kv: (-kv[1], kv[0]))[:3])


def maint_txt(ah):
    mc = ah.get("maintenance_counts") or {}
    return ", ".join("%s %d" % (k, v) for k, v in sorted(mc.items(), key=lambda kv: (-kv[1], kv[0]))[:2]) if mc else None


def sevw(s):
    return (s or "").replace("_", " ")


def ttl(i):
    return i["title"].split(":")[0]


def A_drill(R, widen=False):
    d = R.choice(["air_quality", "water", "power", "hvac"])
    sv = "critical" if widen else R.choice([None, "critical", "warning"])
    rb = RB2(R)
    fmt = pickfmt(R)
    dn = DN[d]
    sw = (sv + " ") if sv else ""
    qs = ["What was the latest %s%s incident and what was done about it?" % (sw, dn), "Tell me about the newest %s%s incident, and what actions were taken on that sensor." % (sw, dn),
          "Latest %s%s incident: what caused it and did anyone act on that sensor before?" % (sw, dn), "Find the last %s%s alert and its past actions." % (sw, dn),
          "Why did the last %s%s alert fire, and what has been done on that sensor?" % (sw, dn), "What is the most recent %s%s event, its cause and the history of fixes?" % (sw, dn),
          "newest %s%s incident, cause and previous actions" % (sw, dn), "Explain the latest %s%s problem and say what maintenance that sensor had." % (sw, dn)]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    pre = None
    flt = {"domain": d}
    if sv:
        flt["severity"] = [sv]
    if widen:
        pr = R.choice(["today", "yesterday"])
        if rb.peek("find_incidents", dict(time={"preset": pr}, limit=3, **flt)).get("items"):
            return None
        rb.call("find_incidents", dict(time={"preset": pr}, limit=3, **flt), plan=plan(R, "recover"))
        pre = "No %s%s incident %s, so I looked back 30 days" % (sw, dn, BC.PRESETS[pr])
        fi = rb.call("find_incidents", dict(time={"preset": "last_30d"}, limit=3, **flt))
    else:
        fi = rb.call("find_incidents", dict(time={"preset": "last_30d"}, limit=3, **flt), plan=plan(R, "drill"))
    if not fi.get("items"):
        return None
    inc = fi["items"][0]
    g = rb.call("get_incident", {"id": inc["id"]})
    if not g.get("sensors") or not g.get("root_cause"):
        return None
    s0 = g["sensors"][0]
    ah = rb.call("get_action_history", {"node": s0["node"], "metric": s0["metric"], "time": {"preset": "last_30d"}})
    oc, mt = outcomes_txt(ah), maint_txt(ah)
    state = "closed as %s" % g["outcome"].replace("_", " ") if g.get("outcome") else "still %s" % g.get("workflow", "open").replace("_", " ")
    p0 = "[%s] %s is %s and %s: %s" % (inc["id"], ttl(g), sevw(g["severity"]), state, g["root_cause"])
    if pre:
        p0 = pre + ": " + p0
    parts = [p0, ("On %s %s in the past month: %s" % (s0["node"], s0["metric"], oc + ((", maintenance " + mt) if mt else ""))) if oc else "No past actions are recorded on %s %s in the past month" % (s0["node"], s0["metric"])]
    return rb.fin("gen5_agentic", "drill_widen" if widen else "drill", parts, fmt, recovery=widen)


RANKS = {"critical": 3, "sensor_fault": 2, "warning": 1, "normal": 0}


def B_health(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    qs = ["Which domain is in the worst shape and what is its top open problem?", "What is the most urgent problem on campus right now, and which domain is it in?", "Find the unhealthiest domain and tell me its worst open incident.",
          "Where is it worst right now? Give me the domain and the incident to look at first.", "Which area needs attention first, and why?", "Worst domain today and its main open incident?",
          "Check the health of all domains, then explain the top issue of the worst one.", "what should I look at first on campus?"]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    h = rb.call("domain_health", {}, plan=plan(R, "health"))
    ds = [x for x in h.get("domains", []) if x.get("open_ids")]
    if not ds:
        return None
    ds.sort(key=lambda x: (-RANKS.get(x["worst_status"], 0), -x["open_incidents"], x["domain"]))
    top = ds[0]
    g = rb.call("get_incident", {"id": top["open_ids"][0]})
    if not g.get("root_cause"):
        return None
    parts = ["%s is the worst domain: status %s with %d open incidents (%d need a decision)" % (top["domain"].replace("_", " "), sevw(top["worst_status"]), top["open_incidents"], top["needs_decision"]),
             "Start with [%s] %s (%s): %s" % (g["id"], ttl(g), sevw(g["severity"]), g["root_cause"])]
    if R.random() < 0.45:
        co = rb.call("co_occurring_incidents", {"id": g["id"], "window_min": 120})
        if co.get("total"):
            it = co["items"][0]
            parts.append("It overlaps [%s] (%s) in time, which alone does not show one caused the other" % (it["id"], "/".join(it["domains"])))
        else:
            parts.append("Nothing else was flagged within 120 minutes of it")
    return rb.fin("gen5_agentic", "health_top", parts, fmt)


def C_recur(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    d = R.choice([None, None, "air_quality", "water", "power"])
    dw = (DN[d] + " ") if d else ""
    qs = ["Which %ssensor keeps alarming, how are its readings this week, and what was done before?" % dw, "Find the %srepeat offender, show its last 7 days and the past actions." % dw,
          "What %ssensor has the most repeated incidents lately? Is it getting worse and has it been repaired?" % dw, "Worst recurring %ssensor: readings over the week and maintenance history?" % dw,
          "Who is the repeat offender among %ssensors this month, and what happened to it before?" % dw, "Which %ssensor keeps coming back? Check its week and its action history." % dw,
          "%sproblem sensor of the month: how does it look this week, and what fixes were tried?" % cap(dw), "Top recurring %ssensor, its recent trend and what maintenance it had." % dw]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    args = {"time": {"preset": "last_30d"}, "min_count": 3}
    if d:
        args["domain"] = d
    rr = rb.call("recurring_issues", args, plan=plan(R, "recur"))
    if not rr.get("items"):
        return None
    it = rr["items"][0]
    node, metric = it["sensor"].split(" ", 1)
    hs = rb.call("get_sensor_history", {"node": node, "metric": metric, "time": {"preset": "last_7d"}})
    if "summary" not in hs:
        return None
    ah = rb.call("get_action_history", {"node": node, "metric": metric, "time": {"preset": "last_30d"}})
    last, u = BC.hnum(BC.H(hs, 5), "last")
    mx, _ = BC.hnum(BC.H(hs, 4), "max")
    tr, tu = BC.hnum(BC.H(hs, 6), "trend")
    oc, mt = outcomes_txt(ah), maint_txt(ah)
    parts = ["%s had %d incidents in the past month (mostly %s), the most of any %ssensor" % (it["sensor"], it["count"], (it["top_label"] or "unlabelled").replace("_", " "), dw),
             "Over the past week it is at %s %s now, peak %s %s, trend %s %s" % (last, u, mx, u, tr, tu),
             ("Past outcomes on it: %s%s" % (oc, (", maintenance " + mt) if mt else "")) if oc else "No past actions are recorded on it"]
    return rb.fin("gen5_agentic", "recurring_history", parts, fmt)


def D_compare(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    pairs = [("last_month", "this_month", "last month", "this month"), ("yesterday", "today", "yesterday", "today"), ("last_30d", "last_7d", "the last 30 days", "the last 7 days"),
             ("last_month", "last_7d", "last month", "the last 7 days")]
    pa, pb, wa, wb = R.choice(pairs)
    d = R.choice([None, None, "air_quality", "water", "power", "hvac"])
    dw = (DN[d] + " ") if d else ""
    qs = ["Compare %sincidents %s vs %s, then show me the worst critical one of the busier period." % (dw, wa, wb), "Were there more %sincidents %s or %s? Pick the busier one and name its top critical incident." % (dw, wa, wb),
          "%s vs %s for %sincidents: which was worse, and what was the main critical case there?" % (cap(wa), wb, dw), "Which had more %sincidents, %s or %s? Show the critical one that stands out." % (dw, wa, wb),
          "Check %sincident counts for %s and %s and explain the top critical incident of the higher one." % (dw, wa, wb), "Busier period for %sincidents: %s or %s? What was its main critical issue?" % (dw, wa, wb),
          "compare %sincidents %s and %s and dig into the critical one in the worse period" % (dw, wa, wb), "Did %sincidents rise from %s to %s? Show a critical example from the busier one." % (dw, wa, wb)]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    args = {"period_a": {"preset": pa}, "period_b": {"preset": pb}}
    if d:
        args["domain"] = d
    c = rb.call("compare_periods", args, plan=plan(R, "compare"))
    if "a" not in c:
        return None
    na, nb = c["a"]["count"], c["b"]["count"]
    if na == nb:
        return None
    big, bw, sw_ = (pb, wb, wa) if nb > na else (pa, wa, wb)
    fa = dict(time={"preset": big}, severity=["critical"], limit=3)
    if d:
        fa["domain"] = d
    fi = rb.call("find_incidents", fa)
    if not fi.get("items"):
        return None
    g = rb.call("get_incident", {"id": fi["items"][0]["id"]})
    if not g.get("root_cause"):
        return None
    parts = ["%s had more %sincidents: %d against %d for %s" % (cap(bw), dw, max(na, nb), min(na, nb), sw_),
             "Its newest critical one is [%s] %s: %s" % (g["id"], ttl(g), g["root_cause"])]
    return rb.fin("gen5_agentic", "compare_find", parts, fmt)


def E_tree(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    b = R.choice([n["id"] for n in rb.W["site"]["nodes"] if n["kind"] == "building"])
    x = pnode(rb, b)
    st = R.choice(["critical", "warning", "data_issue"])
    kw = {"critical": "critical", "warning": "in warning", "data_issue": "with a data problem"}[st]
    qs = ["What is in %s, and are any of its sensors %s?" % (x, kw), "Open %s and check whether any sensor there is %s." % (x, kw), "Look at %s: what parts does it have, and which sensors are %s?" % (x, kw),
          "Show me %s and tell me which of its sensors are %s." % (x, kw), "Any sensors %s in %s? Start from its layout." % (kw, x), "%s: layout first, then the sensors %s." % (cap(x), kw),
          "Walk through %s and find the sensors that are %s." % (x, kw), "Check %s for sensors %s, I do not know its layout." % (x, kw)]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    t = rb.call("get_site_tree", {"node": x}, plan=plan(R, "tree"))
    if t.get("found") is False or not t.get("children"):
        return None
    nu = rb.call("nodes_under", {"node": t["node"], "kind": "sensor", "status": st})
    parts = ["%s has %d parts: %s" % (t["name"], t["children_total"], kidnames(t["children"], 4))]
    if nu["total"] == 0:
        parts.append("No sensor under it is %s right now" % kw)
        return rb.fin("gen5_agentic", "tree_none", parts, fmt)
    first = nu["items"][0]
    ss = rb.call("site_status", {"node": first["id"]})
    oi = ss.get("open_incidents") or []
    parts.append("%d sensors under it are %s, for example %s" % (nu["total"], kw, first["id"]))
    parts.append(("Its open incident is [%s] %s" % (oi[0]["id"], ttl(oi[0]))) if oi else "It has no open incident yet, only the status flag")
    return rb.fin("gen5_agentic", "tree_status", parts, fmt)


def F_faulty(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    qs = ["Which sensor is faulty right now and what do its last 24 hours look like?", "Find a broken sensor and show me its readings from the last day.", "Is any sensor flagged faulty? Check how its readings look.",
          "Show me a faulty sensor and its recent data, and tell me if it was serviced.", "What sensor looks broken now? Give me its last day of readings.", "List the sensors with problems and check the first one.",
          "Are there faulty sensors? Look at one of them in detail.", "A sensor seems faulty: which one, and what do the readings say?"]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    fs = rb.call("faulty_sensors", {"time": {"preset": "last_30d"}}, plan=plan(R, "faulty"))
    live, ai = fs.get("live") or [], fs.get("ai_diagnosed") or []
    if live:
        s0, why = live[0], "flagged faulty live since %s" % live[0]["since"]
    elif ai:
        s0, why = ai[0], "diagnosed as a %s fault by the AI (last %s)" % (ai[0].get("fault_kind", "sensor"), ai[0]["last"])
    else:
        return None
    hs = rb.call("get_sensor_history", {"node": s0["node"], "metric": s0["metric"], "time": {"preset": "last_24h"}})
    if "summary" not in hs:
        return None
    mn, u = BC.hnum(BC.H(hs, 3), "min")
    mx, _ = BC.hnum(BC.H(hs, 4), "max")
    last, _ = BC.hnum(BC.H(hs, 5), "last")
    parts = ["%s %s is %s" % (s0["node"], s0["metric"], why), "Over the past day it ranged from %s to %s %s and the last value is %s %s" % (mn, mx, u, last, u)]
    if R.random() < 0.55:
        mt = maint_txt(rb.call("get_action_history", {"node": s0["node"], "metric": s0["metric"], "time": {"preset": "last_30d"}}))
        parts.append(("Maintenance on it in the past month: %s" % mt) if mt else "No maintenance is recorded on it in the past month")
    return rb.fin("gen5_agentic", "flt_history", parts, fmt)


KB = [("Is the highest CO2 today above the campus alarm limit?", "campus alarm limits CO2 indoor air", "co2"),
      ("Is the worst PM2.5 reading today over the campus limit?", "campus alarm limits PM2.5", "pm25"),
      ("Is any room hotter than the campus warning limit today?", "campus alarm limits indoor temperature", "temp"),
      ("How does the peak humidity today compare with the campus limit?", "campus alarm limits indoor humidity", "rh"),
      ("Is the top CO2 reading today a problem by the ventilation guidance?", "indoor CO2 ventilation indicator ppm", "co2"),
      ("How does the highest PM2.5 today compare with the national standard?", "NAAQS PM2.5", "pm25")]


def G_know(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    q0, query, m = R.choice(KB)
    rb.ask(with_fmt(R, R.choice(["", "Quick check: ", "Please check: ", "Operator question: "]) + q0, fmt))
    k = rb.call("search_knowledge", {"query": query, "k": 3}, plan=plan(R, "know"))
    r = rb.call("rank_readings", {"metric": m, "time": {"preset": "today"}, "limit": 1})
    if not r.get("items"):
        return None
    it = r["items"][0]
    p0 = "The highest %s today is %s %s at %s (status %s)" % (MN[m], it["value"], it["unit"], it["location"], it["status"])
    ps = k.get("passages") or []
    if ps and k.get("available", True):
        s1 = re.split(r"(?<=[a-z\)])\. ", ps[0]["text"])[0].rstrip(".")
        if "." in s1 or len(s1) > 260:
            return None
        parts = [p0, "Per %s (%s): %s" % (ps[0]["title"], ps[0]["source"], s1)]
    else:
        down = "the fog server is unreachable" if k.get("source") == "device_fallback" else "the knowledge base has nothing on it"
        parts = [p0, "I could not look up the limit document (%s), so I cannot say what the official limit is" % down]
    return rb.fin("gen5_agentic", "know_levels", parts, fmt)


def H_whatif(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    b = R.choice(["KH", "VN", "BK"])
    pct = R.choice([-50, -30, -20, 20, 30, 50])
    drv = R.choice([("occ", "occupancy"), ("ac_units_on", "AC use")])
    sg = "+" if pct > 0 else "-"
    ap = abs(pct)
    qs = ["What if %s%d%% %s in %s? Which sensor reacts most and where is it now?" % (sg, ap, drv[1], b), "Estimate %s%d%% %s in %s and check the most affected sensor's current level." % (sg, ap, drv[1], b),
          "Suppose %s in %s changes by %s%d%%: what moves most, and how is it now?" % (drv[1], b, sg, ap), "How would a %d%% %s in %s in %s change things? Also give the live value of the most affected sensor." % (ap, "rise" if pct > 0 else "drop", drv[1], b),
          "%s %s%d%% in %s: biggest effect and its current reading?" % (cap(drv[1]), sg, ap, b), "Run a what-if for %s %s%d%% at %s and tell me the live level of the top-affected sensor." % (drv[1], sg, ap, b),
          "what happens if %s %s%d%% in %s, and what is the top-affected sensor reading right now" % (drv[1], sg, ap, b), "Model %s %s%d%% for %s, then show where that sensor stands today." % (drv[1], sg, ap, b)]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    w = rb.call("what_if", {"driver": drv[0], "change_pct": pct, "location": b}, plan=plan(R, "whatif"))
    if not w.get("estimates"):
        return None
    e = w["estimates"][0]
    cl = rb.call("current_levels", {"metric": e["metric"], "location": e["node"]})
    its = cl.get("items") or []
    if not its:
        return None
    c0 = its[0]
    parts = ["If %s at %s changed by %s%d%%, %s at %s would go from %s to about %s %s" % (drv[1], b, sg, ap, e["metric"], e["node"], e["now"], e["after"], e["unit"]),
             "Its live reading is %s %s with status %s" % (c0["last"], c0["unit"], c0["status"]),
             "This is an association fitted on %d hours of history (r2 %s), not a controlled test" % (e["hours"], e["r2"])]
    return rb.fin("gen5_agentic", "whatif_levels", parts, fmt)


def I_fog(R):
    rb = RB2(R, state=R.choice(["online", "offline", "online", "offline", "timeout"]))
    fmt = pickfmt(R)
    mo = R.choice(["2026-06", "2026-07", "2026-08", "2026-09", "2026-05"])
    d = R.choice(["power", "air_quality", "water", "hvac"])
    a, b = BC._month(mo)
    mname = {"05": "May", "06": "June", "07": "July", "08": "August", "09": "September"}[mo[5:]]
    qs = ["Is the fog reachable, and what %s incidents did we have in %s?" % (DN[d], mname), "Check the fog link, then list the %s incidents from %s." % (DN[d], mname),
          "Can you reach the fog? Either way, tell me what happened with %s in %s." % (DN[d], mname), "Fog status first, then the %s history for %s." % (DN[d], mname),
          "Is the fog up? I need the %s incidents of %s either way." % (DN[d], mname), "Are we online? And which %s incidents happened in %s?" % (DN[d], mname),
          "Tell me the fog connection state and the %s incidents in %s." % (DN[d], mname), "fog ok? %s incidents %s please" % (DN[d], mname)]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    fs = rb.call("fog_status", {}, plan=plan(R, "fog"))
    fh = rb.call("fog_search_history", {"time": {"from": a, "to": b}, "domain": d, "limit": 5})
    if "error" in fh:
        return None
    on = fs.get("fog") == "reachable"
    p0 = "The fog server is %s (last sync %s)" % ("reachable" if on else "unreachable", fs.get("last_sync") or "never")
    if not fh.get("items"):
        parts = [p0, "There are no %s incidents for %s%s" % (DN[d], mname, "" if on else " in the device store, and older history is not available while the fog is down")]
    else:
        it = fh["items"][0]
        parts = [p0, "%s: %d %s incidents in %s, the newest is [%s] %s" % ("From the fog" if on else "From the device store", fh["total"], DN[d], mname, it["id"], ttl(it))]
        cov = fh.get("coverage") or {}
        if not on and cov.get("from") and not cov.get("complete", True):
            parts.append("Full records on the board only go back to %s, so older ones may be incomplete" % cov["from"][:10])
    return rb.fin("gen5_agentic", "fog_search", parts, fmt)


def J_cooccur(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    d = R.choice([None, "power", "hvac", "air_quality"])
    dw = (DN[d] + " ") if d else ""
    qs = ["Take the latest %sincident: what caused it, and did anything else happen around it?" % dw, "Newest %sincident, its cause, and the incidents nearby in time?" % dw,
          "What is the most recent %sincident and was it linked to anything else?" % dw, "Open the latest %sincident and check what overlapped with it." % dw,
          "Explain the last %sincident and any events close to it in other domains." % dw, "latest %sincident: cause plus whatever else fired around it" % dw,
          "Find the last %sincident, tell me the cause and if other incidents happened around the same time." % dw, "What happened around the newest %sincident, and why did it fire?" % dw]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    args = {"limit": 3}
    if d:
        args["domain"] = d
    ri = rb.call("recent_incidents", args, plan=plan(R, "cooccur"))
    if not ri.get("items"):
        return None
    iid = ri["items"][0]["id"]
    g = rb.call("get_incident", {"id": iid})
    if not g.get("root_cause"):
        return None
    co = rb.call("co_occurring_incidents", {"id": iid, "window_min": 120})
    if co.get("error"):
        return None
    p0 = "[%s] %s is %s: %s" % (iid, ttl(g), sevw(g["severity"]), g["root_cause"])
    if co["total"] == 0:
        parts = [p0, "Nothing else was flagged within 120 minutes of it"]
    else:
        parts = [p0, "Within 120 minutes the device also logged %s" % " and ".join("[%s] (%s)" % (i["id"], "/".join(i["domains"])) for i in co["items"][:2]), "That timing alone does not show one caused the other"]
    return rb.fin("gen5_agentic", "cooccur_chain", parts, fmt)


def L_open(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    d = R.choice([None, "air_quality", "water", "power", "hvac"])
    dw = (DN[d] + " ") if d else ""
    qs = ["What %sincidents still need a decision, and what is the most urgent one about?" % dw, "Open %sincidents: take the top one, explain it and tell me what was done on that sensor before." % dw,
          "What is waiting for me in %s, and what should I look at first?" % (DN[d] if d else "all domains"), "Give me the top pending %sincident with its cause and past actions." % dw,
          "Pending %sincidents: how many, and what is the first one?" % dw, "What is open on %s? Detail the most urgent and its history of fixes." % (DN[d] if d else "campus"),
          "Show what needs my decision in %s and dig into the top item." % (DN[d] if d else "the system"), "most urgent open %sincident and what maintenance that sensor had" % dw]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    o = rb.call("open_incidents", {"domain": d} if d else {}, plan=plan(R, "open"))
    tp = o.get("top_pending") or []
    if not tp:
        return None
    g = rb.call("get_incident", {"id": tp[0]["id"]})
    if not g.get("sensors") or not g.get("root_cause"):
        return None
    s0 = g["sensors"][0]
    oc = outcomes_txt(rb.call("get_action_history", {"node": s0["node"], "metric": s0["metric"], "time": {"preset": "last_30d"}}))
    parts = ["%d %sincidents wait for a decision; the most urgent is [%s] %s (%s)" % (o["total_pending_review"], dw, g["id"], ttl(g), sevw(g["severity"])),
             "Cause: %s" % g["root_cause"], ("Earlier on that sensor: %s" % oc) if oc else "No earlier actions are recorded on that sensor in the past month"]
    return rb.fin("gen5_agentic", "open_detail", parts, fmt)


def M_faults(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    qs = ["Which sensors had AI-diagnosed faults this month, and what happened to the worst one?", "How many sensors were diagnosed faulty in the past month? Take the worst, show its latest incident and its repairs.",
          "Count the faulty sensors of the month and look into the most affected one.", "Sensors with faults lately: worst offender, its newest incident and maintenance?",
          "List the faults of the last month and explain the latest incident of the worst sensor.", "Which sensor is faulty most often this month, and was it repaired?",
          "faulty sensors this month and what we did about the worst", "Who has the most fault incidents in 30 days? Show the latest and what was fixed."]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    sf = rb.call("sensor_faults", {"time": {"preset": "last_30d"}, "basis": "ai"}, plan=plan(R, "faults"))
    ss = sf.get("sensors") or []
    if not ss or not ss[0].get("incidents"):
        return None
    s0 = ss[0]
    g = rb.call("get_incident", {"id": s0["incidents"][-1]})
    if not g.get("root_cause"):
        return None
    ah = rb.call("get_action_history", {"node": s0["node"], "metric": s0["metric"], "time": {"preset": "last_30d"}})
    mt = maint_txt(ah) or outcomes_txt(ah)
    parts = ["%d sensors had AI-diagnosed faults in the past month; the worst is %s %s with %d incidents" % (sf["count"], s0["node"], s0["metric"], s0["incident_count"]),
             "Its latest is [%s] %s: %s" % (g["id"], ttl(g), g["root_cause"]),
             ("Recorded on it: %s" % mt) if mt else "No repairs or actions are recorded on it in the past month"]
    return rb.fin("gen5_agentic", "faults_worst", parts, fmt)


# ------------------------------------------------------------ recoveries
def N_badid(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    bad = "INC-%d" % R.choice([R.randrange(9000, 9999), R.randrange(8000, 8999), R.randrange(30000, 39999)])
    qs = ["Show me %s." % bad, "What happened in %s, and what is the latest incident anyway?" % bad, "Summarise %s for me." % bad, "details of %s" % bad, "Who handled %s?" % bad,
          "Tell me about %s." % bad, "What was the cause of %s?" % bad, "Open %s and explain it." % bad]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    e = rb.call("get_incident", {"id": bad}, plan=plan(R, "recover"))
    if "error" not in e:
        return None
    ri = rb.call("recent_incidents", {"limit": 3})
    if not ri.get("items"):
        return None
    g = rb.call("get_incident", {"id": ri["items"][0]["id"]})
    if "error" in g:
        return None
    parts = ["%s is not on this device: there is no incident with that id" % bad, "The latest one is [%s] %s (%s): %s" % (g["id"], ttl(g), sevw(g["severity"]), g.get("root_cause") or "no root cause is written yet")]
    return rb.fin("gen5_agentic", "recover_badid", parts, fmt, recovery=True)


def O_badnode(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    m = R.choice(["co2", "temp", "pm25", "rh"])
    node = R.choice([k for k in sorted(rb.ex.dev.cat) if k[1] == m and k[0].startswith("SR-AQ-")])[0]
    mm = re.match(r"SR-AQ-([A-Z]{2})(\d\d)-(\d\d)", node)
    if not mm:
        return None
    typo = R.choice(["SR-AQ-%s%d-%d" % (mm.group(1), int(mm.group(2)), int(mm.group(3))), "SR-AQ-%s%s-9%s" % (mm.group(1), mm.group(2), mm.group(3)[1]), "SR-AQ-%s%s" % (mm.group(1), mm.group(2))])
    if typo == node:
        return None
    nm = MN[m]
    qs = ["How was %s at %s over the last day?" % (nm, typo), "Show the %s history of %s for 24 hours." % (nm, typo), "%s trend for %s today" % (cap(nm), typo), "What did %s on %s do in the last 24 hours?" % (nm, typo),
          "Give me %s readings of %s for the last day." % (nm, typo), "Is %s at %s stable over the last day?" % (nm, typo), "last 24 h of %s on %s" % (nm, typo), "Summary of %s at %s, last day." % (nm, typo)]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    e = rb.call("get_sensor_history", {"node": typo, "metric": m, "time": {"preset": "last_24h"}}, plan=plan(R, "recover"))
    if "error" not in e:
        return None
    loc = mm.group(1) + mm.group(2)
    ls = rb.call("list_sensors", {"location": loc})
    cand = [s["node"] for s in ls.get("sensors", []) if s["metric"] == m]
    if not cand:
        return None
    hs = rb.call("get_sensor_history", {"node": cand[0], "metric": m, "time": {"preset": "last_24h"}})
    if "summary" not in hs:
        return None
    mn, u = BC.hnum(BC.H(hs, 3), "min")
    mx, _ = BC.hnum(BC.H(hs, 4), "max")
    last, _ = BC.hnum(BC.H(hs, 5), "last")
    parts = ["I cannot find a sensor called %s; the %s sensor at %s is %s" % (typo, nm, loc, cand[0]), "Over the past day it ranged from %s to %s %s and the last value is %s %s" % (mn, mx, u, last, u)]
    return rb.fin("gen5_agentic", "recover_badnode", parts, fmt, recovery=True)


def P_noplace(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    m = R.choice(["co2", "temp", "pm25", "rh"])
    place = R.choice(["Block 7", "ZZ%d" % R.randrange(10, 99), "the library annex", "QQ-%d" % R.randrange(100, 999), "Hostel 3", "WW%d" % R.randrange(10, 99)])
    nm = MN[m]
    qs = ["What is the %s in %s right now?" % (nm, place), "Current %s at %s?" % (nm, place), "How is %s in %s?" % (nm, place), "Read me the %s from %s." % (nm, place),
          "%s level in %s now" % (cap(nm), place), "Is %s in %s ok?" % (nm, place), "check %s at %s" % (nm, place), "Any %s data for %s?" % (nm, place)]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    e = rb.call("current_levels", {"metric": m, "location": place}, plan=plan(R, "recover"))
    if "error" not in e and e.get("items"):
        return None
    ls = rb.call("list_sensors", {"domain": "air_quality"})
    sens = [s for s in ls.get("sensors", []) if s["metric"] == m]
    if not sens:
        return None
    mm = re.search(r"([A-Z]{2})(\d\d)", sens[0]["node"])
    if not mm:
        return None
    cl = rb.call("current_levels", {"metric": m, "location": mm.group(1) + mm.group(2)})
    its = cl.get("items") or []
    if not its:
        return None
    bl = sorted({re.search(r"([A-Z]{2})\d\d", s["node"]).group(1) for s in sens if re.search(r"([A-Z]{2})\d\d", s["node"])})
    parts = ["I cannot find any sensor for %s on this device, so I have no %s reading for it" % (place, nm), "%s sensors exist in %s; for example %s reads %s %s now (status %s)" % (nm, C.fmt_list(bl), its[0]["node"], its[0]["last"], its[0]["unit"], its[0]["status"])]
    return rb.fin("gen5_agentic", "recover_noplace", parts, fmt, recovery=True)


def Q_nosite(R):
    rb = RB2(R)
    fmt = pickfmt(R)
    x = R.choice(["Block 7", "Annex B", "ZZ-%d" % R.randrange(100, 999), "Hostel 3", "the old lab", "QQ%d" % R.randrange(10, 99)])
    st = R.choice(["critical", "warning", None])
    kw = {"critical": "critical", "warning": "in warning", None: "installed"}[st]
    qs = ["Which sensors are %s under %s?" % (kw, x), "Any %s sensors in %s?" % (kw, x), "List the sensors %s in %s." % (kw, x), "What is %s under %s?" % (kw, x),
          "show %s sensors at %s" % (kw, x), "Check %s for %s sensors." % (x, kw), "Are there %s sensors in %s?" % (kw, x), "%s: %s sensors?" % (cap(x), kw)]
    rb.ask(with_fmt(R, BC.pick(R, qs, "train"), fmt))
    args = {"node": x, "kind": "sensor"}
    if st:
        args["status"] = st
    e = rb.call("nodes_under", args, plan=plan(R, "recover"))
    if e.get("found") is not False:
        return None
    t = rb.call("get_site_tree", {})
    b = next((c for c in t["children"] if c["kind"] == "building"), None)
    if not b:
        return None
    a2 = {"node": b["id"], "kind": "sensor"}
    if st:
        a2["status"] = st
    nu = rb.call("nodes_under", a2)
    parts = ["There is no %s in the site map on this device" % x, "The campus has %s; under %s there %s %d %s sensor%s" % (kidnames(t["children"], 4), b["name"], "is" if nu["total"] == 1 else "are", nu["total"], kw, "" if nu["total"] == 1 else "s")]
    return rb.fin("gen5_agentic", "recover_nosite", parts, fmt, recovery=True)


def A_widen(R):
    return A_drill(R, widen=True)


AGENTIC = [(A_drill, 90), (B_health, 100), (C_recur, 100), (D_compare, 100), (E_tree, 100), (F_faulty, 100), (G_know, 100), (H_whatif, 100), (I_fog, 100),
           (J_cooccur, 100), (L_open, 100), (M_faults, 100), (N_badid, 75), (O_badnode, 75), (P_noplace, 50), (Q_nosite, 50), (A_widen, 60)]


def agentic_rows(n_total, R, seen):
    tot = sum(w for _, w in AGENTIC)
    out, why = [], collections.Counter()
    for fn, w in AGENTIC:
        goal, got, tries = round(n_total * w / tot), 0, 0
        while got < goal and tries < goal * 40:
            tries += 1
            try:
                r = fn(R)
            except (KeyError, IndexError, TypeError, StopIteration, ValueError) as e:
                why["%s:exc:%s" % (fn.__name__, type(e).__name__)] += 1
                continue
            if r is None:
                why["%s:none" % fn.__name__] += 1
                continue
            key = (next(m["content"] for m in r["messages"] if m["role"] == "user"), r["fog"], json.dumps(r["gold_calls"], sort_keys=True), r["messages"][-1]["content"])
            if key in seen:
                why["%s:dup" % fn.__name__] += 1
                continue
            e = gate(r)
            if e:
                why["%s:check:%s" % (fn.__name__, e[0].split(":")[0])] += 1
                continue
            seen.add(key)
            out.append(r)
            got += 1
        STATS["agentic_goal:%s" % fn.__name__] = goal
        STATS["agentic_got:%s" % fn.__name__] = got
    STATS.update({"drop:" + k: v for k, v in why.items()})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-single", type=int, default=240)
    ap.add_argument("--n-agentic", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=2111)
    a = ap.parse_args()
    R = random.Random(a.seed)
    os.makedirs(OUT, exist_ok=True)
    rows, seen = [], set()
    for tool in R3KINDS:
        rows += r3_rows(tool, a.n_single, R, seen)
    for tool, fn in (("get_site_tree", k_tree), ("nodes_under", k_nodes), ("forecast_crossing", k_forecast), ("data_health", k_health)):
        rows += single_custom(tool, fn, a.n_single if tool != "data_health" else 160, R, seen)
    rows += agentic_rows(a.n_agentic, R, seen)
    c = collections.Counter()
    for i, r in enumerate(rows):
        r["id"] = "gen5-%s-%05d" % (r["family"][5:], i)
        c[r["family"]] += 1
        if r["family"] in ("gen5_forecast_crossing", "gen5_data_health"):
            r["tools"] = "chat_r6"      # tools_v5.json chat_r6 = chat_r5 + the two router-only tools
    with open(OUT + "/gen5_tools.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    json.dump({"rows": len(rows), "families": c, "stats": STATS}, open(OUT + "/gen5_stats.json", "w"), indent=1)
    print(len(rows), dict(c))


if __name__ == "__main__":
    main()
