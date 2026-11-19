"""Reasoner part 2 families (2026-11-18), r4-style family functions registered in gen_r4_inc.FAMS (install_p2). From board findings
2026-11-17 (app_test + sensor_fault_check):
 (a) p2_flat_alone / p2_step_real / p2_plateau_real : flat run, plateau or instant step ALONE -> warning "possible sensor fault" or the real event,
     never sensor_fault, whatever the agent said;  p2_fault_2nd : sensor_fault only with a 2nd evidence kind (impossible value, neighbour/AC/people
     disagreement, history shows variation then freeze).
 (b) hygiene: evidence ids are only S<n>.E<n>; quality text ('uncertain (...)') is never an id (rows carry such quality lines, reports ignore them)
 (c) 'uncertain (1 of 48 readings in the 4 h window filled in)' (app text) quality lines: negligible, no data-gap claim
 (d,e) p2_batch : combined-cause pair + a separate unrelated abnormal sensor, each with its own line/verdict; late-abnormal (promoted) variant
 (f) MEMORY with operator outcomes: confirmed sensor_replaced/repaired flips a flat-only to sensor_fault; unconfirmed past 'sensor fault'
     (false_alarm / no_action_needed / resolved_on_its_own) is NOT used; confirmed fixed_by_action backs the real event."""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v2_gen as X0  # noqa: E402

M, G2 = X0.M, X0.G2
P, ag, ob, rep, ev_of, S, X = M.P, M.ag, M.ob, M.rep, M.ev_of, M.S, M.X
P2 = {"memory": None}
_orig_mk = G2.mk_row
NAMES = ("p2_flat_alone", "p2_flat_mem", "p2_step_real", "p2_step_real_mem", "p2_plateau_real", "p2_fault_2nd", "p2_batch", "p2_batch_late")
P2_NAMES = {"p2_flat_alone": 140, "p2_flat_mem": 170, "p2_step_real": 130, "p2_step_real_mem": 90, "p2_plateau_real": 130, "p2_fault_2nd": 260,
            "p2_batch": 160, "p2_batch_late": 140}


def _mk(R, sc, fam, sensors, report, root_metric, rid, pair, mode="early", recheck=None, memory=None, outdoor=None, end=None):
    if fam.startswith("p2_"):
        r = R.random()   # (b)/(c) data-quality text variants (never cited as ids)
        if r < 0.22:
            s = R.choice(sensors[1:] or sensors)
            if s["quality"] == "good":
                s["quality"] = "uncertain (%d of 48 readings in the 4 h window filled in)" % R.randrange(4, 9)
        elif r < 0.40:
            s = R.choice(sensors)
            if s["quality"] == "good":
                s["quality"] = "uncertain (1 of 48 readings in the 4 h window filled in)"
        if P2["memory"] is not None:
            memory = P2["memory"]
    P2["memory"] = None
    return _orig_mk(R, sc, fam, sensors, report, root_metric, rid, pair, mode=mode, recheck=recheck, memory=memory, outdoor=outdoor, end=end)


def mem(R, sc, node, title, outcome):
    dd = sc["end"].date() - dt.timedelta(days=R.choice([4, 11, 19, 33, 52, 80]))
    return ["%s INC-%04d %s on %s, closed: %s" % (dd.isoformat(), R.randrange(100, 999), title, node, outcome)]


