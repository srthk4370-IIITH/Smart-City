"""big_chat.py: reasoner big run, block C (chat + tool use). Rows use the app's chat_r5 protocol (system r5, device tools executed by the
Python twin ToolsV3 on the training store, site tools by gen_chat_v4.SiteTools on the campus tree). Gold = executed results; finals are
templated from the results (numbers/ids only from results or the question, <= 3 sentences unless a format is asked). Hard rows (>= 2 calls)
carry the usual short numberless plan on the first assistant turn only. split="train" uses bank[:-2] phrasings, split="gate" bank[-2:].
Kinds (HOLES.md): find_get, find_empty, get_missing, unknown_sensor, followup_filter, forecast, faulty_vs_empty, rank_linked, short_status,
cooccur, fog (search/analytics, empty + long payloads), fmt_* (two lines / one word each / manager / simple / one sentence / shorter),
nocall (answer in context), units (ppm), site_* (unknown node, hard_hot AC chain, ac_flagged, bld_status, crit_under)."""
import collections
import json
import random
import re
import sys

P = "/mnt/c/Users/hp/Desktop/qidk/proofs/"
RSN = P + "2026-11-13_v3_data/rsn"
for p in (RSN, P + "2026-11-13_v3_data/core", P + "2026-10-29_rsn_v3/pipeline", P + "2026-10-25_reasoner_final/pipeline"):
    sys.path.insert(0, p)
import build_rsn as B  # noqa: E402
import gen_chat_v4 as C  # noqa: E402
import sitegraph as SG  # noqa: E402
import tools_v3_impl as T  # noqa: E402
import verify as V  # noqa: E402

SITE_TOOLS = {"get_site_tree", "nodes_under", "linked_equipment", "site_status"}
DOMS = {"air_quality": "air quality", "water": "water", "power": "power", "hvac": "HVAC", "weather": "weather", "occupancy": "occupancy"}
PRESETS = {"today": "today", "yesterday": "yesterday", "last_24h": "in the last 24 hours", "last_7d": "in the last 7 days", "last_30d": "in the last 30 days",
           "this_month": "this month"}
OCC = {"KH": "SR-OC-GW-KH95-01", "BK": "SR-OC-GW-BK95-01", "VN": "SR-OC-GW-VN95-02"}
PLANS = {"find_get": ["Find the incident first, then read its report.", "List the matching incidents, then open the newest one."],
         "faulty": ["Check the sensor history, then the room's occupancy before judging.", "Read the CO2 history, then whether the room was occupied."],
         "rank_linked": ["Find the hottest place first, then the unit that serves it.", "Rank the readings, then look up what serves the top room."],
         "cooccur": ["Read the incident report, then the incidents around it in other domains."]}
_W = {}


def world():
    if not _W:
        ex = T.ToolsV3()
        site = SG.campus_site()
        _W.update(ex=ex, site=site, ST=C.SiteTools(site, {}, {}), systems=B.chat_systems(),
                  sensors=ex.run("list_sensors", {})["sensors"])
    return _W


def pick(R, bank, split):
    assert len(bank) >= 4, bank[0]
    return R.choice(bank[-2:] if split == "gate" else bank[:-2])


def H(res, i):
    return next(x["text"] for x in res["summary"] if x["id"] == "H%d" % i)


def hnum(text, key):
    m = re.search(key + r" = ([+-]?[\d.]+) (\S+)", text)
    return m.group(1), m.group(2)


class RB:
    def __init__(s, R, split, hist=None, fog=None):
        W = world()
        s.R, s.W, s.split = R, W, split
        s.fog = fog or R.choices(["online", "offline", "timeout"], [40, 50, 10])[0]
        s.msgs = [{"role": "system", "content": B.r5_system(R.choice(W["systems"][s.fog]))}]
        for q, a in (hist or []):
            s.msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        s.k, s.gold, s.res, s.hist = 0, [], [], hist
        W["ex"].qid = 0

    def ask(s, q):
        s.msgs.append({"role": "user", "content": q})
        s.q = q

    def call(s, name, args, plan=None):
        W = s.W
        res = W["ST"].call(name, dict(args)) if name in SITE_TOOLS else W["ex"].run(name, dict(args))
        s.k += 1
        a = {"role": "assistant", "content": "", "tool_calls": [C.tc(s.k, name, args)]}
        if plan and s.k == 1:
            a["reasoning_content"] = plan
        s.msgs += [a, {"role": "tool", "tool_call_id": "call_%d" % s.k, "content": json.dumps(res, ensure_ascii=False)}]
        s.gold.append({"name": name, "args": args})
        s.res.append(res)
        return res

    def done(s, kind, final, **kw):
        if not final or not final.strip():
            return None
        s.msgs.append({"role": "assistant", "content": final})
        r = {"id": "x", "family": "big_chat:" + kind, "tools": "chat_r5", "think": True, "hard": len(s.gold) >= 2, "fog": s.fog, "hinglish": False,
             "site_id": "iiith", "reasoning_type": "none", "hops": 0, "messages": s.msgs, "gold_calls": s.gold, "multi_turn": bool(s.hist), "kind": kind}
        r.update(kw)
        return r


def cap(t):
    return t[:1].upper() + t[1:]


def incs(R, **flt):
    """recent real incident ids (store) matching a filter"""
    ex = world()["ex"]
    ex.qid = 0
    return ex.run("find_incidents", dict(time={"preset": "last_30d"}, limit=10, **flt)).get("items", [])


