"""r4 chat records (gen_chat_r3 format) on the r4 store (make_store_r4.py): cross-domain reasoning kinds tagged with
reasoning_type/hops, the r3 fog kinds re-weighted to offline/timeout, and the r3 weak kinds with a fixed gold policy.

Causal rules (the known graph; applied to any incident pair of a co_occurring_incidents result + the anchor):
  edge(a, b): a not after b, b at most 90 min after a, (label a, label b) in EDGES, and same building unless the pair is campus-wide
  relation(A, B): A drove B | B drove A | same cause C | one is a sensor fault | no known link (independent)
Cross-domain kinds (hard: short numberless plan think; calls = get_incident(anchor) + co_occurring_incidents(anchor[, window]))
  x_relation  pair_relation  "Were [A] and [B] related?"                  key: relation class
  x_who       pair_who       "Which started it, [A] or [B]?"              key: root id
  x_first     pairwise       "Which came first, [A] or [B]?" (1 call)     key: earlier id
  x_severe    pairwise       "Which was more severe, [A] or [B]?"         key: more severe id
  x_direct    chain_direct   "What directly caused [Y]?" (2 h window)     key: direct parent id
  x_trans     transitive     "Could [C] have affected [E]?" (2 h)         key: mediator id (C -> D -> E, no edge C -> E)
  x_three     three_way      "How are [B] and [C] connected to [A]?"      key: root id
  x_chain     multihop       "Walk me through what [W] led to." (2 h)     key: ordered ids (2-3 hops)
  x_max       chain_max      "Which incident explains most around [X]?"   key: id with most descendants
  x_fu_links  pair_relation  follow-up after "what happened in [A]?": "was anything else linked to it?"
Gold policy fixes (r3 test showed unstated parameters in the gold): a parameter is in the gold call ONLY when the question
states it (co_occurring window, recurring min_count); listings always state the total; fog_status answers give link state,
last sync and pending uploads.
  python3 gen_chat_r4.py --n-x 2600 --n-fix 3700 --n-test-x 560 --n-test-fix 300 --n-dev 60 --seed 41114
"""
import argparse
import collections
import datetime as dt
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
R3T = os.path.abspath(os.path.join(HERE, "..", "..", "2026-11-06_4b_local", "tools"))
sys.path.insert(0, R3T)
import gen_chat_r3 as GR  # noqa: E402
import tools_r3_impl as TR  # noqa: E402
G = GR.G
num, ident, phrase, call, cap = G.num, G.ident, G.phrase, G.call, G.cap
STORE = os.path.abspath(os.path.join(HERE, "..", "build", "store_r4"))
OUT = os.path.abspath(os.path.join(HERE, "..", "build", "records"))
FOG_DB = os.path.join(STORE, "fog_store_r4.sqlite")
DEV_DB = os.path.join(STORE, "device_store_r4.sqlite")

EDGES = {("weather_driven", "hvac_or_thermal_issue"): ("campus", "the outdoor heat warms the rooms and loads the AC"),
         ("hvac_or_thermal_issue", "power_load_anomaly"): ("same", "the AC working harder raises the room power"),
         ("power_load_anomaly", "power_quality_issue"): ("campus", "the extra load pulls the power factor down"),
         ("occupancy_driven_load", "power_load_anomaly"): ("same", "people in the room add load"),
         ("occupancy_driven_load", "hvac_or_thermal_issue"): ("same", "people add heat to the room"),
         ("water_leak_or_overuse", "power_load_anomaly"): ("same", "the pump runs longer to refill the draining tank"),
         ("power_load_anomaly", "water_supply_issue"): ("same", "the pump lost power, so the tank is not refilled")}
REL_PH = {"drove": ["drove", "caused", "led to", "triggered", "because of", "explains", "followed from", "result of", "driven by"],
          "same": ["same cause", "shared cause", "common cause", "both came from", "both caused by", "both driven by", "both followed"],
          "fault": ["sensor fault", "faulty", "bad data", "sensor_fault", "not a real"],
          "indep": ["unrelated", "independent", "no link", "not linked", "no known link", "coincid", "not related", "no causal"]}
SEVR = {"normal": 0, "sensor_fault": 0, "warning": 1, "critical": 2}


def bld(it):
    m = re.search(r"\b([A-Z]{2}) building", it.get("title") or "")
    if "SB00 substation" in (it.get("title") or ""):
        return "SB"
    return m.group(1) if m else None