def f_flat_alone(R, sc, nd, memkind=None):
    """room power meter flat for the whole window and history, ALONE (room empty): possible sensor fault, not a fault verdict"""
    end = sc["end"]
    lvl = R.choice([0.0, 0.0, round(R.uniform(0.35, 0.9), 2)])
    xs = [lvl] * 144
    st = R.choice(["sensor_fault", "sensor_fault", "warning", "normal"])

    def ag_p(s):
        p = P(s)
        if st == "sensor_fault":
            return ag("flatline", "sensor_fault", "sensor_fault", 0.8, ["Power flat at %s kW [E1,E8]" % p["last"]])
        return ag("stable", st, "low_load", 0.75, ["Power steady at %s kW [E1,E4]" % p["last"]])
    s1 = S("S1", "power", "power_kw", nd["em"][0], nd["em"][1], xs, True, agent=ag_p)
    s2 = M.occ_sensor("S2", nd["occ"], end, None)
    p1 = P(s1)
    obs = [ob("Room power flat at %s kW, flat run %s points" % (p1["last"], p1["flat"]), ["S1.E8"]),
           ob("Room unoccupied for the whole window", ["S2.E1", "S2.E2"]), ob("No level shift or drift in the 12 h view", ["S1.E9"])]
    checks = []
    if st == "sensor_fault":
        checks.append({"ref": "S1", "claim": "sensor_fault", "verdict": "corrected",
                       "fact": "a flat run alone is not proof: the room is empty and the 12 h view shows the same level", "src": ["S1.E8", "S2.E1"]})
    elif st == "normal":
        checks.append({"ref": "S1", "claim": "status normal (low load)", "verdict": "corrected",
                       "fact": "a perfectly flat run cannot be called healthy without a second check", "src": ["S1.E8"]})
    ps = "S1 (%s)" % nd["em"][0]
    sev, label, nmd, conf = "warning", "unknown", True, round(R.uniform(0.5, 0.65), 2)
    title = R.choice(["Possible sensor fault: room power flat at %s kW: %s" % (p1["last"], nd["place"]),
                      "Room power meter flat at %s kW, cause unclear: %s" % (p1["last"], nd["place"])])
    rc = "Room power is flat at %s kW in an empty room; a flat run alone fits both a standby load and a stuck meter, and there is no second evidence." % p1["last"]
    cl = [("check_sensor", ps, "Compare with a clamp reading"), ("monitor", ps, "Look for any change when the room is used")]
    chain = "flat run %s points (S1.E8) in an empty room (S2.E1); no second evidence of a fault" % p1["flat"]
    expl = "Flat alone is not enough to call a fault; check the meter once and watch it."
    if memkind == "confirmed_fault":
        sev, label, nmd, conf = "sensor_fault", "sensor_fault", False, round(R.uniform(0.78, 0.88), 2)
        P2["memory"] = mem(R, sc, nd["em"][0], "Room power meter flat", R.choice(["sensor_replaced", "sensor_repaired"]))
        title = "Room power meter flat again after a confirmed repair: %s" % nd["place"]
        rc = "The same meter was confirmed faulty (flat) and fixed before, and it is flat again at %s kW with the room empty: a repeat sensor fault." % p1["last"]
        cl = [("check_sensor", ps, "Same meter failed before"), ("recalibrate_sensor", ps, "The repair may not have held")]
        chain = "flat run %s points (S1.E8) in an empty room (S2.E1); the same meter was confirmed faulty before (memory)" % p1["flat"]
        expl = "A past confirmed fault on this meter plus the same flat signature again: treat as a sensor fault."
        checks = [] if st == "sensor_fault" else [{"ref": "S1", "claim": "status %s" % st, "verdict": "corrected",
                                                   "fact": "flat run %s points on a meter confirmed faulty before" % p1["flat"], "src": ["S1.E8"]}]
    elif memkind == "unconfirmed":
        P2["memory"] = mem(R, sc, nd["em"][0], "Possible sensor fault", R.choice(["false_alarm", "no_action_needed", "resolved_on_its_own"]))
        rc += " An earlier 'possible sensor fault' on this meter was never confirmed (closed without repair), so it is no evidence."
    r = rep(title, sev, label, rc, chain, obs, checks, ["power", "occupancy"], ["S1"], ev_of(obs), conf, cl, "Power once the room is occupied", expl, nmd)
    return X(sensors=[s1, s2], report=r, root_metric="power_kw", rtype="pair_relation", hops=0, think=None,
             fam="p2_flat_alone" + ("_" + memkind if memkind else ""), outdoor=None, ctx=("Room power flat: %s" % nd["place"], "warning", title, sev))


def f_flat_mem(R, sc, nd):
    return f_flat_alone(R, sc, nd, R.choice(["confirmed_fault", "unconfirmed", "unconfirmed"]))


