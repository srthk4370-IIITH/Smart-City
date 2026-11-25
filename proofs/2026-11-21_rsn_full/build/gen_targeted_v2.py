"""gen_targeted_v2.py: targeted chat top-up v2 (block=targeted_v2) for the per-row eval failures (final/gen_rows.jsonl slice chat):
 A site/linked chains (room contents, AC flagged rooms, rank->linked, find->get) with exact calls + short non-empty final;
 B fog/history answers citing INC ids + key phrases (co_occurring with window_min, find_incidents, fog_search_history, get_incident);
 C follow-ups reusing the previous tool with one changed arg, final cites ids/numbers.
Reuses gen_targeted (RB3 + A_rank_linked/A_find_get) and gen_tools. Leakage: last-user-text hash vs gate/tests/dev/r3/eval rows dropped.
  python3 gen_targeted_v2.py -> ../data/targeted_v2.jsonl + ../data/targeted_v2_stats.json"""
import collections
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_targeted as T  # noqa: E402
GT, BC, C = T.GT, T.BC, T.C
RB3, DN, MN, cap, sv_, pw = T.RB3, T.DN, T.MN, T.cap, T.sv_, T.pw
P, D = T.P, T.D
OUT, BLOCK = D + "/targeted_v2.jsonl", "targeted_v2"
R = T.R
R.seed(20261125)
EVAL_NODES = {"room of energy meter 01"}


def ids_txt(its, k=3):
    return ", ".join("[%s]" % i["id"] for i in its[:k])


def short(i):
    t = GT.ttl(i)
    return t if len(t) <= 90 else t[:87].rstrip() + "..."


def sites(rb, kinds):
    return [n for n in rb.W["site"]["nodes"] if n["kind"] in kinds and rb.ST.find(n["name"]) == n["id"] and n["name"] not in EVAL_NODES]


# ------------------------------------------------------------------------------------------------------------------------ A
def A_contents():
    rb = RB3(R)
    ns = [n for n in sites(rb, ("room", "floor", "building", "equipment")) if rb.ST.ix.children.get(n["id"])]
    n = R.choice(ns)
    x = n["name"]
    qs = ["Which sensors does %s hold?" % x, "List what is in %s." % x, "What sensors sit in %s?" % x, "Show me the contents of %s." % x, "What is installed in %s?" % x,
          "Name the sensors of %s and tell me if any is flagged." % x, "What measures things in %s?" % x, "inventory of %s please" % x, "which sensors are under %s?" % x]
    rb.ask(R.choice(qs))
    r = rb.call("get_site_tree", {"node": x, "depth": 1}, plan=R.choice(["Contents of %s: get_site_tree(node=%s, depth=1), then list the children and flag the ones not normal." % (x, x), None]))
    if r.get("found") is False or not r.get("children"):
        return None
    ch = r["children"]
    bad = [c for c in ch if c["status"] != "normal"]
    f = "%s holds %d item%s: %s." % (r["name"], r["children_total"], "" if r["children_total"] == 1 else "s", C.fmt_list([c["name"] for c in ch], 4))
    f += (" Flagged: %s." % ", ".join("%s (%s)" % (c["name"], sv_(c["status"])) for c in bad[:3])) if bad else " None is flagged."
    return rb.fin("targeted2_contents", "tree_node", None, final=f)


def acs(rb):
    return [n for n in rb.W["site"]["nodes"] if n.get("etype") == "ac_unit"]


def ac_label(rb, a):
    c = [a["name"], a["id"], a["name"].replace("AC indoor unit", "AC unit")]
    c = [x for x in c if rb.ST.find(x) == a["id"]]
    return R.choice(c)


def A_ac_flagged():
    rb = RB3(R)
    a = R.choice(acs(rb))
    x = ac_label(rb, a)
    qs = ["Is any room served by %s flagged right now?" % x, "Does %s serve a room that has a problem?" % x, "Check the rooms %s feeds: anything flagged?" % x,
          "Which room does %s serve, and is it flagged?" % x, "Any alert on the room cooled by %s?" % x, "%s: rooms it serves, any flagged?" % x, "Is the space under %s in trouble?" % x]
    rb.ask(R.choice(qs))
    r = rb.call("linked_equipment", {"node": x, "link": "serves", "direction": "out"}, plan=R.choice([None, "Rooms served by %s: linked_equipment(node=%s, link=serves, direction=out) already returns each room status; no second call needed." % (x, x)]))
    if r.get("found") is False or not r.get("links"):
        return None
    ls = r["links"]
    bad = [l for l in ls if l["status"] != "normal"]
    if bad:
        f = "Yes. %s serves %s, flagged: %s." % (r["name"], C.fmt_list([l["name"] for l in ls], 3), "; ".join("%s is %s%s" % (l["name"], sv_(l["status"]), (" " + C.cite(l["open"])) if l["open"] else "") for l in bad[:3]))
    else:
        f = "No. %s serves %s and %s normal with no open incident." % (r["name"], C.fmt_list([l["name"] for l in ls], 3), "it is" if len(ls) == 1 else "all are")
    return rb.fin("targeted2_ac_flagged", "ac_flagged", None, final=f)


