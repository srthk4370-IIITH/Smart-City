"""v4 incident rows (rsn v3 fine-tune): every family is generated on a SITE (synthetic train/dev/test site or the IIITH tree)
and rendered with fmt_v4.render_v4 (SITE, cards, agent data, LINKS, SIBLINGS, NEARBY, SUSPECT).

Sources of scenarios (all deterministic, seeded):
  r4  : the r4 cross-domain families (gen_r4_inc.py, 18 families, 8 reasoning types, adaptive think)
  r1  : the round-1 regression families (families.py, 36) + memory / re-check / notes / incident tool rows (gen_incidents.make)
  real: real agent outputs (real_pool.jsonl), ONLY windows whose gold passes the 2026-11-13 label audit; plus synthetic
        real-error kinds (visible fault called normal, under-graded severity) made by flipping a correct real output
  site: new site families (shared panel trip -> SUSPECT confirmed; two rooms on one panel with their own occupancy -> SUSPECT
        rejected; one AC serving two rooms trips -> SUSPECT confirmed)
  card: single-sensor rows on synthetic spec cards (24 train types / 8 test types) with the core simulator + E-lines
The old node_* / place / WEATHER / SUBSTATION names are resolved through place.Place, so prompt and gold use site names."""
import collections
import copy
import datetime as dt
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-11-12_topup_r4", "tools"))
import gen_r4_inc as M  # noqa: E402  (pulls G2, lib, textbank, verify, heat helpers)
L, G2, V, VC, H = M.L, M.G2, M.V, M.VC, M.H
import gen_incidents as GI  # noqa: E402  round-1 (families + real_case + make)
import prompts as PR  # noqa: E402
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "core"))
import fmt_v4 as FM  # noqa: E402
import place as PL  # noqa: E402
import sitegraph as SG  # noqa: E402
import cards as CD  # noqa: E402
import sim as SM  # noqa: E402
import evidence as EV  # noqa: E402

assert FM.L is L
SYS_V4 = FM.system_v4(PR.SYSTEM_INCIDENT_SHORT)
OLD_CODES = set(SG.IIITH_CODES) | set(G2.TRAIN_B) | set(G2.NOVEL_B) | {"SB"}
CUR = {"P": None}
_orig_render = L.render


# ------------------------------------------------------------------------------------------------- hooks
def _reason(s):
    ag, E = s["agent"], dict(s.get("ev", []))
    st = ag["status"]
    if st == "sensor_fault":
        k = "E8" if "E8" in E else "E1"
    elif st in ("warning", "critical"):
        k = "E2" if "E2" in E else "E1"
    else:
        k = "E1"
    t = E.get(k, "")
    if not t:
        return "no evidence line"
    tail = {"sensor_fault": "data looks implausible", "warning": "beyond the card warning", "critical": "beyond the card critical",
            "normal": "inside the card normal"}.get(st, "")
    return "%s %s (%s)" % (k, t, tail)


def _dq(q):
    q = (q or "good").split(" ")[0]
    return {"good": "ok", "uncertain": "suspect", "bad": "bad", "stale": "bad"}.get(q, "suspect")


def build_ctx(case):
    P = CUR["P"]
    ss = case["sensors"]
    s1 = next((s for s in ss if s["flagged"]), ss[0])
    links = {}
    for s in ss:
        if not s["flagged"]:
            links[s["ref"]] = (s.get("why") or "related", P.link_of(s1["node"], s1["metric"], s["node"], s["metric"]))
    agd = {}
    if CUR.get("agt"):
        for s in ss:
            if s.get("agent"):
                agd[s["ref"]] = "dq=%s | reason: %s" % (_dq(s.get("quality")), _reason(s))
    fl = [s for s in ss if s["flagged"]]
    indoor = [s for s in fl if s["role"] not in ("weather",) and not P.ix.nodes[P.host.get(s["node"], P.room)].get("etype") in (
        "weather_station", "meter")] or fl or ss[:1]
    name, host = P.scope_name([s["node"] for s in indoor])
    CUR["scope"] = name
    inp = collections.defaultdict(set)
    for s in ss:
        inp[s["node"]].add(s["metric"])
    h1 = P.host.get(s1["node"], P.room)
    sib_host = h1
    bname = P.ix.name(P._bld_of(h1) or P.bld)
    return {"site_line": P.site_line(host), "links": links, "agent_data": agd,
            "links_line": P.links_line([(s["ref"], s["node"]) for s in ss]),
            "siblings": P.siblings(sib_host, {k: {(k, m) for m in v} for k, v in inp.items()}, CUR["rng"]),
            "nearby": (bname, CUR.get("nearby") or []), "suspect": CUR.get("suspect")}


