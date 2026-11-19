"""Chat r5 rows: the 4 site tools (fmt_v4.SITE_TOOLS) on synthetic sites / the IIITH tree, executed by the Python twin of
chat_site.go (SiteTools below). Gold calls are executed on the row's site + status overlay; answers are templated from the
results (<= 3 sentences, [INC-] citations, names only from tool results). Think rule: easy = no reasoning at all (also after
the tool result); hard (2 calls) = a short numberless plan on the first assistant turn only."""
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "core"))
import fmt_v4 as FM  # noqa: E402
import sitegraph as SG  # noqa: E402

QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3", "pipeline"))
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-10-25_reasoner_final", "pipeline"))
import verify_chat as VC  # noqa: E402
import verify as V  # noqa: E402

RANK = {"normal": 0, "warning": 1, "critical": 2}
TITLE = {"co2": "CO2 above limit", "temp": "room temperature high", "power_kw": "load step", "level": "tank level falling",
         "room_temp": "room too warm", "flow": "flow anomaly", "rh": "humidity high", "pm25": "PM2.5 high", "occ": "off-hours presence"}


class SiteTools:
    """Python twin of chat_site.go: get_site_tree, nodes_under, linked_equipment, site_status"""

    def __init__(self, site, status, incidents):
        self.site, self.ix = site, SG.Index(site)
        self.status = status            # sensor id -> warning | critical | data_issue
        self.inc = incidents            # sensor id -> {"id","severity","title"}
        roll = self.ix.rollup({k: ("sensor_fault" if v == "data_issue" else v) for k, v in status.items()})
        self.roll = roll
        self.byname = {}
        for n in site["nodes"]:
            self.byname[n["id"].lower()] = n["id"]
            if n.get("name"):
                self.byname.setdefault(n["name"].lower(), n["id"])

    def find(self, x):
        return self.byname.get((x or "").strip().lower())

    def st(self, nid):
        n = self.ix.nodes[nid]
        if n["kind"] == "sensor":
            return self.status.get(nid, "normal")
        return self.roll[nid]["status"]

    def name(self, nid):
        n = self.ix.nodes[nid]
        return nid if n["kind"] == "sensor" else self.ix.name(nid)

    def open_under(self, nid):
        ss = self.ix.sensors_under(nid) if self.ix.nodes[nid]["kind"] != "sensor" else [nid]
        out = [dict(self.inc[s], node=s) for s in sorted(ss) if s in self.inc]
        return sorted(out, key=lambda o: (-RANK.get(o["severity"], 0), o["id"]))

    def nf(self, node):
        return {"found": False, "node": node, "note": "no such node in the site map", "source": "device"}

    def get_site_tree(self, node=None, depth=1):
        nid = self.find(node) if node else next(n["id"] for n in self.site["nodes"] if n["kind"] == "campus")
        if not nid:
            return self.nf(node)

        def walk(x, d):
            kids = sorted(self.ix.children.get(x, []), key=lambda c: (self.ix.nodes[c]["kind"] == "sensor", c))
            items = []
            for c in kids[:15]:
                it = {"id": c, "name": self.name(c), "kind": self.ix.nodes[c]["kind"], "status": self.st(c)}
                if self.ix.nodes[c]["kind"] == "sensor":
                    it["metric"] = self.ix.nodes[c]["metric"]
                if d > 1 and self.ix.children.get(c):
                    it["children"] = walk(c, d - 1)
                items.append(it)
            return items
        kids = self.ix.children.get(nid, [])
        return {"node": nid, "name": self.name(nid), "kind": self.ix.nodes[nid]["kind"], "status": self.st(nid),
                "children_total": len(kids), "children": walk(nid, max(1, min(3, int(depth or 1)))), "source": "device"}

    def nodes_under(self, node, kind=None, metric=None, status=None):
        nid = self.find(node)
        if not nid:
            return self.nf(node)
        out, q = [], list(self.ix.children.get(nid, []))
        while q:
            x = q.pop(0)
            q.extend(self.ix.children.get(x, []))
            n = self.ix.nodes[x]
            if kind and n["kind"] != kind:
                continue
            if metric and n.get("metric") != metric:
                continue
            s = self.st(x)
            if status and not (s == status or (status == "data_issue" and self.status.get(x) == "data_issue")):
                continue
            out.append(x)
        out.sort()
        f = {k: v for k, v in (("kind", kind), ("metric", metric), ("status", status)) if v}
        return {"node": nid, "name": self.name(nid), "filters": f, "total": len(out),
                "items": [{"id": x, "name": self.name(x), "kind": self.ix.nodes[x]["kind"], "status": self.st(x)} for x in out[:12]],
                "source": "device"}

    def linked_equipment(self, node, link=None, direction="both"):
        nid = self.find(node)
        if not nid:
            return self.nf(node)
        res = []
        for other, t, d in self.ix.neighbours(nid):
            if link and t != link:
                continue
            if direction in ("out", "in") and d != direction:
                continue
            res.append({"type": t, "direction": d, "node": other, "name": self.name(other), "status": self.st(other),
                        "open": [o["id"] for o in self.open_under(other)][:3]})
        res.sort(key=lambda r: (r["type"], r["direction"], r["node"]))
        return {"node": nid, "name": self.name(nid), "links": res[:12], "total": len(res), "source": "device"}

    def site_status(self, node):
        nid = self.find(node)
        if not nid:
            return self.nf(node)
        r = self.roll.get(nid, {"status": self.st(nid), "data_issues": 0})
        return {"node": nid, "name": self.name(nid), "status": r["status"], "data_issues": r["data_issues"],
                "open_incidents": [{"id": o["id"], "severity": o["severity"], "title": o["title"], "sensor": o["node"]}
                                   for o in self.open_under(nid)][:5], "source": "device"}

    def call(self, name, args):
        return getattr(self, name)(**args)


