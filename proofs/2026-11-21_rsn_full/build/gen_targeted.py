"""gen_targeted.py: targeted chat top-up block (block=targeted_v1) for the failures in gate_full/FAILS.md. Reuses gen_tools (RB2 builder, real tool twins),
big_chat (BC) helpers. Categories: A chains (rank_linked / find_get / faulty_vs_empty), B node-name args + status + unknown entities,
C follow-ups / no-call / one-word / incidents-today / co-occurring with explicit window. Leakage: last-user-text hash vs gate + tests dropped.
  python3 gen_targeted.py   ->  ../data/targeted_v1.jsonl + ../data/targeted_v1_stats.json"""
import collections
import glob
import hashlib
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_tools as GT  # noqa: E402
BC, C = GT.BC, GT.C
RB2, DN, MN, cap = GT.RB2, GT.DN, GT.MN, GT.cap
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/"
D = os.path.abspath(os.path.join(HERE, "..", "data"))
OUT = D + "/targeted_v1.jsonl"
R = random.Random(20261124)
BLOCK = "targeted_v1"


def hh(t):
    return hashlib.md5(re.sub(r"\s+", " ", re.sub(r"INC-\d+", "INC", t or "")).strip().lower().encode()).hexdigest()


def user_last(r):
    return next((m.get("content") or "" for m in reversed(r["messages"]) if m["role"] == "user"), "")


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


class RB3(RB2):
    """RB2 with text-only history turns before the asked question"""

    def __init__(s, R, state=None, hist=None):
        super().__init__(R, state)
        for q, a in hist or []:
            s.msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        s.hist = hist

    def fin(s, fam, kind, parts, fmt=None, final=None, **kw):
        if final is not None:
            if not final.strip() or len(final) > 640:
                return None
            s.msgs.append({"role": "assistant", "content": final})
            r = {"id": "x", "family": fam, "tools": "chat_r5", "think": True, "hard": len(s.gold) >= 2, "fog": s.fog, "hinglish": False, "site_id": "iiith",
                 "reasoning_type": "none", "hops": 0, "messages": s.msgs, "gold_calls": s.gold, "multi_turn": bool(s.hist), "kind": kind, "src_real": False,
                 "last_sync": s.ls, "since": GT.SINCE}
            if fmt:
                r["fmt"] = fmt
            if any("error" in x for x in s.res if isinstance(x, dict)):
                r["allow_error"] = True
            r.update(kw)
        else:
            r = super().fin(fam, kind, parts, fmt, **kw)
        if r:
            r["multi_turn"] = bool(s.hist)
        return r


PW = {"today": ["today", "so far today"], "yesterday": ["yesterday"], "last_24h": ["in the last 24 hours", "over the past day", "in the past 24 h"],
      "last_7d": ["in the last 7 days", "over the past week", "during the last 7 days"], "last_30d": ["in the last 30 days", "over the past month"],
      "this_week": ["this week"]}


def pw(p):
    return R.choice(PW[p])


def sv_(s):
    return (s or "").replace("_", " ")


# ------------------------------------------------------------------------------------------------------------------------------ A
def A_rank_linked():
    rb = RB3(R)
    ex, ST = rb.ex, rb.ST
    metric = R.choice(["temp", "temp", "co2", "rh", "pm25"])
    order = "lowest" if (metric in ("temp", "rh") and R.random() < 0.18) else "highest"
    pr = R.choice(["today", "last_24h", "last_7d", "this_week", "yesterday"])
    loc = R.choice([None, None, "KH", "KH03"])
    a = dict(metric=metric, domain="air_quality", time={"preset": pr}, limit=1)
    if order == "lowest":
        a["order"] = "lowest"
    if loc:
        a["location"] = loc
    r0 = rb.peek("rank_readings", a)
    it = (r0.get("items") or [None])[0]
    mm = it and re.search(r"SR-AQ-([A-Z]{2})(\d\d)-(\d\d)", it["node"])
    room = mm and "%s-%s-AQ%s" % mm.groups()
    if not mm or not ST.find(room):
        return None
    nm = {"temp": {"highest": "hottest", "lowest": "coolest"}[order], "co2": "stuffiest (highest CO2)", "rh": {"highest": "most humid", "lowest": "driest"}[order], "pm25": "dustiest (highest PM2.5)"}[metric]
    w = pw(pr)
    qs = ["Which room is the %s %s, and is the AC serving it fine?" % (nm, w), "Find the %s room %s and check the unit that serves it." % (nm, w),
          "%s room %s: what unit cools it and how is that unit?" % (cap(nm), w), "Pick the %s room %s, then tell me about its air conditioner." % (nm, w),
          "Where was it %s %s, and what AC serves that room?" % (nm, w), "Look up the %s place %s and see if its AC is healthy." % (nm, w),
          "Is the AC in the %s room %s working normally?" % (nm, w), "I need the %s room %s and the equipment feeding it." % (nm, w),
          "Check the AC of the room that was %s %s." % (nm, w), "Which room was %s %s? And what is the status of its AC?" % (nm, w)]
    q = R.choice(qs)
    if loc:
        q = q.replace(" room", " room in %s" % ("KH building" if loc == "KH" else "floor " + loc), 1) if " room" in q else q + " (%s)" % loc
    rb.ask(q)
    rb.call("rank_readings", a, plan=R.choice(BC.PLANS["rank_linked"]))
    lk = rb.call("linked_equipment", dict(node=room, link="serves", direction="in"))
    if lk.get("found") is False or not lk.get("links"):
        return None
    u = lk["links"][0]
    tail = "It is normal with no open incident, so check the room itself (doors, crowd, sun)." if u["status"] == "normal" else "It is %s%s." % (u["status"], (" " + C.cite(u["open"])) if u["open"] else "")
    f = "%s: %s %s at %s on %s. It is served by %s. %s" % (it["location"], it["value"], it["unit"], it["at"][11:], it["at"][:10], u["name"], tail)
    return rb.fin("targeted_rank_linked", "rank_linked", None, final=f)