def A_ac_room_contents():
    rb = RB3(R)
    a = R.choice(acs(rb))
    x = ac_label(rb, a)
    qs = ["What sensors are in the room that %s serves?" % x, "List the sensors of the room cooled by %s." % x, "Which sensors sit in the room %s serves?" % x, "Show me what is in the room under %s." % x]
    rb.ask(R.choice(qs))
    lk = rb.call("linked_equipment", {"node": x, "link": "serves", "direction": "out"}, plan="Sensors of the room that %s serves: linked_equipment(node=%s, link=serves, direction=out) to find the room, then get_site_tree on it." % (x, x))
    if not lk.get("links"):
        return None
    room = lk["links"][0]
    if room["name"] in EVAL_NODES:
        return None
    r = rb.call("get_site_tree", {"node": room["node"], "depth": 1})
    if r.get("found") is False or not r.get("children"):
        return None
    f = "%s serves %s, which holds %d sensors (%s)." % (lk["name"], room["name"], len(r["children"]), C.fmt_list(sorted({c.get("metric", "?") for c in r["children"]}), 4))
    bad = [c for c in r["children"] if c["status"] != "normal"]
    f += (" Flagged: %s." % ", ".join("%s (%s)" % (c["name"], sv_(c["status"])) for c in bad[:3])) if bad else " All normal."
    return rb.fin("targeted2_ac_room_contents", "ac_room_contents", None, final=f)


def A_room_ac():
    rb = RB3(R)
    n = R.choice(sites(rb, ("room",)))
    x = n["name"]
    qs = ["Which AC serves %s, and is it healthy?" % x, "What cools %s? Is that unit fine?" % x, "Tell me the AC unit of %s and its state." % x, "Who serves %s, and is it flagged?" % x]
    rb.ask(R.choice(qs))
    lk = rb.call("linked_equipment", {"node": x, "link": "serves", "direction": "in"})
    if not lk.get("links"):
        return None
    u = lk["links"][0]
    t = "It is normal with no open incident." if u["status"] == "normal" else "It is %s%s." % (sv_(u["status"]), (" " + C.cite(u["open"])) if u["open"] else "")
    return rb.fin("targeted2_room_ac", "room_ac", None, final="%s is served by %s. %s" % (lk["name"], u["name"], t))


def A_rank_linked():
    return T.A_rank_linked()


def A_find_get():
    return T.A_find_get()


# ------------------------------------------------------------------------------------------------------------------------ B
WIN = [(30, ["within 30 minutes of %s", "30 minutes around %s"]), (45, ["within 45 minutes of %s"]), (60, ["within an hour of %s", "an hour around %s"]),
       (90, ["within 90 minutes of %s", "an hour and a half around %s"]), (120, ["in the two hours around %s", "two hours either side of %s"]), (180, ["three hours around %s"]),
       (240, ["within four hours of %s", "the four hours around %s"])]