# --------------------------------------------------------------------------------------------- overlay + helpers
def overlay(R, site):
    ix = SG.Index(site)
    sens = sorted(n["id"] for n in site["nodes"] if n["kind"] == "sensor" and n["metric"] in TITLE)
    st, inc = {}, {}
    for s in R.sample(sens, min(len(sens), R.choice([0, 1, 2, 2, 3, 4]))):
        v = R.choice(["warning", "warning", "critical", "data_issue"])
        st[s] = v
        if v != "data_issue":
            host = ix.parent(s)
            inc[s] = {"id": "INC-%04d" % R.randrange(100, 9999), "severity": v,
                      "title": "%s: %s" % (TITLE[ix.nodes[s]["metric"]], ix.name(host))}
    return st, inc


def nodes_of(site, kind=None, etype=None, use_ok=True):
    return sorted(n["id"] for n in site["nodes"] if (kind is None or n["kind"] == kind) and (etype is None or n.get("etype") == etype))


def fmt_list(xs, k=4):
    xs = list(xs)
    if len(xs) <= k:
        return ", ".join(xs[:-1]) + (" and " if len(xs) > 1 else "") + xs[-1] if xs else ""
    return ", ".join(xs[:k]) + " and others"


def cite(ids):
    return " ".join("[%s]" % i for i in ids)


HING = {"room_contents": "{x} mein kaun kaun se sensors hain?", "ac_serves": "{x} kaun se rooms ko cool karta hai?",
        "bld_status": "{x} ka status kya hai abhi?", "tank_feed": "{x} ko paani kahan se aata hai?",
        "crit_under": "{x} pe koi critical sensor hai kya?", "hard_hot": "{x} bahut garam hai, uska AC theek hai kya?"}
EN = {"room_contents": ["What sensors are in {x}?", "what is installed in {x}", "List the sensors in {x}."],
      "ac_serves": ["Which rooms does {x} serve?", "what rooms are on {x}?", "Which spaces does {x} cool?"],
      "ac_flagged": ["Are any rooms served by {x} flagged right now?", "anything wrong in the rooms {x} serves?"],
      "tank_feed": ["What feeds {x}?", "Which pump fills {x}?"],
      "panel_supplies": ["What does {x} supply?", "Which loads are on {x}?"],
      "bld_status": ["Why is {x} amber?", "What is the status of {x}?", "Is everything ok in {x}?"],
      "crit_under": ["Any critical sensors on {x}?", "Is anything critical under {x}?"],
      "metric_under": ["How many {m} sensors are in {x}?", "count the {m} sensors in {x}"],
      "hard_hot": ["{x} is too hot. Is the AC serving it ok?", "People say {x} feels warm; check the AC that serves it."],
      "define": ["What does 'supplies' mean on the site map?", "What is a 'serves' link?", "What does SUSPECT mean on the map?"],
      "refuse": ["Switch off {x} now.", "Turn {x} off, it is wasting power."],
      "unknown": ["What is in room ZZ-{n}?", "Status of block QQ{n}?"]}