def A_find_get():
    rb = RB3(R)
    d = R.choice(list(DN))
    bld = R.choice([None, "KH", "VN", "BK", "KN"])
    sv = R.choice([None, None, "critical", "warning"])
    pr = R.choice(["last_30d", "last_30d", "last_7d", "this_week"])
    flt = {"domain": d}
    if sv:
        flt["severity"] = [sv]
    if bld:
        flt["node"] = bld
    a = dict(time={"preset": pr}, limit=3, **flt)
    pk = rb.peek("find_incidents", a)
    if not pk.get("items"):
        return None
    where = (" in %s" % bld) if bld else ""
    sw = (sv + " ") if sv else ""
    tw = {"last_30d": ["", " recently", " in the last 30 days"], "last_7d": [" in the last 7 days", " this past week"], "this_week": [" this week"]}[pr]
    t = R.choice(tw)
    qs = ["Walk me through the most recent %s%s incident%s%s." % (sw, DN[d], where, t), "What is the newest %s%s alert%s%s about, and what caused it?" % (sw, DN[d], where, t),
          "Open the latest %s%s incident%s%s and explain it." % (sw, DN[d], where, t), "Last %s%s event%s%s: cause and current state?" % (sw, DN[d], where, t),
          "I want the details of the newest %s%s incident%s%s." % (sw, DN[d], where, t), "Why did the most recent %s%s problem%s%s happen?" % (sw, DN[d], where, t),
          "Tell me the story of the last %s%s incident%s%s." % (sw, DN[d], where, t), "Check the latest %s%s incident%s%s and its root cause." % (sw, DN[d], where, t)]
    rb.ask(re.sub(r"\s+", " ", R.choice(qs)).replace(" .", "."))
    fi = rb.call("find_incidents", a, plan=R.choice(BC.PLANS["find_get"]))
    if not fi.get("items"):
        return None
    iid = fi["items"][0]["id"]
    g = rb.call("get_incident", {"id": iid})
    if not g.get("root_cause"):
        return None
    state = "closed as %s" % sv_(g["outcome"]) if g.get("outcome") else "still %s" % sv_(g.get("workflow", "open"))
    f = "[%s] %s is %s and %s. Cause: %s." % (iid, GT.ttl(g), sv_(g["severity"]), state, g["root_cause"])
    return rb.fin("targeted_find_get", "find_get", None, final=f)


def A_faulty_vs_empty():
    rb = RB3(R)
    cs = [s for s in rb.W["sensors"] if s["metric"] == "co2" and re.search(r"SR-AQ-([A-Z]{2})", s["node"]) and re.search(r"SR-AQ-([A-Z]{2})", s["node"]).group(1) in BC.OCC]
    s = R.choice(cs)
    bld = re.search(r"SR-AQ-([A-Z]{2})", s["node"]).group(1)
    pr = R.choice(["last_24h", "last_7d", "last_30d", "today"])
    w, n = pw(pr), s["node"]
    qs = ["%s CO2 %s: is the sensor broken or was the room just empty?" % (n, w), "Is %s faulty, or was nobody in the room %s?" % (n, w), "Faulty or vacant: %s %s?" % (n, w),
          "Check %s %s. Bad CO2 sensor or an empty room?" % (n, w), "Is the meter %s misbehaving or is the room simply unused %s?" % (n, w), "Tell me if %s is defective or the room had no people %s." % (n, w),
          "CO2 on %s looks strange %s. Sensor fault or empty room?" % (n, w), "Decide for %s %s: broken sensor or empty room?" % (n, w)]
    rb.ask(R.choice(qs))
    r1 = rb.call("get_sensor_history", dict(node=n, metric="co2", time={"preset": pr}), plan=R.choice(BC.PLANS["faulty"]))
    r2 = rb.call("get_sensor_history", dict(node=BC.OCC[bld], metric="occ", time={"preset": pr}))
    if "summary" not in r1 or "summary" not in r2:
        return None
    f1, f2 = BC._facts_h(r1), BC._facts_h(r2)
    mn, mx, oc = float(f1["min"][0]), float(f1["max"][0]), float(f2["mean"][0])
    if mx > 5000 or mn < 250:
        v, f = "fault", "The readings are not credible: CO2 ranged %s to %s ppm (mean %s), outside what a working sensor reads, and the room occupancy mean was %s. That points to a faulty sensor, not an empty room." % (f1["min"][0], f1["max"][0], f1["mean"][0], f2["mean"][0])
    elif oc >= 0.08 and mx - mn >= 150:
        v, f = "people", "The room was in use: occupancy averaged %s and CO2 moved between %s and %s ppm with it. The sensor looks fine." % (f2["mean"][0], f1["min"][0], f1["max"][0])
    elif oc < 0.08:
        v, f = "empty", "The room was mostly empty (occupancy mean %s) and CO2 stayed between %s and %s ppm, so low readings are expected. Nothing suggests a faulty sensor." % (f2["mean"][0], f1["min"][0], f1["max"][0])
    else:
        v, f = "flat", "Occupancy averaged %s but CO2 barely moved (%s to %s ppm). That could be a stuck sensor: check it on site." % (f2["mean"][0], f1["min"][0], f1["max"][0])
    return rb.fin("targeted_faulty_vs_empty", "faulty_vs_empty", None, final=f, verdict=v)