def B_cooccur():
    rb = RB3(R)
    cand = rb.peek("find_incidents", dict(time={"preset": R.choice(["last_30d", "last_7d"])}, limit=10)).get("items", [])
    if not cand:
        return None
    iid = R.choice(cand)["id"]
    wmin, phr = R.choice(WIN)
    ph = R.choice(phr) % iid
    wtxt = ph.replace(" of " + iid, "").replace(" around " + iid, "").replace(" either side", "")
    qs = ["What else fired %s?" % ph, "Find the direct cause of %s (%s)." % (iid, wtxt), "What happened next to %s, %s?" % (iid, wtxt), "Anything downstream or upstream of %s, %s?" % (iid, wtxt),
          "List the incidents %s and what the report of %s says." % (ph, iid), "Which incidents overlap %s? Give me the ids." % ph, "Show what else was flagged %s and the cause of %s." % (ph, iid)]
    rb.ask(re.sub(r"\s+", " ", R.choice(qs)))
    g = rb.call("get_incident", {"id": iid}, plan=R.choice(BC.PLANS["cooccur"]))
    if "error" in g:
        return None
    co = rb.call("co_occurring_incidents", {"id": iid, "window_min": wmin})
    if co.get("error") or "total" not in co:
        return None
    rc = g.get("root_cause") or short(g)
    if co["total"] == 0:
        f = "Nothing else was flagged within %d minutes of [%s]. Its report says: %s." % (wmin, iid, rc)
    else:
        its = sorted(co["items"], key=lambda i: abs(i.get("offset_min", 0)))[:3]
        f = "Within %d minutes of [%s] I see %d other incident%s: %s. The nearest is [%s], %d minutes %s it. Timing alone does not prove cause; the report of [%s] says: %s." % (
            wmin, iid, co["total"], "" if co["total"] == 1 else "s", "; ".join("[%s] %s" % (i["id"], short(i)) for i in its), its[0]["id"], abs(its[0].get("offset_min", 0)), "before" if its[0].get("offset_min", 0) < 0 else "after", iid, rc)
    return rb.fin("targeted2_cooccur", "cooccur", None, final=f)


def B_find():
    rb = RB3(R)
    d = R.choice(list(DN))
    pr = R.choice(["today", "yesterday", "last_24h", "last_7d", "this_week", "last_30d"])
    sv = R.choice([None, None, "critical", "warning", "sensor_fault"])
    bld = R.choice([None, None, "KH", "VN", "BK", "KN"])
    a = dict(time={"preset": pr}, domain=d, limit=3)
    if sv:
        a["severity"] = [sv]
    if bld:
        a["node"] = bld
    w = pw(pr)
    s = (sv_(sv) + " ") if sv else ""
    where = (" in %s" % bld) if bld else ""
    qs = ["List the %s%s incidents%s %s with ids." % (s, DN[d], where, w), "Which %s%s incidents%s %s? Give me the ids." % (s, DN[d], where, w), "Show %s%s alerts%s %s and what each is about." % (s, DN[d], where, w),
          "What %s%s incidents did we have%s %s?" % (s, DN[d], where, w), "Give me the incident ids for %s%s problems%s %s." % (s, DN[d], where, w)]
    rb.ask(re.sub(r"\s+", " ", R.choice(qs)))
    r = rb.call("find_incidents", a)
    if "total" not in r:
        return None
    if not r["items"]:
        f = "No %s%s incidents%s %s." % (s, DN[d], where, w)
    else:
        f = "%d %s%s incident%s%s %s. Latest: %s." % (r["total"], s, DN[d], "" if r["total"] == 1 else "s", where, w, "; ".join("[%s] %s" % (i["id"], short(i)) for i in r["items"][:3]))
    return rb.fin("targeted2_find", "find_ids" if r["items"] else "find_empty", None, final=f)


def B_fog():
    rb = RB3(R, state="online")
    d = R.choice(list(DN))
    pr = R.choice(["last_7d", "last_30d", "this_month", "last_month", "this_year"])
    sv = R.choice([None, "critical", "warning"])
    a = dict(time={"preset": pr}, domain=d)
    if sv:
        a["severity"] = [sv]
    w = {"last_7d": "the last 7 days", "last_30d": "the last 30 days", "this_month": "this month", "last_month": "last month", "this_year": "this year"}[pr]
    s = (sv + " ") if sv else ""
    qs = ["Search the history for %s%s incidents in %s and give me the ids and causes." % (s, DN[d], w), "From the archive: %s%s incidents in %s, which ids and why?" % (s, DN[d], w),
          "Look through the record of %s%s problems over %s: how many, and which ones?" % (s, DN[d], w), "Pull the history of %s%s incidents for %s with their ids." % (s, DN[d], w)]
    rb.ask(R.choice(qs))
    r = rb.call("fog_search_history", a)
    if not isinstance(r.get("total"), int) or r.get("error"):
        return None
    its = r.get("items") or []
    if not its:
        f = "The history has no %s%s incidents in %s." % (s, DN[d], w)
    else:
        f = "The history has %d %s%s incident%s in %s. Most recent: %s." % (r["total"], s, DN[d], "" if r["total"] == 1 else "s", w, "; ".join("[%s] %s" % (i["id"], i.get("root_cause") or short(i)) for i in its[:2]))
    return rb.fin("targeted2_fog", "fog_ids" if its else "fog_empty", None, final=f)