DEFINE = {"supplies": "A 'supplies' link means a panel, feeder or tank feeds power or water to that equipment or room.",
          "serves": "A 'serves' link means an AC, AHU or chiller cools or ventilates that room, zone or floor.",
          "SUSPECT": "SUSPECT marks a parent node when two or more of the things below it or linked to it flag together; the AI "
                     "report then confirms or rejects it as the common cause."}


def q_of(R, kind, x, m=None, hing=False):
    if hing and kind in HING:
        return HING[kind].format(x=x), True
    return R.choice(EN[kind]).format(x=x, m=m, n=R.randrange(100, 999)), False


def tc(i, name, args):
    return {"id": "call_%d" % i, "type": "function", "function": {"name": name, "arguments": args}}


def make_row(R, site, system, kind, hing_p=0.12, ov=None, prev=None):
    stt, inc = ov or overlay(R, site)
    T = SiteTools(site, stt, inc)
    ix = T.ix
    campus = next(n for n in site["nodes"] if n["kind"] == "campus")
    rooms = [r for r in nodes_of(site, "room") if any(ix.nodes[c]["kind"] == "sensor" for c in ix.children.get(r, []))]
    acs = [a for a in nodes_of(site, "equipment", "ac_unit") if any(l["from"] == a for l in site["links"])]
    tanks = [t for t in nodes_of(site, "equipment", "tank") if any(l["to"] == t and l["type"] == "feeds" for l in site["links"])]
    panels = [p for p in nodes_of(site, "equipment", "panel") if any(l["from"] == p for l in site["links"])]
    blds, floors = nodes_of(site, "building"), nodes_of(site, "floor")
    hing = R.random() < hing_p
    calls, final, hard, plan = [], None, False, None
    nm = ix.name
    if kind == "room_contents" and rooms:
        x = nm(R.choice(rooms))
        q, hing = q_of(R, kind, x, hing=hing)
        calls = [("get_site_tree", {"node": x, "depth": 1})]
    elif kind in ("ac_serves", "ac_flagged") and acs:
        x = nm(R.choice(acs))
        q, hing = q_of(R, "ac_serves" if kind == "ac_serves" else "ac_flagged", x, hing=hing and kind == "ac_serves")
        calls = [("linked_equipment", {"node": x, "link": "serves", "direction": "out"})]
    elif kind == "tank_feed" and tanks:
        x = nm(R.choice(tanks))
        q, hing = q_of(R, kind, x, hing=hing)
        calls = [("linked_equipment", {"node": x, "link": "feeds", "direction": "in"})]
    elif kind == "panel_supplies" and panels:
        x = nm(R.choice(panels))
        q, hing = q_of(R, kind, x)
        calls = [("linked_equipment", {"node": x, "link": "supplies", "direction": "out"})]
    elif kind == "bld_status" and blds:
        flagged = [b for b in blds if T.st(b) != "normal"]
        x = nm(R.choice(flagged or blds))
        q, hing = q_of(R, kind, x, hing=hing)
        calls = [("site_status", {"node": x})]
    elif kind == "crit_under" and floors:
        x = R.choice(floors)
        x = "%s, %s" % (nm(ix.parent(x)), nm(x)) if False else nm(x)
        fl_ids = [f for f in floors if nm(f) == x]
        if len(fl_ids) != 1:
            x = nm(R.choice(blds))
        q, hing = q_of(R, kind, x, hing=hing)
        calls = [("nodes_under", {"node": x, "kind": "sensor", "status": "critical"})]
    elif kind == "metric_under" and blds:
        x = nm(R.choice(blds))
        m = R.choice(["co2", "temp", "power_kw", "occ"])
        q, hing = q_of(R, kind, x, m={"co2": "CO2", "temp": "temperature", "power_kw": "energy meter", "occ": "occupancy"}[m])
        calls = [("nodes_under", {"node": x, "kind": "sensor", "metric": m})]
    elif kind == "hard_hot" and rooms:
        served = [r for r in rooms if any(l["to"] == r and l["type"] == "serves" for l in site["links"])]
        if not served:
            return None, "no_served"
        rid = R.choice(served)
        x = nm(rid)
        q, hing = q_of(R, kind, x, hing=hing)
        hard = True
        plan = R.choice(["Find the unit that serves this room, then check that unit's status and open incidents.", "Look up which AC serves the room, then read its roll-up status."])
        calls = [("linked_equipment", {"node": x, "link": "serves", "direction": "in"})]
    elif kind == "define":
        q = R.choice(EN["define"])
        key = "supplies" if "supplies" in q else ("serves" if "serves" in q else "SUSPECT")
        final = DEFINE[key]
    elif kind == "refuse" and acs:
        x = nm(R.choice(acs))
        q = R.choice(EN["refuse"]).format(x=x)
        final = "I can't switch equipment: my tools are read-only. An operator can switch off %s after approval; I can check what it serves first." % x
    elif kind == "unknown":
        q = R.choice(EN["unknown"]).format(n=R.randrange(100, 999))
        x = re.search(r"(ZZ-\d+|QQ\d+)", q).group(1)
        calls = [("site_status", {"node": x})]
    else:
        return None, "no_nodes:" + kind
    # execute
    msgs = [{"role": "system", "content": system}]
    if prev:
        msgs += prev
    msgs.append({"role": "user", "content": q})
    results = []
    k = 0
    if calls:
        first = calls[0]
        k += 1
        res = T.call(first[0], dict(first[1]))
        results.append(res)
        a = {"role": "assistant", "content": "", "tool_calls": [tc(k, first[0], first[1])]}
        if hard:
            a["reasoning_content"] = plan
        msgs.append(a)
        msgs.append({"role": "tool", "tool_call_id": "call_%d" % k, "content": json.dumps(res, ensure_ascii=False)})
        if kind == "hard_hot":
            units = [l for l in res.get("links", [])]
            if not units:
                return None, "no_unit"
            u = units[0]
            k += 1
            res2 = T.call("site_status", {"node": u["name"]})
            results.append(res2)
            msgs.append({"role": "assistant", "content": "", "tool_calls": [tc(k, "site_status", {"node": u["name"]})]})
            msgs.append({"role": "tool", "tool_call_id": "call_%d" % k, "content": json.dumps(res2, ensure_ascii=False)})
    final = final or answer(kind, results, hing)
    if final is None:
        return None, "answer"
    msgs.append({"role": "assistant", "content": final})
    row = {"id": "x", "family": "site:" + kind, "tools": "chat_r5", "think": True, "hard": hard, "fog": "online" if "online" in system else "offline",
           "hinglish": hing, "site_id": site.get("site_id"), "reasoning_type": "none", "hops": 0, "messages": msgs,
           "gold_calls": [{"name": c[0], "args": c[1]} for c in calls] + ([{"name": "site_status", "args": {"node": results[0]["links"][0]["name"]}}] if kind == "hard_hot" else []),
           "multi_turn": bool(prev)}
    row["_ov"] = (stt, inc)
    return row, None


