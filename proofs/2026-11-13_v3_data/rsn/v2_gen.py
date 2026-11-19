"""v2 families on top of gen_inc_v4 (v1 files untouched; everything here is monkeypatch-free for v1 except the added r4
families, which are appended to gen_r4_inc.FAMS only inside a v2 build process).

  agt3      : agt_v3 snap_1750 REAL outputs (CPU llama.cpp, greedy) on fresh synthetic train-site windows and on cleaned real
              pool windows; the S1 agent line + 'agent data' line are the model's own output; gold from the evidence-supported
              window gold (label-audit judge on the same E-lines), the agent claim is a hypothesis the report corrects.
  r4 (new)  : heat_feeder2 (multihop 2: heat -> AC -> feeder load), pf_chain4 (multihop 4: heat -> room -> AC -> feeder -> pf)
  xfloor    : cross-floor flow on a deterministic vertical link (room above `drains-to` room below; room below `below` room above):
              water leak upstairs -> damp air downstairs, heat rising from the floor below, smoke (PM2.5) rising from below;
              negative controls: same time, rooms on other floors with no link -> two separate events."""
import collections
import json
import re
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_inc_v4 as G  # noqa: E402

M, L, G2 = G.M, G.L, G.G2
AGT = {"line": None}
_orig_bc = G.build_ctx


def _bc(case):
    ctx = _orig_bc(case)
    if AGT["line"] and ctx.get("agent_data") is not None:
        ctx["agent_data"]["S1"] = AGT["line"]
    return ctx


G.build_ctx = _bc
DQ = {"ok": "ok", "suspect": "suspect", "fault": "bad", "insufficient": "bad"}


def parse_agent(text):
    t = (text or "").strip()
    i = t.find('"action"')
    if i >= 0:
        t = t[:i]
    t = re.sub(r",\s*$", "", t.strip())
    for cand in (t, t + "}", t + "]}", t + '"}'):
        try:
            o = json.loads(cand)
            if isinstance(o, dict) and o.get("status") in ("normal", "warning", "critical", "sensor_fault"):
                return o
        except Exception:  # noqa: BLE001
            pass
    return None


def agent_line(o):
    dq = DQ.get(((o.get("data_quality") or {}).get("verdict") or "ok"), "suspect")
    rs = re.sub(r"\s+", " ", str(o.get("severity_reason") or "no reason given")).strip()[:140]
    return "dq=%s | reason: %s" % (dq, rs)


def gen_agt3(R, win, otext, split="train"):
    o = parse_agent(otext)
    if o is None:
        return None, "agent_unparsable"
    pred = {"pattern": o.get("pattern", "?"), "status": o["status"], "observations": [str(x) for x in (o.get("observations") or [])][:2],
            "likely_cause": o.get("likely_cause", "?"), "confidence": o.get("confidence", 0.5)}
    try:
        pred["confidence"] = max(0.0, min(1.0, float(pred["confidence"])))
    except Exception:  # noqa: BLE001
        pred["confidence"] = 0.5
    row = {"id": win["wid"], "role": win["role"], "node": win["node"], "metric": win["metric"], "head": list(win["head"]),
           "ev": [list(e) for e in win["ev"]], "gold": dict(win["gold"]), "pred": pred, "n": win["n"], "end_epoch": win["end_epoch"], "model": "agt3",
           "split": "train"}
    AGT["line"] = agent_line(o)
    try:
        ex, why = G.gen_real(R, split, row, flip=False, agt=True)
    finally:
        AGT["line"] = None
    if ex is None:
        return None, why
    rep = json.loads(ex["messages"][-1]["content"])
    E = dict(map(tuple, win["ev"]))
    for c in rep["agent_checks"]:   # the 'normal' correction quotes E1: cite E1
        if c.get("fact", "").startswith("the evidence stays within normal behaviour: ") and "E1" in E:
            c["src"] = ["S1.E1"]
    v = (o.get("data_quality") or {}).get("verdict")
    if v == "fault" and win["gold"]["status"] != "sensor_fault" and o["status"] != "sensor_fault" and "E8" in E and len(rep["agent_checks"]) < 4:
        rep["agent_checks"].append({"ref": "S1", "claim": "data quality fault", "verdict": "corrected",
                                    "fact": "the evidence shows no data fault: %s" % E["E8"], "src": ["S1.E8"]})
    ex["messages"][-1]["content"] = json.dumps(rep, ensure_ascii=False)
    ex["family"] = "agt3_real:%s:%s:%s" % (win["src"], win["role"], "agent_wrong" if o["status"] != win["gold"]["status"] else "agent_right")
    ex["agent_source"] = "agt_v3_snap_1750_q4_0_cpu"
    ex["window_src"] = win["src"]
    ex["agent_status"], ex["gold_status"] = o["status"], win["gold"]["status"]
    return ex, None