# ------------------------------------------------------------------------------------------------------------------------------ B
def uname(rb, kinds):
    ix = rb.ST.ix
    out = []
    for n in rb.W["site"]["nodes"]:
        if n["kind"] in kinds and rb.ST.find(n["name"]) == n["id"]:
            out.append(n)
    return out


def B_status():
    rb = RB3(R)
    n = R.choice(uname(rb, ("building", "room")))
    x = n["name"]
    qs = ["Why is %s amber?" % x, "What is the status of %s?" % x, "Is %s ok right now?" % x, "Any open problem in %s?" % x, "How is %s doing?" % x, "Why is %s showing red?" % x,
          "Give me the current state of %s." % x, "Check %s for me: anything flagged?" % x, "Is there an alert on %s?" % x, "%s status?" % x]
    rb.ask(R.choice(qs))
    r = rb.call("site_status", {"node": x})
    if r.get("found") is False:
        return None
    op = r.get("open_incidents") or []
    st = sv_(r["status"])
    if op:
        f = "%s is %s with %d open incident%s: %s." % (r["name"], st, len(op), "" if len(op) == 1 else "s", ", ".join("[%s]" % (o["id"] if isinstance(o, dict) else o) for o in op[:3]))
    else:
        f = "%s is %s with no open incident%s." % (r["name"], st, ("" if not r.get("data_issues") else " and %d data issue%s" % (r["data_issues"], "" if r["data_issues"] == 1 else "s")))
    return rb.fin("targeted_site_status", "site_status", None, final=f)


def B_tree():
    rb = RB3(R)
    ix = rb.ST.ix
    ns = [n for n in uname(rb, ("building", "room", "floor")) if ix.children.get(n["id"])]
    n = R.choice(ns)
    x = n["name"]
    qs = ["List the sensors in %s." % x, "What sensors are in %s?" % x, "What is inside %s?" % x, "Show me what %s contains." % x, "Which devices are in %s?" % x,
          "What does %s have in it?" % x, "Show the layout of %s." % x, "give me the children of %s" % x]
    rb.ask(R.choice(qs))
    r = rb.call("get_site_tree", {"node": x, "depth": 1})
    if r.get("found") is False or not r.get("children"):
        return None
    ch = r["children"]
    nm = [c["name"] for c in ch]
    bad = [c for c in ch if c["status"] != "normal"]
    f = "%s has %d item%s: %s." % (r["name"], r["children_total"], "" if r["children_total"] == 1 else "s", C.fmt_list(nm, 4))
    f += (" Not normal: %s." % ", ".join("%s (%s)" % (c["name"], sv_(c["status"])) for c in bad[:3])) if bad else " All are normal."
    return rb.fin("targeted_site_tree", "tree_node", None, final=f)


def B_nodes():
    rb = RB3(R)
    n = R.choice(uname(rb, ("building",)))
    x = n["name"]
    kind = R.choice(["sensor", "sensor", "room", "equipment"])
    metric = R.choice([None, "co2", "temp", "pm25", "power_kw", "occ"]) if kind == "sensor" else None
    mw = (MN[metric] + " ") if metric else ""
    kn = {"sensor": "sensors", "room": "rooms", "equipment": "equipment items"}[kind]
    qs = ["How many %s%s are in %s?" % (mw, kn, x), "count the %s%s in %s" % (mw, kn, x), "List the %s%s under %s." % (mw, kn, x), "Which %s%s does %s have?" % (mw, kn, x),
          "How many %s%s does %s have?" % (mw, kn, x)]
    rb.ask(R.choice(qs))
    a = {"node": x, "kind": kind}
    if metric:
        a["metric"] = metric
    r = rb.call("nodes_under", a)
    if r.get("found") is False:
        return None
    if r["total"] == 0:
        f = "There are no %s%s under %s." % (mw, kn, r["name"])
    else:
        f = "%s has %d %s%s: %s." % (r["name"], r["total"], mw, kn if r["total"] != 1 else kn.rstrip("s"), GT.kidnames(r["items"], 4))
    return rb.fin("targeted_nodes_under", "nodes_list", None, final=f)