def tmin(it):
    return dt.datetime.strptime(it["time"], "%Y-%m-%d %H:%M")


def edge(a, b):
    if a["id"] == b["id"]:
        return None
    e = EDGES.get((a.get("label"), b.get("label")))
    if not e:
        return None
    d = (tmin(b) - tmin(a)).total_seconds() / 60
    if d < 0 or d > 90:
        return None
    if e[0] == "same" and (bld(a) is None or bld(a) != bld(b)):
        return None
    return e[1]


def relation(a, b, S):
    """('drove', cause, effect, mediator or None) | ('same', a, b, shared cause) | ('fault', ...) | ('indep', ...)"""
    if edge(a, b):
        return "drove", a, b, None
    if edge(b, a):
        return "drove", b, a, None
    for x, y in ((a, b), (b, a)):
        for m in S:
            if m["id"] not in (a["id"], b["id"]) and edge(x, m) and edge(m, y):
                return "drove", x, y, m
    for c in S:
        if c["id"] not in (a["id"], b["id"]) and edge(c, a) and edge(c, b):
            return "same", a, b, c
    if "sensor_fault" in (a.get("label"), b.get("label")):
        return "fault", a, b, None
    return "indep", a, b, None


def desc(x, S):
    out, todo = set(), [x]
    while todo:
        y = todo.pop()
        for z in S:
            if z["id"] not in out and z["id"] != x["id"] and edge(y, z):
                out.add(z["id"])
                todo.append(z)
    return out


def chains(x, S, depth=3):
    """all edge paths starting at x inside S"""
    res = []

    def go(p):
        ext = False
        for z in S:
            if z["id"] not in [q["id"] for q in p] and edge(p[-1], z):
                ext = True
                go(p + [z])
        if len(p) > 1:
            res.append(p)
    go([x])
    return res


def th(it):
    return G.titlehead(it["title"])


def ref(it):
    return "[%s] %s" % (it["id"], th(it))


def lab(it):
    return G.dname(it.get("label") or "unlabelled")