def render_hook(case):
    if CUR["P"] is None:
        return _orig_render(case)
    if case.get("inc_id") == "":       # related_context tool blocks: sensor lines only (v4 headers + card lines)
        txt = FM.render_v4(dict(case, inc_id="X", ask=""), build_ctx(case))
        body = txt.split("DOMAIN AGENT FINDINGS:\n", 1)[1]
        return "DOMAIN AGENT FINDINGS:\n" + body.split("\nLINKS: ", 1)[0] + "\n"
    return FM.render_v4(case, build_ctx(case))


L.render = render_hook
for _nm, _k in (("node_aq", "aq"), ("node_em", "em"), ("node_ac", "ac")):
    setattr(L, _nm, (lambda k: lambda b, fl, kk=None: CUR["P"].resolve(k, b, fl, kk))(_k))
L.node_occ = lambda b, k=None: CUR["P"].resolve("occ", b, None, k)
L.node_out = lambda b: CUR["P"].resolve("out", b)
L.node_tank = lambda b: CUR["P"].resolve("tank", b)
L.node_flow = lambda b: CUR["P"].resolve("fout", b)
L.node_wq = lambda b: CUR["P"].resolve("wq", b)
L.place = lambda b, fl=None: CUR["P"].place_for(b, fl)


def r4_nodes(sc):
    P = CUR["P"]
    b, fl, k = sc["b"], sc["fl"], sc["k"]
    d = dict(aq=P.resolve("aq", b, fl, k), occ=P.resolve("occ", b, None, sc["occ_k"]), em=P.resolve("em", b, fl, k),
             ac=P.resolve("ac", b, fl, k), out=P.resolve("out", b), tank=P.resolve("tank", b), fin=P.resolve("flow", b),
             fout=P.resolve("fout", b), pump=P.resolve("pump", b), wq=P.resolve("wq", b))
    d["place"] = P.place_for(b, fl)
    d["wplace"] = P.place_text(P.host[d["tank"][0]])
    return d


M.nodes = r4_nodes


def set_site(site, R, agt=True):
    P = PL.Place(site, R)
    CUR.update(P=P, rng=R, agt=agt, suspect=None, suspect_gold=None, nearby=[], scope=None)
    we = P.weather()
    fdev, floc, fname = P.feeder()
    L.WEATHER, L.SUBSTATION = we, (fdev, floc)
    for mod in (M, G2, H, GI, GI.F):
        if hasattr(mod, "WE_NODE"):
            mod.WE_NODE, mod.WE_LOC = we
        if hasattr(mod, "SUB_NODE"):
            mod.SUB_NODE, mod.SUB_LOC = fdev, floc
    CUR["feeder"] = (fdev, fname)
    if R.random() < 0.2:
        others = [n for n in P.site["nodes"] if n["kind"] == "sensor" and P._bld_of(n["parent"]) == P.bld
                  and n["metric"] in ("co2", "temp", "power_kw")]
        if others:
            o = R.choice(others)
            CUR["nearby"] = ["%s %s warning since %s (INC-%04d)" % (o["device"], o["metric"], "%02d:%02d" % (R.randrange(8, 20), R.choice(range(0, 60, 5))),
                                                                 R.randrange(100, 9999))]
    return P


def site_codes(P):
    return set(re.findall(r"[A-Z]{2}", json.dumps(P.site)))


def postfix(row, P):
    """leftover old names -> site names; returns error or None"""
    fdev, fname = CUR["feeder"]
    s = json.dumps(row, ensure_ascii=False)
    s = s.replace("the SB00 substation", "the " + fname).replace("SB00 substation", fname).replace("SB00", fname)
    row2 = json.loads(s)
    u = row2["messages"][1]["content"] + row2["messages"][-1]["content"] + (row2["messages"][-1].get("reasoning_content") or "")
    bad = (OLD_CODES - site_codes(P)) if not P.site.get("site_id", "").startswith("iiith") else set()
    m = re.search(r"\b(%s)(?:\d\d|\b| building)" % "|".join(sorted(bad)), u) if bad else None
    if m:
        return None, "old_name:" + m.group(1)
    return row2, None


def add_gold(row):
    m = row["messages"][-1]
    th = m.get("reasoning_content")
    rep = json.loads(m["content"])
    rep["scope"] = CUR["scope"]
    if CUR.get("suspect_gold"):
        rep["suspect_node"] = CUR["suspect_gold"]
    m["content"] = json.dumps(rep, ensure_ascii=False)
    if th is not None:
        m["reasoning_content"] = th
    row["messages"][0] = {"role": "system", "content": SYS_V4}
    row["tools"] = "incident_v4"
    return row


# ------------------------------------------------------------------------------------------------- v4 checks
SUSV = {"confirmed", "rejected", "undecided"}