def B_sensor_problem():
    rb = RB3(R)
    m = R.choice(["pm25", "co2", "temp", "rh", "power_kw"])
    ss = [s for s in rb.W["sensors"] if s["metric"] == m]
    if not ss:
        return None
    s = R.choice(ss)
    mm = re.search(r"([A-Z]{2})(\d\d)", s["node"])
    if not mm:
        return None
    loc = mm.group(0)
    nm = MN[m]
    qs = ["%s at %s: is the sensor having a problem?" % (nm, loc), "any problem with the %s sensor at %s?" % (nm, loc), "Is something wrong with the %s sensor in %s?" % (nm, loc),
          "%s sensor %s, anything wrong with it?" % (loc, nm), "Does the %s sensor at %s have a fault?" % (nm, loc), "Is the %s meter at %s misbehaving?" % (nm, loc),
          "Any trouble with %s at %s?" % (nm, loc), "%s %s: sensor ok or faulty?" % (nm, loc)]
    rb.ask(R.choice(qs))
    r = rb.call("current_levels", {"metric": m, "location": loc})
    its = r.get("items") or []
    if not its:
        return None
    it = its[0]
    if it["status"] == "normal":
        f = "No problem: %s reports %s %s and its status is normal." % (it["node"], it["last"], it["unit"])
    else:
        f = "It reports, but the status is %s: %s %s on %s." % (sv_(it["status"]), it["last"], it["unit"], it["node"])
    return rb.fin("targeted_sensor_problem", "short_status", None, final=f)


def B_unknown():
    rb = RB3(R)
    mode = R.choice(["sensor", "sensor", "bldg", "bldg", "tree"])
    code = R.choice(["ZZ99", "QQ-204", "XY12", "QQ77", "WW31", "RR08", "TT-512", "ZZ-45", "UU19"])
    bn = R.choice(["Block 9", "ZZ building", "QX building", "Annex C", "Hostel 5", "WP building", "the north lab"])
    if mode == "sensor":
        m = R.choice(["co2", "temp", "pm25", "power_kw", "rh"])
        nm = MN[m]
        qs = ["How is the %s at %s?" % (nm, code), "any %s reading at %s?" % (nm, code), "show me %s for room %s" % (nm, code), "Is the %s sensor in %s alive?" % (nm, code), "%s now at %s?" % (nm, code)]
        rb.ask(R.choice(qs))
        r = rb.call("current_levels", {"metric": m, "location": code})
        if r.get("items"):
            return None
        f = R.choice(["I cannot find any sensor for %s on this device, so I have no %s reading for it. Check the name or tell me a building." % (code, nm), "There is no sensor matching %s on this device, so I cannot give a %s value. Check the name and ask again." % (code, nm)])
        return rb.fin("targeted_unknown", "unknown_sensor", None, final=f)
    if mode == "bldg":
        qs = ["Why is %s amber?" % bn, "Status of %s?" % bn, "Is %s ok?" % bn, "Any problem in %s?" % bn, "How is %s doing today?" % bn]
        rb.ask(R.choice(qs))
        r = rb.call("site_status", {"node": bn})
        if r.get("found") is not False:
            return None
        f = R.choice(["There is no %s in the site map on this device. Check the name, or ask me about a building I can see." % bn, "I cannot find %s in the site map, so I have no status for it. Tell me another building name." % bn])
        return rb.fin("targeted_unknown", "unknown_bldg", None, final=f)
    qs = ["What sensors are in %s?" % bn, "List the sensors in %s." % bn, "What is inside %s?" % bn, "Show what %s contains." % bn]
    rb.ask(R.choice(qs))
    r = rb.call("get_site_tree", {"node": bn, "depth": 1})
    if r.get("found") is not False:
        return None
    f = R.choice(["I cannot find %s in the site map on this device. Give me an existing building or room name." % bn, "There is no %s in the site map, so I have nothing to list. Ask for a name that exists." % bn])
    return rb.fin("targeted_unknown", "unknown_tree", None, final=f)