# ------------------------------------------------------------------------------------------------- new r4 multihop families
def _hot_agent(sevw):
    return lambda s: M.ag("gradual_increase", sevw, "heat_buildup", 0.8, ["Temperature climbing at %s C/h, now %s C [E4,E1]" % (M.P(s)["slope"], M.P(s)["last"])])


def _ac(ref, nd, on, a0, a1):
    return M.S(ref, "hvac", "ac_units_on", nd["ac"][0], nd["ac"][1], [a0] * on + [a1] * (48 - on), False, "AC response", unit_shown="units",
               agent=lambda s: M.ag("step_increase", "normal", "hvac_context", 0.8, ["AC units running: now %s [E1,E4]" % M.P(s)["last"]]))


def f_heat_feeder2(R, sc, nd):
    temps, sevw = M.heat_base(R, sc, R.choice(["critical", "warning"]))
    if sevw is None:
        return None
    s1 = M.S("S1", "weather", "temp", M.WE_NODE, M.WE_LOC, temps, True, head=[M.LIM["wtemp"]], agent=_hot_agent(sevw))
    on = R.randrange(6, 26)
    k0 = R.uniform(900, 1300)
    s2 = M.S("S2", "power", "power_kw", M.SUB_NODE, M.SUB_LOC, M.ramp(R, on, k0, k0 + R.uniform(180, 420), 6, 2, shape="lin"), True,
             agent=lambda s: M.trend_ag(s, "warning", "high_load", word="Power"))
    a0, a1 = R.choice([1, 2]), R.choice([3, 4])
    s3 = _ac("S3", nd, on, a0, a1)
    sens = [s1, s2, s3]
    p1, p3 = M.P(s1), M.P(s3)
    sev = sevw
    obs = [M.o_tr(s1, "Outdoor temperature"), M.ob("AC units running now %s" % p3["last"], ["S3.E1"]), M.o_tr(s2, "Feeder load")]
    title = R.choice(["Outdoor heat %s C raising the feeder load through the AC: SB00 substation" % p1["last"],
                      "Heat, more AC units, feeder load up: SB00 substation"])
    checks = [{"ref": "S2", "claim": "high_load", "verdict": "corrected", "fact": "the load rise follows the AC units rising to %s in the heat" % p3["last"],
               "src": ["S2.E4", "S3.E1"]}]
    acts = [("inspect_electrical", "S2 (%s)" % M.SUB_NODE, "Feeder load climbing with the cooling load"),
            ("review_schedule", "S1 (%s)" % M.WE_NODE, "Stagger AC start-ups in the hottest hours")]
    if sev == "critical":
        acts.insert(1, ("request_facility_review", "S2 (%s)" % M.SUB_NODE, "Heat beyond the critical limit with a rising load"))
    r = M.rep(title, sev, "weather_driven", "Outdoor heat started more AC units and the extra cooling load raised the feeder load; the heat is the root, two steps from the meter.",
              "outdoor heat (S1.E4) -> AC units to %s (S3.E1) -> feeder load up (S2.E4)" % p3["last"], obs, checks, ["weather", "power", "hvac"], [],
              M.ev_of(obs), round(R.uniform(0.8, 0.9), 2), acts, "Feeder load as the afternoon cools",
              R.choice(["The meter only shows the end of the chain: heat, then AC, then load.", "Weather drives this load; no electrical fault."]))
    link = "Chain: heat S1 starts more AC S3, so the feeder load S2 climbs. Two hops from weather to power."
    root = "Root: outdoor heat; the feeder load is the symptom."
    return M.X(sensors=sens, report=r, root_metric="power_kw", rtype="multihop", hops=2, think=(link, root), fam="heat_feeder2",
               outdoor=(p1["last"], M.WE_NODE, L.tstr(sc["end"])), ctx=("Feeder load rising: SB00 substation", "warning", title, sev))