def tail_of(inc):
    t = inc["title"]
    return t


# ----------------------------------------------------------------------------------------------------------- kinds
def k_find_get(R, split):
    W = world()
    d = R.choice(list(DOMS))
    sv = R.choice([None, "critical", "warning"])
    bld = R.choice([None, "KH", "VN", "BK"])
    flt = {"domain": d}
    if sv:
        flt["severity"] = [sv]
    if bld:
        flt["node"] = bld
    if not incs(R, **flt):
        return None
    where = {None: "", "KH": " in KH", "VN": " in VN", "BK": " in BK"}[bld]
    qs = ["What was the latest %s%s incident%s?" % (sv or "", " " + DOMS[d], where), "Tell me about the newest %s %s incident%s." % (sv or "open", DOMS[d], where),
          "Any recent %s%s problem%s? What caused it?" % (sv + " " if sv else "", DOMS[d], where), "Explain the last %s%s incident%s." % (sv + " " if sv else "", DOMS[d], where),
          "latest %s incident%s, why did it happen" % (DOMS[d], where), "Why did the last %s alert%s fire?" % (DOMS[d], where),
          "What is the most recent %s%s event%s and its cause?" % (sv + " " if sv else "", DOMS[d], where), "Give me the story of the latest %s%s incident%s." % (sv + " " if sv else "", DOMS[d], where)]
    rb = RB(R, split)
    rb.ask(re.sub(r"\s+", " ", pick(R, qs, split)).replace(" incident incident", " incident"))
    fi = rb.call("find_incidents", dict(time={"preset": "last_30d"}, limit=3, **flt), plan=R.choice(PLANS["find_get"]))
    if not fi.get("items"):
        return None
    iid = fi["items"][0]["id"]
    g = rb.call("get_incident", {"id": iid})
    if not g.get("root_cause") and R.random() < 0.8:
        return None
    rc = g.get("root_cause") or "no root cause was written yet"
    state = "It is closed: %s." % g["outcome"].replace("_", " ") if g.get("outcome") else "It is still %s." % g.get("workflow", "open").replace("_", " ")
    f = R.choice(["[%s] %s is %s: %s. %s" % (iid, g["title"], g["severity"], rc, state), "The latest is [%s], %s (%s). Cause: %s. %s" % (iid, g["title"], g["severity"], rc, state)])
    return rb.done("find_get", f)


def k_find_empty(R, split):
    d = R.choice(["weather", "occupancy", "water", "hvac"])
    sv = R.choice(["critical", "sensor_fault"])
    pr = R.choice(["today", "yesterday", "last_24h"])
    rb = RB(R, split)
    ex = rb.W["ex"]
    if ex.run("find_incidents", dict(time={"preset": pr}, domain=d, severity=[sv], limit=3)).get("items"):
        return None
    qs = ["Any %s %s incidents %s?" % (sv.replace("_", " "), DOMS[d], PRESETS[pr]), "Were there %s %s alerts %s?" % (sv.replace("_", " "), DOMS[d], PRESETS[pr]),
          "Show %s incidents in %s %s." % (sv.replace("_", " "), DOMS[d], PRESETS[pr]), "is there a %s %s incident %s" % (sv.replace("_", " "), DOMS[d], PRESETS[pr]),
          "Did %s raise a %s incident %s?" % (DOMS[d], sv.replace("_", " "), PRESETS[pr]), "Check %s %s incidents %s", "%s: any %s incidents %s?" % (DOMS[d], sv.replace("_", " "), PRESETS[pr]),
          "Have we had %s %s incidents %s?" % (sv.replace("_", " "), DOMS[d], PRESETS[pr])]
    qs[5] = qs[5] % (sv.replace("_", " "), DOMS[d], PRESETS[pr])
    rb.ask(pick(R, qs, split))
    rb.call("find_incidents", dict(time={"preset": pr}, domain=d, severity=[sv], limit=3))
    return rb.done("find_empty", R.choice(["No %s %s incidents %s on the device." % (sv.replace("_", " "), DOMS[d], PRESETS[pr]),
                                           "None: there is no %s %s incident %s." % (sv.replace("_", " "), DOMS[d], PRESETS[pr])]))


def k_get_missing(R, split):
    ex = world()["ex"]
    n = R.choice([9999, 9100, 8888, 7777, 6543, 5000, 4999])
    iid = "INC-%04d" % (n + R.randrange(0, 90))
    qs = ["Show me %s." % iid, "What happened in %s?" % iid, "Summarise %s for me." % iid, "details of %s" % iid, "Who handled %s?" % iid, "Is %s still open?" % iid,
          "Tell me about %s." % iid, "What was the cause of %s?" % iid]
    rb = RB(R, split)
    rb.ask(pick(R, qs, split))
    res = rb.call("get_incident", {"id": iid})
    if "error" not in res:
        return None
    return rb.done("get_missing", R.choice(["%s is not on this device: there is no incident with that id. I can list the recent incidents if you want." % iid,
                                            "I cannot find %s; the device has no incident with that id. Check the number or ask for the latest incidents." % iid]), allow_error=True)