# ------------------------------------------------------------------------------------------------------------------------------ C
CP = {"today": "today", "yesterday": "yesterday", "last_24h": "in the last 24 hours", "last_7d": "in the last 7 days", "last_30d": "in the last 30 days", "this_month": "this month"}
CPS = {"today": ["and today?", "what about today?", "same for today", "today too?"], "yesterday": ["and yesterday?", "yesterday too?", "what about yesterday"],
       "last_24h": ["and the last 24 hours?", "last day too?", "what about the past 24 hours"], "last_7d": ["and the last 7 days?", "same for the past week", "week too?"],
       "last_30d": ["and the last 30 days?", "what about the past month?", "month too?"], "this_month": ["and this month?", "this month too?"]}


def cnt_ans(res, d, p, sv=None):
    return "There %s %d %s%s incident%s %s." % ("was" if res["count"] == 1 else "were", res["count"], (sv_(sv) + " ") if sv else "", DN[d], "" if res["count"] == 1 else "s", CP[p])


def C_follow_count():
    d1, d2 = R.sample(list(DN), 2)
    p1, p2 = R.sample(list(CP), 2)
    mode = R.choice(["domain", "domain", "period", "severity"])
    sv = R.choice(["critical", "warning"])
    rb0 = RB3(R)
    a1 = rb0.peek("count_incidents", dict(time={"preset": p1}, domain=d1))
    if "count" not in a1:
        return None
    h = [(R.choice(["How many %s incidents %s?" % (DN[d1], CP[p1]), "Count the %s incidents %s." % (DN[d1], CP[p1]), "%s incidents %s, how many?" % (cap(DN[d1]), CP[p1])]), cnt_ans(a1, d1, p1))]
    if mode == "domain":
        qs = ["ok and %s?" % DN[d2], "and %s?" % DN[d2], "what about %s?" % DN[d2], "%s too?" % DN[d2], "now %s" % DN[d2], "same for %s" % DN[d2]]
        args, ans = dict(time={"preset": p1}, domain=d2), lambda r: cnt_ans(r, d2, p1)
    elif mode == "period":
        qs = R.sample(CPS[p2], 1)
        args, ans = dict(time={"preset": p2}, domain=d1), lambda r: cnt_ans(r, d1, p2)
    else:
        qs = ["only the %s ones?" % sv, "just %s?" % sv, "and the %s ones?" % sv, "%s only please" % sv]
        args, ans = dict(time={"preset": p1}, domain=d1, severity=[sv]), lambda r: cnt_ans(r, d1, p1, sv)
    rb = RB3(R, state=rb0.fog, hist=h)
    rb.ask(R.choice(qs))
    r = rb.call("count_incidents", args)
    if "count" not in r:
        return None
    return rb.fin("targeted_followup", "followup_" + mode, None, final=ans(r))


def C_follow_levels():
    m1, m2 = R.sample(["co2", "temp", "rh", "pm25"], 2)
    loc = R.choice(["KH03", "KH03", "BK03", "VN02"])
    rb0 = RB3(R)
    a1 = rb0.peek("current_levels", {"metric": m1, "location": loc})
    a2 = rb0.peek("current_levels", {"metric": m2, "location": loc})
    if not a1.get("items") or not a2.get("items"):
        return None
    i1 = a1["items"][0]
    ans1 = "%s reads %s %s (status %s)." % (i1["node"], i1["last"], i1["unit"], sv_(i1["status"]))
    h = [(R.choice(["What is the %s at %s?" % (MN[m1], loc), "Current %s at %s?" % (MN[m1], loc), "%s reading at %s please" % (cap(MN[m1]), loc)]), ans1)]
    rb = RB3(R, state=rb0.fog, hist=h)
    rb.ask(R.choice(["ok and %s?" % MN[m2], "and %s?" % MN[m2], "%s too?" % MN[m2], "what about %s?" % MN[m2], "now %s" % MN[m2]]))
    r = rb.call("current_levels", {"metric": m2, "location": loc})
    if not r.get("items"):
        return None
    i2 = r["items"][0]
    f = "%s reads %s %s (status %s)." % (i2["node"], i2["last"], i2["unit"], sv_(i2["status"]))
    return rb.fin("targeted_followup", "followup_metric", None, final=f)


MONTHS = {"2026-03": "March", "2026-04": "April", "2026-05": "May", "2026-06": "June", "2026-07": "July", "2026-08": "August"}


def C_follow_month():
    m1, m2 = R.sample(list(MONTHS), 2)
    d = R.choice(["power", "water", "air_quality", "hvac"])
    rb0 = RB3(R, state="online")
    a1 = rb0.peek("fog_search_history", dict(time={"from": BC._month(m1)[0], "to": BC._month(m1)[1]}, domain=d))
    if not isinstance(a1.get("total"), int):
        return None
    h = [(R.choice(["How many %s incidents were there in %s?" % (DN[d], MONTHS[m1]), "%s incidents in %s: how many?" % (cap(DN[d]), MONTHS[m1])]), "There were %d %s incidents in %s." % (a1["total"], DN[d], MONTHS[m1]))]
    rb = RB3(R, state="online", hist=h)
    rb.ask(R.choice(["%s too?" % MONTHS[m2], "and %s?" % MONTHS[m2], "what about %s?" % MONTHS[m2], "same for %s" % MONTHS[m2]]))
    r = rb.call("fog_search_history", dict(time={"from": BC._month(m2)[0], "to": BC._month(m2)[1]}, domain=d))
    if not isinstance(r.get("total"), int) or r.get("error"):
        return None
    return rb.fin("targeted_followup", "followup_month", None, final="There were %d %s incidents in %s." % (r["total"], DN[d], MONTHS[m2]))