def B_get():
    rb = RB3(R)
    its = rb.peek("find_incidents", dict(time={"preset": R.choice(["last_30d", "last_7d"])}, limit=10)).get("items", [])
    if not its:
        return None
    iid = R.choice(its)["id"]
    qs = ["Explain %s." % iid, "What is %s about and what caused it?" % iid, "Open %s and give me the cause." % iid, "Details of %s please." % iid, "Why did %s happen, and is it closed?" % iid]
    rb.ask(R.choice(qs))
    g = rb.call("get_incident", {"id": iid})
    if "error" in g:
        return None
    state = "closed as %s" % sv_(g["outcome"]) if g.get("outcome") else "still %s" % sv_(g.get("workflow", "open"))
    rc = ("Cause: %s." % g["root_cause"]) if g.get("root_cause") else "No root cause is written yet."
    return rb.fin("targeted2_get", "get_cite", None, final="[%s] %s is %s and %s. %s" % (iid, short(g), sv_(g["severity"]), state, rc))


# ------------------------------------------------------------------------------------------------------------------------ C
def C_follow_find():
    d1, d2 = R.sample(list(DN), 2)
    pr = R.choice(["last_7d", "last_30d", "this_week"])
    w = pw(pr)
    rb0 = RB3(R)
    a1 = rb0.peek("find_incidents", dict(time={"preset": pr}, domain=d1, limit=3))
    if not a1.get("items"):
        return None
    h = [("List the %s incidents %s." % (DN[d1], w), "%d %s incidents %s. Latest: %s." % (a1["total"], DN[d1], w, "; ".join("[%s] %s" % (i["id"], short(i)) for i in a1["items"][:3])))]
    mode = R.choice(["domain", "domain", "sev"])
    if mode == "domain":
        qs, args, lab = ["and %s?" % DN[d2], "ok, %s ones?" % DN[d2], "same for %s" % DN[d2], "now %s" % DN[d2]], dict(time={"preset": pr}, domain=d2, limit=3), DN[d2]
    else:
        sv = R.choice(["critical", "warning"])
        qs, args, lab = ["only the %s ones?" % sv, "just %s, with ids" % sv, "and the %s ones?" % sv], dict(time={"preset": pr}, domain=d1, severity=[sv], limit=3), sv + " " + DN[d1]
    rb = RB3(R, state=rb0.fog, hist=h)
    rb.ask(R.choice(qs))
    r = rb.call("find_incidents", args)
    if "total" not in r:
        return None
    if not r["items"]:
        f = "No %s incidents %s." % (lab, w)
    else:
        f = "%d %s incident%s %s: %s." % (r["total"], lab, "" if r["total"] == 1 else "s", w, "; ".join("[%s] %s" % (i["id"], short(i)) for i in r["items"][:3]))
    return rb.fin("targeted2_followup", "followup_find", None, final=f)


def C_follow_cooccur():
    rb0 = RB3(R)
    cand = rb0.peek("find_incidents", dict(time={"preset": "last_30d"}, limit=10)).get("items", [])
    if not cand:
        return None
    iid = R.choice(cand)["id"]
    w1, w2 = R.choice([(30, 120), (60, 180), (45, 240), (120, 60), (180, 90)])
    a1 = rb0.peek("co_occurring_incidents", {"id": iid, "window_min": w1})
    if a1.get("error") or "total" not in a1:
        return None
    ans1 = ("Within %d minutes of [%s]: %s." % (w1, iid, "; ".join("[%s] %s" % (i["id"], short(i)) for i in a1["items"][:3]))) if a1["items"] else "Nothing else within %d minutes of [%s]." % (w1, iid)
    h = [("What else happened within %d minutes of %s?" % (w1, iid), ans1)]
    rb = RB3(R, state=rb0.fog, hist=h)
    rb.ask(R.choice(["and with %d minutes?" % w2, "widen it to %d minutes" % w2, "try %d minutes instead" % w2, "what about %d minutes?" % w2]))
    r = rb.call("co_occurring_incidents", {"id": iid, "window_min": w2})
    if r.get("error") or "total" not in r:
        return None
    its = sorted(r["items"], key=lambda i: abs(i.get("offset_min", 0)))[:3]
    f = ("Within %d minutes of [%s] there %s %d: %s." % (w2, iid, "is" if r["total"] == 1 else "are", r["total"], "; ".join("[%s] %s" % (i["id"], short(i)) for i in its))) if its else "Nothing else within %d minutes of [%s]." % (w2, iid)
    return rb.fin("targeted2_followup", "followup_cooccur", None, final=f)