def check_v4(row):
    e = []
    u = row["messages"][1]["content"]
    rep = json.loads(row["messages"][-1]["content"])
    if not rep.get("scope") or rep["scope"] not in u:
        e.append("v4_scope")
    has_s = "\nSUSPECT: " in u
    if has_s != ("suspect_node" in rep):
        e.append("v4_suspect_presence")
    if "suspect_node" in rep:
        sn = rep["suspect_node"]
        if sn.get("verdict") not in SUSV or sn.get("node") not in u:
            e.append("v4_suspect")
        ids = set(re.findall(r"\b(S\d+(?:\.E\d+)?)\b", u))
        if any(x not in ids for x in sn.get("src", [])):
            e.append("v4_suspect_src")
    for k in ("LIMITS:", "TANK:"):
        if "\n  " + k in u:
            e.append("v4_old_head")
    if not re.search(r"^SITE: ", u, re.M) or "\nLINKS: " not in u:
        e.append("v4_blocks")
    # trust: an impossible current value is never a process event
    for blk in re.split(r"\n(?=S\d+ \[)", u):
        m = re.match(r"(S\d+) \[FLAGGED\]", blk)
        mi = re.search(r"\| impossible <([\d.]+)", blk)
        ml = re.search(r"\.E1 last = ([-\d.]+)", blk)
        if m and mi and ml and float(ml.group(1)) < float(mi.group(1)) and rep["severity"] in ("warning", "critical") \
                and rep["label"] != "sensor_fault" and m.group(1) in rep.get("suspect_sensors", []) is False:
            e.append("v4_trust_impossible")
    return e


def full_check(row):
    e = V.check_incident(row)
    th = row["messages"][-1].get("reasoning_content")
    need = len(set(re.findall(r"^S\d+ \[FLAGGED\]: .*\((\w+)\)$", row["messages"][1]["content"], re.M))) >= 2
    if need:
        e += M.think_ok(th, row["messages"][1]["content"])
    elif th:
        e.append("think_unexpected")
    return e + check_v4(row)


# ------------------------------------------------------------------------------------------------- site pools
def site_for(R, split, seed=None):
    if split == "campus":
        return SG.campus_site()
    lo, hi = {"train": (0, 5999), "dev": (0, 299), "test": (0, 399)}[split]
    for _ in range(50):
        s = SG.gen_site(R.randint(lo, hi) if seed is None else seed, split)
        bl = [n for n in s["nodes"] if n["kind"] == "building"]
        if len(bl) >= 2 and sum(1 for n in s["nodes"] if n["kind"] == "room") >= 4:
            return s
        seed = None
    return s


# ------------------------------------------------------------------------------------------------- r4 families
def gen_r4(R, i, split, fam_w=None, refine=0.25, memory=0.2, agt=True):
    P = set_site(site_for(R, split), R, agt)
    row, why = M.gen_one(R, i, "v4r4", 0.0, refine, memory, fam_w)
    if row is None:
        return None, why
    row = add_gold(row)
    row, why = postfix(row, P)
    if row is None:
        return None, why
    return row, None


# ------------------------------------------------------------------------------------------------- r1 families (+ tools, memory, notes)
def gen_r1(R, split, kind, agt=True):
    P = set_site(site_for(R, split), R, agt)
    ex = GI.make(R, kind, "train", [])
    ex = G2.fix(dict(ex, id="x"))
    ex = add_gold(ex)
    ex, why = postfix(ex, P)
    return ex, why


# ------------------------------------------------------------------------------------------------- real agent rows
def _audit_ok():
    p = os.path.join(QIDK, "proofs", "2026-11-13_label_audit", "pool_audit.jsonl")
    return {json.loads(l)["pool_id"]: json.loads(l) for l in open(p)}


def real_host(P, row):
    role, metric, node = row["role"], row["metric"], row["node"]
    if role == "air_quality":
        if metric in ("pm25", "pm10") and node.startswith("AQ-"):
            d, l = P.resolve("out", "KH")
            dev = P._sensor_dev(P.host[d], metric, "outdoor")
            P.host[dev] = P.host[d]
            return dev, l
        dev = P._sensor_dev(P.room, metric, "air")
        P.host[dev] = P.room
        return dev, P.loc(P.room)
    if role == "water":
        k = {"level": "tank", "flow": "flow", "ph": "wq", "tds": "wq"}[metric]
        d, l = P.resolve(k, "KH")
        if metric == "tds":
            d = P._sensor_dev(P.host[d], "tds", "wq")
            P.host[d] = P.host[P.resolve("wq", "KH")[0]]
        return d, l
    if role == "power":
        if metric == "pf":
            f = CUR["feeder"][0]
            return f, P.loc(P.host[f])
        return P.resolve("em", "KH", 1, 1)
    if role == "weather":
        w = L.WEATHER[0]
        dev = w
        P._sensor_dev(P.host[w], metric, "weather")
        return dev, P.loc(P.host[w])
    if role == "hvac":
        return P.resolve("ac", "KH", 1, 1)
    if role == "occupancy":
        return P.resolve("occ", "KH", None, 1)
    raise KeyError(role)