NOCALL_GREET = [("hi", "Hello. Ask me about incidents, sensors or the site and I will check the tools."), ("hello there", "Hello. Which building, sensor or incident should I look at?"),
                ("good morning", "Good morning. Tell me what to check: incidents, a sensor, or a building."), ("thanks, that helps", "You are welcome. Ask again whenever you need a check."),
                ("ok thanks", "You are welcome. I can look into another sensor or incident if you want."), ("hey", "Hello. What should I look at: an incident, a sensor or a building?"),
                ("thank you!", "You are welcome. Let me know if you want another check."), ("hi, are you there?", "Yes, I am here. Ask about incidents, sensors or the site."),
                ("good evening", "Good evening. Tell me what to check and I will read the tools."), ("cool, that is all for now", "Fine. Ask again whenever you need something checked."),
                ("hello, what can you do?", "I can read incidents, sensor levels and history, maintenance actions and the site map, and I cannot change anything. What do you want to check?"),
                ("who are you?", "I am the operator assistant of the campus monitor. I read incidents, sensors and the site map with read-only tools.")]
NOCALL_CLARIFY = [("check the sensor", "Which sensor do you mean? Give me a name like KH03 and a metric such as CO2."), ("is it fine?", "What should I check? Name a sensor, building or incident."),
                  ("look at the room", "Which room? Tell me the room or building name and what to check."), ("is the reading ok?", "Which reading? Give me the sensor or place and the metric."),
                  ("show me the incident", "Which incident? Give me an id like INC-0123 or say the latest in a domain."), ("what is wrong there?", "Where do you mean? Name a building, room or sensor."),
                  ("compare them", "Compare what? Tell me the two sensors, buildings or periods."), ("any alerts?", "Which area or domain: air quality, water, power, HVAC, weather or occupancy?"),
                  ("fix it", "I cannot change anything: the tools are read-only. Tell me which sensor or incident and I can read it and suggest what you can do.")]


def C_nocall():
    mode = R.choice(["greet", "clarify", "context"])
    if mode in ("greet", "clarify"):
        q, a = R.choice(NOCALL_GREET if mode == "greet" else NOCALL_CLARIFY)
        if R.random() < 0.3:
            q = q.capitalize() + R.choice(["", ".", "!"]) if not q.endswith(("?", "!")) else q.capitalize()
        rb = RB3(R)
        rb.ask(q)
        return rb.fin("targeted_nocall", "nocall", None, final=a, nocall=True)
    m = R.choice(["co2", "temp", "pm25", "rh"])
    pr = R.choice(["today", "last_24h", "yesterday"])
    rb0 = RB3(R)
    r0 = rb0.peek("rank_readings", dict(metric=m, time={"preset": pr}, limit=2))
    its = r0.get("items", [])
    if len(its) < 2 or its[0]["value"] == its[1]["value"]:
        return None
    nm = MN[m]
    a1 = "Top %s %s: %s %s %s at %s, then %s %s %s at %s." % (nm, CP[pr], its[0]["location"], its[0]["value"], its[0]["unit"], its[0]["at"][11:], its[1]["location"], its[1]["value"], its[1]["unit"], its[1]["at"][11:])
    h = [(R.choice(["Give me the two highest %s readings %s." % (nm, CP[pr]), "Top two %s %s?" % (nm, CP[pr])]), a1)]
    rb = RB3(R, state=rb0.fog, hist=h)
    rb.ask(R.choice(["hi, which of those should I check first?", "thanks. which one is the worst?", "ok, where first?", "hello again, which place was higher?", "which one do I look at first?", "and which of the two is worse?"]))
    f = R.choice(["%s: %s %s at %s." % (its[0]["location"], its[0]["value"], its[0]["unit"], its[0]["at"][11:]), "Start with %s, which had %s %s." % (its[0]["location"], its[0]["value"], its[0]["unit"])])
    return rb.fin("targeted_nocall", "nocall", None, final=f, nocall=True)