class GenR4(GR.GenR3):
    def __init__(self, R, exs, split, since, test_anchor):
        super().__init__(R, exs, split, since)
        self.test_anchor = test_anchor
        self._mine()

    # ---------------------------------------------------------------- candidates
    def _mine(self):
        ex = self.exs["offline"]
        self.cand = collections.defaultdict(list)
        for x in self.full:
            if self.test_anchor(x["id"]) != (self.split == "dev"):
                continue
            for w in (None, 120):
                args = {"id": x["id"]} if w is None else {"id": x["id"], "window_min": w}
                ex.qid = 0
                r = ex.run("co_occurring_incidents", args)
                if "error" in r or not r["items"]:
                    continue
                gi = ex.run("get_incident", {"id": x["id"]})
                A = {"id": x["id"], "time": x["time"], "title": x["title"], "label": x["label"], "severity": x["severity"], "domains": x["domains"]}
                S = [A] + r["items"]
                self.cand[("S", w)].append((A, S, r, gi))

    def _pick(self, w, pred):
        pool = self.cand[("S", w)]
        for _ in range(40):
            A, S, r, gi = self.R.choice(pool)
            got = pred(A, S)
            if got:
                return A, S, got
        return None

    def _calls(self, A, w, with_get=True):
        args = {"id": A["id"]}
        if w:
            args["window_min"] = w
        c = [call("co_occurring_incidents", args)]
        return ([call("get_incident", {"id": A["id"]})] + c) if with_get else c

    def _x(self, q, A, w, ans, rtype, hops, key, with_get=True):
        return {"q": cap(q), "rounds": [self._calls(A, w, with_get)], "ans": ans, "hard": True, "rtype": rtype, "hops": hops, "key": key}

    # ---------------------------------------------------------------- cross-domain kinds
    def k_x_relation(self):
        R = self.R
        w = R.choice([None, None, 120])
        cls = R.choice(["drove", "drove", "same", "fault", "indep"])

        def pred(A, S):
            bs = [b for b in S[1:] if relation(A, b, S)[0] == cls and (w or abs(b["offset_min"]) <= 60)]
            return R.choice(bs) if bs else None
        p = self._pick(w, pred)
        if not p:
            return None
        A, S, B = p
        wq = " within two hours" if w else ""
        q = self.pick(["Were {a} and {b} related{w}?", "Is {b} connected to {a}{w}?", "did {a} have anything to do with {b}{w}?",
                       "Any link between {a} and {b}{w}?", "{a} and {b}{w}: same problem or separate?", "Was {b} caused by {a} or unrelated{w}?",
                       "Check whether {a} and {b} are linked{w}.", "are {a} and {b} part of the same event{w}"]).format(a=A["id"], b=B["id"], w=wq)

        def ans(r):
            gi, co = r[0][0], r[0][1]
            S2 = [dict(A, label=gi.get("label") or A["label"])] + co["items"]
            b2 = next((i for i in co["items"] if i["id"] == B["id"]), None)
            if not b2:
                return None
            c, x, y, z = relation(S2[0], b2, S2)
            if c != cls:
                return None
            if c == "drove" and z is not None:
                s = "Linked, indirectly: %s drove %s, which drove %s." % (ref(x), ref(z), ref(y))
            elif c == "drove":
                s = "Likely linked: %s drove %s %s min later, because %s." % (ref(x), ref(y), abs(int((tmin(y) - tmin(x)).total_seconds() // 60)), EDGES[(x["label"], y["label"])][1])
            elif c == "same":
                s = "Not one causing the other: %s and %s both followed %s, a shared cause." % (ref(x), ref(y), ref(z))
            elif c == "fault":
                f = x if x.get("label") == "sensor_fault" else y
                s = "No real link: %s is a sensor fault (bad data), so it is not an effect of %s." % (ref(f), ref(y if f is x else x))
            else:
                s = "Probably unrelated: %s (%s) and %s (%s) have no known link; they only happened close in time." % (ref(x), lab(x), ref(y), lab(y))
            return s, [ident(A["id"]), ident(B["id"]), phrase(*REL_PH[c])]
        hops = 2 if cls == "same" else (1 if cls == "drove" else 0)
        return self._x(q, A, w, ans, "pair_relation", hops, {"relation": cls})

    def k_x_who(self):
        R = self.R
        w = R.choice([None, 120])

        def pred(A, S):
            ps = [(x, y) for x in S for y in S if edge(x, y) and A["id"] in (x["id"], y["id"]) and (w or abs((tmin(y) - tmin(x)).total_seconds()) <= 3600)]
            return R.choice(ps) if ps else None
        p = self._pick(w, pred)
        if not p:
            return None
        A, S, (x, y) = p
        B = y if x["id"] == A["id"] else x
        a1, a2 = (A, B) if R.random() < 0.5 else (B, A)
        wq = " (look two hours around %s)" % A["id"] if w else ""
        q = self.pick(["Which one started it, {a} or {b}?{w}", "{a} or {b}: which is the root cause?{w}", "Did {a} cause {b}, or the other way round?{w}",
                       "between {a} and {b}, which came from which?{w}", "What's the cause and what's the effect: {a}, {b}?{w}",
                       "Root cause between {a} and {b}?{w}", "which of {a} and {b} triggered the other{w}", "Who caused whom: {a} or {b}?{w}"]).format(
            a=a1["id"], b=a2["id"], w=wq)

        def ans(r):
            co = r[0][1]
            if not any(i["id"] == B["id"] for i in co["items"]):
                return None
            s = "%s is the likely root: %s, and %s followed %s min later." % (ref(x), EDGES[(x["label"], y["label"])][1], ref(y),
                                                                             int((tmin(y) - tmin(x)).total_seconds() // 60))
            return s, [ident(x["id"]), ident(y["id"]), phrase("root", "cause", "started", "drove", "triggered")]
        return self._x(q, A, w, ans, "pair_who", 1, {"first_id": x["id"]})

    def k_x_first(self):
        R = self.R

        def pred(A, S):
            bs = [b for b in S[1:] if b["offset_min"] != 0 and abs(b["offset_min"]) <= 60]
            return R.choice(bs) if bs else None
        p = self._pick(None, pred)
        if not p:
            return None
        A, S, B = p
        a1, a2 = (A, B) if R.random() < 0.5 else (B, A)
        q = self.pick(["Which came first, {a} or {b}?", "{a} vs {b}: which was raised earlier?", "Did {a} happen before {b}?", "which was earlier, {a} or {b}",
                       "Order of {a} and {b}?", "Was {b} after {a}?", "{a} and {b} - which one started first?", "first one between {a} and {b}?"]).format(a=a1["id"], b=a2["id"])
        first = A if B["offset_min"] > 0 else B

        def ans(r):
            co = r[0][0]
            b2 = next((i for i in co["items"] if i["id"] == B["id"]), None)
            if not b2:
                return None
            later = B if first is A else A
            return ("%s came first; %s was %s min later (%s vs %s)." % (ref(first), ref(later), abs(b2["offset_min"]), first["time"][11:], later["time"][11:]),
                    [ident(first["id"]), num(abs(b2["offset_min"]))])
        return {"q": cap(q), "rounds": [[call("co_occurring_incidents", {"id": A["id"]})]], "ans": ans, "hard": False, "rtype": "pairwise", "hops": 0,
                "key": {"first_id": first["id"]}}

    def k_x_severe(self):
        R = self.R

        def pred(A, S):
            bs = [b for b in S[1:] if SEVR.get(b["severity"], 0) != SEVR.get(A["severity"], 0) and abs(b["offset_min"]) <= 60]
            return R.choice(bs) if bs else None
        p = self._pick(None, pred)
        if not p:
            return None
        A, S, B = p
        a1, a2 = (A, B) if R.random() < 0.5 else (B, A)
        q = self.pick(["Which was more severe, {a} or {b}?", "{a} or {b}: which one is worse?", "Which should I handle first, {a} or {b}?",
                       "compare severity of {a} and {b}", "Is {a} worse than {b}?", "{a} vs {b} - which is more serious?", "worse one: {a} or {b}?",
                       "Which of {a} and {b} matters more?"]).format(a=a1["id"], b=a2["id"])
        top = A if SEVR[A["severity"]] > SEVR[B["severity"]] else B
        low = B if top is A else A

        def ans(r):
            gi, co = r[0][0], r[0][1]
            if gi.get("severity") != A["severity"] or not any(i["id"] == B["id"] for i in co["items"]):
                return None
            return ("%s is more severe (%s) than %s (%s); handle it first." % (ref(top), top["severity"], ref(low), low["severity"].replace("_", " ")),
                    [ident(top["id"]), phrase(*G.SEV_PHRASE[top["severity"]])])
        return self._x(q, A, None, ans, "pairwise", 0, {"first_id": top["id"]})

    def k_x_direct(self):
        R = self.R

        def pred(Y, S):
            par = [x for x in S if edge(x, Y)]
            if len(par) != 1:
                return None
            direct = par
            up = [x for x in S if not edge(x, Y) and edge(x, par[0])]
            if not up:
                return None
            return direct[0], up
        p = self._pick(120, pred)
        if not p:
            return None
        Y, S, (D, up) = p
        q = self.pick(["What directly caused {y}? Check two hours around it.", "{y}: what was the immediate cause (within two hours)?",
                       "Which incident directly led to {y}, looking two hours around it?", "what triggered {y} directly? look 2 hours around",
                       "Direct cause of {y} within two hours?", "Within two hours of {y}, which incident caused it directly?",
                       "find the direct cause of {y} (two hours either side)", "{y} - immediate trigger, two-hour window?"]).format(y=Y["id"])

        def ans(r):
            return ("The direct cause is %s: %s. %s is further upstream: it drove %s, not %s directly." % (
                ref(D), EDGES[(D["label"], Y["label"])][1], ref(up[0]), D["id"], Y["id"]), [ident(D["id"]), ident(up[0]["id"]), phrase("direct", "immediate")])
        return self._x(q, Y, 120, ans, "chain_direct", 2, {"first_id": D["id"]})

    def k_x_trans(self):
        R = self.R

        def pred(C, S):
            ps = [(D, E) for D in S for E in S if edge(C, D) and edge(D, E) and not edge(C, E) and E["id"] != C["id"]]
            return R.choice(ps) if ps else None
        p = self._pick(120, pred)
        if not p:
            return None
        C, S, (D, E) = p
        q = self.pick(["Could {c} have affected {e}? Look two hours around {c}.", "Is there a path from {c} to {e} within two hours?",
                       "Did {c} lead to {e} somehow (two-hour window)?", "{c} and {e}: indirect link within two hours?",
                       "could {c} explain {e}? check 2 hours", "Any chain from {c} to {e} within two hours?",
                       "is {e} downstream of {c}? two hours", "{c} -> {e}: possible within two hours?"]).format(c=C["id"], e=E["id"])

        def ans(r):
            return ("Yes, indirectly: %s drove %s (%s), and that drove %s (%s). There is no direct link from %s to %s." % (
                ref(C), ref(D), EDGES[(C["label"], D["label"])][1], ref(E), EDGES[(D["label"], E["label"])][1], C["id"], E["id"]),
                [ident(D["id"]), ident(E["id"]), phrase("indirect", "through", "via")])
        return self._x(q, C, 120, ans, "transitive", 2, {"mediator_id": D["id"]})

    def k_x_three(self):
        R = self.R

        def pred(A, S):
            for B in S[1:]:
                for Cc in S[1:]:
                    if B["id"] >= Cc["id"]:
                        continue
                    trio = [A, B, Cc]
                    if len({d for t in trio for d in t["domains"][:1]}) < 3:
                        continue
                    roots = [t for t in trio if desc(t, trio) == {u["id"] for u in trio if u is not t}]
                    if len(roots) == 1:
                        return B, Cc, roots[0]
            return None
        p = self._pick(120, pred)
        if not p:
            return None
        A, S, (B, Cc, rt) = p
        q = self.pick(["How are {b} and {c} connected to {a}? Look two hours around {a}.", "What links {a}, {b} and {c} (two hours around {a})?",
                       "{a}, {b}, {c}: one story or three? check two hours around {a}", "explain how {b} and {c} relate to {a} within two hours",
                       "Is there one cause behind {a}, {b} and {c}? two-hour window around {a}", "Tie {a}, {b} and {c} together (two hours around {a}).",
                       "what connects {a} with {b} and {c}, 2 hour window", "{b} and {c} - related to {a} within two hours?"]).format(a=A["id"], b=B["id"], c=Cc["id"])
        trio = [A, B, Cc]
        others = [t for t in trio if t is not rt]
        chain = [o for o in others if edge(rt, o)]
        mid = [o for o in others if not edge(rt, o)]

        if mid and not (chain and edge(chain[0], mid[0])):
            return None
        if not mid and not all(edge(rt, o) for o in others):
            return None

        def ans(r):
            if mid:
                s = "One chain: %s drove %s, which drove %s. The root is [%s]." % (ref(rt), ref(chain[0]), ref(mid[0]), rt["id"])
            else:
                s = "One root, two effects: %s drove both %s (%s) and %s (%s)." % (ref(rt), ref(others[0]), EDGES[(rt["label"], others[0]["label"])][1],
                                                                               ref(others[1]), EDGES[(rt["label"], others[1]["label"])][1])
            return s, [ident(rt["id"]), phrase("root", "drove", "both")]
        return self._x(q, A, 120, ans, "three_way", 2 if mid else 1, {"first_id": rt["id"]})

    def k_x_chain(self):
        R = self.R

        def pred(W, S):
            cs = [c for c in chains(W, S) if len(c) >= 3]
            if not cs:
                return None
            m = max(len(c) for c in cs)
            best = [c for c in cs if len(c) == m]
            return best[0] if len(best) == 1 else None
        p = self._pick(120, pred)
        if not p:
            return None
        W, S, ch = p
        q = self.pick(["Walk me through what {w} led to in the next two hours.", "Trace the chain starting at {w} (two hours).", "What followed from {w} within two hours, step by step?",
                       "{w}: what did it set off over two hours?", "show the knock-on effects of {w}, 2 hours", "Chain of events after {w} within two hours?",
                       "what happened downstream of {w} in two hours", "{w} - follow the causes for two hours"]).format(w=W["id"])

        def ans(r):
            steps = " -> ".join(ref(c) for c in ch)
            return ("The chain: %s. Each step: %s." % (steps, "; ".join(EDGES[(a["label"], b["label"])][1] for a, b in zip(ch, ch[1:]))),
                    [ident(c["id"]) for c in ch[1:]])
        return self._x(q, W, 120, ans, "multihop", len(ch) - 1, {"ids_order": [c["id"] for c in ch]})

    def k_x_max(self):
        R = self.R

        def pred(X, S):
            sc = sorted(((len(desc(x, S)), x) for x in S), key=lambda z: -z[0])
            if sc[0][0] < 2 or (len(sc) > 1 and sc[1][0] == sc[0][0]):
                return None
            others = [x for x in S if x["id"] != sc[0][1]["id"] and x["id"] not in desc(sc[0][1], S)]
            return sc[0][1], sorted(desc(sc[0][1], S)), others
        p = self._pick(120, pred)
        if not p:
            return None
        X, S, (top, ds, others) = p
        q = self.pick(["Around {x}, which incident explains the most of what happened? Two hours.", "Within two hours of {x}, which one is the main root?",
                       "Which incident near {x} (two hours) caused the most others?", "What's the biggest root cause around {x} in two hours?",
                       "main driver of everything around {x}? 2 hour window", "two hours around {x}: which incident sits at the top of the chain?",
                       "find the incident that explains most others near {x} (two hours)", "{x}: which nearby incident explains the most, two-hour window?"]).format(x=X["id"])

        def ans(r):
            s = "%s explains the most: it drove %s." % (ref(top), ", ".join("[%s]" % d for d in ds))
            if others:
                s += " %s %s not part of that chain." % (", ".join("[%s]" % o["id"] for o in others[:3]), "is" if len(others[:3]) == 1 else "are")
            return s, [ident(top["id"])] + [ident(d) for d in ds[:2]]
        return self._x(q, X, 120, ans, "chain_max", max(1, len(ds)), {"first_id": top["id"]})

    def k_x_fu_links(self):
        """turn 1: what happened in [A] (get_incident); turn 2: was anything else linked to it? (co_occurring + relations)"""
        R = self.R

        def pred(A, S):
            return True if len(S) >= 2 else None
        p = self._pick(None, pred)
        if not p:
            return None
        A, S, _ = p
        t1 = self.k_detail_r4(A["id"])
        an = self._anchor(t1)
        if not an:
            return None
        q = self.pick(["was anything else linked to it?", "Did it cause anything else?", "anything related in other systems?", "was it part of something bigger?",
                       "What else was connected to that one?", "linked incidents?", "did other domains get hit by it", "any knock-on effects?"])

        def ans(r):
            co = r[0][0]
            S2 = [A] + co["items"]
            parts = []
            for b in co["items"][:3]:
                c, x, y, z = relation(A, b, S2)
                if c == "drove" and z is not None:
                    parts.append("[%s] is linked through [%s]" % (b["id"], z["id"]))
                elif c == "drove":
                    parts.append("[%s] %s (%s)" % (b["id"], "drove it" if x["id"] == b["id"] else "followed from it", EDGES[(x["label"], y["label"])][1]))
                else:
                    parts.append({"same": "[%s] shares a cause with it" % b["id"], "fault": "[%s] is a sensor fault, not linked" % b["id"],
                                  "indep": "[%s] is unrelated" % b["id"]}[c])
            return ("%s incident%s in other domains within %s minutes: %s." % (co["total"], "" if co["total"] == 1 else "s", co["window_min"], "; ".join(parts)),
                    [num(co["total"])] + [ident(b["id"]) for b in co["items"][:2]])
        return {"q": q, "rounds": [[call("co_occurring_incidents", {"id": A["id"]})]], "ans": ans, "hard": True, "history": [an[:2]], "rtype": "pair_relation",
                "hops": 1, "key": {}}

    def k_detail_r4(self, iid):
        q = self.pick(["What happened in {i}?", "Tell me about {i}.", "{i} details?", "explain {i}", "What was {i} about?", "give me {i}",
                       "what's {i}", "summary of {i}"]).format(i=iid)

        def ans(r):
            x = r[0][0]
            return ("[%s] at %s: %s, severity %s, label %s. Root cause: %s." % (x["id"], x["time"], x["title"], x["severity"], G.lab(x),
                                                                                x.get("root_cause") or "not recorded"), [ident(x["id"])])
        return {"q": q, "rounds": [[call("get_incident", {"id": iid})]], "ans": ans, "hard": False}

    # ---------------------------------------------------------------- r3 kinds with the fixed gold policy
    def k_cooccur(self, iid=None):
        R = self.R
        w = R.choice([None, None, 30, 90, 120, 240])
        if iid is None:
            iid = R.choice(self.full if R.random() < 0.75 else self.arch)["id"]
        if w:
            q = self.pick(["Any incidents in other domains within {w} of {i}?", "Was {i} linked to anything else within {w}?", "Cross-domain check for {i}: anything within {w}?",
                           "Did anything happen in other systems within {w} of {i}?", "{i}: other alerts within {w}?", "anything within {w} of {i} in other domains",
                           "other-domain incidents {w} either side of {i}?", "within {w} of {i}, what else fired?"]).format(i=iid, w="%d minutes" % w)
        else:
            q = self.pick(["What else happened around {i}?", "Show related incidents around the time of {i}.", "Was {i} linked to anything else?",
                           "Cross-domain check for {i}.", "Did anything happen in other systems around {i}?", "{i}: other alerts around it?",
                           "anything co-occurring with {i}?", "what else was going on when {i} fired"]).format(i=iid)
        t = GR.GenR3.k_cooccur(self, iid)
        args = {"id": iid}
        if w:
            args["window_min"] = w
        t["rounds"] = [[call("co_occurring_incidents", args)]]
        t["q"] = cap(q)
        return t

    def k_recurring(self):
        R = self.R
        t = None
        for _ in range(5):
            t = GR.GenR3.k_recurring(self)
            a = t["rounds"][0][0]["args"]
            if "min_count" in a and not re.search(r"\b%d\b" % a["min_count"], t["q"]):
                a.pop("min_count")
            return t
        return t

    def k_fu_cooccur(self):
        c, ans = self._recent({})
        an = self._anchor({"q": self.R.choice(["latest incidents?", "Show me the newest alerts.", "What happened recently?"]), "rounds": [c], "ans": ans})
        if not an:
            return None
        items = an[2][0][0]["items"]
        if not items:
            return None
        t = GR.GenR3.k_cooccur(self, items[0]["id"])
        t["rounds"] = [[call("co_occurring_incidents", {"id": items[0]["id"]})]]
        t["q"] = self.pick(["anything else happening around the first one?", "Was the first one linked to other domains?", "what else happened at that time?",
                            "Any cross-domain incidents near the top one?", "other alerts around it?", "did something else go wrong then?",
                            "Check what co-occurred with the first.", "was that alone or part of something bigger?"])
        t["history"] = [an[:2]]
        return t


X_KINDS = [("x_relation", 3), ("x_who", 3), ("x_first", 1.5), ("x_severe", 1.5), ("x_direct", 3), ("x_trans", 3), ("x_three", 3), ("x_chain", 3),
           ("x_max", 3), ("x_fu_links", 1.5)]
RT = {"x_relation": "pair_relation", "x_who": "pair_who", "x_first": "pairwise", "x_severe": "pairwise", "x_direct": "chain_direct", "x_trans": "transitive",
      "x_three": "three_way", "x_chain": "multihop", "x_max": "chain_max", "x_fu_links": "pair_relation"}
FIX_KINDS = [("fog_find_old", 5), ("fog_text", 6), ("fog_old_detail", 4), ("fog_trend", 3), ("fog_resolve", 4), ("fog_sensor_monthly", 3), ("knowledge", 2),
             ("fog_status", 4), ("old_count", 4), ("recent_vs_fog", 5), ("cooccur", 6), ("recurring", 5), ("compare_tool", 4), ("fu_fog_detail", 2),
             ("fu_fog_period", 2), ("fu_fog_status", 3), ("fu_cooccur", 5), ("fog_drop", 5), ("inject_fog", 2), ("refuse_fog", 1),
             ("explain_latest", 2), ("explain_incident", 2), ("rank_clean", 2), ("trend", 2), ("recent_filtered", 2), ("whatif_ac", 2), ("whatif_occ", 1.5),
             ("whatif_temp", 1.5), ("open_domain", 1.5), ("unanswerable", 1.5), ("followup_worst", 1.5), ("recommend", 1.5), ("compare_levels", 1)]


def pick_state(R, kind):
    if kind == "fog_drop":
        return "timeout"
    if kind == "fu_fog_status":
        return "offline"
    if kind in GR.FOG_KINDS or kind in ("fog_text", "recent_vs_fog", "old_count"):
        return R.choices(["online", "offline", "timeout"], [0.3, 0.52, 0.18])[0]
    return R.choice(["online", "offline", "offline"])


def make(exs, split, plan, seed, ban=None, test_anchor=None, since=None):
    R = random.Random(seed)
    g = GenR4(R, exs, split, since, test_anchor)
    rows, seen, fails = [], collections.Counter(), collections.Counter()
    for tag, n, kinds in plan:
        got, tries, rr = 0, 0, 0
        names, wts = [k for k, _ in kinds], [w for _, w in kinds]
        while got < n and tries < n * 30:
            tries += 1
            kind = names[rr % len(names)] if split == "dev" else R.choices(names, wts)[0]
            state = pick_state(R, kind)
            ls = GR.last_sync_for(R) if state == "offline" else None
            g.use(state)
            g.exs["offline"].last_sync = ls
            g.exs["timeout"].last_sync = (GR.NOW - dt.timedelta(minutes=R.randrange(2, 12))).strftime("%Y-%m-%d %H:%M")
            try:
                t = getattr(g, "k_" + kind)()
            except (IndexError, KeyError, ValueError):
                t = None
            if not t:
                fails[kind] += 1
                if split == "dev" and fails[kind] % 25 == 0:
                    rr += 1
                continue
            t["q"] = G.noisy(R, t["q"])
            sol = g.solve(t)
            if not sol:
                fails[kind] += 1
                if split == "dev" and fails[kind] % 25 == 0:
                    rr += 1
                continue
            nq = G.norm(t["q"])
            if ban is not None and nq in ban:
                continue
            key = (nq, state, json.dumps([c for rd in t["rounds"] for c in rd], sort_keys=True), json.dumps(t.get("history", [])))
            if seen[key] >= 1:
                continue
            pads = []
            if R.random() < 0.2 and not t.get("history"):
                pk = R.choice(["recent", "count_metric", "levels_place", "fog_status", "old_count"])
                pt = getattr(g, "k_" + pk)()
                if pt:
                    ps = g.solve(pt)
                    if ps:
                        pads.append((G.noisy(R, pt["q"]), ps[0]))
            seen[key] += 1
            rr += 1
            rec = G.build_record(g, t, sol, split, len(rows), kind, pads)
            rec["id"] = "r4-%s-%s-%05d" % (split, tag, len(rows))
            rec["messages"][0]["content"] = GR.system_r3(state, ls, since)
            rec.update({"fog": state, "last_sync": ls if state == "offline" else g.exs[state].last_sync, "since": since, "group": tag,
                        "tools_file": "tools_r3.json", "tool_names": TR.CHAT_TOOLS_R3, "reasoning_type": t.get("rtype", "none"), "hops": t.get("hops", 0),
                        "answer_key": t.get("key", {})})
            rows.append(rec)
            got += 1
        print("%s %s: %d rows (%d tries) fails %s" % (split, tag, got, tries, dict(fails.most_common(8))), file=sys.stderr)
    return rows


def tools_r4():
    return {s: TR.ToolsR3(fog=s, fog_path=FOG_DB, dev_path=DEV_DB) for s in ("online", "offline", "timeout")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-x", type=int, default=2600)
    ap.add_argument("--n-fix", type=int, default=3700)
    ap.add_argument("--n-test-x", type=int, default=560)
    ap.add_argument("--n-test-fix", type=int, default=300)
    ap.add_argument("--n-dev", type=int, default=60)
    ap.add_argument("--seed", type=int, default=41114)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    exs = tools_r4()
    since = exs["online"].D.full_from.strftime("%Y-%m-%d")
    test_anchor = lambda iid: int(iid[4:]) % 5 == 0
    test = make(exs, "dev", [("x", a.n_test_x, X_KINDS), ("fix", a.n_test_fix, FIX_KINDS)], a.seed + 1000, test_anchor=test_anchor, since=since)
    ban = {G.norm(next(m["content"] for m in reversed(r["messages"]) if m["role"] == "user")) for r in test}
    dev = make(exs, "dev", [("x", a.n_dev // 2, X_KINDS), ("fix", a.n_dev - a.n_dev // 2, FIX_KINDS)], a.seed + 2000, ban=ban, test_anchor=test_anchor, since=since)
    ban |= {G.norm(next(m["content"] for m in reversed(r["messages"]) if m["role"] == "user")) for r in dev}
    train = make(exs, "train", [("x", a.n_x, X_KINDS), ("fix", a.n_fix, FIX_KINDS)], a.seed, ban=ban, test_anchor=test_anchor, since=since)
    for name, rows in (("train", train), ("test", test), ("dev", dev)):
        with open(os.path.join(a.out, name + ".jsonl"), "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        c = collections.Counter((r["group"], r["reasoning_type"]) for r in rows)
        print(name, len(rows), dict(c), file=sys.stderr)


if __name__ == "__main__":
    main()