def f_step_real(R, sc, nd, memreal=False):
    """instant step in room power with an AC start at the same time: real load step, whatever the agent said"""
    at = R.randrange(10, 38)
    base = R.uniform(0.35, 0.9)
    xs = M.step(R, at, base, base + R.uniform(1.0, 2.2), 0.02, 2)
    ac = [0] * at + [R.choice([1, 2])] * (48 - at)
    st = R.choice(["sensor_fault", "sensor_fault", "warning"])

    def ag_p(s):
        p = P(s)
        if st == "sensor_fault":
            return ag("step_increase", "sensor_fault", "sensor_fault", 0.8, ["Power jumped %s kW at %s [E5]" % (p["jump"], p["jump_t"])])
        return ag("step_increase", "warning", "load_step", 0.8, ["Power stepped up %s kW at %s [E5,E1]" % (p["jump"].lstrip("+"), p["jump_t"])])
    s1 = S("S1", "power", "power_kw", nd["em"][0], nd["em"][1], xs, True, agent=ag_p)
    s2 = S("S2", "hvac", "ac_units_on", nd["ac"][0], nd["ac"][1], ac, False, "AC response", unit_shown="units",
           agent=lambda s: ag("step_increase", "normal", "hvac_context", 0.8, ["AC units running: now %s [E1,E4]" % P(s)["last"]]))
    p1, p2 = P(s1), P(s2)
    obs = [ob("Room power stepped up %s kW at %s" % (p1["jump"].lstrip("+"), p1["jump_t"]), ["S1.E5"]), ob("Room power now %s kW" % p1["last"], ["S1.E1"]),
           ob("AC units running now %s, started with the step" % p2["last"], ["S2.E1", "S2.E4"])]
    checks = []
    if st == "sensor_fault":
        checks.append({"ref": "S1", "claim": "sensor_fault", "verdict": "corrected",
                       "fact": "an instant step alone is not a fault: the AC units started at the same time", "src": ["S1.E5", "S2.E1"]})
    ps = "S1 (%s)" % nd["em"][0]
    conf = round(R.uniform(0.75, 0.88), 2)
    rc = "The AC units started and the room power stepped up at the same time: a real load step, not a bad meter."
    if memreal:
        P2["memory"] = mem(R, sc, nd["em"][0], "Load step after AC start", "fixed_by_action")
        rc += " A past step on this meter was confirmed real and fixed."
        conf = round(R.uniform(0.82, 0.92), 2)
    title = R.choice(["Room load step of %s kW after the AC start: %s" % (p1["jump"].lstrip("+"), nd["place"]), "AC start raised the room power to %s kW: %s" % (p1["last"], nd["place"])])
    r = rep(title, "warning", "power_load_anomaly", rc, "AC units started (S2.E1) -> room power stepped up (S1.E5)", obs, checks, ["power", "hvac"], [], ev_of(obs), conf,
            [("inspect_electrical", ps, "Confirm the new AC load is expected"), ("monitor", ps, "Power should stay at the new level")],
            "Power with the AC running", "An instant step plus a matching AC start is a real event.")
    return X(sensors=[s1, s2], report=r, root_metric="power_kw", rtype="pair_relation", hops=1, think=None, fam="p2_step_real" + ("_mem" if memreal else ""),
             outdoor=None, ctx=("Room power step: %s" % nd["place"], "warning", title, "warning"))


def f_step_real_mem(R, sc, nd):
    return f_step_real(R, sc, nd, True)