def flip_agent(R, row):
    """synthetic real-error kinds on a correct real output: visible fault called normal / one level under-graded"""
    g, p = row["gold"], dict(row["pred"] or {})
    if g["status"] == "sensor_fault":
        p.update(status="normal", pattern="stable", likely_cause={"air_quality": "normal_conditions", "water": "normal_usage",
                                                                   "power": "normal_load", "weather": "normal_weather",
                                                                   "hvac": "normal_operation", "occupancy": "normal_occupancy"}[row["role"]],
                 observations=["Readings steady, no event in the window [E6]"], confidence=round(R.uniform(0.6, 0.85), 2))
        return p, "fault_called_normal"
    if g["status"] in ("warning", "critical"):
        p.update(status={"critical": "warning", "warning": "normal"}[g["status"]], confidence=round(R.uniform(0.55, 0.8), 2))
        return p, "under_graded"
    return None, None


def gen_real(R, split, pool_row, flip=False, agt=False):
    P = set_site(site_for(R, split), R, agt)
    P.bld_for("KH")
    row = copy.deepcopy(pool_row)
    src = "pool"
    if flip:
        p, k = flip_agent(R, row)
        if p is None:
            return None, "noflip"
        row["pred"] = p
        src = "synthetic_real_kind:" + k
    dev, loc = real_host(P, row)
    row["node"] = dev
    row["head"] = ["NODE: %s (%s)" % (dev, loc) if h.startswith("NODE:") else h for h in row["head"]]
    ex = GI.make(R, "real", "train", [row])
    if row["role"] == "hvac":       # round-1 facts quote E8 (a continuous-sensor line); for an AC unit the flat-run line is E7
        E = dict((e[0], e[1]) for e in row["ev"])
        rep = json.loads(ex["messages"][-1]["content"])
        for c in rep["agent_checks"]:
            if c.get("src") == ["S1.E8"] and "E7" in E and "sensor problem" in c.get("fact", ""):
                c["fact"], c["src"] = "the readings point to a sensor problem: %s" % E["E7"], ["S1.E7"]
        ex["messages"][-1]["content"] = json.dumps(rep, ensure_ascii=False)
    ex["family"] = ex["family"].replace("real_agent:", "real_agent_v4:") + ("+" + src if flip else "")
    ex = G2.fix(dict(ex, id="x"))
    ex = add_gold(ex)
    ex, why = postfix(ex, P)
    if ex is not None:
        ex["agent_source"] = "pool" if not flip else "synthetic"
    return ex, why


# ------------------------------------------------------------------------------------------------- new site families
def _sens(c_end, ref, role, metric, dev, loc, xs, flagged, why=None, agent=None, head=None):
    M.S.end = c_end
    return M.S(ref, role, metric, dev, loc, xs, flagged, why=why, agent=agent, head=head)