def answer(kind, results, hing):
    r = results[0] if results else None
    if r is not None and r.get("found") is False:
        return "There is no node %s in the site map. Check the name, or ask me for the site tree." % r["node"]
    if kind == "room_contents":
        sens = [c for c in r["children"] if c["kind"] == "sensor"]
        other = [c for c in r["children"] if c["kind"] != "sensor"]
        if not sens and not other:
            return "%s has nothing placed under it in the site map." % r["name"]
        bad = [c for c in r["children"] if c["status"] != "normal"]
        lst = fmt_list(["%s (%s)" % (c["id"], c.get("metric", c["kind"])) for c in sens] + ["%s (%s)" % (c["name"], c["kind"]) for c in other])
        if len(sens) + len(other) == r["children_total"] and not other:
            s = "%s has %d sensor%s: %s." % (r["name"], len(sens), "" if len(sens) == 1 else "s", lst)
        else:
            s = "%s contains %s." % (r["name"], lst)
        if bad:
            s += " Not normal now: %s." % fmt_list("%s %s" % (c["id"], c["status"]) for c in bad)
        else:
            s += " All are normal right now."
        return s
    if kind in ("ac_serves", "ac_flagged", "tank_feed", "panel_supplies"):
        L_ = r["links"]
        if not L_:
            return "%s has no %s links in the site map." % (r["name"], {"tank_feed": "feeds", "panel_supplies": "supplies"}.get(kind, "serves"))
        verb = {"tank_feed": "is fed by", "panel_supplies": "supplies"}.get(kind, "serves")
        s = "%s %s %s." % (r["name"], verb, fmt_list(l["name"] for l in L_))
        bad = [l for l in L_ if l["status"] != "normal"]
        if bad:
            s += " " + " ".join("%s is %s %s." % (l["name"], l["status"], cite(l["open"])) if l["open"] else "%s is %s." % (l["name"], l["status"]) for l in bad[:2])
        else:
            s += " None of them is flagged right now." if kind != "tank_feed" else " It is normal right now."
        return re.sub(r"\s+", " ", s).strip()
    if kind == "bld_status":
        if r["status"] == "normal" and not r["open_incidents"]:
            s = "%s is normal: no open incidents." % r["name"]
            if r["data_issues"]:
                s += " %d sensor%s %s a data issue, shown separately." % (r["data_issues"], "" if r["data_issues"] == 1 else "s", "has" if r["data_issues"] == 1 else "have")
            return s
        o = r["open_incidents"]
        s = "%s is %s because of %s." % (r["name"], {"warning": "amber (warning)", "critical": "red (critical)"}.get(r["status"], r["status"]),
                                        fmt_list("[%s] %s" % (x["id"], x["title"]) for x in o[:3]) if o else "a flagged sensor")
        if r["data_issues"]:
            s += " Data issues are counted separately (%d)." % r["data_issues"]
        return s
    if kind in ("crit_under", "metric_under"):
        if r["total"] == 0:
            return "No %s under %s right now." % ("critical sensors" if kind == "crit_under" else "such sensors", r["name"])
        return "%s has %d %s: %s." % (r["name"], r["total"], "critical sensor%s" % ("" if r["total"] == 1 else "s") if kind == "crit_under" else
                                      "matching sensor%s" % ("" if r["total"] == 1 else "s"), fmt_list([x["id"] for x in r["items"]][:4] if r["total"] <= 4 else [x["id"] for x in r["items"]][:5]))
    if kind == "hard_hot":
        u, s2 = r["links"][0], results[1]
        s = "%s is served by %s, which is %s." % (r["name"], u["name"], s2["status"])
        if s2["open_incidents"]:
            s += " Open: %s." % fmt_list("[%s] %s" % (x["id"], x["title"]) for x in s2["open_incidents"][:2])
        else:
            s += " It has no open incident, so check the room itself (doors, crowd, sun) and its temperature trend."
        return s
    if kind == "unknown":
        return "There is no node %s in the site map." % r["node"]
    return None