def k_unknown_sensor(R, split):
    code = R.choice(["ZZ99", "QQ-204", "XY12", "ZZ-317", "QQ45", "WW07"])
    m = R.choice(["co2", "temp", "pm25", "power_kw"])
    nm = {"co2": "CO2", "temp": "temperature", "pm25": "PM2.5", "power_kw": "power"}[m]
    qs = ["What is the %s at %s?" % (nm, code), "status of sensor %s-%s" % (code, m), "Is the %s sensor in %s working?" % (nm, code), "show the %s in room %s" % (nm, code),
          "How is %s doing right now?" % code, "Current %s at %s?" % (nm, code), "Any %s data for %s?" % (nm, code), "Read me the %s from %s." % (nm, code)]
    rb = RB(R, split)
    rb.ask(pick(R, qs, split))
    if R.random() < 0.5:
        res = rb.call("current_levels", {"metric": m, "location": code})
        ok = not res.get("items")
    else:
        res = rb.call("list_sensors", {"location": code})
        ok = not res.get("sensors")
    if not ok:
        return None
    return rb.done("unknown_sensor", allow_error=("error" in res), final= R.choice(["I cannot find any sensor for %s on this device, so I have no %s reading for it. Check the name or ask me to list the sensors." % (code, nm),
                                               "There is no sensor matching %s on this device; I will not guess a value. Tell me a building or ask for the sensor list." % code]))


def _count_ans(res, d, pr, sv=None):
    return "There %s %d %s%s incident%s %s." % ("was" if res["count"] == 1 else "were", res["count"], (sv.replace("_", " ") + " ") if sv else "", DOMS[d], "" if res["count"] == 1 else "s", PRESETS[pr])


def k_followup_filter(R, split):
    ex = world()["ex"]
    d1, d2 = R.sample(list(DOMS), 2)
    p1, p2 = R.sample(list(PRESETS), 2)
    mode = R.choice(["domain", "period", "severity"])
    sv = R.choice(["critical", "warning"])
    rbq = RB(R, split)
    ex.qid = 0
    a1 = ex.run("count_incidents", dict(time={"preset": p1}, domain=d1))
    q1 = "How many %s incidents %s?" % (DOMS[d1], PRESETS[p1])
    h = [(q1, _count_ans(a1, d1, p1))]
    if mode == "domain":
        qs = ["And for %s?" % DOMS[d2], "what about %s?" % DOMS[d2], "same but %s" % DOMS[d2], "Now %s." % DOMS[d2], "How about %s?" % DOMS[d2], "and %s?" % DOMS[d2],
              "Same question for %s." % DOMS[d2], "ok and %s?" % DOMS[d2]]
        args, ans = dict(time={"preset": p1}, domain=d2), lambda r: _count_ans(r, d2, p1)
    elif mode == "period":
        qs = ["And %s?" % PRESETS[p2], "what about %s?" % PRESETS[p2], "same %s" % PRESETS[p2], "How about %s?" % PRESETS[p2], "and %s?" % PRESETS[p2], "Now %s." % PRESETS[p2],
              "Same for the period: %s?" % PRESETS[p2], "ok %s?" % PRESETS[p2]]
        args, ans = dict(time={"preset": p2}, domain=d1), lambda r: _count_ans(r, d1, p2)
    else:
        qs = ["Only the %s ones?" % sv, "and just the %s?" % sv, "how many of those are %s" % sv, "filter to %s." % sv, "What about only %s?" % sv, "just %s please" % sv,
              "Of those, the %s ones?" % sv, "ok only %s" % sv]
        args, ans = dict(time={"preset": p1}, domain=d1, severity=[sv]), lambda r: _count_ans(r, d1, p1, sv)
    rb = RB(R, split, hist=h)
    rb.ask(pick(R, qs, split))
    r = rb.call("count_incidents", args)
    return rb.done("followup_" + mode, ans(r))


def _sens(m, bld=None):
    return [s for s in world()["sensors"] if s["metric"] == m and (bld is None or ("-" + bld) in s["node"] or (" " + bld) in s["location"])]


def k_forecast(R, split):
    m = R.choice(["co2", "co2", "pm25", "temp"])
    s = R.choice(_sens(m))
    nm = {"co2": "CO2", "pm25": "PM2.5", "temp": "temperature"}[m]
    lim = {"co2": 1000, "pm25": 60, "temp": 30}[m]
    qs = ["When will %s at %s cross %d?" % (nm, s["node"], lim), "Will %s at %s go above %d tonight?" % (nm, s["node"], lim), "Forecast %s for %s this afternoon." % (nm, s["node"]),
          "How long until %s on %s reaches %d?" % (nm, s["node"], lim), "predict when %s %s passes %d" % (s["node"], nm, lim), "Is %s on %s heading for %d?" % (nm, s["node"], lim),
          "Estimate the time %s at %s hits %d." % (nm, s["node"], lim), "Will %s at %s keep rising?" % (nm, s["node"])]
    rb = RB(R, split)
    rb.ask(pick(R, qs, split))
    r = rb.call("get_sensor_history", dict(node=s["node"], metric=m, time={"preset": "last_24h"}))
    if "summary" not in r:
        return None
    last, u = hnum(H(r, 5), "last")
    tr, tu = hnum(H(r, 6), "trend")
    mx, _ = hnum(H(r, 4), "max")
    q = rb.q
    mlim = re.search(r"\b(%d)\b" % lim, q)
    f = R.choice(["I have no forecasting tool, so I cannot give a time. %s at %s is %s %s now; over the last day the trend is %s %s and the peak was %s %s." % (nm, s["node"], last, u, tr, tu, mx, u),
                  "I can only report what the readings show: %s at %s is %s %s now, trend %s %s over the last 24 hours, peak %s %s. I will not guess a crossing time." % (nm, s["node"], last, u, tr, tu, mx, u)])
    return rb.done("forecast", f)