def gen_site_fam(R, split, kind, agt=True):
    """panel_trip (SUSPECT panel confirmed) | shared_panel_occ (SUSPECT panel rejected) | ac_multi_trip (SUSPECT AC confirmed)"""
    P = set_site(site_for(R, split), R, agt)
    sc = M.scen(R, 0, months=[3, 4, 5] if kind == "ac_multi_trip" else None, hours=list(range(10, 17)))
    M.S.end = end = sc["end"]
    co2r = P._rooms_with(("co2",))
    byfl = collections.defaultdict(list)
    for r_ in co2r:
        if P._bld_of(r_) == P.bld:
            byfl[P.ix.parent(r_)].append(r_)
    fls = sorted(f for f, v in byfl.items() if len(v) >= 2)
    if not fls:
        return None, "no_second_room"
    fl = R.choice(fls)
    room1 = R.choice(sorted(byfl[fl]))
    P.room = room1
    rooms = [r for r in byfl[fl] if r != room1]
    room2 = R.choice(sorted(rooms))
    if kind == "ac_multi_trip":
        eq = P._equip("ac_unit", room1, "ac", "AC unit", link=("serves", room1))
        P._add_link(eq, room2, "serves")
    else:
        eq = P._equip("panel", room1, "panel", "panel", link=("supplies", room1))
        P._add_link(eq, room2, "supplies")
    ename = P.ix.name(eq)
    on_t = R.randrange(8, 30)
    fails = 48 - R.randrange(6, 14)
    sens, refs = [], []
    if kind in ("panel_trip", "shared_panel_occ"):
        lag = R.randrange(0, 3) if kind == "panel_trip" else R.randrange(1, 3)
        for j, rm in enumerate((room1, room2)):
            dev = P._sensor_dev(rm, "power_kw", "em")
            P.host[dev] = rm
            base = R.uniform(2.0, 5.5)
            xs = M.noise(R, 144, base, 0.05, 2)
            if kind == "panel_trip":
                at = 96 + fails + (lag if j else 0)
                xs = [v if i < at else M.r1(R.uniform(0.0, 0.04), 2) for i, v in enumerate(xs)]
                ag = M.ag("step_decrease", R.choice(["warning", "critical"]), "load_drop_or_outage", round(R.uniform(0.7, 0.9), 2),
                          ["Load fell to near zero [E1,E5]"])
            else:
                at = 96 + on_t + j * lag * 2
                gain = R.uniform(1.6, 3.2)
                xs = [M.r1(v + (gain if i >= at else 0), 2) for i, v in enumerate(xs)]
                ag = M.ag("step_increase", "warning", "load_surge", round(R.uniform(0.7, 0.88), 2), ["Load stepped up [E5]"])
            sens.append(_sens(end, "S%d" % (j + 1), "power", "power_kw", dev, P.loc(rm), xs, True, agent=ag))
        if kind == "shared_panel_occ":
            for j, rm in enumerate((room1, room2)):
                dv = P._sensor_dev(rm, "occ", "occ")
                P.host[dv] = rm
                st = on_t + j * lag * 2 - R.randrange(0, 2)
                sens.append(_sens(end, "S%d" % (len(sens) + 1), "occupancy", "occ", dv, P.loc(rm), [0] * st + [1] * (48 - st), False,
                                  why="occupancy of %s" % P.ix.name(rm),
                                  agent=M.ag("arrival", "normal", "arrival", 0.9, ["Room became occupied [E4,E1]"])))
    else:
        for j, rm in enumerate((room1, room2)):
            dev = P._sensor_dev(rm, "temp", "air")
            P.host[dev] = rm
            b0 = R.uniform(23.0, 24.8)
            top = R.uniform(29.0, 33.6) if R.random() < 0.6 else R.uniform(34.3, 36.0)
            at = fails - R.randrange(0, 3)
            xs = M.noise(R, 96, b0, 0.08, 1) + [M.r1(b0 + (top - b0) * max(0, i - at) / max(1, 47 - at) + R.uniform(-0.08, 0.08), 1) if i >= at else
                                              M.r1(b0 + R.uniform(-0.1, 0.1), 1) for i in range(48)]
            st = M.sev_hi(xs[-1], 30, 34)
            ag = M.ag("gradual_increase", st, "hvac_cooling_issue", round(R.uniform(0.7, 0.9), 2), ["Room temperature climbing [E4,E1]"])
            sens.append(_sens(end, "S%d" % (j + 1), "air_quality", "temp", dev, P.loc(rm), xs, True, agent=ag, head=[M.LIM["temp"]]))
    p1, p2 = M.P(sens[0]), M.P(sens[1])
    n1, n2 = P.ix.name(room1), P.ix.name(room2)
    if kind == "panel_trip":
        sev = "critical"
        label = "power_load_anomaly"
        title = "%s: loads in %s and %s lost together" % (ename, n1, n2)
        rc = "%s stopped supplying both rooms at the same time: a supply interruption at the shared panel, not two room faults." % ename
        chain = "%s trips -> %s load drop (S1.E5) and %s load drop (S2.E5)" % (ename, n1, n2)
        obs = [M.ob("%s load now %s kW" % (n1, p1["last"]), ["S1.E1"]), M.ob("%s load now %s kW" % (n2, p2["last"]), ["S2.E1"]),
               M.ob("Both drops in the same minutes: %s and %s" % (p1["jump_t"], p2["jump_t"]), ["S1.E5", "S2.E5"])]
        sus = {"node": ename, "verdict": "confirmed", "why": "both supplied loads dropped together", "src": ["S1.E5", "S2.E5"]}
        clist = [("inspect_electrical", ename, "Both supplied rooms lost power together"), ("monitor", "S1", "Load should return after the reset")]
        expl = "Both rooms on %s lost their load at once, so the panel is the common cause." % ename
        rt, hops, doms = "chain_max", 1, ["power"]
    elif kind == "shared_panel_occ":
        sev = "warning" if R.random() < 0.5 else "normal"
        label = "occupancy_driven_load"
        title = "%s and %s loads up with their own occupancy, %s fine" % (n1, n2, ename)
        rc = "Each room's load rose after its own arrival; the shared panel %s is not the common cause." % ename
        p3, p4 = M.P(sens[2]), M.P(sens[3])
        chain = "arrival %s (S3.E4) -> %s load up (S1.E5); arrival %s (S4.E4) -> %s load up (S2.E5)" % (p3["first_on"], n1, p4["first_on"], n2)
        obs = [M.ob("%s load up %s kW at %s" % (n1, p1["jump"].lstrip("+"), p1["jump_t"]), ["S1.E5"]),
               M.ob("%s load up %s kW at %s" % (n2, p2["jump"].lstrip("+"), p2["jump_t"]), ["S2.E5"]),
               M.ob("Rooms occupied since %s and %s" % (p3["first_on"], p4["first_on"]), ["S3.E4", "S4.E4"])]
        sus = {"node": ename, "verdict": "rejected", "why": "each load follows its own room's arrival", "src": ["S3.E4", "S4.E4"]}
        clist = [("monitor", "S1", "Loads should fall when the rooms empty")]
        expl = "Two rooms filled up at about the same time; the panel %s is fine." % ename
        rt, hops, doms = "pair_relation", 1, ["power", "occupancy"]
    else:
        st1, st2 = sens[0]["agent"]["status"], sens[1]["agent"]["status"]
        sev = M.worst(st1, st2)
        if sev == "normal":
            return None, "ac_normal"
        label = "hvac_or_thermal_issue"
        title = "%s down: %s and %s heating up" % (ename, n1, n2)
        rc = "%s serves both rooms and stopped cooling; both rooms warm together." % ename
        chain = "%s stops -> %s warms (S1.E4) and %s warms (S2.E4)" % (ename, n1, n2)
        obs = [M.ob("%s at %s C" % (n1, p1["last"]), ["S1.E1"]), M.ob("%s at %s C" % (n2, p2["last"]), ["S2.E1"]),
               M.ob("Both rising: %s and %s C/h" % (p1["slope"], p2["slope"]), ["S1.E4", "S2.E4"])]
        sus = {"node": ename, "verdict": "confirmed", "why": "both rooms it serves warm together", "src": ["S1.E4", "S2.E4"]}
        clist = [("inspect_hvac", ename, "One AC serves both warming rooms"), ("monitor", "S1", "Room temperature after the repair")]
        expl = "One AC serves both rooms and both are warming, so check %s first." % ename
        rt, hops, doms = "chain_max", 1, ["air_quality"]
    checks = []
    if kind == "shared_panel_occ":
        checks = [{"ref": "S1", "claim": "load_surge", "verdict": "corrected", "fact": "the step follows the arrival in the room",
                   "src": ["S1.E5", "S3.E4"]}]
    clr = [(a, t if not (len(t) == 2 and t.startswith("S")) else "%s (%s)" % (t, sens[int(t[1]) - 1]["node"]), w) for a, t, w in clist]
    rep = M.rep(title[:80], sev, label, rc, chain, obs, checks, doms, [], M.ev_of(obs), round(R.uniform(0.78, 0.9), 2), clr,
                "Both rooms over the next re-check", expl)
    CUR["suspect"] = "%s? %s -> confirm or reject" % (ename, "2 of its %s loads flagged within 15 min" % (
        "served" if kind == "ac_multi_trip" else "supplied"))
    CUR["suspect_gold"] = sus
    row = G2.mk_row(R, sc, "site:" + kind, sens, rep, sens[0]["metric"], "x", 0)
    th = None
    if len({s["role"] for s in sens if s["flagged"]}) >= 2:
        th = "Flagged %s. %s" % (", ".join(sorted({s["role"] for s in sens if s["flagged"]})), sus["why"])
    row = G2.fix(dict(row, id="x"))
    if th:
        row["messages"][-1]["reasoning_content"] = th
    row = add_gold(row)
    CUR["suspect_gold"] = None
    row.update(reasoning_type=rt, hops=hops)
    row, why = postfix(row, P)
    return row, why