def f_plateau_real(R, sc, nd):
    """CO2 rises with people then levels off (plateau at max): real warning, agent may say sensor_fault"""
    end = sc["end"]
    on = R.randrange(4, 14)
    top = R.uniform(1060, 1450)
    ramp = M.ramp(R, on, R.uniform(420, 520), top, 6, 0, n=144)
    k = 144 - R.randrange(16, 28)
    xs = ramp[:k] + [round(top + R.gauss(0, 3)) for _ in range(144 - k)]
    st = R.choice(["sensor_fault", "warning", "warning"])

    def ag_c(s):
        p = P(s)
        if st == "sensor_fault":
            return ag("flatline", "sensor_fault", "sensor_fault", 0.75, ["CO2 plateau at %s ppm [E8]" % p["last"]])
        return ag("gradual_increase", "warning", "occupancy_load", 0.8, ["CO2 at %s ppm, over the warning limit [E1]" % p["last"]])
    s1 = S("S1", "air_quality", "co2", nd["aq"][0], nd["aq"][1], xs, True, agent=ag_c, head=[M.LIM["co2"]])
    s2 = M.occ_sensor("S2", nd["occ"], end, on)
    p1, p2 = P(s1), P(s2)
    if M.sev_hi(float(p1["last"]), 1000, 1500) != "warning":
        return None
    obs = [ob("CO2 now %s ppm, over the warning limit" % p1["last"], ["S1.E1"]), ob("CO2 levels off near the top (plateau at max)", ["S1.E8"]), M.o_occ(s2)]
    checks = []
    if st == "sensor_fault":
        checks.append({"ref": "S1", "claim": "sensor_fault", "verdict": "corrected",
                       "fact": "the plateau follows a smooth rise after the arrival and the room is occupied", "src": ["S1.E8", "S2.E1"]})
    pa = "S1 (%s)" % nd["aq"][0]
    r = rep("CO2 %s ppm with people, levelling off: %s" % (p1["last"], nd["place"]), "warning", "occupancy_driven_load",
            "People raised the CO2; it levels off near %s ppm while the room stays occupied. A plateau alone is not a sensor fault." % p1["last"],
            "arrival at %s (S2.E4) -> CO2 up then plateau (S1.E8)" % p2["first_on"], obs, checks, ["air_quality", "occupancy"], [], ev_of(obs), round(R.uniform(0.78, 0.9), 2),
            [("inspect_ventilation", pa, "Fresh-air supply is not keeping up with the people"), ("monitor", pa, "Falls once the room empties")],
            "CO2 after more ventilation", "A plateau with people present is the room reaching its balance.")
    return X(sensors=[s1, s2], report=r, root_metric="co2", rtype="pair_relation", hops=1, think=None, fam="p2_plateau_real", outdoor=None,
             ctx=("CO2 rising: %s" % nd["place"], "warning", r["title"], "warning"))