def _facts_h(r):
    out = {}
    for k, key in ((2, "mean"), (3, "min"), (4, "max"), (5, "last"), (6, "trend")):
        out[key] = hnum(H(r, k), key)
    return out


def k_faulty_vs_empty(R, split):
    s = R.choice(_sens("co2"))
    bld = re.search(r"SR-AQ-([A-Z]{2})", s["node"]).group(1)
    if bld not in OCC:
        return None
    pr = R.choice(["last_24h", "last_7d", "last_30d", "today"])
    qs = ["Is the CO2 sensor %s faulty or is the room just empty?" % s["node"], "%s CO2 looks odd: bad sensor or nobody in the room?" % s["node"],
          "Why is %s CO2 so low, is the meter broken or is the room unused?" % s["node"], "check if %s is faulty or the room is empty" % s["node"],
          "CO2 on %s %s: sensor problem or just no people?" % (s["node"], PRESETS[pr]), "Is %s stuck, or is it simply empty there?" % s["node"],
          "Faulty meter or empty room for %s?" % s["node"], "Can you tell whether %s is broken or the room is vacant?" % s["node"]]
    rb = RB(R, split)
    rb.ask(pick(R, qs, split))
    r1 = rb.call("get_sensor_history", dict(node=s["node"], metric="co2", time={"preset": pr}), plan=R.choice(PLANS["faulty"]))
    r2 = rb.call("get_sensor_history", dict(node=OCC[bld], metric="occ", time={"preset": pr}))
    if "summary" not in r1 or "summary" not in r2:
        return None
    f1, f2 = _facts_h(r1), _facts_h(r2)
    mn, mx, me, oc = float(f1["min"][0]), float(f1["max"][0]), float(f1["mean"][0]), float(f2["mean"][0])
    if mx > 5000 or mn < 250:
        v = "fault"
        f = "The readings are not credible: CO2 ranged %s to %s ppm (mean %s), outside what a working sensor reads, and the room occupancy mean was %s. That points to a faulty sensor, not an empty room." % (f1["min"][0], f1["max"][0], f1["mean"][0], f2["mean"][0])
    elif oc >= 0.08 and mx - mn >= 150:
        v = "people"
        f = "The room was in use: occupancy averaged %s and CO2 moved between %s and %s ppm with it. The sensor looks fine." % (f2["mean"][0], f1["min"][0], f1["max"][0])
    elif oc < 0.08:
        v = "empty"
        f = "The room was mostly empty (occupancy mean %s) and CO2 stayed between %s and %s ppm, so low readings are expected. Nothing suggests a faulty sensor." % (f2["mean"][0], f1["min"][0], f1["max"][0])
    else:
        v = "flat"
        f = "Occupancy averaged %s but CO2 barely moved (%s to %s ppm). That could be a stuck sensor: check it on site." % (f2["mean"][0], f1["min"][0], f1["max"][0])
    row = rb.done("faulty_vs_empty", f, verdict=v)
    return row


def k_rank_linked(R, split):
    W = world()
    ex, ST = W["ex"], W["ST"]
    cands = W.get("rank_cands")
    for m in (() if cands is not None else ("temp", "co2", "rh", "pm25")):
        for pr in ("today", "last_24h", "last_7d"):
            for loc in (None, "KH", "KH03"):
                a = dict(metric=m, domain="air_quality", time={"preset": pr}, limit=1)
                if loc:
                    a["location"] = loc
                ex.qid = 0
                r = ex.run("rank_readings", a)
                it = (r.get("items") or [None])[0]
                mm = it and re.search(r"SR-AQ-([A-Z]{2})(\d\d)-(\d\d)", it["node"])
                if mm and ST.find("%s-%s-AQ%s" % mm.groups()):
                    cands = (cands or []) + [(m, pr, loc, a, it, "%s-%s-AQ%s" % mm.groups())]
    W["rank_cands"] = cands = cands or []
    if not cands:
        return None
    m, pr, loc, a, it, room = R.choice(cands)
    nm = {"temp": "hottest", "co2": "highest CO2", "rh": "most humid", "pm25": "highest PM2.5"}[m]
    pw = PRESETS[pr]
    qs = ["Which room is %s %s and what serves it?" % (nm, pw), "Where is it %s %s? Is the AC unit there OK?" % (nm, pw), "Find the %s room %s and the equipment that serves it." % (nm, pw),
          "What is the %s spot %s, and is its AC fine?" % (nm, pw), "%s room %s: which unit cools it?" % (cap(nm), pw), "Which room is %s %s and is the unit serving it healthy?" % (nm, pw),
          "Tell me the %s room %s, then check its AC." % (nm, pw), "Is the AC ok in the %s room %s?" % (nm, pw)]
    if loc:
        qs = [q.replace(" room", " room in %s" % loc, 1) if " room" in q else q + " (in %s)" % loc for q in qs]
    rb = RB(R, split)
    rb.ask(pick(R, qs, split))
    r = rb.call("rank_readings", a, plan=R.choice(PLANS["rank_linked"]))
    lk = rb.call("linked_equipment", dict(node=room, link="serves", direction="in"))
    if lk.get("found") is False or not lk.get("links"):
        return None
    u = lk["links"][0]
    if u["status"] == "normal":
        tail = "It is normal with no open incident, so check the room itself (doors, crowd, sun)."
    else:
        tail = "It is %s%s." % (u["status"], (" " + C.cite(u["open"])) if u["open"] else "")
    f = "%s: %s %s at %s on %s. It is served by %s. %s" % (it["location"], it["value"], it["unit"], it["at"][11:], it["at"][:10], u["name"], tail)
    return rb.done("rank_linked", f)