def f_pf_chain4(R, sc, nd):
    temps, sevw = M.heat_base(R, sc, R.choice(["critical", "warning"]))
    if sevw is None:
        return None
    pfx = M.ev_pf(R, sc, nd, "S4")
    if not pfx:
        return None
    s1 = M.S("S1", "weather", "temp", M.WE_NODE, M.WE_LOC, temps, True, head=[M.LIM["wtemp"]], agent=_hot_agent(sevw))
    rt0, gain = R.uniform(24.0, 25.5), R.uniform(0.25, 0.45)
    rt = [M.r1(rt0 + max(0.0, t - temps[0]) * gain + R.gauss(0, 0.08), 1) for t in temps]
    s2 = M.S("S2", "air_quality", "temp", nd["aq"][0], nd["aq"][1], rt, True, "indoor temperature",
             agent=lambda s: M.trend_ag(s, M.sev_hi(float(M.P(s)["last"]), 30, 34), "high_heat_load", word="Temperature"), head=[M.LIM["temp"]])
    on = R.randrange(6, 26)
    k0 = R.uniform(900, 1300)
    s3 = M.S("S3", "power", "power_kw", M.SUB_NODE, M.SUB_LOC, M.ramp(R, on, k0, k0 + R.uniform(180, 420), 6, 2, shape="lin"), True,
             agent=lambda s: M.trend_ag(s, "warning", "high_load", word="Power"))
    s4 = pfx["s"][0]
    a0, a1 = R.choice([1, 2]), R.choice([3, 4])
    s5 = _ac("S5", nd, on, a0, a1)
    sens = [s1, s2, s3, s4, s5]
    p1, p2, p4, p5 = M.P(s1), M.P(s2), M.P(s4), M.P(s5)
    sev = M.worst(sevw, M.sev_hi(float(p2["last"]), 30, 34), pfx["sev"])
    obs = [M.o_tr(s1, "Outdoor temperature"), M.o_tr(s2, "Room temperature"), M.ob("AC units running now %s" % p5["last"], ["S5.E1"]),
           M.o_tr(s3, "Feeder load"), M.o_now(s4, "Power factor")]
    title = R.choice(["Power factor %s at the end of a heat chain: SB00 substation" % p4["last"], "Heat to room to AC to feeder: power factor %s" % p4["last"]])
    acts = [("inspect_electrical", "S4 (%s)" % M.SUB_NODE, "Capacitor bank must cover the extra inductive AC load")]
    if sev == "critical":
        acts.append(("request_facility_review", "S4 (%s)" % M.SUB_NODE, "Beyond the critical limit"))
    acts.append(("inspect_hvac", "S5 (%s)" % nd["ac"][0], "AC working hard against the heat"))
    r = M.rep(title, sev, "power_quality_issue",
              "Outdoor heat warmed the room, more AC compressors started, the feeder load rose and the extra inductive load pulled the power factor down.",
              "outdoor heat (S1.E4) -> room temperature up (S2.E4) -> AC units to %s (S5.E1) -> feeder load up (S3.E4) -> power factor %s (S4.E1)" % (p5["last"], p4["last"]),
              obs, [], ["weather", "air_quality", "hvac", "power"], [], M.ev_of(obs), round(R.uniform(0.8, 0.9), 2), acts,
              "Power factor once the capacitor bank is checked", "Four steps from the weather to the power factor; fix the compensation first.")
    link = "Chain: heat S1 warms room S2, more AC S5 runs, feeder load S3 climbs, power factor S4 dips. Four hops."
    root = "Root: outdoor heat; the actionable event is the power factor."
    return M.X(sensors=sens, report=r, root_metric="pf", rtype="multihop", hops=4, think=(link, root), fam="pf_chain4",
               outdoor=(p1["last"], M.WE_NODE, L.tstr(sc["end"])), ctx=("Feeder load rising: SB00 substation", "warning", title, sev))


def install_r4():
    if any(f[0] == "heat_feeder2" for f in M.FAMS):
        return
    M.FAMS.append(("heat_feeder2", lambda R, sc, nd, nd2: f_heat_feeder2(R, sc, nd), 0.0))
    M.FAMS.append(("pf_chain4", lambda R, sc, nd, nd2: f_pf_chain4(R, sc, nd), 0.0))
    M.RT_OF.update(heat_feeder2="multihop", pf_chain4="multihop")
    M.HEAT_FAMS.update({"heat_feeder2", "pf_chain4"})


def weights(names_w):
    return [names_w.get(f[0], 0.0) for f in M.FAMS]