def C_oneword():
    rb = RB3(R)
    mode = R.choice(["open", "open", "yesno", "num"])
    if mode == "open":
        rb.ask(R.choice(["Name the incidents that need a decision, one word each.", "one word each: what is pending?", "Pending incidents, one word per incident please.",
                         "Just one word per incident: what should I handle first?", "one word each, the top open incidents"]))
        o = rb.call("open_incidents", {})
        if not o.get("top_pending"):
            return None
        ws = [re.split(r"[ :]", i["title"])[0] for i in o["top_pending"][:3]]
        ws = [w.upper() if w.lower() in ("co2", "pm25", "tds", "ph", "pf") else w.capitalize() for w in ws]
        return rb.fin("targeted_format", "fmt_one_word", None, final=", ".join(ws) + ".", fmt="one_word")
    if mode == "yesno":
        n = R.choice(uname(rb, ("building",)))
        rb.ask(R.choice(["one word: is %s normal?" % n["name"], "Just yes or no: is %s fine right now?" % n["name"], "yes or no, any problem in %s?" % n["name"]]))
        r = rb.call("site_status", {"node": n["name"]})
        if r.get("found") is False:
            return None
        bad = r["status"] != "normal"
        q = rb.msgs[-2]["content"].lower() if rb.msgs[-2]["role"] == "user" else ""
        ask_problem = "problem" in rb.q.lower()
        ans = ("Yes." if bad else "No.") if ask_problem else ("No." if bad else "Yes.")
        return rb.fin("targeted_format", "fmt_one_word", None, final=ans, fmt="one_word")
    d = R.choice(list(DN))
    p = R.choice(["today", "last_7d", "last_30d"])
    rb.ask(R.choice(["Only the number: %s incidents %s?" % (DN[d], CP[p]), "just the count of %s incidents %s" % (DN[d], CP[p]), "%s incidents %s, number only." % (cap(DN[d]), CP[p])]))
    r = rb.call("count_incidents", dict(time={"preset": p}, domain=d))
    if "count" not in r:
        return None
    return rb.fin("targeted_format", "fmt_number", None, final="%d." % r["count"])


def C_today_by_domain():
    rb = RB3(R)
    mode = R.choice(["by_domain", "filtered", "filtered"])
    if mode == "by_domain":
        pr = R.choice(["today", "yesterday"])
        rb.ask(R.choice(["Incidents %s by domain?" % pr, "Break down %s's incidents by domain." % pr, "Which domains had incidents %s?" % pr, "List %s's incidents grouped by domain." % pr, "show the incidents %s, split by domain" % pr]))
        r = rb.call("find_incidents", dict(time={"preset": pr}, limit=10))
        if not r.get("items"):
            return None
        its = r["items"]
        f = "%d incidents %s. The latest: %s." % (r["total"], pr, "; ".join("[%s] %s" % (i["id"], "/".join(sv_(x) for x in i["domains"])) for i in its[:4]))
        return rb.fin("targeted_today", "find_today_domain", None, final=f)
    d = R.choice(list(DN))
    sv = R.choice(["sensor_fault", "critical", "warning"])
    pr = R.choice(["today", "yesterday", "last_24h"])
    rb.ask(R.choice(["%s %s incidents %s?" % (cap(sv_(sv)), DN[d], CP[pr]), "Any %s incident in %s %s?" % (sv_(sv), DN[d], CP[pr]), "Were there %s alerts for %s %s?" % (sv_(sv), DN[d], CP[pr]),
                     "%s %s incidents %s, any?" % (cap(sv_(sv)), DN[d], CP[pr])]))
    r = rb.call("find_incidents", dict(time={"preset": pr}, domain=d, severity=[sv], limit=3))
    if "total" not in r:
        return None
    if not r["items"]:
        f = "No %s %s incidents %s." % (sv_(sv), DN[d], CP[pr])
    else:
        f = "%d %s %s incident%s %s: %s." % (r["total"], sv_(sv), DN[d], "" if r["total"] == 1 else "s", CP[pr], "; ".join("[%s] %s" % (i["id"], GT.ttl(i)) for i in r["items"][:3]))
    return rb.fin("targeted_today", "find_empty" if not r["items"] else "find_today_filter", None, final=f)


WIN = [(30, ["within 30 minutes of %s", "30 minutes either side of %s"]), (60, ["an hour either side of %s", "within an hour of %s"]), (45, ["within 45 minutes of %s"]),
       (120, ["two hours either side of %s", "within two hours of %s"]), (180, ["three hours around %s", "within 3 hours of %s"]), (90, ["within 90 minutes of %s"]), (120, ["around %s"])]


def C_cooccur():
    rb = RB3(R)
    cand = [i for d in ("power", "hvac", "air_quality", "water") for i in BC.incs(R, domain=d)[:3]]
    cand = [i for i in rb.ex.run("find_incidents", dict(time={"preset": "last_30d"}, limit=10)).get("items", [])] or cand
    rb.ex.qid = 0
    if not cand:
        return None
    iid = R.choice(cand)["id"]
    wmin, phr = R.choice(WIN)
    ph = R.choice(phr) % iid
    qs = ["What other incidents happened %s?" % ph, "Did anything else fire %s, and what caused %s?" % (ph, iid), "Check %s: is it related to anything else, and what is the cause of %s?" % (ph, iid),
          "Which incidents overlap %s, and what does the report say about %s?" % (ph, iid), "Explain %s and list what happened %s." % (iid, ph)]
    rb.ask(R.choice(qs))
    g = rb.call("get_incident", {"id": iid}, plan=R.choice(BC.PLANS["cooccur"]))
    if "error" in g:
        return None
    co = rb.call("co_occurring_incidents", {"id": iid, "window_min": wmin})
    if co.get("error") or "total" not in co:
        return None
    rc = g.get("root_cause") or "no root cause was written"
    if co["total"] == 0:
        f = "Nothing else was flagged within %d minutes of [%s]. Its report says: %s." % (wmin, iid, rc)
    else:
        f = "Within %d minutes of [%s] the device also logged %s. That timing alone does not show one caused the other; the report of [%s] says: %s." % (wmin, iid, " and ".join("[%s] (%s)" % (i["id"], "/".join(i["domains"])) for i in co["items"][:2]), iid, rc)
    return rb.fin("targeted_cooccur", "cooccur", None, final=f)