def k_short_status(R, split):
    m = R.choice(["pm25", "co2", "temp", "rh", "power_kw"])
    s = R.choice(_sens(m))
    nm = {"pm25": "PM2.5", "co2": "CO2", "temp": "temperature", "rh": "humidity", "power_kw": "power"}[m]
    loc = re.search(r"([A-Z]{2})(\d\d)", s["node"]).group(0)
    qs = ["Is the %s sensor in %s working?" % (nm, loc), "is %s at %s ok?" % (nm, loc), "%s sensor %s alive?" % (nm, loc), "Is %s reporting at %s?" % (nm, loc),
          "Is the %s sensor at %s healthy?" % (nm, loc), "check %s %s sensor, is it fine" % (loc, nm), "Quick check: is %s working at %s?" % (nm, loc), "%s at %s: any problem with the sensor?" % (nm, loc)]
    rb = RB(R, split)
    rb.ask(pick(R, qs, split))
    r = rb.call("current_levels", dict(metric=m, location=loc))
    it = next((x for x in r.get("items", []) if x["node"] == s["node"]), (r.get("items") or [None])[0])
    if not it:
        return None
    f = R.choice(["Yes: %s is reporting %s %s (status %s)." % (it["node"], it["last"], it["unit"], it["status"]), "Working: the last %s reading is %s %s, status %s (%s)." % (nm, it["last"], it["unit"], it["status"], it["node"])])
    if it["status"] != "normal":
        f = "It reports, but the status is %s: %s %s on %s." % (it["status"], it["last"], it["unit"], it["node"])
    return rb.done("short_status", f)