# ------------------------------------------------------------------------------------------------- cross-floor flow
def vertical_pairs(P):
    """deterministic vertical adjacency in the scenario building: (room above, room below) with the same position index on
    adjacent levels (room i of level L sits above room i mod n of level L-1)"""
    by = collections.defaultdict(list)
    for n in P.site["nodes"]:
        if n["kind"] == "room" and P._bld_of(n["id"]) == P.bld:
            by[P._code_level(n["id"])[1]].append(n["id"])
    out = []
    for lv in sorted(by):
        if lv - 1 in by:
            up, dn = sorted(by[lv]), sorted(by[lv - 1])
            out += [(u, dn[i % len(dn)]) for i, u in enumerate(up)]
    return out, by


def _ramp_at(R, on, base, top, nz, dec):
    return M.ramp(R, on, base, top, nz, dec, shape="lin")


def gen_xfloor(R, split, kind, agt=True):
    """kind: water | heat | smoke | neg_water | neg_heat | neg_smoke"""
    P = G.set_site(G.site_for(R, split), R, agt)
    pairs, by = vertical_pairs(P)
    if not pairs:
        return None, "no_vertical_pair"
    up, dn = R.choice(pairs)
    neg = kind.startswith("neg_")
    if neg:   # a room on the level below that is NOT under `up` (no link between them)
        lv = P._code_level(up)[1]
        others = sorted(r for r in by[lv - 1] if r != dn)
        if not others:
            return None, "no_unlinked_room"
        dn = R.choice(others)
    elif kind == "water":
        P._add_link(up, dn, "drains-to")
    else:
        P._add_link(dn, up, "below")
    sc = M.scen(R, 0, hours=list(range(9, 19)) if kind.endswith(("heat", "smoke")) else list(range(19, 23)) + list(range(6, 9)))
    M.S.end = sc["end"]
    nU, nD = P.ix.name(up), P.ix.name(dn)
    fU, fD = P.ix.name(P.ix.parent(up)), P.ix.name(P.ix.parent(dn))
    base = kind.replace("neg_", "")
    on = R.randrange(4, 18)
    lag = R.randrange(3, 9)
    sens = []
    if base == "water":
        d1 = P._sensor_dev(dn, "rh", "air")
        P.host[d1] = dn
        top = R.uniform(74, 83) if R.random() < 0.65 else R.uniform(87, 93)
        s1 = M.S("S1", "air_quality", "rh", d1, P.loc(dn), _ramp_at(R, on + lag, R.uniform(50, 58), top, 0.3, 1), True,
                 agent=lambda s: M.trend_ag(s, M.sev_hi(float(M.P(s)["last"]), 70, 85), "humidity_control_issue", word="Humidity"),
                 head=["LIMITS: warning above 70, critical above 85"])
        d2 = P._sensor_dev(up, "flow", "flow")
        P.host[d2] = up
        b0 = R.uniform(0.05, 0.3)
        xs2 = M.step(R, on, b0, b0 + R.uniform(1.0, 2.4), 0.03, 2)
        wv = xs2[-48:]
        fh = sum(wv[:12]) / 12.0
        sevf = "critical" if (max(wv) - min(wv)) > 1.5 * max(fh, 1e-6) else "warning"
        s2 = M.S("S2", "water", "flow", d2, P.loc(up), xs2, True,
                 agent=lambda s: M.ag("step_increase", sevf, "possible_leak", 0.75, ["Flow stepped up %s m3/h at %s and stays high [E5,E1]" % (M.P(s)["jump"].lstrip("+"), M.P(s)["jump_t"])]))
        d3 = P._sensor_dev(up, "occ", "occ")
        P.host[d3] = up
        s3 = M.S("S3", "occupancy", "occ", d3, P.loc(up), [0] * 48, False, why="occupancy of %s" % nU,
                 agent=M.ag("vacant", "normal", "vacant", 0.95, ["Room unoccupied for the whole 4-hour window [E2,E1]"]))
        sens = [s1, s2, s3]
    else:
        met = "temp" if base == "heat" else "pm25"
        lim = M.LIM[met]
        if base == "heat":
            topD, topU = R.uniform(34.5, 39.0), R.uniform(30.6, 33.4) if R.random() < 0.6 else R.uniform(34.3, 35.5)
            bD, bU, nz, dec, w, c = R.uniform(25, 27), R.uniform(24, 25.5), 0.08, 1, 30, 34
        else:
            topD, topU = R.uniform(140, 260), R.uniform(66, 115)
            bD, bU, nz, dec, w, c = R.uniform(12, 30), R.uniform(10, 25), 1.0, 1, 60, 120
        if topU >= topD:
            return None, "order"
        cause = "high_heat_load" if base == "heat" else "indoor_emission_source"
        word = "Temperature" if base == "heat" else "PM2.5"
        dD = P._sensor_dev(dn, met, "air")
        P.host[dD] = dn
        dU = P._sensor_dev(up, met, "air")
        P.host[dU] = up
        uon = on if neg else on + lag
        s1 = M.S("S1", "air_quality", met, dU, P.loc(up), _ramp_at(R, uon, bU, topU, nz, dec), True,
                 agent=lambda s: M.trend_ag(s, M.sev_hi(float(M.P(s)["last"]), w, c), "hvac_cooling_issue" if base == "heat" else "ventilation_insufficient", word=word),
                 head=[lim])
        s2 = M.S("S2", "air_quality", met, dD, P.loc(dn), _ramp_at(R, on, bD, topD, nz, dec), True,
                 agent=lambda s: M.trend_ag(s, M.sev_hi(float(M.P(s)["last"]), w, c), cause, word=word), head=[lim])
        d3 = P._sensor_dev(up, "occ", "occ")
        P.host[d3] = up
        s3 = M.S("S3", "occupancy", "occ", d3, P.loc(up), [0] * 48, False, why="occupancy of %s" % nU,
                 agent=M.ag("vacant", "normal", "vacant", 0.95, ["Room unoccupied for the whole 4-hour window [E2,E1]"]))
        sens = [s1, s2, s3]
    p1, p2 = M.P(sens[0]), M.P(sens[1])
    try:
        l1, l2 = float(p1["last"]), float(p2["last"])
    except (KeyError, ValueError):
        return None, "parse"
    if base == "water":
        sev1 = M.sev_hi(l1, 70, 85)
        if sev1 == "normal":
            return None, "rh_normal"
        sev = M.worst(sev1, sevf)
    else:
        w, c = (30, 34) if base == "heat" else (60, 120)
        sv1, sv2 = M.sev_hi(l1, w, c), M.sev_hi(l2, w, c)
        if sv1 == "normal" or sv2 == "normal" or (not neg and l1 >= l2):
            return None, "levels"
        sev = M.worst(sv1, sv2)
    d1, d2 = sens[0]["node"], sens[1]["node"]
    th = None
    if not neg:
        if base == "water":
            title = "Water from %s upstairs showing as damp air in %s" % (nU, nD)
            rc = "Water runs in %s on %s with nobody there and drains to %s below; the damp air downstairs is the symptom, the source is upstairs." % (nU, fU, nD)
            chain = "flow up in %s (S2.E5) -> water drains to %s (drains-to) -> humidity rising (S1.E4)" % (nU, nD)
            obs = [M.o_tr(sens[0], "Humidity in %s" % nD), M.o_now(sens[0], "Humidity"),
                   M.ob("Flow in %s stepped up %s m3/h at %s" % (nU, p2["jump"].lstrip("+"), p2["jump_t"]), ["S2.E5"]),
                   M.ob("Nobody in %s during the window" % nU, ["S3.E1", "S3.E2"])]
            checks = [{"ref": "S1", "claim": "humidity_control_issue", "verdict": "corrected",
                       "fact": "the damp air follows the flow in %s on the floor above, which drains to this room" % nU, "src": ["S1.E4", "S2.E5"]}]
            acts = [("inspect_water_system", "S2 (%s)" % d2, "Continuous flow in an empty room on the floor above"),
                    ("monitor", "S1 (%s)" % d1, "Humidity should fall once the leak is stopped")]
            label, doms, rt = "water_leak_or_overuse", ["water", "air_quality"], "pair_who"
            expl = "Find the leak upstairs in %s: the damp air in %s is water coming down from it." % (nU, nD)
            th = "Damp air S1 in %s follows the flow S2 in %s on the floor above, which drains to it; S3 shows the room empty. Root: water upstairs; humidity below is the symptom." % (nD, nU)
        else:
            what = "Heat" if base == "heat" else "Smoke or dust"
            title = "%s rising from %s into %s above" % (what, nD, nU)
            rc = "%s comes from %s on %s, the floor below: it is higher there (%s) and %s above follows it with nobody inside; the source is downstairs." % (
                what, nD, fD, p2["last"], nU)
            chain = "%s rising in %s (S2.E4) -> rises to the room above (below link) -> %s rising (S1.E4)" % (word.lower() if base == "heat" else "PM2.5", nD, nU)
            obs = [M.o_now(sens[1], "%s in %s" % (word, nD)), M.o_tr(sens[1], word + " below"), M.o_now(sens[0], "%s in %s" % (word, nU)),
                   M.o_tr(sens[0], word + " above"), M.ob("Nobody in %s during the window" % nU, ["S3.E1", "S3.E2"])]
            checks = [{"ref": "S1", "claim": sens[0]["agent"]["cause"] if isinstance(sens[0]["agent"], dict) else "local cause", "verdict": "corrected",
                       "fact": "%s below is higher and the room above is empty: the source is downstairs" % nD, "src": ["S2.E1", "S1.E1", "S3.E1"]}]
            acts = [("inspect_hvac" if base == "heat" else "inspect_ventilation", "S2 (%s)" % d2, "Source of the %s is the room below" % ("heat" if base == "heat" else "smoke")),
                    ("monitor", "S1 (%s)" % d1, "Room above should recover once the source is fixed")]
            label = "hvac_or_thermal_issue" if base == "heat" else "air_pollution_event"
            doms, rt = ["air_quality"], "pair_who"
            expl = "Fix the source downstairs in %s; the room above only follows it." % nD
        hops = 1
        if sev == "critical":
            acts.insert(1, ("request_facility_review", "S2 (%s)" % d2, "Beyond the critical limit"))
    else:
        title = "Two separate events: %s and %s" % (nU, nD)
        rc = "No site link between %s (%s) and %s (%s): the two rises happen at the same time but are separate events; handle each on its own." % (nU, fU, nD, fD)
        chain = "%s (S1.E4) and %s (S2.E%s) independent: no link between the rooms" % (nU, nD, "5" if base == "water" else "4")
        if base == "water":
            obs = [M.o_tr(sens[0], "Humidity in %s" % nD), M.ob("Flow in %s stepped up %s m3/h at %s" % (nU, p2["jump"].lstrip("+"), p2["jump_t"]), ["S2.E5"])]
            label, doms = "unknown", ["air_quality", "water"]
            acts = [("inspect_water_system", "S2 (%s)" % d2, "Continuous flow in an empty room"), ("inspect_ventilation", "S1 (%s)" % d1, "Damp air with no linked water source")]
            th = "Humidity S1 in %s and flow S2 in %s rise together, but no drains-to link joins the rooms. Root: two separate events." % (nD, nU)
            chain = "humidity in %s (S1.E4) and flow in %s (S2.E5) independent: no link between the rooms" % (nD, nU)
        else:
            obs = [M.o_now(sens[0], "%s in %s" % (word, nU)), M.o_now(sens[1], "%s in %s" % (word, nD)), M.o_tr(sens[0], word + " in " + nU)]
            label = "hvac_or_thermal_issue" if base == "heat" else "air_pollution_event"
            doms = ["air_quality"]
            act = "inspect_hvac" if base == "heat" else "inspect_ventilation"
            acts = [(act, "S1 (%s)" % d1, "Own cause in this room"), (act, "S2 (%s)" % d2, "Own cause in this room")]
            chain = "%s (S1.E4) and %s (S2.E4) independent: no link between the rooms" % (nU, nD)
        checks = []
        rt, hops = "pair_relation", 0
        expl = "Same time is not a cause: these rooms are not linked, so treat them as two incidents."
        if sev == "critical":
            acts.append(("request_facility_review", "S1 (%s)" % d1, "Beyond the critical limit"))
    rep = M.rep(title[:80], sev, label, rc, chain, obs, checks, doms, [], M.ev_of(obs), round(R.uniform(0.78, 0.9), 2), acts,
                "Both rooms at the next re-check", expl)
    row = G2.mk_row(R, sc, "xfloor:" + kind, sens, rep, sens[0]["metric"], "x", 0)
    row = G2.fix(dict(row, id="x"))
    if len({s["role"] for s in sens if s["flagged"]}) >= 2:
        row["messages"][-1]["reasoning_content"] = th
    row = G.add_gold(row)
    row.update(reasoning_type=rt, hops=hops, xfloor={"up": nU, "down": nD, "floor_up": fU, "floor_down": fD, "linked": not neg})
    return G.postfix(row, P)