# ------------------------------------------------------------------------------------------------- card family (unseen metrics)
DOM_LABEL = {"air_quality": "air_pollution_event", "water": "water_quality_issue", "power": "power_load_anomaly",
             "weather": "weather_driven", "hvac": "hvac_or_thermal_issue", "occupancy": "occupancy_driven_load"}
DOM_ACT = {"air_quality": "inspect_ventilation", "water": "inspect_water_system", "power": "inspect_electrical",
           "weather": "monitor", "hvac": "inspect_hvac", "occupancy": "review_schedule",
           "building": "request_facility_review", "environment": "monitor", "equipment": "request_facility_review",
           "safety": "request_facility_review"}
DOM_LABEL.update({"building": "unknown", "environment": "unknown", "equipment": "unknown", "safety": "unknown"})


def _lvl(card, v):
    w, c = card.get("warning"), card.get("critical")
    def beyond(lim, v):
        if not lim:
            return False
        if lim["dir"] == "high":
            return v > lim["at"]
        if lim["dir"] == "low":
            return v < lim["at"]
        return v < lim["low"] or v > lim["high"]
    return "critical" if beyond(c, v) else ("warning" if beyond(w, v) else "normal")


def gen_card(R, split, types, agt=True, want=None, r_err=None):
    P = set_site(site_for(R, split), R, agt)
    tname = R.choice(sorted(types))
    card = CD.synthetic_card(tname, R)
    if card.get("rate_rules") or not card.get("warning") or card["kind"] != "continuous":
        return None, "card_kind"
    EV.register(card)
    cal = SM.Calendar(R.randrange(10 ** 6))
    end_dt = dt.datetime(2026, R.randrange(1, 13), R.randrange(1, 28), R.randrange(7, 21), R.choice(range(0, 60, 5)), tzinfo=L.IST)
    end = int(end_dt.timestamp())
    drv = SM.Drivers(R.randrange(10 ** 6), end - 143 * 300, 144, "office", R.randint(5, 60), cal)
    y = SM.channel(card, drv, R)
    want = want or R.choices(["normal", "warning", "critical", "fault"], [0.3, 0.25, 0.2, 0.25])[0]
    dec = card.get("decimals", 1)
    fk = None
    lim = card["warning"] if want == "warning" else card.get("critical")
    if want in ("warning", "critical") and lim:
        hi = lim.get("dir") != "low"
        tgt = (lim.get("at") if lim.get("at") is not None else (lim["high"] if hi else lim["low"]))
        span = abs(tgt) * R.uniform(0.04, 0.12) + (card.get("noise") or 0) * 2
        tgt = tgt + span if hi else tgt - span
        if want == "warning" and card.get("critical"):
            c = card["critical"]
            ct = c.get("at") if c.get("at") is not None else (c["high"] if hi else c["low"])
            tgt = (tgt + ct) / 2 if (hi and tgt >= ct) or (not hi and tgt <= ct) else tgt
        on = 144 - R.randrange(8, 30)
        ms = card.get("max_step") or abs(tgt - y[on]) or 1
        k = max(144 - on, 1)
        for i in range(on, 144):
            frac = (i - on + 1) / k
            y[i] = y[i] + (tgt - y[on]) * frac
        if max(abs(y[i] - y[i - 1]) for i in range(on, 144)) > ms:
            return None, "step"
    elif want == "fault":
        fk = R.choice(["stuck", "impossible", "noise"])
        imp = card.get("impossible") or {}
        on = 144 - R.randrange(24, 40)
        if fk == "stuck":
            v = y[on]
            y = y[:on] + [v] * (144 - on)
        elif fk == "impossible":
            if imp.get("below") is not None:
                bad = imp["below"] - abs(imp["below"]) * 0.2 - 1
            elif imp.get("above") is not None:
                bad = imp["above"] * 1.1 + 1
            else:
                return None, "no_imp"
            y = y[:-6] + [bad + R.uniform(-0.5, 0.5) for _ in range(6)]
        else:
            nz = (card.get("noise") or 1) * 10
            y = y[:on] + [v + R.gauss(0, nz) for v in y[on:]]
    y = [round(v, dec) if dec else round(v) for v in y]
    st, ev, info = EV.evidence_lines(card, y, 48, end)
    E = {a: c for a, b, c in ev}
    last = float(re.search(r"last = ([-\d.]+)", E["E1"]).group(1))
    imp = card.get("impossible") or {}
    is_imp = (imp.get("below") is not None and last < imp["below"]) or (imp.get("above") is not None and last > imp["above"])
    fl = re.search(r"longest flat run (\d+) pts", E.get("E8", ""))
    nz = re.search(r"noise ([\d.]+)", E.get("E8", ""))
    if want == "fault":
        vis = is_imp or (fk == "stuck" and fl and int(fl.group(1)) >= 20) or (fk == "noise" and nz and float(nz.group(1)) >= 4 * (card.get("noise") or 1))
        if not vis:
            return None, "fault_not_visible"
        sev = "sensor_fault"
    else:
        if is_imp:
            return None, "imp_event"
        sev = _lvl(card, last)
    dom = card["domain"]
    room = P.room if dom in ("air_quality", "occupancy", "hvac") else P.host[P.resolve("tank", "KH")[0]] if dom == "water" else \
        P.host.get(CUR["feeder"][0], P.room) if dom == "power" else P.host[L.WEATHER[0]]
    code, lv = P._code_level(room)
    dev = P.nm.device("x", code, lv, R.randint(1, 40), P.ix.name(room))
    P._add_node({"id": dev + "/" + card["card_id"], "kind": "sensor", "parent": room, "device": dev, "metric": card["card_id"], "card": card["card_id"], "dev_kind": "x"})
    P.host[dev] = room
    short = card.get("short", card["quantity"])
    unit = card["unit"] or "ratio"
    # agent (real-error kinds at 30 %)
    true_ag = {"sensor_fault": "sensor_fault", "warning": "warning", "critical": "critical", "normal": "normal"}[sev]
    r = R.random()
    if r_err is not None:
        r = r_err
    agst, err = true_ag, None
    if r < 0.12 and sev == "sensor_fault":
        agst, err = "normal", "fault_called_normal"
    elif r < 0.22 and sev in ("warning", "critical"):
        agst, err = {"critical": "warning", "warning": "normal"}[sev], "under_graded"
    elif r < 0.3 and sev == "normal":
        agst, err = "warning", "false_alarm"
    pat = {"sensor_fault": "flatline" if fk == "stuck" else "erratic", "warning": "gradual_increase", "critical": "gradual_increase",
           "normal": "stable"}[agst]
    cause = "sensor_fault" if agst == "sensor_fault" else (card["causes"][1] if agst != "normal" and len(card["causes"]) > 1 else card["causes"][0])
    ag = M.ag(pat, agst, cause, round(R.uniform(0.62, 0.9), 2), ["%s now %s [E1]" % (short, E["E1"].split("= ", 1)[1])])
    s = {"ref": "S1", "role": dom, "metric": card["card_id"].rsplit("_", 1)[0], "node": dev, "loc": P.loc(room), "flagged": True,
         "why": None, "quality": "good", "head": [], "stale": None, "ev": [(a, c) for a, b, c in ev], "agent": ag, "card": card,
         "unit_shown": unit}
    if fk == "impossible":
        s["quality"] = "bad (current value outside the physical range on the card)"
    label = "sensor_fault" if sev == "sensor_fault" else ("normal_operation" if sev == "normal" else DOM_LABEL[dom])
    obs = [M.ob("%s %s" % (short, E["E1"]), ["S1.E1"]), M.ob("%s %s" % (short, E["E8"] if sev == "sensor_fault" else E["E4"]),
                                                             ["S1.E8" if sev == "sensor_fault" else "S1.E4"])]
    checks = []
    if err:
        fact = {"fault_called_normal": "the readings point to a sensor problem: %s" % E["E8"] if not is_imp else "the current value is impossible on the card: %s" % E["E1"],
                "under_graded": "the card limit is crossed: %s" % E["E1"], "false_alarm": "inside the card normal: %s" % E["E1"]}[err]
        checks.append({"ref": "S1", "claim": "status %s" % agst, "verdict": "corrected", "fact": fact,
                       "src": ["S1.E8" if err == "fault_called_normal" and not is_imp else "S1.E1"]})
    if sev == "sensor_fault":
        title = "Suspect %s readings: %s" % (short, P.ix.name(room))
        rc = "The %s readings are not plausible for this sensor (%s): a sensor fault, not a process event." % (short, fk)
        acts = [("check_sensor", "S1 (%s)" % dev, "Readings do not fit the card")]
        expl = "Treat the %s data as unreliable until the sensor is checked." % short
    elif sev == "normal":
        title = "%s within its card normal: %s" % (short, P.ix.name(room))
        rc = "%s stays inside its normal range." % short
        acts = [("monitor", "S1 (%s)" % dev, "Re-check at the next window")]
        expl = "Nothing abnormal for this sensor."
    else:
        title = "%s %s %s: %s" % (short, sev, E["E1"].split("= ", 1)[1], P.ix.name(room))
        rc = "%s is beyond its card %s limit." % (short, sev)
        acts = [(DOM_ACT[dom], "S1 (%s)" % dev, "%s beyond the card %s limit" % (short, sev))]
        if sev == "critical":
            acts.append(("request_facility_review", "S1 (%s)" % dev, "Critical on the card"))
        expl = "%s crossed the %s limit on its card; follow the checklist." % (short, sev)
    gchain = {"sensor_fault": "%s fault -> implausible readings (S1.E8)" % (fk or "sensor"), "normal": "no change beyond the card normal (S1.E1)",
              "warning": "%s rise -> beyond the card warning (S1.E1)" % short, "critical": "%s rise -> beyond the card critical (S1.E1)" % short}[sev]
    if fk == "impossible":
        gchain = "impossible value on the card -> sensor fault (S1.E1)"
    rep = M.rep(title[:80], sev, label, rc, gchain, obs, checks, [dom],
                ["S1"] if sev == "sensor_fault" else [], M.ev_of(obs), round(R.uniform(0.75, 0.9), 2),
                acts, "%s at the next window" % short, expl)
    if sev == "sensor_fault":
        rep["checklist"] = rep["checklist"][:1]
    case = {"end": end_dt, "outdoor": None, "inc_id": "INC-%04d" % R.randrange(100, 9999), "mode": "early", "win_h": "4", "sensors": [s],
            "recheck": None, "memory": [], "notes": None, "missing_note": None, "ask": R.choice(G2.ASKS)}
    user = L.render(case)
    row = {"id": "x", "family": "card:%s%s" % (tname, "+" + err if err else ""), "tools": "incident_v4",
           "messages": [{"role": "system", "content": SYS_V4}, {"role": "user", "content": user},
                        {"role": "assistant", "content": json.dumps(rep, ensure_ascii=False)}],
           "card_type": tname, "fault_kind": fk}
    row = add_gold(row)
    row, why = postfix(row, P)
    return row, why