# --------------------------------------------------------------------------------------------- checks
SCHEMA = {f["function"]["name"]: f["function"]["parameters"] for f in FM.SITE_TOOLS}
NUMRX = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")


def check_row(row):
    e = []
    ex = dict(row, tools="chat")
    e += [x for x in V.check_chat(ex)]
    msgs = row["messages"]
    calls = [c for m in msgs for c in (m.get("tool_calls") or [])]
    if len(calls) > 5:
        e.append("calls>5")
    for c in calls:
        sch = SCHEMA.get(c["function"]["name"])
        if sch is None:
            continue
        for k2, v in c["function"]["arguments"].items():
            if k2 not in sch["properties"]:
                e.append("arg:" + k2)
            elif "enum" in sch["properties"][k2] and v not in sch["properties"][k2]["enum"]:
                e.append("enum:" + k2)
        for rq in sch.get("required", []):
            if rq not in c["function"]["arguments"]:
                e.append("required:" + rq)
    final = msgs[-1]["content"]
    if len(re.findall(r"[.!?](?:\s|$)", final)) > 3:
        e.append("sentences>3")
    lu = max(i for i, m in enumerate(msgs) if m["role"] == "user")
    reas = [m for m in msgs[lu:] if m.get("reasoning_content")]
    if not row["hard"] and reas:
        e.append("think_easy")
    if row["hard"]:
        if not reas or reas[0] is not msgs[lu + 1] or len(reas) > 1:
            e.append("think_hard_place")
        else:
            th = reas[0]["reasoning_content"]
            if VC.think_tokens(th) > 80:
                e.append("think_long")
            if NUMRX.search(re.sub(VC.STRIP, " ", re.sub(r"\S*\d\S*", lambda m: " " if re.search(r"[A-Za-z]", m.group(0)) else m.group(0), th))):
                e.append("think_num")
    if msgs[-1].get("reasoning_content"):
        e.append("think_final")
    return e