def f_fault_2nd(R, sc, nd):
    end = sc["end"]
    kind = R.choice(["impossible", "frozen_ac", "jump_neighbour"])
    st = R.choice(["sensor_fault", "sensor_fault", "normal", "warning"])
    cause = "sensor_fault" if st == "sensor_fault" else "normal_conditions"
    if kind == "impossible":
        xs = M.noise(R, 144, R.uniform(1.4, 3.2), 0.05, 2)
        xs = xs[:140] + [round(-R.uniform(0.5, 5.0), 2) for _ in range(4)]
        s1 = S("S1", "power", "power_kw", nd["em"][0], nd["em"][1], xs, True,
               agent=lambda s: ag("dropout", st, cause, 0.8, ["Power now %s kW [E1]" % P(s)["last"]]))
        sens = [s1, M.occ_sensor("S2", nd["occ"], end, R.randrange(2, 20))]
        p1 = P(s1)
        ev1, sid, second, met, nb = "Room power %s kW is below zero, impossible for a meter" % p1["last"], ["S1.E1"], "negative power is physically impossible and the room is occupied", "power_kw", ["S2.E1"]
        o2 = "Room occupied while the meter reads below zero"
    elif kind == "frozen_ac":
        xs = M.noise(R, 96, R.uniform(24, 26), 0.15, 2)
        xs = xs + [xs[-1]] * 48
        s1 = S("S1", "air_quality", "temp", nd["aq"][0], nd["aq"][1], xs, True, head=[M.LIM["temp"]],
               agent=lambda s: ag("flatline", st, cause, 0.75, ["Temperature flat at %s C [E1,E8]" % P(s)["last"]]))
        a0 = R.choice([1, 2])
        s2 = S("S2", "hvac", "ac_units_on", nd["ac"][0], nd["ac"][1], [a0] * 20 + [a0 + 2] * 28, False, "AC response", unit_shown="units",
               agent=lambda s: ag("step_increase", "normal", "hvac_context", 0.8, ["AC units running: now %s [E1,E4]" % P(s)["last"]]))
        sens = [s1, s2, M.occ_sensor("S3", nd["occ"], end, R.randrange(2, 12))]
        p1 = P(s1)
        ev1, sid, met, nb = "Room temperature frozen at %s C, flat run %s points" % (p1["last"], p1["flat"]), ["S1.E8"], "temp", ["S2.E1", "S3.E4"]
        second = "AC units rose and people arrived yet the temperature did not move, after normal variation earlier"
        o2 = "AC units rose and people arrived, temperature unchanged"
    else:
        hist = M.noise(R, 144, R.uniform(24, 26), 0.1, 1)
        jt = R.randrange(100, 136)
        off = R.uniform(8.0, 13.0)
        xs = [M.r1(v + (off if i >= jt else 0), 1) for i, v in enumerate(hist)]
        s1 = S("S1", "air_quality", "temp", nd["aq"][0], nd["aq"][1], xs, True, head=[M.LIM["temp"]],
               agent=lambda s: ag("step_increase", st, cause, 0.75, ["Temperature jumped %s C at %s [E5]" % (P(s)["jump"], P(s)["jump_t"])]))
        s2 = S("S2", "air_quality", "temp", nd["aq"][0], nd["aq"][1], hist, False, "second temperature sensor in the room", agent=M.steady_ag("Temperature"))
        s3 = S("S3", "hvac", "ac_units_on", nd["ac"][0], nd["ac"][1], [R.choice([1, 2])] * 48, False, "AC response", unit_shown="units",
               agent=lambda s: ag("stable", "normal", "hvac_context", 0.8, ["AC units running: now %s [E1,E4]" % P(s)["last"]]))
        sens = [s1, s2, s3]
        p1 = P(s1)
        ev1, sid, met, nb = "Room temperature jumped %s C within 5 minutes at %s" % (p1["jump"].lstrip("+"), p1["jump_t"]), ["S1.E5"], "temp", ["S2.E1", "S3.E1"]
        second = "the second sensor in the same room stays steady at %s C and the AC units did not change" % P(s2)["last"]
        o2 = "Second room sensor steady, AC units unchanged"
    obs = [ob(ev1, sid), ob(o2, nb)]
    checks = []
    if st != "sensor_fault":
        checks.append({"ref": "S1", "claim": "status %s" % st, "verdict": "corrected", "fact": second, "src": sid + nb[:1]})
    ps = "S1 (%s)" % sens[0]["node"]
    w = {"power_kw": "power", "temp": "temperature"}[met]
    r = rep(R.choice(["Sensor fault: %s reading not credible: %s" % (w, nd["place"]), "Faulty %s sensor (%s): %s" % (w, kind.replace("_", " "), nd["place"])]),
            "sensor_fault", "sensor_fault", "The reading is a sensor fault: %s." % second, "%s (%s) and %s: sensor fault" % (w, sid[0], second[:70]), obs, checks,
            ["power" if met == "power_kw" else "air_quality"], ["S1"], ev_of(obs), round(R.uniform(0.82, 0.92), 2),
            [("check_sensor", ps, "Reading disagrees with the room"), ("recalibrate_sensor", ps, "Compare with a reference")], "Reading after the sensor check",
            "A second kind of evidence confirms it: %s." % second)
    return X(sensors=sens, report=r, root_metric=met, rtype="pair_relation", hops=1, think=None, fam="p2_fault_2nd:" + kind, outdoor=None,
             ctx=("Suspect reading: %s" % nd["place"], "warning", r["title"], "sensor_fault"))


