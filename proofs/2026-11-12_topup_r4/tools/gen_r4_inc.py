"""r4: cross-domain incident reports (synthetic, stdlib python3, CPU) for the rsn_v3 4B r3 top-up.

Concurrent multi-domain events with onsets 0-60 min apart, each with a KNOWN causal graph, rendered exactly like the app
(round-1 lib.render == RenderV3User; LIMITS / TANK head lines, outdoor CONTEXT, related sensors, RE-CHECK, MEMORY).
Families (reasoning_type, hops = edges of the gold causal chain):
  occ_load       occupancy -> CO2 + room power (+ room temp)            chain_max / three_way      think (aq + power flagged)
  occ_fault      real CO2 rise with people + power meter dropout/stuck   pair_relation (fault)      think
  heat_multihop  outdoor heat -> room temp -> AC units -> room power     multihop (3)               think
  heat_trans     outdoor heat ... -> room power (room temp/AC related)   transitive (2)             think
  heat_three     outdoor heat + arrivals -> room temp -> AC power        three_way (2)              think
  ac_fail        AC units stop -> room heats + room power falls          chain_direct               think
  wx_fault       outdoor temp jump/drift, building sensors flat          pair_relation (fault)      single domain: empty think
  wx_fault_co2   weather sensor fault + a real CO2 event                 pair_relation (independent+fault) think
  pm_ingress     outdoor PM -> indoor PM (lagged)                        pair_who                   single domain: empty think
  pm_fault       indoor PM one-sample jump, outdoor clean                pair_relation (fault)      single domain: empty think
  pump_trip      pump power lost -> inflow 0 -> tank level falling       pair_who (root = pump) (2) think
  leak           tank draining fast -> pump power up (symptom)           pair_who (root = water)    think
  dry_run        pump running, inflow ~0 -> level falling                chain_direct               think
  level_fault    level offset -> controller starts the pump              pair_who (root = sensor)   think
  rain_level     rain (outdoor humidity) -> tank level rising            pair_relation (cause)      think
  indep          two unrelated real events, different buildings          pair_relation (independent) think
  worse          two real events, which one is worse                     pairwise                   think
  pf_chain       heat -> AC -> feeder load -> power factor dip           multihop (3)               think
Think rule (owner): 2+ DOMAINS among the FLAGGED sensors -> a short reasoning (<= 80 think tokens, numbers only from the
prompt, no braces) before the JSON report; otherwise the empty think exactly as today (the app pre-fills it).
Every row passes round-1 verify.py check_incident (+ think checks); the Go gate runs afterwards (run_r4.sh).

  python3 gen_r4_inc.py --out DIR [--n 9000] [--seed 41112] [--n-test 720] [--n-dev 60]
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
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
R2T = os.path.join(QIDK, "proofs", "2026-11-02_2b_r2", "tools")
sys.path.insert(0, R2T)
import gen_r2_targeted as G2  # noqa: E402  (pulls lib, textbank, verify, heat helpers)
L, T, V, H = G2.L, G2.T, G2.V, G2.H
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3", "pipeline"))
import verify_chat as VC  # noqa: E402  (think_tokens)

TRAIN_B = G2.TRAIN_B
NOVEL_B = G2.NOVEL_B
WE_NODE, WE_LOC = L.WEATHER
SUB_NODE, SUB_LOC = L.SUBSTATION
r1 = H.r1
P = H.P
ob, ag, rep, ev_of = G2.ob, G2.ag, G2.rep, G2.evidence_of
ASKS = G2.ASKS
DOMS = ["air_quality", "water", "power", "weather", "occupancy", "hvac"]
DW = {"air_quality": "air quality", "water": "water", "power": "power", "weather": "weather", "occupancy": "occupancy", "hvac": "HVAC"}
RTYPES = ["pair_relation", "pair_who", "pairwise", "transitive", "three_way", "multihop", "chain_direct", "chain_max"]


# ---------------------------------------------------------------- series
def noise(R, n, lvl, nz, dec, lo=None, hi=None):
    return G2.noise_series(R, n, lvl, nz, dec, lo, hi)


def ramp(R, on, base, top, nz, dec, n=144, shape="exp", lo=None):
    """flat at base until window index `on`, then a ramp to top by the window end"""
    k0 = n - 48 + on
    out = noise(R, k0, base, nz, dec, lo)
    m = n - k0
    for j in range(m):
        f = (j + 1) / m
        if shape == "exp":
            f = (1 - pow(2.718, -3.0 * f)) / (1 - pow(2.718, -3.0))
        v = base + (top - base) * f + R.gauss(0, nz)
        out.append(r1(max(lo, v) if lo is not None else v, dec))
    return out


def step(R, at, base, new, nz, dec, n=144, lo=None):
    k0 = n - 48 + at
    return noise(R, k0, base, nz, dec, lo) + noise(R, n - k0, new, nz, dec, lo)


def S(ref, role, metric, node, loc, xs, flagged, why=None, agent=None, head=None, hist=True, unit_shown=None):
    w = xs[-48:]
    hx = xs if (flagged and hist and len(xs) > 48) else None
    return G2.sensor(ref, role, metric, node, loc, w, hx, S.end, flagged, why=why, agent=agent, head=head, unit_shown=unit_shown)


S.end = None
LIM = {"co2": "LIMITS: warning above 1000, critical above 1500", "temp": "LIMITS: warning above 30, critical above 34",
       "wtemp": "LIMITS: warning above 38, critical above 42", "pm25": "LIMITS: warning above 60, critical above 120",
       "wrh": "LIMITS: warning above 90, critical above 97", "pf": "LIMITS: warning below 0.85, critical below 0.7"}


def sev_hi(v, w, c):
    return "critical" if v > c else ("warning" if v > w else "normal")


def worst(*s):
    order = ["normal", "sensor_fault", "warning", "critical"]
    return max(s, key=order.index)


def nodes(sc):
    b, fl, k = sc["b"], sc["fl"], sc["k"]
    return dict(aq=L.node_aq(b, fl, k), occ=L.node_occ(b, sc["occ_k"]), em=L.node_em(b, fl, k),
                ac=("AC-%s%02d" % (b, fl), "%s building, level %02d, AC units" % (b, fl)), out=L.node_out(b),
                tank=L.node_tank(b), fin=("WM-WF-%s98-10" % b, "%s building, level 98, water flow meter 10" % b),
                fout=L.node_flow(b), pump=("SR-EM-%s98-07" % b, "%s building, level 98, pump energy meter 07" % b),
                wq=L.node_wq(b), place=L.place(b, fl), wplace=L.place(b, 98))


def scen(R, i, novel=False, months=None, hours=None):
    bl = NOVEL_B if novel else TRAIN_B
    month = R.choice(months or range(1, 13))
    d = dt.date(2026, month, R.randrange(1, 29))
    end = dt.datetime(d.year, d.month, d.day, R.choice(hours or range(8, 20)), R.choice(range(0, 60, 5)), tzinfo=L.IST)
    b = R.choice(bl)
    return dict(i=i, end=end, b=b, b2=R.choice([x for x in bl if x != b]), fl=R.randrange(1, 7), k=R.randrange(1, 10),
                occ_k=R.randrange(1, 30), inc="INC-%04d" % R.randrange(100, 9999))


def wrong_p(R):
    return R.random() < 0.35


def occ_sensor(ref, nd, end, on, why="people in the room"):
    xs = [0] * 48 if on is None else [0] * on + [1] * (48 - on)
    a = ag("arrival", "normal", "arrival", 0.9, ["Room became occupied at %s and is still occupied [E4,E1]" % L.idx_time(end, 48, on)]) if on is not None \
        else ag("vacant", "normal", "vacant", 0.95, ["Room unoccupied for the whole 4-hour window [E2,E1]"])
    return S(ref, "occupancy", "occ", nd[0], nd[1], xs, False, why, agent=a)


def trend_ag(s, status, cause, conf=0.8, word=None):
    p = P(s)
    up = not p["slope"].startswith("-")
    pat = "gradual_increase" if up else "gradual_decrease"
    return ag(pat, status, cause, conf, ["%s %s at %s/h, now %s [E4,E1]" % (word or "Reading", "climbing" if up else "falling", p["slope"], p["last"])])


def steady_ag(word):
    return lambda s: ag("stable", "normal", "normal_conditions", 0.8, ["%s steady around %s [E1,E4]" % (word, P(s)["last"])])


def o_tr(s, w):
    p = P(s)
    up = not p["slope"].startswith("-")
    return ob("%s %s %s%s per hour (r2 %s)" % (w, "rising" if up else "falling", p["slope"].lstrip("+-"), T.uu(s), p["r2"]), [s["ref"] + ".E4"])


def o_now(s, w):
    return ob("%s now %s%s" % (w, P(s)["last"], T.uu(s)), [s["ref"] + ".E1"])


def o_jump(s, w):
    p = P(s)
    return ob("%s jumped %s%s within 5 minutes at %s" % (w, p["jump"].lstrip("+"), T.uu(s), p["jump_t"]), [s["ref"] + ".E5"])


def o_occ(s):
    return ob("Room occupied since %s" % P(s)["first_on"], [s["ref"] + ".E4", s["ref"] + ".E1"])


def cl(a, s, why):
    return (a, "%s (%s)" % (s["ref"], s["node"]), why)


def X(**k):
    return k


# ---------------------------------------------------------------- think
def think_text(R, flagged, link, root, extra=None):
    doms = []
    for s in flagged:
        if s["role"] not in doms:
            doms.append(s["role"])
    fl = ", ".join("%s %s" % (s["ref"], L.word(s["role"], s["metric"])) for s in flagged)
    head = R.choice(["Flagged in %s: %s." % (" and ".join(DW[d] for d in doms), fl), "%s domains flagged: %s." % ("Two" if len(doms) == 2 else "Three", fl),
                     "Cross-domain: %s." % fl])
    parts = [head, link, root] + ([extra] if extra else [])
    return " ".join(p.strip() for p in parts if p)


# ---------------------------------------------------------------- families
def f_occ_load(R, sc, nd):
    end = sc["end"]
    which = R.choice(["critical", "warning", "warning", "normal"])
    top = {"critical": R.uniform(1530, 1900), "warning": R.uniform(1040, 1450), "normal": R.uniform(680, 950)}[which]
    on = R.randrange(4, 26)
    co2 = ramp(R, on + R.randrange(0, 3), R.uniform(420, 520), top, 6, 0)
    if sev_hi(co2[-1], 1000, 1500) != which:
        return None
    gain = R.uniform(1.6, 3.8)
    pw = [r1(v + (gain if i >= 96 + on + 1 else 0), 2) for i, v in enumerate(noise(R, 144, R.uniform(1.2, 3.0), 0.04, 2))]
    with_temp = R.random() < 0.5
    wrong_c, pw_anom = wrong_p(R), R.random() < 0.6

    def ag_c(s):
        p = P(s)
        if wrong_c:
            return ag("step_increase", "sensor_fault", "sensor_fault", round(R.uniform(0.82, 0.95), 2), ["CO2 jumped %s ppm at %s; bias fault sign [E5]" % (p["jump"], p["jump_t"])])
        return ag("gradual_increase", which, "occupancy_load" if which != "normal" else "normal_conditions", 0.85,
                  ["CO2 climbing at %s ppm/h, now %s ppm [E4,E1]" % (p["slope"], p["last"])])

    def ag_p(s):
        p = P(s)
        if pw_anom:
            return ag("step_increase", "warning", "power_load_anomaly", round(R.uniform(0.75, 0.9), 2), ["Power stepped up %s kW at %s [E5]" % (p["jump"], p["jump_t"])])
        return ag("step_increase", "normal", "occupancy_load", 0.8, ["Power up to %s kW with the room in use [E1]" % p["last"]])
    s1 = S("S1", "air_quality", "co2", nd["aq"][0], nd["aq"][1], co2, True, agent=ag_c, head=[LIM["co2"]])
    s2 = S("S2", "power", "power_kw", nd["em"][0], nd["em"][1], pw, True, agent=ag_p)
    s3 = occ_sensor("S3", nd["occ"], end, on)
    sens = [s1, s2, s3]
    if with_temp:
        b0 = R.uniform(23.5, 25.0)
        tt = ramp(R, on + 2, b0, b0 + R.uniform(0.8, 1.8), 0.08, 1, shape="lin")
        s4 = S("S4", "air_quality", "temp", nd["aq"][0], nd["aq"][1], tt, False, "people add heat", agent=lambda s: trend_ag(s, "normal", "occupancy_heat", word="Temperature"))
        sens.append(s4)
    we = R.random() < 0.5
    if we:
        sw = S("S%d" % (len(sens) + 1), "weather", "temp", WE_NODE, WE_LOC, noise(R, 48, R.uniform(26, 33), 0.2, 1), False, "outdoor conditions",
               agent=steady_ag("Temperature"))
        sens.append(sw)
    p1, p2, p3 = P(s1), P(s2), P(s3)
    obs = [o_tr(s1, "CO2"), o_now(s1, "CO2"), o_occ(s3), ob("Room power up %s kW at %s, after the arrival" % (p2["jump"].lstrip("+"), p2["jump_t"]), ["S2.E5"])]
    if with_temp:
        obs.append(o_tr(sens[3], "Room temperature"))
    checks = []
    if wrong_c:
        checks.append({"ref": "S1", "claim": "status sensor_fault (bias)", "verdict": "corrected",
                       "fact": "smooth rise after people arrived at %s, not a one-sample step" % p3["first_on"], "src": ["S1.E4", "S3.E4"]})
    if pw_anom:
        checks.append({"ref": "S2", "claim": "power_load_anomaly", "verdict": "corrected",
                       "fact": "the power step follows the arrival at %s: occupancy load, not an anomaly" % p3["first_on"], "src": ["S2.E5", "S3.E4"]})
    sev = which
    tgt = s1
    if sev == "normal":
        title = R.choice(["Occupied room: CO2 %s ppm and power up, below limits (%s)" % (p1["last"], nd["place"]),
                          "CO2 and room load rise with people, under limits: %s" % nd["place"]])
        clist = [cl("monitor", s1, "Watch whether CO2 nears 1000 ppm")]
    else:
        lim = "1500" if sev == "critical" else "1000"
        title = R.choice(["CO2 %s ppm and power up with people in the room: %s" % (p1["last"], nd["place"]),
                          "Occupied room over the CO2 %s limit, load up: %s" % (sev, nd["place"])])
        clist = [cl("inspect_ventilation", s1, "Fresh-air supply is not keeping up with the people"),
                 cl("request_facility_review", s1, "CO2 beyond the critical limit") if sev == "critical" else cl("monitor", s2, "Room load should settle with the occupancy")]
    doms = ["air_quality", "power", "occupancy"]
    rc = "People arriving explain both the CO2 rise and the room power step: one shared cause, not a power fault."
    chain = "arrival at %s (S3.E4) -> CO2 up to %s ppm (S1.E1) and room load up (S2.E5)%s" % (
        p3["first_on"], p1["last"], ", room warming (S4.E4)" if with_temp else "")
    expl = R.choice(["The room filled up: people raise CO2 and use power. Ventilation is the fix, not the power supply.",
                     "One cause, two symptoms: occupancy drives both the CO2 and the load."]) if sev != "normal" else \
        "Normal for an occupied room: CO2 and power rose with the people and stay under the limits."
    r = rep(title, sev, "occupancy_driven_load", rc, chain, obs, checks, doms, [], ev_of(obs), round(R.uniform(0.8, 0.92), 2), clist,
            "CO2 and room load as the occupancy changes", expl)
    link = R.choice(["Occupancy S3 turned on before both rises, so CO2 and power share one cause.",
                     "Both rises start after the arrival in S3: same cause, neither drives the other."])
    if with_temp:
        link += " Room temperature S4 also creeps up with the people."
    if wrong_c:
        link += " S1 agent calls it a bias, but the rise is smooth."
    root = R.choice(["Root: occupancy; severity from CO2 against its limit.", "Root is the occupancy; CO2 sets the severity."])
    return X(sensors=sens, report=r, root_metric="co2", rtype="three_way" if with_temp else "chain_max", hops=1, think=(link, root),
             fam="occ_load", outdoor=None, ctx=("Room power draw anomaly: %s" % nd["place"], "warning", title, sev))


def f_occ_fault(R, sc, nd):
    end = sc["end"]
    which = R.choice(["critical", "warning", "warning", "normal"])
    top = {"critical": R.uniform(1530, 1900), "warning": R.uniform(1040, 1450), "normal": R.uniform(680, 950)}[which]
    on = R.randrange(4, 24)
    co2 = ramp(R, on + 1, R.uniform(420, 520), top, 6, 0)
    if sev_hi(co2[-1], 1000, 1500) != which:
        return None
    kind = R.choice(["dropout", "stuck"])
    base = R.uniform(1.4, 3.2)
    at = R.randrange(4, 30)
    hist = noise(R, 144, base, 0.05, 2)
    k0 = 96 + at
    pw = hist[:k0] + ([0.0] * (144 - k0) if kind == "dropout" else [hist[k0 - 1]] * (144 - k0))
    wrong_p_ = R.random() < 0.5

    def ag_p(s):
        p = P(s)
        if wrong_p_:
            return ag("step_decrease" if kind == "dropout" else "stable", "normal", "low_load", 0.8, ["Power now %s kW [E1]" % p["last"]])
        return ag("flatline" if kind == "stuck" else "dropout", "sensor_fault", "sensor_fault", 0.85, ["Power flat at %s kW [E1,E8]" % p["last"]])
    s1 = S("S1", "air_quality", "co2", nd["aq"][0], nd["aq"][1], co2, True, agent=lambda s: ag("gradual_increase", which, "occupancy_load", 0.85,
                                                                                               ["CO2 climbing at %s ppm/h, now %s ppm [E4,E1]" % (P(s)["slope"], P(s)["last"])]), head=[LIM["co2"]])
    s2 = S("S2", "power", "power_kw", nd["em"][0], nd["em"][1], pw, True, agent=ag_p)
    s3 = occ_sensor("S3", nd["occ"], end, on)
    sens = [s1, s2, s3]
    p1, p2, p3 = P(s1), P(s2), P(s3)
    fault_txt = "reads 0.00 kW since %s" % p2["jump_t"] if kind == "dropout" else "flat at %s kW, flat run %s points" % (p2["last"], p2["flat"])
    o_f = ob("Room power %s while the room is occupied" % fault_txt, ["S2.E5", "S2.E1"] if kind == "dropout" else ["S2.E8"])
    obs = [o_tr(s1, "CO2"), o_now(s1, "CO2"), o_occ(s3), o_f]
    checks = []
    if wrong_p_:
        checks.append({"ref": "S2", "claim": "status normal (low load)", "verdict": "corrected",
                       "fact": "an occupied room cannot draw %s; the meter is not reporting" % ("0.00 kW" if kind == "dropout" else "an unchanging load"),
                       "src": ["S2.E1", "S3.E1"] if kind == "dropout" else ["S2.E8", "S3.E1"]})
    pm = "S2 (%s)" % nd["em"][0]
    if which == "normal":
        sev, label = "sensor_fault", "sensor_fault"
        title = R.choice(["Room energy meter not reporting (%s): %s" % ("0.00 kW" if kind == "dropout" else "stuck", nd["place"]),
                          "Suspect room power readings while occupied: %s" % nd["place"]])
        clist = [("check_sensor" if kind == "stuck" else "restart_or_reconnect_sensor", pm, "Meter reading does not match an occupied room"),
                 cl("monitor", s1, "CO2 is rising but under the limit")]
        rmet = "power_kw"
    else:
        sev, label = which, "occupancy_driven_load"
        title = R.choice(["CO2 %s ppm in an occupied room; power meter fault: %s" % (p1["last"], nd["place"]),
                          "CO2 over the %s limit with people; room meter not reporting: %s" % (which, nd["place"])])
        clist = [cl("inspect_ventilation", s1, "Fresh-air supply is not keeping up with the people")]
        if which == "critical":
            clist.append(cl("request_facility_review", s1, "CO2 beyond the critical limit"))
        clist.append(("check_sensor", pm, "Meter reading does not match an occupied room"))
        rmet = "co2"
    rc = ("Two separate findings: people raise CO2 (real), and the room power meter %s (sensor fault)." % ("dropped out" if kind == "dropout" else "is stuck"))
    chain = "arrival at %s (S3.E4) -> CO2 up (S1.E4); power meter %s (%s) is a separate sensor fault" % (p3["first_on"], "at 0.00 kW" if kind == "dropout" else "frozen", o_f["src"][0])
    expl = R.choice(["The CO2 is real and comes from the people; the power meter problem is unrelated bad data.",
                     "Do not read the meter as a load change: it stopped reporting while the room was in use."])
    r = rep(title, sev, label, rc, chain, obs, checks, ["air_quality", "power", "occupancy"], ["S2"], ev_of(obs), round(R.uniform(0.8, 0.9), 2), clist,
            "Whether the power meter reports again and CO2 settles", expl)
    link = R.choice(["S1 rises smoothly after the arrival in S3, so the CO2 is real; S2 cannot read %s in an occupied room." % ("zero" if kind == "dropout" else "frozen"),
                     "CO2 follows the people (real). The meter S2 shows %s while the room is used: a meter fault, not a cause." % ("zero" if kind == "dropout" else "no change")])
    root = "Separate: real CO2 event plus a power sensor fault; severity from CO2." if which != "normal" else "CO2 is under the limit, so the main finding is the meter fault."
    return X(sensors=sens, report=r, root_metric=rmet, rtype="pair_relation", hops=1, think=(link, root), fam="occ_fault", outdoor=None,
             ctx=("Room power drop: %s" % nd["place"], "warning", title, sev))


def heat_base(R, sc, sev_want):
    last_t = R.uniform(42.4, 45.8) if sev_want == "critical" else R.uniform(38.4, 41.5)
    temps, _ = H.heat_series(R, sc["end"], last_t)
    w = temps[-48:]
    sev = "critical" if w[-1] >= 42 else ("warning" if w[-1] >= 38 else None)
    return temps, sev


def heat_sensors(R, sc, nd, temps, refs, flag):
    """weather temp -> room temp -> AC units -> room power, all following the heat; refs/flag per element"""
    w = temps[-48:]
    out = {}
    out["wx"] = S(refs["wx"], "weather", "temp", WE_NODE, WE_LOC, temps, flag["wx"], "outdoor heat load",
                  agent=lambda s: ag("gradual_increase", "warning" if float(P(s)["last"]) < 42 else "critical", "heat_buildup", 0.8,
                                     ["Temperature climbing at %s C/h, now %s C [E4,E1]" % (P(s)["slope"], P(s)["last"])]) if flag["wx"]
                  else steady_ag("Temperature"), head=[LIM["wtemp"]] if flag["wx"] else None)
    rt0 = R.uniform(24.0, 25.5)
    gain = R.uniform(0.25, 0.45)
    rt_hist = [r1(rt0 + max(0.0, t - temps[0]) * gain + R.gauss(0, 0.08), 1) for t in temps]
    out["room"] = S(refs["room"], "air_quality", "temp", nd["aq"][0], nd["aq"][1], rt_hist, flag["room"], "indoor temperature",
                    agent=lambda s: trend_ag(s, sev_hi(float(P(s)["last"]), 30, 34), "high_heat_load", word="Temperature"),
                    head=[LIM["temp"]] if flag["room"] else None)
    a0, a1 = R.choice([1, 2]), R.choice([3, 4])
    cut = R.randrange(8, 30)
    out["ac"] = S(refs["ac"], "hvac", "ac_units_on", nd["ac"][0], nd["ac"][1], [a0] * cut + [a1] * (48 - cut), False, "AC response", unit_shown="units",
                  agent=lambda s: ag("step_increase", "normal", "hvac_context", 0.8, ["AC units running: now %s [E1,E4]" % P(s)["last"]]))
    pbase = R.uniform(2.0, 4.0)
    per = R.uniform(1.1, 1.8)
    pw = noise(R, 96 + cut, pbase, 0.05, 2) + noise(R, 48 - cut, pbase + per * (a1 - a0), 0.06, 2)
    out["pw"] = S(refs["pw"], "power", "power_kw", nd["em"][0], nd["em"][1], pw, flag["pw"], "cooling load",
                  agent=lambda s: ag("step_increase", "warning", "power_load_anomaly", 0.8, ["Power stepped up %s kW at %s [E5]" % (P(s)["jump"], P(s)["jump_t"])]))
    return out


def f_heat(R, sc, nd, mode):
    sev_w = R.choice(["critical", "warning"])
    temps, sevw = heat_base(R, sc, sev_w)
    if sevw is None:
        return None
    if mode == "multihop":
        refs, flag = dict(wx="S1", room="S2", pw="S3", ac="S4"), dict(wx=True, room=True, pw=True)
    elif mode == "trans":
        refs, flag = dict(wx="S1", pw="S2", room="S3", ac="S4"), dict(wx=True, room=False, pw=True)
    else:
        refs, flag = dict(wx="S1", room="S2", pw="S3", ac="S4"), dict(wx=True, room=True, pw=False)
    hs = heat_sensors(R, sc, nd, temps, refs, flag)
    sens = sorted(hs.values(), key=lambda s: int(s["ref"][1:]))
    on = None
    if mode == "three":
        on = R.randrange(4, 30)
        sens.append(occ_sensor("S5", nd["occ"], sc["end"], on, "occupancy of the same room"))
    wx, room, ac, pw = hs["wx"], hs["room"], hs["ac"], hs["pw"]
    pwx, pr, pa, pp = P(wx), P(room), P(ac), P(pw)
    sevr = sev_hi(float(pr["last"]), 30, 34)
    sev = worst(sevw, sevr) if flag["room"] else sevw
    wrong_w = wrong_p(R)
    if wrong_w:
        wx["agent"] = ag("step_increase", "sensor_fault", "sensor_fault", round(R.uniform(0.85, 0.95), 2),
                         ["Temperature jumped %s C at %s; sensor bias likely [E5]" % (pwx["jump"], pwx["jump_t"])])
    obs = [o_tr(wx, "Outdoor temperature"), o_tr(room, "Room temperature"), ob("AC units running now %s" % pa["last"], [ac["ref"] + ".E1"]),
           ob("Room power up %s kW at %s as more AC units started" % (pp["jump"].lstrip("+"), pp["jump_t"]), [pw["ref"] + ".E5"])]
    if mode == "three":
        obs.append(o_occ(sens[-1]))
    checks = []
    if wrong_w:
        checks.append({"ref": wx["ref"], "claim": "status sensor_fault (sensor bias)", "verdict": "corrected",
                       "fact": "smooth daytime rise (r2 %s); the room temperature and the AC load rise with it" % pwx["r2"],
                       "src": [wx["ref"] + ".E4", room["ref"] + ".E4", pw["ref"] + ".E5"]})
    if flag["pw"]:
        checks.append({"ref": pw["ref"], "claim": "power_load_anomaly", "verdict": "corrected",
                       "fact": "the load step matches AC units rising to %s in the heat" % pa["last"], "src": [pw["ref"] + ".E5", ac["ref"] + ".E1"]})
    tw = "Outdoor heat %s C drives room temperature and AC load: %s" % (pwx["last"], nd["place"])
    if mode == "multihop":
        title = R.choice([tw, "Heat chain: outdoor %s C, room %s C, AC load up (%s)" % (pwx["last"], pr["last"], nd["place"])])
        chain = "outdoor heat (%s.E4) -> room temperature up (%s.E4) -> AC units to %s (%s.E1) -> room power up (%s.E5)" % (
            wx["ref"], room["ref"], pa["last"], ac["ref"], pw["ref"])
        rt, hops = "multihop", 3
        rc = "Outdoor heat is the root: it warms the room, more AC units run, and the room power rises; one chain, no fault."
    elif mode == "trans":
        title = R.choice(["Outdoor heat %s C raising the AC load: %s" % (pwx["last"], nd["place"]), tw])
        chain = "outdoor heat (%s.E4) -> room warming (%s.E4) and AC units to %s (%s.E1) -> room power up (%s.E5)" % (
            wx["ref"], room["ref"], pa["last"], ac["ref"], pw["ref"])
        rt, hops = "transitive", 2
        rc = "The heat raises the power indirectly: outdoor heat warms the room, the AC works harder, so the room power rises."
    else:
        title = R.choice(["Room temperature %s C from outdoor heat and people: %s" % (pr["last"], nd["place"]), tw])
        chain = "outdoor heat (%s.E4) and arrivals at %s (S5.E4) -> room temperature up (%s.E4) -> AC units to %s (%s.E1)" % (
            wx["ref"], P(sens[-1])["first_on"], room["ref"], pa["last"], ac["ref"])
        rt, hops = "three_way", 2
        rc = "Outdoor heat and the people in the room both warm it; the AC answers with more units. Heat is the larger driver."
    rmet = "temp"
    tgt_room = room
    if sev == "critical":
        clist = [cl("inspect_hvac", ac, "AC is at its limit against the outdoor heat"), cl("request_facility_review", tgt_room, "Heat event beyond the critical limit"),
                 ("review_schedule", "%s (%s)" % (wx["ref"], WE_NODE), "Shift outdoor activity out of the hottest hours")]
    else:
        clist = [("review_schedule", "%s (%s)" % (wx["ref"], WE_NODE), "Shift heavy use out of the hottest hours"),
                 cl("inspect_hvac", ac, "Check the AC keeps up with the heat"), cl("monitor", tgt_room, "Watch room temperature against 30 C")]
    doms = ["weather", "air_quality", "hvac", "power"] + (["occupancy"] if mode == "three" else [])
    expl = R.choice(["A real hot day: the outdoor heat pushes the room up and the AC load with it. Watch the AC and the room temperature.",
                     "Everything moves together with the outdoor heat, so this is weather, not a fault."])
    r = rep(title, sev, "weather_driven", rc, chain, obs, checks, doms[:4] if mode != "three" else ["weather", "air_quality", "hvac", "occupancy"], [],
            ev_of(obs), round(R.uniform(0.8, 0.92), 2), clist, "Room temperature and AC load as the afternoon cools", expl)
    fl = [s for s in sens if s["flagged"]]
    link = {"multihop": "Chain: outdoor heat %s warms the room %s, more AC units %s run, room power %s rises." % (wx["ref"], room["ref"], ac["ref"], pw["ref"]),
            "trans": "Heat %s does not touch power %s directly: it warms the room %s, the AC %s works harder, so power rises." % (wx["ref"], pw["ref"], room["ref"], ac["ref"]),
            "three": "Room %s warms from two drivers: outdoor heat %s and the arrival in S5; the AC %s answers." % (room["ref"], wx["ref"], ac["ref"])}[mode]
    if wrong_w:
        link += " The %s agent says bias, but the rise is smooth and the building follows it." % wx["ref"]
    root = R.choice(["Root: outdoor heat, real; no sensor fault.", "Root is the weather; severity from the hottest reading against its limit."])
    return X(sensors=sens, report=r, root_metric=rmet, rtype=rt, hops=hops, think=(link, root), fam="heat_" + mode,
             outdoor=(pwx["last"], WE_NODE, L.tstr(sc["end"])), ctx=("Room power draw anomaly: %s" % nd["place"], "warning", title, sev))


def f_ac_fail(R, sc, nd):
    end = sc["end"]
    on = R.randrange(4, 26)
    top = R.uniform(30.6, 33.5) if R.random() < 0.6 else R.uniform(34.4, 37.5)
    base = R.uniform(24.0, 25.5)
    rt = ramp(R, on + 1, base, top, 0.1, 1, shape="lin")
    sev = sev_hi(rt[-1], 30, 34)
    if sev == "normal":
        return None
    u0 = R.choice([2, 3, 4])
    units = [u0] * on + [0] * (48 - on)
    pb = R.uniform(4.0, 7.0)
    drop = R.uniform(0.9, 1.4) * u0
    pw = noise(R, 96 + on, pb, 0.05, 2) + noise(R, 48 - on, max(0.6, pb - drop), 0.05, 2)
    wrong_p_ = R.random() < 0.5
    s1 = S("S1", "air_quality", "temp", nd["aq"][0], nd["aq"][1], rt, True, agent=lambda s: trend_ag(s, sev, "hvac_failure", word="Temperature"), head=[LIM["temp"]])
    s2 = S("S2", "power", "power_kw", nd["em"][0], nd["em"][1], pw, True,
           agent=(lambda s: ag("step_decrease", "normal", "low_load", 0.8, ["Power down to %s kW: lower demand [E1]" % P(s)["last"]])) if wrong_p_ else
           (lambda s: ag("step_decrease", "warning", "equipment_off", 0.8, ["Power dropped %s kW at %s [E5]" % (P(s)["jump"], P(s)["jump_t"])])))
    s3 = S("S3", "hvac", "ac_units_on", nd["ac"][0], nd["ac"][1], units, False, "AC response", unit_shown="units",
           agent=lambda s: ag("step_decrease", "normal", "hvac_context", 0.8, ["AC units running: now %s [E1,E4]" % P(s)["last"]]))
    s4 = S("S4", "weather", "temp", WE_NODE, WE_LOC, noise(R, 48, R.uniform(30.0, 35.5), 0.2, 1), False, "outdoor conditions", agent=steady_ag("Temperature"))
    sens = [s1, s2, s3, s4]
    p1, p2, p3, p4 = P(s1), P(s2), P(s3), P(s4)
    obs = [o_tr(s1, "Room temperature"), o_now(s1, "Room temperature"), ob("AC units running now %s" % p3["last"], ["S3.E1"]),
           ob("Room power dropped %s kW at %s" % (p2["jump"].lstrip("-"), p2["jump_t"]), ["S2.E5"]), o_now(s4, "Outdoor temperature")]
    checks = []
    if wrong_p_:
        checks.append({"ref": "S2", "claim": "status normal (lower demand)", "verdict": "corrected",
                       "fact": "the drop is the AC units stopping (now %s) while the room heats up" % p3["last"], "src": ["S2.E5", "S3.E1", "S1.E4"]})
    lim = "34" if sev == "critical" else "30"
    title = R.choice(["AC units stopped, room temperature %s C: %s" % (p1["last"], nd["place"]),
                      "Room overheating after AC dropout (%s C): %s" % (p1["last"], nd["place"])])
    clist = [cl("inspect_hvac", s3, "AC units stopped and the room is heating")]
    clist.append(cl("request_facility_review", s1, "Room above the %s C limit" % lim) if sev == "critical" else cl("monitor", s1, "Watch for the critical limit"))
    rc = "The AC units stopped: that directly heats the room and lowers the room power. Outdoor temperature is steady, not the cause."
    chain = "AC units to %s (S3.E1) -> room temperature up (S1.E4) and room power down (S2.E5); outdoor steady at %s C (S4.E1)" % (p3["last"], p4["last"])
    expl = R.choice(["The direct cause is the AC stopping, not the weather. Inspect the AC units.",
                     "Room heat and the power drop are one event: the AC switched off."])
    r = rep(title, sev, "hvac_or_thermal_issue", rc, chain, obs, checks, ["air_quality", "power", "hvac"], [], ev_of(obs), round(R.uniform(0.82, 0.92), 2), clist,
            "Room temperature once the AC units run again", expl)
    link = R.choice(["Room S1 heats while power S2 falls: opposite moves, one cause. AC units S3 went to zero; outdoor S4 is steady.",
                     "Direct cause of the heating is the AC stop in S3, which also explains the power drop in S2; weather S4 is flat."])
    root = "Root: AC failure (hvac); severity from room temperature."
    return X(sensors=sens, report=r, root_metric="temp", rtype="chain_direct", hops=1, think=(link, root), fam="ac_fail", outdoor=(p4["last"], WE_NODE, L.tstr(end)),
             ctx=("Room power drop: %s" % nd["place"], "normal", title, sev))


def wx_fault_sensor(R, sc, ref, kind):
    end = sc["end"]
    hist = H.normal_day(R, end)
    n = 144
    if kind == "jump":
        jt = R.randrange(100, 140)
        off = R.uniform(9.0, 14.0)
        xs = [r1(v + (off if i >= jt else 0), 1) for i, v in enumerate(hist)]
    else:
        st = R.randrange(96, 120)
        rate = R.uniform(0.25, 0.4)
        xs = [r1(v + max(0, i - st) * rate, 1) for i, v in enumerate(hist)]
    return xs


def f_wx_fault(R, sc, nd, with_co2=False):
    end = sc["end"]
    kind = R.choice(["jump", "jump", "drift"])
    xs = wx_fault_sensor(R, sc, "S1", kind)
    if xs[-1] < 38.2:
        return None
    sevfake = "critical" if xs[-1] > 42 else "warning"
    wrong = R.random() < 0.55

    def ag_w(s):
        p = P(s)
        if wrong:
            return ag("step_increase" if kind == "jump" else "gradual_increase", sevfake, "heat_buildup", round(R.uniform(0.8, 0.95), 2),
                      ["%s C exceeds the %s limit [E1]" % (p["last"], sevfake)])
        return ag("step_increase" if kind == "jump" else "drift", "sensor_fault", "sensor_fault", 0.85,
                  ["Temperature jumped %s C at %s [E5]" % (p["jump"], p["jump_t"])] if kind == "jump" else ["Temperature drifting up at %s C/h [E4]" % p["slope"]])
    s1 = S("S1", "weather", "temp", WE_NODE, WE_LOC, xs, True, agent=ag_w, head=[LIM["wtemp"]])
    sens = [s1]
    p1 = P(s1)
    if with_co2:
        which = R.choice(["critical", "warning"])
        top = R.uniform(1530, 1900) if which == "critical" else R.uniform(1040, 1450)
        on = R.randrange(4, 24)
        co2 = ramp(R, on + 1, R.uniform(420, 520), top, 6, 0)
        if sev_hi(co2[-1], 1000, 1500) != which:
            return None
        s2 = S("S2", "air_quality", "co2", nd["aq"][0], nd["aq"][1], co2, True, head=[LIM["co2"]],
               agent=lambda s: ag("gradual_increase", which, "occupancy_load", 0.85, ["CO2 climbing at %s ppm/h, now %s ppm [E4,E1]" % (P(s)["slope"], P(s)["last"])]))
        s3 = occ_sensor("S3", nd["occ"], end, on)
        rt = S("S4", "air_quality", "temp", nd["aq"][0], nd["aq"][1], noise(R, 48, R.uniform(24, 26), 0.1, 1), False, "indoor temperature", agent=steady_ag("Temperature"))
        sens += [s2, s3, rt]
        ind = rt
    else:
        rt = S("S2", "air_quality", "temp", nd["aq"][0], nd["aq"][1], noise(R, 48, R.uniform(24, 26), 0.1, 1), False, "indoor temperature", agent=steady_ag("Temperature"))
        acu = R.choice([1, 2])
        acs = S("S3", "hvac", "ac_units_on", nd["ac"][0], nd["ac"][1], [acu] * 48, False, "AC response", unit_shown="units",
                agent=lambda s: ag("stable", "normal", "hvac_context", 0.8, ["AC units running: now %s [E1,E4]" % P(s)["last"]]))
        pwr = S("S4", "power", "power_kw", SUB_NODE, SUB_LOC, noise(R, 48, R.uniform(430, 620), 4.5, 2), False, "cooling load", agent=steady_ag("Power"))
        sens += [rt, acs, pwr]
        ind = rt
    pin = P(ind)
    fo = o_jump(s1, "Outdoor temperature") if kind == "jump" else o_tr(s1, "Outdoor temperature")
    obs = [fo, o_now(s1, "Outdoor temperature"), ob("Indoor temperature steady at %s C (trend %s C per hour)" % (pin["last"], pin["slope"]), [ind["ref"] + ".E1", ind["ref"] + ".E4"])]
    if not with_co2:
        obs.append(ob("AC units unchanged at %s; feeder load steady around %s kW" % (P(sens[2])["last"], P(sens[3])["last"]), [sens[2]["ref"] + ".E1", sens[3]["ref"] + ".E1"]))
    checks = []
    if wrong:
        checks.append({"ref": "S1", "claim": "status %s (heat)" % sevfake, "verdict": "corrected",
                       "fact": ("a %s C jump in 5 minutes at %s" % (p1["jump"].lstrip("+"), p1["jump_t"]) if kind == "jump" else "a steady drift on an ordinary day") +
                       " while the building shows no heat", "src": [fo["src"][0], ind["ref"] + ".E4"]})
    ws = "S1 (%s)" % WE_NODE
    wact = [("check_sensor", ws, "Outdoor reading disagrees with the building"), ("recalibrate_sensor", ws, "Compare with a reference thermometer")]
    if with_co2:
        p2, p3 = P(sens[1]), P(sens[2])
        which = sens[1]["agent"]["status"]
        sev = which
        title = R.choice(["CO2 %s ppm with people; outdoor temperature sensor fault: %s" % (p2["last"], nd["place"]),
                          "CO2 over the %s limit, weather sensor reading unreliable (%s)" % (which, nd["place"])])
        obs = [o_tr(sens[1], "CO2"), o_occ(sens[2]), fo, obs[2]]
        clist = [cl("inspect_ventilation", sens[1], "Fresh-air supply is not keeping up with the people")]
        if which == "critical":
            clist.append(cl("request_facility_review", sens[1], "CO2 beyond the critical limit"))
        clist.append(wact[0])
        rc = "Two unrelated findings: people raise CO2 (real), and the outdoor temperature sensor reads false heat (sensor fault)."
        chain = "arrival at %s (S3.E4) -> CO2 up (S2.E4); outdoor reading %s (%s) with the room steady (S4.E4): weather sensor fault" % (
            p3["first_on"], "jump" if kind == "jump" else "drift", fo["src"][0])
        r = rep(title, sev, "occupancy_driven_load", rc, chain, obs, checks, ["air_quality", "occupancy", "weather"], ["S1"], ev_of(obs), round(R.uniform(0.8, 0.9), 2),
                clist, "CO2 after more ventilation; outdoor reading after the sensor check",
                "The CO2 is a real occupancy problem. The outdoor heat is not real: the building is not warming, so check that sensor.")
        link = "S2 CO2 follows the people in S3: real. S1 shows heat %s, yet room temperature S4 is flat: weather sensor fault, unrelated to the CO2." % (
            "in one jump" if kind == "jump" else "by drift")
        root = "Separate events; severity from CO2, S1 is a suspect sensor."
        return X(sensors=sens, report=r, root_metric="co2", rtype="pair_relation", hops=1, think=(link, root), fam="wx_fault_co2",
                 outdoor=(p1["last"], WE_NODE, L.tstr(end)), ctx=("Heatwave: outdoor temperature %s C" % p1["last"], sevfake, title, sev))
    title = R.choice(["Suspect outdoor temperature readings (%s)" % L.place("VN", 4), "Outdoor temperature sensor %s: %s C not seen indoors" % (
        "jump" if kind == "jump" else "drift", p1["last"])])
    rc = "The outdoor temperature %s while the room, the AC units and the feeder load show no heat: the weather sensor is wrong." % ("jumped in one sample" if kind == "jump" else "drifts on an ordinary day")
    chain = "outdoor reading %s (%s) but indoor flat (%s.E4), AC and load unchanged -> weather sensor fault" % ("jump" if kind == "jump" else "drift", fo["src"][0], ind["ref"])
    r = rep(title, "sensor_fault", "sensor_fault", rc, chain, obs, checks, ["weather"], ["S1"], ev_of(obs), round(R.uniform(0.82, 0.92), 2), wact,
            "Whether the outdoor reading agrees with the building after the check",
            R.choice(["Not a heatwave: nothing in the building warmed. Check the weather sensor.", "A real heat event would warm the rooms and load the AC; neither happened."]))
    return X(sensors=sens, report=r, root_metric="temp", rtype="pair_relation", hops=1, think=None, fam="wx_fault", outdoor=(p1["last"], WE_NODE, L.tstr(end)),
             ctx=("Heatwave: outdoor temperature %s C at %s" % (p1["last"], L.place("VN", 4)), sevfake, title, "sensor_fault"))


def f_pm(R, sc, nd, fault=False):
    end = sc["end"]
    no, lo = nd["out"]
    ni, li = nd["aq"]
    if fault:
        out = noise(R, 144, R.uniform(18, 40), 1.2, 1, 1)
        base = R.uniform(15, 35)
        jt = R.randrange(100, 140)
        ind = [r1(v + (R.uniform(70, 140) if i >= jt else 0), 1) for i, v in enumerate(noise(R, 144, base, 1.0, 1, 1))]
        wrong = R.random() < 0.5
        s1 = S("S1", "air_quality", "pm25", ni, li, ind, True, head=[LIM["pm25"]],
               agent=(lambda s: ag("step_increase", sev_hi(float(P(s)["last"]), 60, 120), "air_pollution_event", 0.85, ["PM2.5 now %s ug/m3 [E1]" % P(s)["last"]])) if wrong else
               (lambda s: ag("step_increase", "sensor_fault", "sensor_fault", 0.85, ["PM2.5 jumped %s ug/m3 at %s [E5]" % (P(s)["jump"], P(s)["jump_t"])])))
        s2 = S("S2", "air_quality", "pm25", no, lo, out, False, "outdoor air at the same building", agent=steady_ag("PM2.5"))
        s3 = occ_sensor("S3", nd["occ"], end, None)
        p1, p2 = P(s1), P(s2)
        obs = [o_jump(s1, "Indoor PM2.5"), o_now(s1, "Indoor PM2.5"), ob("Outdoor PM2.5 steady around %s ug/m3" % p2["last"], ["S2.E1", "S2.E4"]), ob("Nobody in the room", ["S3.E2", "S3.E1"])]
        checks = [{"ref": "S1", "claim": "air_pollution_event", "verdict": "corrected", "fact": "a %s ug/m3 step in one sample with clean outdoor air and an empty room" % p1["jump"].lstrip("+"),
                   "src": ["S1.E5", "S2.E1", "S3.E2"]}] if wrong else []
        t = "S1 (%s)" % ni
        r = rep(R.choice(["Indoor PM2.5 sensor offset after a step: %s" % nd["place"], "Suspect indoor PM2.5 readings (%s)" % nd["place"]]), "sensor_fault", "sensor_fault",
                "Indoor PM2.5 stepped up in one sample with clean outdoor air and nobody inside: a sensor offset, not pollution.",
                "%s ug/m3 step (S1.E5), outdoor steady (S2.E1), room empty (S3.E2) -> sensor offset" % p1["jump"].lstrip("+"), obs, checks, ["air_quality"], ["S1"], ev_of(obs),
                round(R.uniform(0.8, 0.9), 2), [("check_sensor", t, "Clean the inlet, check for a local dust source"), ("recalibrate_sensor", t, "Compare with a reference monitor")],
                "Whether indoor PM2.5 returns to the outdoor level after the check", "No source can explain the step: outdoor air is clean and the room is empty. Check the sensor.")
        return X(sensors=[s1, s2, s3], report=r, root_metric="pm25", rtype="pair_relation", hops=1, think=None, fam="pm_fault", outdoor=None,
                 ctx=("Indoor PM2.5 high: %s" % nd["place"], "warning", r["title"], "sensor_fault"))
    which = R.choice(["critical", "warning", "warning"])
    top_o = R.uniform(125, 190) if which == "critical" else R.uniform(64, 115)
    on = R.randrange(4, 20)
    lag = R.randrange(2, 9)
    out = ramp(R, on, R.uniform(25, 45), top_o, 1.5, 1, shape="lin", lo=1)
    ratio = R.uniform(0.55, 0.85)
    ind = ramp(R, on + lag, R.uniform(15, 35), top_o * ratio, 1.2, 1, shape="lin", lo=1)
    sev = worst(sev_hi(out[-1], 60, 120), sev_hi(ind[-1], 60, 120))
    if sev == "normal":
        return None
    wrong = R.random() < 0.4
    s1 = S("S1", "air_quality", "pm25", no, lo, out, True, head=[LIM["pm25"]], agent=lambda s: trend_ag(s, sev_hi(float(P(s)["last"]), 60, 120), "outdoor_pollution", word="PM2.5"))
    s2 = S("S2", "air_quality", "pm25", ni, li, ind, True, head=[LIM["pm25"]],
           agent=(lambda s: ag("gradual_increase", "warning", "indoor_source", 0.8, ["PM2.5 climbing at %s ug/m3/h [E4]" % P(s)["slope"]])) if wrong else
           (lambda s: trend_ag(s, sev_hi(float(P(s)["last"]), 60, 120), "outdoor_ingress", word="PM2.5")))
    p1, p2 = P(s1), P(s2)
    sens = [s1, s2]
    if R.random() < 0.6:
        sens.append(occ_sensor("S3", nd["occ"], end, None if R.random() < 0.5 else R.randrange(4, 40)))
    obs = [o_tr(s1, "Outdoor PM2.5"), o_now(s1, "Outdoor PM2.5"), o_tr(s2, "Indoor PM2.5"), o_now(s2, "Indoor PM2.5")]
    checks = [{"ref": "S2", "claim": "cause indoor_source", "verdict": "corrected", "fact": "indoor PM2.5 rose after the outdoor rise and stays below it (%s vs %s ug/m3)" % (p2["last"], p1["last"]),
               "src": ["S2.E1", "S1.E1", "S1.E4"]}] if wrong else []
    title = R.choice(["Outdoor PM2.5 %s ug/m3 entering the building: %s" % (p1["last"], nd["place"]), "Dust ingress: outdoor PM2.5 %s, indoor %s ug/m3 (%s)" % (p1["last"], p2["last"], nd["place"])])
    clist = [cl("inspect_ventilation", s2, "Close fresh-air intakes, check filters during the outdoor event")]
    if sev == "critical":
        clist.append(cl("request_facility_review", s2, "PM2.5 beyond the critical limit"))
    clist.append(("monitor", "S1 (%s)" % no, "Outdoor PM2.5 trend"))
    r = rep(title, sev, "air_pollution_event", "Outdoor PM2.5 rose first and the indoor sensor followed at a lower level: outdoor air entering, not an indoor source.",
            "outdoor PM2.5 up (S1.E4) -> ingress -> indoor PM2.5 up later (S2.E4), now %s ug/m3 (S2.E1)" % p2["last"], obs, checks, ["air_quality"], [], ev_of(obs),
            round(R.uniform(0.8, 0.9), 2), clist, "Indoor PM2.5 after the intakes are closed",
            R.choice(["The dust comes from outside; the indoor rise is the outdoor air getting in.", "Outdoor event first, indoor follows: reduce fresh-air intake and check filters."]))
    return X(sensors=sens, report=r, root_metric="pm25", rtype="pair_who", hops=1, think=None, fam="pm_ingress", outdoor=None,
             ctx=("Indoor PM2.5 source: %s" % nd["place"], "warning", title, sev))


def tank_head(R, lvl_hi):
    return ["TANK: high level above %.1f, overflow risk above %.1f; usual fill up to %d min" % (lvl_hi, lvl_hi + R.uniform(25, 40), R.choice([60, 90, 120]))]


def f_tank(R, sc, nd, mode):
    end = sc["end"]
    tn, tl = nd["tank"]
    fi, fil = nd["fin"]
    pn, pl = nd["pump"]
    lvl0 = R.uniform(200, 280)
    head = tank_head(R, lvl0 + R.uniform(10, 40))
    at = R.randrange(4, 24)
    pb = R.uniform(4.0, 7.5)
    if mode == "pump_trip":
        pw = step(R, at, pb, 0.02, 0.06, 2, lo=0)
        fl = step(R, at + 1, R.uniform(6, 12), 0.05, 0.15, 2, lo=0)
        lv = ramp(R, at + 2, lvl0, lvl0 - R.uniform(35, 80), 0.6, 1, shape="lin")
        flag_f = False
    elif mode == "leak":
        pw = ramp(R, at, pb, pb + R.uniform(1.0, 2.0), 0.06, 2, shape="lin")
        fl = noise(R, 144, R.uniform(8, 12), 0.15, 2, 0)
        lv = ramp(R, at, lvl0, lvl0 - R.uniform(70, 140), 0.6, 1, shape="lin")
        flag_f = False
    elif mode == "dry_run":
        pw = noise(R, 144, pb, 0.06, 2)
        fl = step(R, at, R.uniform(6, 12), 0.05, 0.12, 2, lo=0)
        lv = ramp(R, at + 2, lvl0, lvl0 - R.uniform(35, 80), 0.6, 1, shape="lin")
        flag_f = True
    else:  # level_fault: level offset down, controller starts the pump, inflow rises, level then climbs from the false low
        off = R.uniform(45, 90)
        pw = step(R, at + 1, 0.03, pb, 0.05, 2, lo=0)
        fl = step(R, at + 1, 0.04, R.uniform(6, 12), 0.12, 2, lo=0)
        base = noise(R, 144, lvl0, 0.5, 1)
        k0 = 96 + at
        lv = [r1(v - (off if i >= k0 else 0) + (max(0, i - k0 - 1) * R.uniform(0.35, 0.5) if i > k0 else 0), 1) for i, v in enumerate(base)]
        flag_f = False
    s1 = S("S1", "water", "level", tn, tl, lv, True, head=head)
    s2 = S("S2", "power", "power_kw", pn, pl, pw, True)
    s3 = S("S3", "water", "flow", fi, fil, fl, flag_f, "supply inflow to the same tank")
    sens = [s1, s2, s3]
    p1, p2, p3 = P(s1), P(s2), P(s3)
    wrong = R.random() < 0.4
    t1, t2, t3 = "S1 (%s)" % tn, "S2 (%s)" % pn, "S3 (%s)" % fi
    lev_down = ob("Tank level falling %s per hour (r2 %s)" % (p1["slope"].lstrip("-"), p1["r2"]), ["S1.E4"])
    if mode == "pump_trip":
        s1["agent"] = trend_ag(s1, "warning", "tank_draining", word="Tank level")
        s2["agent"] = ag("step_decrease", "normal", "low_load", 0.8, ["Pump power down to %s kW: pump off [E1]" % p2["last"]]) if wrong else \
            ag("step_decrease", "warning", "equipment_off", 0.85, ["Pump power dropped %s kW at %s [E5]" % (p2["jump"], p2["jump_t"])])
        s3["agent"] = ag("step_decrease", "normal", "no_inflow", 0.8, ["Inflow now %s m3/h [E1]" % p3["last"]])
        obs = [ob("Pump power dropped %s kW at %s" % (p2["jump"].lstrip("-"), p2["jump_t"]), ["S2.E5"]), ob("Inflow fell to %s m3/h" % p3["last"], ["S3.E1"]), lev_down,
               ob("Tank level now %s" % p1["last"], ["S1.E1"])]
        checks = [{"ref": "S2", "claim": "status normal (pump off)", "verdict": "corrected", "fact": "the pump stopped while the tank is draining (inflow %s m3/h)" % p3["last"],
                   "src": ["S2.E5", "S3.E1", "S1.E4"]}] if wrong else []
        title = R.choice(["Pump power lost, tank level falling: %s" % nd["wplace"], "Tank refill lost after pump power dropped: %s" % nd["wplace"]])
        r = rep(title, "warning", "water_supply_issue", "The pump lost power, inflow stopped and the tank is draining: the pump is the root cause, the level is the symptom.",
                "pump power down at %s (S2.E5) -> inflow %s m3/h (S3.E1) -> tank level falling (S1.E4)" % (p2["jump_t"], p3["last"]), obs, checks,
                ["power", "water"], [], ev_of(obs), round(R.uniform(0.82, 0.92), 2),
                [("inspect_electrical", t2, "Pump lost power: check supply, starter and trip"), ("inspect_water_system", t3, "Confirm the pump and inflow line"),
                 ("monitor", t1, "Watch the tank level until refill resumes")], "Tank level and inflow once the pump runs again",
                R.choice(["The tank is not leaking; it is not being refilled because the pump stopped.", "Fix the pump power first: the falling level follows from it."]))
        link = "Order: pump S2 drops first, then inflow S3, then level S1 falls. The level is the symptom; the pump stop is the cause."
        root = "Root: pump power (power domain), warning."
        return X(sensors=sens, report=r, root_metric="power_kw", rtype="pair_who", hops=2, think=(link, root), fam="pump_trip", outdoor=None,
                 ctx=("Tank level falling: %s" % nd["wplace"], "warning", title, "warning"))
    if mode == "leak":
        sev = "critical" if abs(float(p1["slope"])) > 25 else "warning"
        s1["agent"] = trend_ag(s1, sev, "tank_draining", word="Tank level")
        s2["agent"] = ag("gradual_increase", "warning", "pump_overload", 0.8, ["Pump power climbing at %s kW/h [E4]" % p2["slope"]]) if wrong else \
            trend_ag(s2, "normal", "pump_working_harder", word="Pump power")
        s3["agent"] = steady_ag("Inflow")(s3)
        obs = [lev_down, ob("Tank level now %s" % p1["last"], ["S1.E1"]), ob("Inflow steady around %s m3/h" % p3["last"], ["S3.E1"]), o_tr(s2, "Pump power")]
        checks = [{"ref": "S2", "claim": "pump_overload as the cause", "verdict": "corrected", "fact": "the pump works harder because the tank drains despite steady inflow",
                   "src": ["S2.E4", "S1.E4", "S3.E1"]}] if wrong else []
        title = R.choice(["Tank draining despite inflow, likely leak: %s" % nd["wplace"], "Water loss: tank level falling fast at %s" % nd["wplace"]])
        cl_ = [("inspect_water_system", t1, "Level falls despite steady inflow: find the leak or overuse")]
        if sev == "critical":
            cl_.append(("request_facility_review", t1, "Fast water loss"))
        cl_.append(("monitor", t2, "Pump load should drop once the loss stops"))
        r = rep(title, sev, "water_leak_or_overuse", "Water is leaving the tank faster than the inflow refills it; the pump load rise is a symptom, not the cause.",
                "loss from the tank (S1.E4) with inflow steady (S3.E1) -> pump runs harder (S2.E4)", obs, checks, ["water", "power"], [], ev_of(obs), round(R.uniform(0.8, 0.9), 2),
                cl_, "Tank level trend after the inspection", R.choice(["Look for the leak: the pump is reacting to it, not causing it.", "The water side is the root; the power rise follows."]))
        link = "Level S1 falls while inflow S3 is steady, so water is leaving. Pump S2 rises after, reacting to it."
        root = "Root: water loss (water domain); pump load is a symptom."
        return X(sensors=sens, report=r, root_metric="level", rtype="pair_who", hops=2, think=(link, root), fam="leak", outdoor=None,
                 ctx=("Pump power rising: %s" % nd["wplace"], "warning", title, sev))
    if mode == "dry_run":
        s1["agent"] = trend_ag(s1, "warning", "tank_draining", word="Tank level")
        s2["agent"] = steady_ag("Pump power")(s2)
        s3["agent"] = ag("step_decrease", "warning", "supply_cut", 0.85, ["Inflow dropped to %s m3/h [E1]" % p3["last"]])
        if wrong:
            s2["agent"] = ag("stable", "normal", "normal_load", 0.85, ["Pump running normally at %s kW [E1]" % p2["last"]])
        obs = [ob("Inflow fell to %s m3/h at %s" % (p3["last"], p3["jump_t"]), ["S3.E1", "S3.E5"]), ob("Pump power steady around %s kW" % p2["last"], ["S2.E1"]), lev_down]
        checks = [{"ref": "S2", "claim": "pump running normally", "verdict": "unsupported", "fact": "the pump draws power but no water arrives (%s m3/h)" % p3["last"],
                   "src": ["S2.E1", "S3.E1"]}] if wrong else []
        title = R.choice(["Pump running but no inflow, tank level falling: %s" % nd["wplace"], "Water supply cut: inflow %s m3/h, tank falling (%s)" % (p3["last"], nd["wplace"])])
        r = rep(title, "warning", "water_supply_issue", "The pump runs but no water reaches the tank: the direct cause of the falling level is the lost inflow.",
                "inflow %s m3/h (S3.E1) with the pump running (S2.E1) -> no refill -> tank level falling (S1.E4)" % p3["last"], obs, checks, ["water", "power"], [],
                ev_of(obs), round(R.uniform(0.8, 0.9), 2),
                [("inspect_water_system", t3, "Pump runs but nothing flows: dry run, closed valve or supply cut"), ("inspect_electrical", t2, "Stop a dry-running pump from damage"),
                 ("monitor", t1, "Tank level until inflow returns")], "Inflow and tank level after the supply check",
                "The pump is on, but the water is not coming: check the supply line and protect the pump.")
        link = "Direct cause of the level fall in S1 is zero inflow S3; pump S2 still draws power, so the pump is running dry or the supply is cut."
        root = "Root: supply side (water); warning."
        return X(sensors=sens, report=r, root_metric="flow", rtype="chain_direct", hops=1, think=(link, root), fam="dry_run", outdoor=None,
                 ctx=("Pump power steady, tank low: %s" % nd["wplace"], "normal", title, "warning"))
    # level_fault
    s1["agent"] = ag("step_decrease", "warning", "tank_draining", 0.85, ["Tank level dropped %s at %s [E5]" % (p1["jump"], p1["jump_t"])]) if wrong else \
        ag("step_decrease", "sensor_fault", "sensor_fault", 0.85, ["Level dropped %s in one sample at %s [E5]" % (p1["jump"], p1["jump_t"])])
    s2["agent"] = ag("step_increase", "normal", "pump_start", 0.8, ["Pump started at %s [E5]" % p2["jump_t"]])
    s3["agent"] = ag("step_increase", "normal", "inflow", 0.8, ["Inflow now %s m3/h [E1]" % p3["last"]])
    obs = [ob("Tank level dropped %s in one sample at %s" % (p1["jump"].lstrip("-"), p1["jump_t"]), ["S1.E5"]), ob("Pump started at %s" % p2["jump_t"], ["S2.E5"]),
           ob("Inflow now %s m3/h" % p3["last"], ["S3.E1"])]
    checks = [{"ref": "S1", "claim": "status warning (tank draining)", "verdict": "corrected",
               "fact": "a one-sample drop of %s; no outflow can empty a tank that fast" % p1["jump"].lstrip("-"), "src": ["S1.E5"]}] if wrong else []
    title = R.choice(["Tank level sensor offset started the pump: %s" % nd["wplace"], "Suspect tank level readings (%s)" % nd["wplace"]])
    r = rep(title, "sensor_fault", "sensor_fault", "The level sensor dropped in one sample; the controller then started the pump. The pump start is a response to a false low level.",
            "level offset at %s (S1.E5) -> pump start at %s (S2.E5) -> inflow (S3.E1)" % (p1["jump_t"], p2["jump_t"]), obs, checks, ["water", "power"], ["S1"], ev_of(obs),
            round(R.uniform(0.8, 0.9), 2), [("check_sensor", t1, "One-sample drop is not physical"), ("recalibrate_sensor", t1, "Compare with a manual dip reading"),
                                            ("monitor", t1, "Watch for overflow while the pump runs on a false reading")],
            "Tank level against a manual reading; overflow risk while the pump runs", "The tank did not empty; the sensor jumped and the pump reacted to it. Fix the sensor before trusting the level.")
    link = "Order: level S1 drops in one sample, then pump S2 starts and inflow S3 rises. The pump reacts to the reading; the root is the level sensor."
    root = "Root: level sensor fault; the pump start is a consequence."
    return X(sensors=sens, report=r, root_metric="level", rtype="pair_who", hops=2, think=(link, root), fam="level_fault", outdoor=None,
             ctx=("Pump power step: %s" % nd["wplace"], "warning", title, "sensor_fault"))


def f_rain(R, sc, nd):
    tn, tl = nd["tank"]
    on = R.randrange(4, 22)
    rh = ramp(R, on, R.uniform(70, 80), R.uniform(91.5, 96.4), 0.4, 1, shape="exp")
    if not (90 < rh[-1] < 97):
        return None
    lvl0 = R.uniform(150, 230)
    lv = ramp(R, on + R.randrange(1, 5), lvl0, lvl0 + R.uniform(20, 55), 0.5, 1, shape="lin")
    hi = lv[-1] + R.uniform(-15, 25)
    s1 = S("S1", "weather", "rh", WE_NODE, WE_LOC, rh, True, head=[LIM["wrh"]], agent=lambda s: trend_ag(s, "warning", "rain", word="Humidity"))
    s2 = S("S2", "water", "level", tn, tl, lv, True, head=["TANK: high level above %.1f, overflow risk above %.1f; usual fill up to 90 min" % (hi, hi + 30)],
           agent=lambda s: trend_ag(s, "warning", "unexpected_fill", word="Tank level"))
    s3 = S("S3", "power", "power_kw", nd["pump"][0], nd["pump"][1], noise(R, 48, 0.03, 0.01, 2, 0), False, "pump state", agent=steady_ag("Pump power"))
    sens = [s1, s2, s3]
    p1, p2, p3 = P(s1), P(s2), P(s3)
    obs = [o_tr(s1, "Outdoor humidity"), o_now(s1, "Outdoor humidity"), o_tr(s2, "Tank level"), ob("Pump idle around %s kW" % p3["last"], ["S3.E1"])]
    title = R.choice(["Rain: outdoor humidity %s %% and tank level rising: %s" % (p1["last"], nd["wplace"]), "Tank filling from rain, humidity %s %%: %s" % (p1["last"], nd["wplace"])])
    r = rep(title, "warning", "weather_driven", "Rain (humidity over 90 %) is filling the tank through the rooftop inflow while the pump is idle: weather, not a leak or a fault.",
            "rain (S1.E4) -> rooftop inflow -> tank level rising (S2.E4) with the pump idle (S3.E1)", obs, [], ["weather", "water"], [], ev_of(obs), round(R.uniform(0.78, 0.9), 2),
            [("monitor", "S2 (%s)" % tn, "Tank level against the overflow mark"), ("inspect_water_system", "S2 (%s)" % tn, "Check the overflow and rain inlet")],
            "Tank level against the overflow mark while it rains", "It is raining and the tank is filling by itself. Keep an eye on the overflow.")
    link = "Humidity S1 rose first, then level S2 climbs while pump S3 is idle: rain feeds the tank. Cause then effect, no fault."
    root = "Root: rain (weather); warning for the humidity limit and overflow watch."
    return X(sensors=sens, report=r, root_metric="rh", rtype="pair_relation", hops=1, think=(link, root), fam="rain_level", outdoor=None,
             ctx=("Tank level rising without the pump: %s" % nd["wplace"], "warning", title, "warning"))


def ev_co2(R, sc, nd, ref, which, refo):
    top = {"critical": R.uniform(1530, 1900), "warning": R.uniform(1040, 1450)}[which]
    on = R.randrange(4, 24)
    co2 = ramp(R, on + 1, R.uniform(420, 520), top, 6, 0)
    if sev_hi(co2[-1], 1000, 1500) != which:
        return None
    s = S(ref, "air_quality", "co2", nd["aq"][0], nd["aq"][1], co2, True, head=[LIM["co2"]],
          agent=lambda s: ag("gradual_increase", which, "occupancy_load", 0.85, ["CO2 climbing at %s ppm/h, now %s ppm [E4,E1]" % (P(s)["slope"], P(s)["last"])]))
    o = occ_sensor(refo, nd["occ"], sc["end"], on)
    p = P(s)
    return dict(s=[s, o], sev=which, label="occupancy_driven_load", rm="co2", word="CO2", place=nd["place"],
                obs=[o_tr(s, "CO2"), o_now(s, "CO2")], what="CO2 %s ppm with people at %s" % (p["last"], nd["place"]),
                act=[cl("inspect_ventilation", s, "Fresh-air supply is not keeping up")], dom=["air_quality", "occupancy"])


def ev_ph(R, sc, nd, ref):
    which = R.choice(["critical", "warning"])
    lvl = R.uniform(9.2, 9.8) if which == "critical" else R.uniform(8.6, 8.95)
    t0 = R.randrange(10, 36)
    xs = noise(R, 96 + t0, R.uniform(7.0, 7.6), 0.05, 2) + noise(R, 48 - t0, lvl, 0.04, 2)
    s = S(ref, "water", "ph", nd["wq"][0], nd["wq"][1], xs, True, head=["LIMITS: warning above 8.5, critical above 9.0"],
          agent=lambda s: ag("step_increase", which, "water_quality_issue", 0.9, ["%s pH is beyond the %s limit [E1]" % (P(s)["last"], which)]))
    p = P(s)
    if sev_hi(float(p["last"]), 8.5, 9.0) != which:
        return None
    return dict(s=[s], sev=which, label="water_quality_issue", rm="ph", word="pH", place=nd["wplace"], obs=[o_now(s, "Water pH"), ob("pH moved at %s and stayed there" % p["jump_t"], [ref + ".E5", ref + ".E6"])],
                what="water pH %s at %s" % (p["last"], nd["wplace"]), act=[("inspect_water_system", "%s (%s)" % (ref, nd["wq"][0]), "Find the dosing or supply change")], dom=["water"])


def ev_pf(R, sc, nd, ref):
    which = R.choice(["critical", "warning"])
    tgt = R.uniform(0.62, 0.69) if which == "critical" else R.uniform(0.74, 0.83)
    on = R.randrange(6, 30)
    xs = ramp(R, on, R.uniform(0.92, 0.96), tgt, 0.004, 3, shape="lin")
    s = S(ref, "power", "pf", SUB_NODE, SUB_LOC, xs, True, head=[LIM["pf"]],
          agent=lambda s: ag("gradual_decrease", which, "power_quality_issue", 0.8, ["Power factor falling at %s/h, now %s [E4,E1]" % (P(s)["slope"], P(s)["last"])]))
    p = P(s)
    v = float(p["last"])
    if ("critical" if v < 0.7 else ("warning" if v < 0.85 else "normal")) != which:
        return None
    return dict(s=[s], sev=which, label="power_quality_issue", rm="pf", word="power factor", place="SB00 substation", obs=[o_now(s, "Power factor"), o_tr(s, "Power factor")],
                what="power factor %s at the SB00 substation" % p["last"], act=[("inspect_electrical", "%s (%s)" % (ref, SUB_NODE), "Check the capacitor bank and inductive loads")],
                dom=["power"])


def capw(w):
    return w if w.startswith("pH") else w[0].upper() + w[1:]


def f_two(R, sc, nd, nd2, mode):
    kinds = R.sample(["co2", "ph", "pf"], 2)
    evs = []
    ref = 1
    for j, k in enumerate(kinds):
        n_ = nd if j == 0 else nd2
        if k == "co2":
            e = ev_co2(R, sc, n_, "S%d" % ref, R.choice(["critical", "warning"]), "S%d" % (ref + 1))
        elif k == "ph":
            e = ev_ph(R, sc, n_, "S%d" % ref)
        else:
            e = ev_pf(R, sc, n_, "S%d" % ref)
        if not e:
            return None
        ref += len(e["s"])
        evs.append(e)
    a, b = evs
    order = ["warning", "critical"]
    if mode == "worse" and a["sev"] == b["sev"]:
        return None
    if mode == "indep" and R.random() < 0.5 and a["sev"] != b["sev"]:
        pass
    top, other = (a, b) if order.index(a["sev"]) >= order.index(b["sev"]) else (b, a)
    sev = top["sev"]
    sens = a["s"] + b["s"]
    obs = (top["obs"][:2] + other["obs"][:2])[:5]
    if mode == "worse":
        title = R.choice(["%s (%s) is the worse of two events: %s" % (capw(top["word"]), sev, top["place"]),
                          "%s %s, more severe than %s" % (capw(top["word"]), sev, other["word"])])
        rc = "Two real, unrelated events; the %s one is worse (%s vs %s), so it sets the severity." % (top["word"], sev, other["sev"])
    else:
        title = R.choice(["%s %s and an unrelated %s event: %s" % (capw(top["word"]), sev, other["word"], top["place"]),
                          "Two separate events: %s and %s" % (top["word"], other["word"])])
        rc = "Two real events at the same time with no physical link between them: separate causes, handle both."
    if top["place"] not in title and re.search(r"[A-Z]{2} building, level \d+", title) is None:
        pass
    acts = top["act"][:1] + ([("request_facility_review", top["act"][0][1], "Beyond the critical limit")] if sev == "critical" else []) + other["act"][:1]
    chain = "%s (%s) and %s (%s) are independent; no shared driver" % (top["what"], top["obs"][0]["src"][0], other["what"], other["obs"][0]["src"][0])
    if len(chain.split()) > 40:
        chain = "%s (%s) and %s (%s): independent" % (top["word"], top["obs"][0]["src"][0], other["word"], other["obs"][0]["src"][0])
    doms = []
    for d in top["dom"] + other["dom"]:
        if d not in doms:
            doms.append(d)
    r = rep(title, sev, top["label"], rc, chain, obs, [], doms, [], ev_of(obs), round(R.uniform(0.8, 0.9), 2), acts,
            "Both events until each is resolved", R.choice(["Two problems at once, not one: fix each on its own.", "These happened together by chance; neither causes the other."]))
    fl = [s for s in sens if s["flagged"]]
    if mode == "worse":
        link = "Compare: %s is %s, %s is %s; different places, no link." % (top["s"][0]["ref"], top["sev"], other["s"][0]["ref"], other["sev"])
        root = "The worse event sets severity and the title; both get an action."
    else:
        link = "%s and %s sit in different systems with no physical path between them; they only coincide in time." % (a["s"][0]["ref"], b["s"][0]["ref"])
        root = "Independent events; severity from the worse one."
    return X(sensors=sens, report=r, root_metric=top["rm"], rtype="pairwise" if mode == "worse" else "pair_relation", hops=0 if mode == "worse" else 1,
             think=(link, root), fam=mode, outdoor=None, ctx=("%s %s" % (other["word"], other["sev"]), other["sev"], title, sev))


def f_pf_chain(R, sc, nd):
    temps, sevw = heat_base(R, sc, R.choice(["critical", "warning"]))
    if sevw is None:
        return None
    pfx = ev_pf(R, sc, nd, "S3")
    if not pfx:
        return None
    s1 = S("S1", "weather", "temp", WE_NODE, WE_LOC, temps, True, head=[LIM["wtemp"]],
           agent=lambda s: ag("gradual_increase", sevw, "heat_buildup", 0.8, ["Temperature climbing at %s C/h, now %s C [E4,E1]" % (P(s)["slope"], P(s)["last"])]))
    on = R.randrange(6, 26)
    k0 = R.uniform(900, 1300)
    kw = ramp(R, on, k0, k0 + R.uniform(180, 420), 6, 2, shape="lin")
    s2 = S("S2", "power", "power_kw", SUB_NODE, SUB_LOC, kw, True, agent=lambda s: trend_ag(s, "warning", "high_load", word="Power"))
    s3 = pfx["s"][0]
    a0, a1 = R.choice([1, 2]), R.choice([3, 4])
    s4 = S("S4", "hvac", "ac_units_on", nd["ac"][0], nd["ac"][1], [a0] * on + [a1] * (48 - on), False, "AC response", unit_shown="units",
           agent=lambda s: ag("step_increase", "normal", "hvac_context", 0.8, ["AC units running: now %s [E1,E4]" % P(s)["last"]]))
    sens = [s1, s2, s3, s4]
    p1, p2, p3, p4 = P(s1), P(s2), P(s3), P(s4)
    sev = worst(sevw, pfx["sev"])
    obs = [o_tr(s1, "Outdoor temperature"), ob("AC units running now %s" % p4["last"], ["S4.E1"]), o_tr(s2, "Feeder load"), o_now(s3, "Power factor")]
    title = R.choice(["Power factor %s under heat-driven AC load: SB00 substation" % p3["last"], "Heat, AC load and a power factor dip to %s" % p3["last"]])
    acts = [("inspect_electrical", "S3 (%s)" % SUB_NODE, "Capacitor bank must cover the extra inductive AC load")]
    if sev == "critical":
        acts.append(("request_facility_review", "S3 (%s)" % SUB_NODE, "Power quality beyond the critical limit"))
    acts.append(("review_schedule", "S1 (%s)" % WE_NODE, "Stagger AC start-ups in the hottest hours"))
    r = rep(title, sev, "power_quality_issue", "Outdoor heat started more AC compressors; the extra inductive load raised the feeder load and pulled the power factor down.",
            "outdoor heat (S1.E4) -> AC units to %s (S4.E1) -> feeder load up (S2.E4) -> power factor %s (S3.E1)" % (p4["last"], p3["last"]), obs, [],
            ["weather", "power", "hvac"], [], ev_of(obs), round(R.uniform(0.8, 0.9), 2), acts, "Power factor once the capacitor bank is checked",
            "The heat is the start of a chain that ends at the power factor. Fix the compensation, not the weather.")
    link = "Chain: heat S1 starts more AC S4, feeder load S2 climbs, power factor S3 dips. Three hops from weather to power quality."
    root = "Root: outdoor heat; the actionable event is the power factor."
    return X(sensors=sens, report=r, root_metric="pf", rtype="multihop", hops=3, think=(link, root), fam="pf_chain",
             outdoor=(p1["last"], WE_NODE, L.tstr(sc["end"])), ctx=("Feeder load rising: SB00 substation", "warning", title, sev))


# family -> (generator, reasoning type, weight)
FAMS = [
    ("occ_load", lambda R, sc, nd, nd2: f_occ_load(R, sc, nd), 2.0),
    ("occ_fault", lambda R, sc, nd, nd2: f_occ_fault(R, sc, nd), 1.0),
    ("heat_multihop", lambda R, sc, nd, nd2: f_heat(R, sc, nd, "multihop"), 1.2),
    ("heat_trans", lambda R, sc, nd, nd2: f_heat(R, sc, nd, "trans"), 2.0),
    ("heat_three", lambda R, sc, nd, nd2: f_heat(R, sc, nd, "three"), 1.0),
    ("ac_fail", lambda R, sc, nd, nd2: f_ac_fail(R, sc, nd), 1.0),
    ("wx_fault", lambda R, sc, nd, nd2: f_wx_fault(R, sc, nd), 1.0),
    ("wx_fault_co2", lambda R, sc, nd, nd2: f_wx_fault(R, sc, nd, True), 0.8),
    ("pm_ingress", lambda R, sc, nd, nd2: f_pm(R, sc, nd), 0.7),
    ("pm_fault", lambda R, sc, nd, nd2: f_pm(R, sc, nd, True), 0.4),
    ("pump_trip", lambda R, sc, nd, nd2: f_tank(R, sc, nd, "pump_trip"), 0.8),
    ("leak", lambda R, sc, nd, nd2: f_tank(R, sc, nd, "leak"), 0.7),
    ("dry_run", lambda R, sc, nd, nd2: f_tank(R, sc, nd, "dry_run"), 1.0),
    ("level_fault", lambda R, sc, nd, nd2: f_tank(R, sc, nd, "level_fault"), 0.8),
    ("rain_level", lambda R, sc, nd, nd2: f_rain(R, sc, nd), 0.5),
    ("indep", lambda R, sc, nd, nd2: f_two(R, sc, nd, nd2, "indep"), 0.8),
    ("worse", lambda R, sc, nd, nd2: f_two(R, sc, nd, nd2, "worse"), 2.0),
    ("pf_chain", lambda R, sc, nd, nd2: f_pf_chain(R, sc, nd), 1.0),
]
HEAT_FAMS = {"heat_multihop", "heat_trans", "heat_three", "pf_chain", "wx_fault", "wx_fault_co2"}
RAIN_FAMS = {"rain_level"}


def flagged_domains(sensors):
    out = []
    for s in sensors:
        if s["flagged"] and s["role"] not in out:
            out.append(s["role"])
    return out


def think_ok(th, user):
    if not th:
        return ["think_empty"]
    errs = []
    if VC.think_tokens(th) > VC.THINK_MAX:
        errs.append("think_long:%d" % VC.think_tokens(th))
    if re.search(r"[{}\"]", th):
        errs.append("think_brace")
    t = re.sub(r"\b(?:S\d+\.E\d+|S\d+|E\d+|R\d+|M\d+|PM2\.5|PM10|CO2|SB00|11 kV|r2)\b", " ", th)
    cn = V.numset(re.sub(V.STRIP, " ", user))
    for tm in re.findall(r"\b\d\d:\d\d\b", t):
        if tm not in user:
            errs.append("think_time:" + tm)
    t = re.sub(r"\b\d\d:\d\d\b", " ", t)
    for x in V.numset(t):
        if x not in cn:
            errs.append("think_num:" + x)
    return errs


def gen_one(R, i, prefix, novel_frac, refine_frac, memory_frac, fam_w=None):
    names = [f[0] for f in FAMS]
    w = fam_w or [f[2] for f in FAMS]
    name = R.choices(names, w)[0]
    fn = dict((f[0], f[1]) for f in FAMS)[name]
    months = [3, 4, 5, 6] if name in HEAT_FAMS else ([6, 7, 8, 9] if name in RAIN_FAMS else None)
    hours = [12, 13, 14, 15, 16] if name in HEAT_FAMS else None
    sc = scen(R, i, novel=R.random() < novel_frac, months=months, hours=hours)
    S.end = sc["end"]
    nd = nodes(sc)
    sc2 = dict(sc, b=sc["b2"], fl=R.randrange(1, 7), k=R.randrange(1, 10))
    nd2 = nodes(sc2)
    g = fn(R, sc, nd, nd2)
    if not g:
        return None, name + ":none"
    report = g["report"]
    mode, recheck, fam = "early", None, g["fam"]
    if R.random() < refine_frac:
        stage, recheck, was_wrong = G2.refine_ctx(R, sc, *g["ctx"])
        mode = stage
        fam += "+%s%s" % (stage, "+prev_wrong" if was_wrong else "")
        if was_wrong:
            report = dict(report, agent_checks=report["agent_checks"][:3])
            ch = report["causal_chain"] + "; the earlier revision (R1) is not supported now"
            if len(ch.split()) <= 40:
                report["causal_chain"] = ch
    memory = []
    if R.random() < memory_frac:
        dd = sc["end"].date() - dt.timedelta(days=R.choice([3, 9, 16, 40, 75]))
        memory = ["%s INC-%04d %s on %s, closed: %s" % (dd.isoformat(), R.randrange(100, 999), R.choice(["Suspect readings", "Load step judged ordinary", "Spike checked"]),
                                                       g["sensors"][0]["node"], R.choice(["resolved_on_its_own (auto)", "no_action_needed"]))]
    row = G2.mk_row(R, sc, fam, g["sensors"], report, g["root_metric"], "%s-%05d" % (prefix, i), i, mode=mode, recheck=recheck, memory=memory, outdoor=g["outdoor"])
    doms = flagged_domains(g["sensors"])
    th = None
    if len(doms) >= 2:
        link, root = g["think"]
        fl = [s for s in g["sensors"] if s["flagged"]]
        th = think_text(R, fl, link, root)
        if VC.think_tokens(th) > VC.THINK_MAX:
            th = " ".join([link, root])
        if mode != "early" and "prev_wrong" in fam and VC.think_tokens(th + " Earlier revision R1 no longer fits.") <= VC.THINK_MAX:
            th += " Earlier revision R1 no longer fits."
    row.update({"reasoning_type": g["rtype"], "hops": g["hops"], "flagged_domains": doms, "think": th is not None})
    if th is not None:
        row["messages"][-1]["reasoning_content"] = th
    return row, None


def finish_row(r):
    th = r["messages"][-1].get("reasoning_content")
    r = G2.compact_row(r)
    fr = G2.fix(dict(r))
    for k in ("pair", "meta", "reasoning_type", "hops", "flagged_domains", "think"):
        fr[k] = r[k]
    if th is not None:
        fr["messages"][-1]["reasoning_content"] = th
    return fr


def check_row(r):
    e = V.check_incident(r)
    th = r["messages"][-1].get("reasoning_content")
    if r["think"]:
        e += think_ok(th, r["messages"][1]["content"])
    elif th:
        e.append("think_unexpected")
    return e


def build(R, n, prefix, novel_frac=0.0, refine_frac=0.3, memory_frac=0.2, balance=True):
    """balance: reasoning types equally represented (family weights re-scaled by type)"""
    rows, fails, tries = [], collections.Counter(), 0
    want = collections.Counter()
    while len(rows) < n and tries < n * 30:
        tries += 1
        fw = None
        if balance and rows:
            have = collections.Counter(r["reasoning_type"] for r in rows)
            tgt = min(RTYPES, key=lambda t: have[t])
            fw = [f[2] * (6.0 if RT_OF[f[0]] == tgt else 1.0) for f in FAMS]
        r, why = gen_one(R, len(rows), prefix, novel_frac, refine_frac, memory_frac, fw)
        if r is None:
            fails[why] += 1
            continue
        e = check_row(r)
        if e:
            for y in set(z.split(":")[0] for z in e):
                fails["%s %s" % (r["family"].split("+")[0], y)] += 1
            continue
        fr = finish_row(r)
        if check_row(fr):
            fails["finish"] += 1
            continue
        rows.append(fr)
    return rows, fails, tries


RT_OF = {"occ_load": "chain_max", "occ_fault": "pair_relation", "heat_multihop": "multihop", "heat_trans": "transitive", "heat_three": "three_way",
         "ac_fail": "chain_direct", "wx_fault": "pair_relation", "wx_fault_co2": "pair_relation", "pm_ingress": "pair_who", "pm_fault": "pair_relation",
         "pump_trip": "pair_who", "leak": "pair_who", "dry_run": "chain_direct", "level_fault": "pair_who", "rain_level": "pair_relation",
         "indep": "pair_relation", "worse": "pairwise", "pf_chain": "multihop"}


def write(p, rows):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def comp(rows):
    c = collections.Counter()
    for r in rows:
        rp = json.loads(r["messages"][-1]["content"])
        c["fam:" + r["family"].split("+")[0]] += 1
        c["rtype:" + r["reasoning_type"]] += 1
        c["hops:%d" % r["hops"]] += 1
        c["sev:" + rp["severity"]] += 1
        c["think:%s" % r["think"]] += 1
        c["mode:" + ("refine" if "+refine" in r["family"] else "early")] += 1
    return dict(sorted(c.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=9000)
    ap.add_argument("--seed", type=int, default=41112)
    ap.add_argument("--n-test", type=int, default=720)
    ap.add_argument("--n-dev", type=int, default=60)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    te, fte, _ = build(random.Random(a.seed + 7), a.n_test, "r4it", novel_frac=0.35)
    dv, fdv, _ = build(random.Random(a.seed + 13), a.n_dev, "r4id", novel_frac=0.2)
    tr, ftr, ttr = build(random.Random(a.seed), a.n, "r4i")
    ban = {r["messages"][1]["content"] for r in te + dv}
    n0 = len(tr)
    tr = [r for r in tr if r["messages"][1]["content"] not in ban]
    for r in te:
        r["slice"] = "xdomain"
        rp = json.loads(r["messages"][-1]["content"])
        r["gold_text"] = {"title": rp["title"], "root_cause": rp["root_cause"], "causal_chain": rp["causal_chain"], "explanation": rp["explanation"],
                          "think": r["messages"][-1].get("reasoning_content") or ""}
        r["novel_names"] = any(c in r["messages"][1]["content"] for c in (" %s building" % b for b in NOVEL_B))
    write(os.path.join(a.out, "train.jsonl"), tr)
    write(os.path.join(a.out, "test.jsonl"), te)
    write(os.path.join(a.out, "dev.jsonl"), dv)
    man = {"generator": "proofs/2026-11-12_topup_r4/tools/gen_r4_inc.py", "seed": a.seed, "rows": {"train": len(tr), "test": len(te), "dev": len(dv)},
           "train_dropped_overlap": n0 - len(tr), "train": comp(tr), "test": comp(te), "dev": comp(dv),
           "verify_fail": {"train": dict(ftr.most_common(40)), "test": dict(fte.most_common(20))}, "tries_train": ttr}
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    print("r4 inc: train %d test %d dev %d; fails %s" % (len(tr), len(te), len(dv), dict(ftr.most_common(12))))


if __name__ == "__main__":
    main()