def twin_cooccur(ex, iid, window=120):
    a = ex.run("get_incident", {"id": iid})
    if "error" in a:
        return a
    import datetime as dt
    t0 = dt.datetime.strptime(a["time"], "%Y-%m-%d %H:%M")
    items = []
    d0 = set(next((i.get("domains") for i in ex.run("find_incidents", dict(time={"from": a["time"][:10], "to": (t0 + dt.timedelta(days=2)).strftime("%Y-%m-%d")}, limit=10)).get("items", []) if i["id"] == iid), []) or [])
    for i in ex.run("find_incidents", dict(time={"from": (t0 - dt.timedelta(days=1)).strftime("%Y-%m-%d"), "to": (t0 + dt.timedelta(days=2)).strftime("%Y-%m-%d")}, limit=10)).get("items", []):
        if i["id"] == iid:
            continue
        off = int((dt.datetime.strptime(i["time"], "%Y-%m-%d %H:%M") - t0).total_seconds() // 60)
        if abs(off) <= window and not (set(i["domains"]) & d0 and False):
            items.append({"id": i["id"], "time": i["time"], "title": i["title"], "severity": i["severity"], "label": i["label"], "domains": i["domains"], "offset_min": off})
    return {"anchor": {"id": iid, "time": a["time"], "title": a["title"], "domains": sorted(d0)}, "window_min": window, "other_domains_only": True, "total": len(items), "items": items[:5]}


def k_cooccur(R, split):
    ex = world()["ex"]
    cand = [i for d in ("power", "hvac", "air_quality") for i in incs(R, domain=d)[:3]]
    if not cand:
        return None
    a = R.choice(cand)
    iid = a["id"]
    qs = ["Did something else cause %s?" % iid, "What else happened around %s and did it cause it?" % iid, "Is %s related to other incidents, did one trigger the other?" % iid,
          "Which incidents overlap %s, and are they the cause?" % iid, "Was %s caused by another problem nearby?" % iid, "Check what co-occurred with %s. Is that the cause?" % iid,
          "Did the AC or power trip cause %s?" % iid, "Are there linked incidents for %s? What caused it?" % iid]
    rb = RB(R, split)
    rb.ask(pick(R, qs, split))
    g = rb.call("get_incident", {"id": iid}, plan=R.choice(PLANS["cooccur"]))
    res = twin_cooccur(world()["ex"], iid)
    # replay the call through the builder so the transcript matches
    rb.k += 1
    rb.msgs += [{"role": "assistant", "content": "", "tool_calls": [C.tc(rb.k, "co_occurring_incidents", {"id": iid, "window_min": 120})]},
                {"role": "tool", "tool_call_id": "call_%d" % rb.k, "content": json.dumps(res, ensure_ascii=False)}]
    rb.gold.append({"name": "co_occurring_incidents", "args": {"id": iid, "window_min": 120}})
    rc = g.get("root_cause") or "no root cause was written"
    if res["total"] == 0:
        f = "Nothing else was flagged within 120 minutes of [%s]. Its report says: %s." % (iid, rc)
    else:
        its = res["items"][:2]
        lst = " and ".join("[%s] (%s)" % (i["id"], "/".join(i["domains"])) for i in its)
        f = "Within 120 minutes of [%s] the device also logged %s. That timing alone does not show one caused the other; the report of [%s] says: %s." % (iid, lst, iid, rc)
    return rb.done("cooccur", f)


def _month(ym):
    import calendar
    y, m = map(int, ym.split("-"))
    return "%s-%02d-01" % (y, m), "%s-%02d-%02d" % (y, m, calendar.monthrange(y, m)[1])


def k_fog(R, split):
    ex = world()["ex"]
    mo = R.choice(["2026-06", "2026-07", "2026-08", "2026-09", "2026-05", "2026-04"])
    d = R.choice(["power", "air_quality", "water", "hvac"])
    a, b = _month(mo)
    mname = {"04": "April", "05": "May", "06": "June", "07": "July", "08": "August", "09": "September"}[mo[5:]]
    kind = R.choice(["search", "search", "trend", "empty"])
    hist = None
    if kind == "search" and R.random() < 0.4:                          # multi-turn: the follow-up names only the month, the domain comes from the earlier turn
        om = R.choice([m_ for m_ in ("2026-06", "2026-07", "2026-08", "2026-09") if m_ != mo])
        oa, ob_ = _month(om)
        ex.qid = 0
        c0 = ex.run("count_incidents", dict(time={"from": oa, "to": ob_}, domain=d))["count"]
        omn = {"06": "June", "07": "July", "08": "August", "09": "September"}[om[5:]]
        hist = [("How many %s incidents in %s?" % (DOMS[d], omn), "The device store shows %d %s incidents in %s." % (c0, DOMS[d], omn))]
    rb = RB(R, split, hist=hist, fog=R.choice(["offline", "timeout"]))
    if kind == "empty":
        d = "weather"
        a, b = _month("2026-05")
        mname = "May"
    if kind in ("search", "empty"):
        qs = ["Which %s incidents did we have in %s?" % (DOMS[d], mname), "List %s incidents from %s." % (DOMS[d], mname), "What went wrong with %s in %s?" % (DOMS[d], mname),
              "Show the %s history for %s." % (DOMS[d], mname), "Any %s trouble back in %s?" % (DOMS[d], mname), "%s incidents %s, top ones please" % (cap(DOMS[d]), mname),
              "Pull up %s incidents of %s." % (DOMS[d], mname), "What %s issues happened in %s?" % (DOMS[d], mname)]
        if hist:
            qs = ["And %s?" % mname, "what about %s?" % mname, "same for %s" % mname, "How about %s?" % mname, "and in %s?" % mname, "ok %s too" % mname, "Now %s." % mname, "And what about %s?" % mname]
        rb.ask(pick(R, qs, split))
        ex.qid = 0
        raw = ex.run("find_incidents", dict(time={"from": a, "to": b}, domain=d, limit=10))
        res = {"source": "device_fallback", "fog": "unreachable", "total": raw.get("total", len(raw.get("items", []))),
               "items": [dict(i, root_cause=None) for i in raw.get("items", [])][:10],
               "coverage": {"source": "device", "complete": False, "note": "fog unreachable: answered from the device store"}}
        rb.k += 1
        args = dict(time={"from": a, "to": b}, domain=d)
        rb.msgs += [{"role": "assistant", "content": "", "tool_calls": [C.tc(rb.k, "fog_search_history", args)]}, {"role": "tool", "tool_call_id": "call_%d" % rb.k, "content": json.dumps(res, ensure_ascii=False)}]
        rb.gold.append({"name": "fog_search_history", "args": args})
        if not res["items"]:
            f = "The device store has no %s incidents for %s; the fog is unreachable, so older history is not available." % (DOMS[d], mname)
        else:
            top = res["items"][:2]
            f = "The fog is unreachable, so this is from the device store: %d %s incidents in %s. The newest are %s." % (res["total"], DOMS[d], mname, " and ".join("[%s] %s" % (i["id"], i["title"]) for i in top))
        return rb.done("fog_" + kind + ("_followup" if hist else ""), f)
    qs = ["Show the monthly incident trend this year.", "How have incidents changed month by month?", "Incident counts per month so far?", "What is the monthly trend of incidents?",
          "Give me incidents per month for 2026.", "Which month had the most incidents this year?", "Is the incident count going up or down by month?", "Month by month incident numbers please."]
    rb.ask(pick(R, qs, split))
    buckets = []
    for ym in ("2026-06", "2026-07", "2026-08", "2026-09", "2026-10"):
        x, y = _month(ym)
        ex.qid = 0
        buckets.append({"bucket": ym, "count": ex.run("count_incidents", dict(time={"from": x, "to": y}))["count"]})
    res = {"source": "device_fallback", "fog": "unreachable", "analysis": "incident_trend", "bucket": "month", "buckets": buckets,
           "coverage": {"source": "device", "complete": False, "from": "2026-06-24", "to": "2026-10-22 12:00", "note": "fog unreachable: counts from the device store (since 2026-06-24)"}}
    rb.k += 1
    args = {"analysis": "incident_trend", "time": {"preset": "this_year"}, "bucket": "month"}
    rb.msgs += [{"role": "assistant", "content": "", "tool_calls": [C.tc(rb.k, "fog_analytics", args)]}, {"role": "tool", "tool_call_id": "call_%d" % rb.k, "content": json.dumps(res, ensure_ascii=False)}]
    rb.gold.append({"name": "fog_analytics", "args": args})
    top = max(buckets, key=lambda x: x["count"])
    f = "The fog is unreachable, so these counts come from the device store since 2026-06-24: the busiest month is %s with %d incidents, the latest is %s with %d." % (top["bucket"], top["count"], buckets[-1]["bucket"], buckets[-1]["count"])
    return rb.done("fog_trend", f)


def _opens(rb):
    return rb.call("open_incidents", {})


def k_fmt(R, split):
    sub = R.choice(["two_lines", "one_word", "manager", "simple", "one_sentence", "shorter"])
    ex = world()["ex"]
    if sub in ("two_lines", "manager", "simple", "one_sentence"):
        cand = incs(R, severity=[R.choice(["critical", "warning"])])
        if not cand:
            return None
        iid = R.choice(cand)["id"]
        tail = {"two_lines": ["Summarise %s in two lines." % iid, "Give me %s in 2 lines." % iid, "two line summary of %s" % iid, "Explain %s, two lines max." % iid, "Short two-line version of %s." % iid, "%s in two lines please" % iid],
                "manager": ["Summarise %s for my manager." % iid, "Explain %s for my manager, no jargon." % iid, "manager summary of %s" % iid, "Write %s up for my boss." % iid, "I need to brief my manager on %s." % iid, "Brief for my manager: %s" % iid],
                "simple": ["Explain %s in simple words." % iid, "what is %s, in plain words" % iid, "In simple words, what happened in %s?" % iid, "Explain %s like I am new here." % iid, "Plain-language version of %s please." % iid, "%s in simple words" % iid],
                "one_sentence": ["Describe %s in exactly one sentence." % iid, "one sentence on %s" % iid, "In one sentence, what is %s?" % iid, "Sum up %s in a single sentence." % iid, "%s: one sentence only" % iid, "Say what %s is in one sentence." % iid]}[sub]
        rb = RB(R, split)
        rb.ask(pick(R, tail, split))
        g = rb.call("get_incident", {"id": iid})
        rc = g.get("root_cause") or "the cause is not written yet"
        sv = g["severity"].replace("_", " ")
        what = re.sub(r"^(\w+) ", lambda m: m.group(1).upper() + " " if m.group(1).lower() in ("co2", "pm25", "tds", "ph", "pf") else m.group(1) + " ", g["title"], count=1).split(":")[0]
        place = g["title"].split(": ", 1)[-1]
        if sub == "two_lines":
            f = "[%s] %s: %s.\n%s." % (iid, g["title"], sv, cap(rc))
        elif sub == "manager":
            f = "One %s alert at %s: %s. %s." % (sv, place, what.lower(), "The team has handled it" if g.get("outcome") else "It still needs a decision")
        elif sub == "simple":
            f = "A sensor at %s raised a %s alert (%s). In short: %s. %s." % (place, sv, what.lower(), rc, "It is closed now" if g.get("outcome") else "It is still open")
        else:
            f = "[%s] is a %s alert at %s about %s." % (iid, sv, place, what.lower())
        return rb.done("fmt_" + sub, f, fmt=sub)
    if sub == "one_word":
        qs = ["List the open incidents, one word each.", "Open incidents, one word each please.", "what is waiting for a decision? one word per incident", "Name the top pending incidents in one word each.",
              "Pending incidents: one word each.", "one word each: the incidents to handle first"]
        rb = RB(R, split)
        rb.ask(pick(R, qs, split))
        o = _opens(rb)
        if not o.get("top_pending"):
            return None
        ws = [re.split(r"[ :]", i["title"])[0] for i in o["top_pending"][:3]]
        ws = [w.upper() if w.lower() in ("co2", "pm25", "tds", "ph", "pf") else w.capitalize() for w in ws]
        return rb.done("fmt_one_word", ", ".join(ws) + ".", fmt=sub)
    cand = incs(R, severity=["critical"]) or incs(R)
    if not cand:
        return None
    a = R.choice(cand)
    ex.qid = 0
    qa = "What is the latest critical incident?"
    first = "[%s] %s is critical (%s)." % (a["id"], a["title"], a["severity"])
    qs = ["Make that shorter, 8 words.", "shorter please, 8 words max", "Shorten it to 8 words.", "Say it in 8 words.", "8 words only, please", "Cut that down: 8 words."]
    rb = RB(R, split, hist=[(qa, first)])
    rb.ask(pick(R, qs, split))
    wd = a["title"].split(":")[0]
    f = "[%s] %s, critical." % (a["id"], " ".join(wd.split()[:5]))
    if len(f.split()) > 8:
        return None
    return rb.done("fmt_shorter", f, fmt=sub, nocall=True)


def k_nocall(R, split):
    ex = world()["ex"]
    m = R.choice(["co2", "temp"])
    ex.qid = 0
    r = ex.run("rank_readings", dict(metric=m, time={"preset": "today"}, limit=2))
    its = r.get("items", [])
    if len(its) < 2 or its[0]["value"] == its[1]["value"]:
        return None
    nm = {"co2": "CO2", "temp": "temperature"}[m]
    q1 = "Give me the top two %s readings today." % nm
    a1 = "Top %s today: %s %s %s at %s, then %s %s %s at %s." % (nm, its[0]["location"], its[0]["value"], its[0]["unit"], its[0]["at"][11:], its[1]["location"], its[1]["value"], its[1]["unit"], its[1]["at"][11:])
    qs = ["Which of those was higher?", "which one is higher", "And the highest one was where?", "Which place was worse?", "Remind me which was the top one.", "Which was first?",
          "So which location should I check first?", "Which one is higher, then?"]
    rb = RB(R, split, hist=[(q1, a1)])
    rb.ask(pick(R, qs, split))
    f = R.choice(["%s: %s %s at %s." % (its[0]["location"], its[0]["value"], its[0]["unit"], its[0]["at"][11:]), "The first one, %s, with %s %s." % (its[0]["location"], its[0]["value"], its[0]["unit"])])
    return rb.done("nocall", f, nocall=True)


def k_units(R, split):
    m = R.choice(["co2", "pm25"])
    nm = {"co2": "CO2", "pm25": "PM2.5"}[m]
    pr = R.choice(["today", "last_7d", "last_30d"])
    qs = ["What is the highest %s %s, and where?" % (nm, PRESETS[pr]), "Peak %s %s?" % (nm, PRESETS[pr]), "Where was %s highest %s?" % (nm, PRESETS[pr]),
          "worst %s reading %s" % (nm, PRESETS[pr]), "Which sensor saw the top %s %s?" % (nm, PRESETS[pr]), "Highest %s %s, with the time." % (nm, PRESETS[pr]),
          "Give the maximum %s %s and its place." % (nm, PRESETS[pr]), "How high did %s get %s?" % (nm, PRESETS[pr])]
    rb = RB(R, split)
    rb.ask(pick(R, qs, split))
    r = rb.call("rank_readings", dict(metric=m, time={"preset": pr}, limit=1))
    if not r.get("items"):
        return None
    it = r["items"][0]
    if it["value"] > 5000:
        return None
    f = "The highest %s %s is %s %s at %s (%s), status %s." % (nm, PRESETS[pr], it["value"], it["unit"], it["location"], it["at"], it["status"])
    return rb.done("units", f)


def k_site(R, split):
    W = world()
    kind = R.choices(["unknown", "hard_hot", "ac_flagged", "bld_status", "crit_under", "room_contents"], [4, 3, 2, 1, 1, 1])[0]
    fog = R.choices(["online", "offline", "timeout"], [45, 45, 10])[0]
    sysm = B.r5_system(R.choice(W["systems"][fog]), W["site"])
    r, why = C.make_row(R, W["site"], sysm, kind)
    if r is None or C.check_row(r):
        return None
    r["fog"], r["kind"] = fog, "site_" + kind
    r.pop("_ov", None)
    r["family"] = "big_chat:site_" + kind
    return r


KINDS = [("find_get", k_find_get, 450), ("find_empty", k_find_empty, 150), ("get_missing", k_get_missing, 120), ("unknown_sensor", k_unknown_sensor, 200),
         ("followup_filter", k_followup_filter, 450), ("forecast", k_forecast, 300), ("faulty_vs_empty", k_faulty_vs_empty, 350), ("rank_linked", k_rank_linked, 350),
         ("short_status", k_short_status, 250), ("cooccur", k_cooccur, 300), ("fog", k_fog, 400), ("fmt", k_fmt, 450), ("nocall", k_nocall, 250), ("units", k_units, 150),
         ("site", k_site, 500)]
TOOL_CRITICAL = {"find_get", "get_missing", "unknown_sensor", "followup_filter", "forecast", "faulty_vs_empty", "rank_linked", "cooccur", "fog"}


def check(r):
    """gen-time check = gen_chat_v4.check_row (verify.check_chat grounded numbers/ids + schema/enum of every call + think rules);
    allow_error rows may carry a tool error result; no-call rows are grounded in the earlier assistant turns"""
    e = C.check_row(r)
    if r.get("allow_error"):
        e = [x for x in e if x != "tool_error"]
    if r.get("nocall"):
        hist = " ".join(m["content"] for m in r["messages"][1:-1] if m["role"] == "assistant")
        fin = r["messages"][-1]["content"]
        e = [x for x in e if not x.startswith(("num:", "inc:"))]
        e += ["inc:" + t for t in re.findall(r"INC-\d+", fin) if t not in hist]
        e += ["num:" + n for n in re.findall(r"(?<![\w.-])\d+(?:\.\d+)?(?![\w])", re.sub(r"\d\d:\d\d", "", fin)) if n not in hist]
        if r["gold_calls"]:
            e.append("nocall_has_call")
    return e


# ----------------------------------------------------------------------------------------------------------- live executor (gate)
def twin_fog_search(args):
    ex = world()["ex"]
    t = args.get("time") or {}
    raw = ex.run("find_incidents", dict(time=t, limit=10, **{k: v for k, v in args.items() if k in ("domain", "severity", "node", "metric")}))
    return {"source": "device_fallback", "fog": "unreachable", "total": raw.get("total", len(raw.get("items", []))),
            "items": [dict(i, root_cause=None) for i in raw.get("items", [])][:10],
            "coverage": {"source": "device", "complete": False, "note": "fog unreachable: answered from the device store"}}


def twin_fog_trend(args):
    ex = world()["ex"]
    buckets = []
    for ym in ("2026-06", "2026-07", "2026-08", "2026-09", "2026-10"):
        x, y = _month(ym)
        buckets.append({"bucket": ym, "count": ex.run("count_incidents", dict(time={"from": x, "to": y}))["count"]})
    return {"source": "device_fallback", "fog": "unreachable", "analysis": "incident_trend", "bucket": "month", "buckets": buckets,
            "coverage": {"source": "device", "complete": False, "from": "2026-06-24", "to": "2026-10-22 12:00", "note": "fog unreachable: counts from the device store (since 2026-06-24)"}}


def exec_tool(name, args):
    W = world()
    try:
        if name in SITE_TOOLS:
            return W["ST"].call(name, dict(args))
        if name == "co_occurring_incidents":
            return twin_cooccur(W["ex"], args.get("id"), int(args.get("window_min", 120)))
        if name == "fog_search_history":
            return twin_fog_search(args)
        if name == "fog_analytics":
            return twin_fog_trend(args)
        return W["ex"].run(name, dict(args))
    except Exception as e:  # a malformed call from the model is a tool error, as in the app
        return {"error": "bad call: %s" % str(e)[:120]}