def f_batch(R, sc, nd, nd2, late=False):
    """(d,e) combined-cause pair (people -> CO2 + room temperature) + a separate unrelated PM2.5 rise in another building; late = the PM
    sensor turns abnormal only late in the window (promoted)"""
    end = sc["end"]
    on = R.randrange(4, 16)
    which = R.choice(["critical", "warning"])
    top = R.uniform(1530, 1900) if which == "critical" else R.uniform(1040, 1450)
    co2 = M.ramp(R, on + 1, R.uniform(420, 520), top, 6, 0)
    if M.sev_hi(co2[-1], 1000, 1500) != which:
        return None
    tt = M.ramp(R, on + 2, R.uniform(24, 25.5), R.uniform(30.5, 33.5), 0.08, 1)
    s1 = S("S1", "air_quality", "co2", nd["aq"][0], nd["aq"][1], co2, True, head=[M.LIM["co2"]], agent=lambda s: M.trend_ag(s, which, "occupancy_load", word="CO2"))
    s2 = S("S2", "air_quality", "temp", nd["aq"][0], nd["aq"][1], tt, True, head=[M.LIM["temp"]],
           agent=lambda s: M.trend_ag(s, M.sev_hi(float(P(s)["last"]), 30, 34), "high_heat_load", word="Temperature"))
    s3 = M.occ_sensor("S3", nd["occ"], end, on)
    pon = R.randrange(34, 44) if late else R.randrange(6, 28)
    pm = M.ramp(R, pon, R.uniform(10, 24), R.uniform(70, 140), 1.0, 1)
    s4 = S("S4", "air_quality", "pm25", nd2["aq"][0], nd2["aq"][1], pm, True, head=[M.LIM["pm25"]],
           agent=lambda s: M.trend_ag(s, M.sev_hi(float(P(s)["last"]), 60, 120), "indoor_emission_source", word="PM2.5"))
    p1, p2, p3, p4 = P(s1), P(s2), P(s3), P(s4)
    sv2, sv4 = M.sev_hi(float(p2["last"]), 30, 34), M.sev_hi(float(p4["last"]), 60, 120)
    if sv2 == "normal" or sv4 == "normal":
        return None
    sev = M.worst(which, sv2, sv4)
    obs = [M.o_tr(s1, "CO2"), M.o_tr(s2, "Room temperature"), M.o_occ(s3), M.o_tr(s4, "PM2.5 elsewhere")]
    acts = [M.cl("inspect_ventilation", s1, "Fresh-air supply is not keeping up with the people"), M.cl("inspect_hvac", s2, "Room warming with the crowd"),
            M.cl("inspect_ventilation", s4, "Separate PM2.5 source in the other building")]
    if sev == "critical":
        acts.append(M.cl("request_facility_review", s1 if which == "critical" else s4, "Beyond the critical limit"))
    late_txt = " The PM2.5 sensor turned abnormal late in the window (promoted)." if late else ""
    r = rep("People raise CO2 %s ppm and temperature; separate PM2.5 rise: %s" % (p1["last"], nd["place"]), sev, "occupancy_driven_load",
            "Two separate events: people in the room raise CO2 and the room temperature together (S1, S2); the PM2.5 rise in another building (S4) has its own source.%s" % late_txt,
            "arrival at %s (S3.E4) -> CO2 up (S1.E4) and temperature up (S2.E4); separately PM2.5 up (S4.E4)" % p3["first_on"], obs, [],
            ["air_quality", "occupancy"], [], ev_of(obs), round(R.uniform(0.78, 0.9), 2), acts[:5], "Each sensor at the next re-check",
            "Report each: S1 and S2 (people, %s and %s), S4 on its own (%s)." % (which, sv2, sv4))
    link = "S1 and S2 follow the arrival in S3: one cause, people. S4 is another building with no link: its own event."
    root = "Two events, report both; severity is the worst of the three."
    return X(sensors=[s1, s2, s3, s4], report=r, root_metric="co2", rtype="pair_relation", hops=1, think=(link, root), fam="p2_batch" + ("_late" if late else ""),
             outdoor=None, ctx=("CO2 rising: %s" % nd["place"], which, r["title"], sev))


def install_p2():
    if any(f[0] == "p2_batch" for f in M.FAMS):
        return
    G2.mk_row = _mk
    fns = {"p2_flat_alone": lambda R, sc, nd, nd2: f_flat_alone(R, sc, nd), "p2_flat_mem": lambda R, sc, nd, nd2: f_flat_mem(R, sc, nd),
           "p2_step_real": lambda R, sc, nd, nd2: f_step_real(R, sc, nd), "p2_step_real_mem": lambda R, sc, nd, nd2: f_step_real_mem(R, sc, nd),
           "p2_plateau_real": lambda R, sc, nd, nd2: f_plateau_real(R, sc, nd), "p2_fault_2nd": lambda R, sc, nd, nd2: f_fault_2nd(R, sc, nd),
           "p2_batch": lambda R, sc, nd, nd2: f_batch(R, sc, nd, nd2), "p2_batch_late": lambda R, sc, nd, nd2: f_batch(R, sc, nd, nd2, True)}
    for name in NAMES:
        def wrap(R, sc, nd, nd2, fn=fns[name]):
            P2["memory"] = None
            return fn(R, sc, nd, nd2)
        M.FAMS.append((name, wrap, 0.0))
        M.RT_OF[name] = "pair_relation"