# ------------------------------------------------------------------------------------------------------------------------------ main
PLAN = [("A", A_rank_linked, 100), ("A", A_find_get, 100), ("A", A_faulty_vs_empty, 100),
        ("B", B_status, 40), ("B", B_tree, 35), ("B", B_nodes, 30), ("B", B_sensor_problem, 100), ("B", B_unknown, 95),
        ("C", C_follow_count, 60), ("C", C_follow_levels, 20), ("C", C_follow_month, 20), ("C", C_nocall, 70), ("C", C_oneword, 50), ("C", C_today_by_domain, 40), ("C", C_cooccur, 40)]


def main():
    sys.path.insert(0, P + "2026-11-20_rsn_big/build")
    os.chdir(P + "2026-11-20_rsn_big/build")
    sys.argv[1:] = [D]
    import types
    CB = types.ModuleType("check_big")
    CB.__file__ = os.path.abspath("check_big.py")
    exec(compile(open("check_big.py").read().rsplit("\nmain()", 1)[0], "check_big.py", "exec"), CB.__dict__)
    T = json.load(open(D + "/tools_v5.json"))
    r6 = {f["function"]["name"] for f in T["chat_r6"]}
    ban, nban = set(), 0
    files = [D + "/../gate_full/gate_set.jsonl"] + glob.glob(D + "/gate/*") + glob.glob(D + "/tests/*") + glob.glob(P + "2026-11-13_v3_data/rsn/data/final_v2/tests/*")
    for f in files:
        if f.endswith(".jsonl") and os.path.exists(f):
            for r in jl(f):
                if r.get("messages"):
                    ban.add(hh(user_last(r)))
                    nban += 1
    st = {"rows_per_category": collections.Counter(), "rows_per_generator": collections.Counter(), "drops": collections.Counter(), "ban_rows": nban}
    out, seen = [], set()
    for cat, fn, goal in PLAN:
        got, tries = 0, 0
        while got < goal and tries < goal * 60:
            tries += 1
            try:
                r = fn()
            except (KeyError, IndexError, TypeError, StopIteration, ValueError, AttributeError) as e:
                st["drops"]["%s:exc:%s" % (fn.__name__, type(e).__name__)] += 1
                continue
            if not r:
                st["drops"]["none"] += 1
                continue
            r["block"], r["src_real"], r["think"] = BLOCK, False, True
            r.setdefault("gold_calls", [])
            key = (json.dumps([m.get("content") for m in r["messages"] if m["role"] == "user"]), json.dumps(r["gold_calls"], sort_keys=True), r["messages"][-1]["content"])
            if key in seen:
                st["drops"]["dup"] += 1
                continue
            if hh(user_last(r)) in ban:
                st["drops"]["overlap_gate_test"] += 1
                continue
            e = CB.BC.check(r) + CB.audit_chat(r)
            if r["tools"] == "chat_r6":
                e += [] if all(tc["function"]["name"] in r6 for m in r["messages"] for tc in m.get("tool_calls") or []) else ["r6 name"]
            if e or GT.co2_bad(r):
                st["drops"]["check:" + (e[0].split(":")[0][:30] if e else "co2ppm")] += 1
                continue
            if sum(len(m.get("content") or "") + len(m.get("reasoning_content") or "") + len(json.dumps(m.get("tool_calls", ""))) for m in r["messages"][1:]) > 14000:
                st["drops"]["too_long"] += 1
                continue
            seen.add(key)
            out.append(r)
            got += 1
            st["rows_per_category"][cat] += 1
            st["rows_per_generator"][fn.__name__] += 1
    R.shuffle(out)
    for i, r in enumerate(out):
        r["id"] = "targeted-%s-%05d" % (r["family"][9:], i)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
    bad = [r for r in out if hh(user_last(r)) in ban]
    st["rows"] = len(out)
    st["overlap_check"] = "%d rows vs %d gate/test hashes: %d overlapping" % (len(out), len(ban), len(bad))
    json.dump(st, open(D + "/targeted_v1_stats.json", "w"), indent=1)
    print(json.dumps(st))


if __name__ == "__main__":
    main()