MONTHS = T.MONTHS


def C_follow_fog():
    m1, m2 = R.sample(list(MONTHS), 2)
    d = R.choice(["power", "water", "air_quality", "hvac"])
    rb0 = RB3(R, state="online")

    def mk(m):
        return dict(time={"from": BC._month(m)[0], "to": BC._month(m)[1]}, domain=d)
    a1 = rb0.peek("fog_search_history", mk(m1))
    if not isinstance(a1.get("total"), int):
        return None
    h = [("Search the history for %s incidents in %s." % (DN[d], MONTHS[m1]), "The history has %d %s incidents in %s%s." % (a1["total"], DN[d], MONTHS[m1], (", e.g. " + ids_txt(a1["items"], 2)) if a1.get("items") else ""))]
    rb = RB3(R, state="online", hist=h)
    rb.ask(R.choice(["%s too, with ids?" % MONTHS[m2], "and %s? list ids" % MONTHS[m2], "same search for %s" % MONTHS[m2]]))
    r = rb.call("fog_search_history", mk(m2))
    if not isinstance(r.get("total"), int) or r.get("error"):
        return None
    its = r.get("items") or []
    f = ("The history has %d %s incidents in %s, e.g. %s." % (r["total"], DN[d], MONTHS[m2], "; ".join("[%s] %s" % (i["id"], i.get("root_cause") or short(i)) for i in its[:2]))) if its else "The history has %d %s incidents in %s." % (r["total"], DN[d], MONTHS[m2])
    return rb.fin("targeted2_followup", "followup_fog", None, final=f)


PLAN = [("A", A_rank_linked, 55), ("A", A_find_get, 45), ("A", A_contents, 60), ("A", A_ac_flagged, 55), ("A", A_ac_room_contents, 20), ("A", A_room_ac, 15),
        ("B", B_cooccur, 95), ("B", B_find, 70), ("B", B_fog, 55), ("B", B_get, 30),
        ("C", C_follow_find, 40), ("C", C_follow_cooccur, 30), ("C", C_follow_fog, 30)]


def main():
    sys.path.insert(0, P + "2026-11-20_rsn_big/build")
    os.chdir(P + "2026-11-20_rsn_big/build")
    sys.argv[1:] = [D]
    import types
    CB = types.ModuleType("check_big")
    CB.__file__ = os.path.abspath("check_big.py")
    exec(compile(open("check_big.py").read().rsplit("\nmain()", 1)[0], "check_big.py", "exec"), CB.__dict__)
    ban, nban = set(), 0
    root = P + "2026-11-21_rsn_full/"
    files = [D + "/../gate_full/gate_set.jsonl"] + glob.glob(D + "/gate/*") + glob.glob(D + "/tests/*") + glob.glob(D + "/dev*.jsonl") + glob.glob(P + "2026-11-13_v3_data/rsn/data/final_v2/tests/*") + \
        [P + "2026-11-06_4b_local/data/final/gen_chat_r3.jsonl"]
    for f in files:
        if f.endswith(".jsonl") and os.path.exists(f):
            for r in T.jl(f):
                if r.get("messages"):
                    ban.add(T.hh(T.user_last(r)))
                    nban += 1
    for r in T.jl(root + "final/gen_rows.jsonl"):
        if r.get("user"):
            ban.add(T.hh(r["user"]))
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
            if T.hh(T.user_last(r)) in ban:
                st["drops"]["overlap_gate_test"] += 1
                continue
            if not (r["messages"][-1].get("content") or "").strip():
                st["drops"]["empty_final"] += 1
                continue
            e = CB.BC.check(r) + CB.audit_chat(r)
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
        r["id"] = "targeted2-%s-%05d" % (r["family"].split("_", 1)[-1], i)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
    bad = [r for r in out if T.hh(T.user_last(r)) in ban]
    st["rows"] = len(out)
    st["overlap_check"] = "%d rows vs %d gate/test/dev/r3/eval hashes: %d overlapping" % (len(out), len(ban), len(bad))
    json.dump(st, open(D + "/targeted_v2_stats.json", "w"), indent=1)
    print(json.dumps(st))


if __name__ == "__main__":
    main()
