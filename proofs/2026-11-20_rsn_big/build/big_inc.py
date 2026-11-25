"""big_inc.py: reasoner big run, block B (holes) incident families on the p2 pipeline (r4-style family functions, same helpers as
v2_gen_p2.py; rows go through the same full_check / dedup as every earlier build).
Contrastive severity quadruples (hole 1, HOLES.md): per family the SAME window shape (same arrival time, base level, noise stream)
is rendered 4 times with a different deciding evidence: normal (benign, under the card limit) / warning / critical / sensor_fault
(impossible value or a jump the neighbour sensor does not share). Consecutive family calls cycle the variant (BIG state).
  big_co2   CO2 with people (+ occupancy sensor)          normal 850-985 | warning 1060-1450 | critical 1560-1900 | fault: reads below card 'impossible'
  big_pm    indoor PM2.5, outdoor steady, room occupancy  normal 34-57   | warning 65-115    | critical 125-210   | fault: one-sample step, clean outdoor, empty room
  big_temp  room temperature + AC units + occupancy       normal 27.4-29.6| warning 30.8-33.4 | critical 34.6-38   | fault: jump, 2nd room sensor steady
  big_benign  normals that look busy: two occupied rooms under limit; AC cycling with steady temperature
Agent claim: right 60% / adjacent wrong 40% (corrected in agent_checks), like the p2 families."""
import os
import random
import sys

RSN = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn"
sys.path.insert(0, RSN)
import v2_gen as X0  # noqa: E402
import v2_gen_p2 as P2  # noqa: E402

M, G2 = X0.M, X0.G2
P, ag, ob, rep, ev_of, S, X = M.P, M.ag, M.ob, M.rep, M.ev_of, M.S, M.X
BIG = {"i": 0, "seed": 0, "variant": "normal"}
VARS = ["normal", "warning", "critical", "sensor_fault"]
ADJ = {"normal": ["warning", "sensor_fault"], "warning": ["normal", "critical", "sensor_fault"], "critical": ["warning", "sensor_fault"],
       "sensor_fault": ["warning", "normal"]}
NAMES = {"big_co2": 800, "big_pm": 600, "big_temp": 600, "big_benign": 300}


def _next(R):
    if BIG["i"] % 4 == 0:
        BIG["seed"] = R.randrange(10 ** 9)
    BIG["variant"] = VARS[BIG["i"] % 4]
    BIG["i"] += 1
    return random.Random(BIG["seed"]), BIG["variant"]


def _agent(R, gold, word, last, jump=None):
    """(status, cause, claim_wrong) of the domain agent for this row"""
    if R.random() < 0.6:
        return gold, None
    return R.choice(ADJ[gold]), True


def _check(ref, wrong_st, gold, fact, src):
    if not wrong_st or wrong_st == gold:
        return []
    return [{"ref": ref, "claim": "status %s" % wrong_st, "verdict": "corrected", "fact": fact, "src": src}]


def f_co2(R, sc, nd, nd2=None):
    Rs, var = _next(R)
    end = sc["end"]
    on = Rs.randrange(4, 22)
    base = Rs.uniform(420, 520)
    top = {"normal": R.uniform(850, 985), "warning": R.uniform(1060, 1450), "critical": R.uniform(1560, 1900), "sensor_fault": R.uniform(1100, 1500)}[var]
    co2 = M.ramp(Rs, on + 1, base, top, 6, 0)
    if var == "sensor_fault":   # the sensor stops following the people: reads far below the card's possible range after the arrival
        k = 144 - Rs.randrange(18, 34)
        co2 = co2[:k] + [round(R.uniform(60, 240) + R.gauss(0, 4)) for _ in range(144 - k)]
    elif M.sev_hi(co2[-1], 1000, 1500) != var:
        return None
    wrong = _agent(R, var, "CO2", co2[-1])
    st = wrong[0]

    def ag_c(s):
        p = P(s)
        cause = "sensor_fault" if st == "sensor_fault" else ("occupancy_load" if st != "normal" else "normal_conditions")
        pat = "flatline" if st == "sensor_fault" else "gradual_increase"
        return ag(pat, st, cause, round(R.uniform(0.7, 0.9), 2), ["CO2 now %s ppm, trend %s ppm/h [E1,E4]" % (p["last"], p["slope"])])
    s1 = S("S1", "air_quality", "co2", nd["aq"][0], nd["aq"][1], co2, True, head=[M.LIM["co2"]], agent=ag_c)
    s2 = M.occ_sensor("S2", nd["occ"], end, on)
    p1, p2 = P(s1), P(s2)
    pa = "S1 (%s)" % nd["aq"][0]
    if var == "sensor_fault":
        obs = [ob("CO2 reads %s ppm, below the card's possible range" % p1["last"], ["S1.E1"]), ob("Room occupied since %s while CO2 should rise" % p2["first_on"], ["S2.E4", "S2.E1"])]
        chk = _check("S1", st, var, "a reading of %s ppm is impossible for this sensor while the room is occupied" % p1["last"], ["S1.E1", "S2.E1"])
        r = rep(R.choice(["Sensor fault: CO2 reads %s ppm in an occupied room: %s" % (p1["last"], nd["place"]), "CO2 sensor reading not credible (%s ppm): %s" % (p1["last"], nd["place"])]),
                "sensor_fault", "sensor_fault", "The CO2 reading of %s ppm is below the sensor's possible range while people are in the room: a sensor fault, not clean air." % p1["last"],
                "occupied room (S2.E1) but CO2 %s ppm (S1.E1) below the possible range -> sensor fault" % p1["last"], obs, chk, ["air_quality"], ["S1"], ev_of(obs),
                round(R.uniform(0.8, 0.9), 2), [("check_sensor", pa, "Reading is impossible with people present"), ("recalibrate_sensor", pa, "Compare with a reference")],
                "Reading after the sensor check", "The value is below what the sensor can truly read, with people present: treat as a sensor fault.")
        sevf = "sensor_fault"
    else:
        obs = [M.o_tr(s1, "CO2"), M.o_now(s1, "CO2"), M.o_occ(s2)]
        chk = _check("S1", st, var, "CO2 %s ppm is %s the %s limit and follows the arrival at %s" % (
            p1["last"], "under" if var == "normal" else "over", {"normal": "1000 ppm warning", "warning": "1000 ppm warning", "critical": "1500 ppm critical"}[var], p2["first_on"]), ["S1.E1", "S2.E4"])
        lim = {"normal": "stays under the 1000 ppm warning limit", "warning": "is over the 1000 ppm warning limit, under 1500", "critical": "is over the 1500 ppm critical limit"}[var]
        title = {"normal": "CO2 %s ppm with people, under the limit: %s", "warning": "CO2 %s ppm with people, over the warning limit: %s",
                 "critical": "CO2 %s ppm with people, over the critical limit: %s"}[var] % (p1["last"], nd["place"])
        clist = [M.cl("monitor", s1, "Watch whether CO2 nears 1000 ppm")] if var == "normal" else [M.cl("inspect_ventilation", s1, "Fresh-air supply is not keeping up with the people")]
        if var == "critical":
            clist.append(M.cl("request_facility_review", s1, "CO2 beyond the critical limit"))
        r = rep(title, var, "occupancy_driven_load", "People arrived at %s and raised the CO2, which now %s (%s ppm)." % (p2["first_on"], lim, p1["last"]),
                "arrival at %s (S2.E4) -> CO2 up to %s ppm (S1.E1)" % (p2["first_on"], p1["last"]), obs, chk, ["air_quality", "occupancy"], [], ev_of(obs),
                round(R.uniform(0.8, 0.92), 2), clist, "CO2 as the occupancy changes",
                {"normal": "Normal for an occupied room: CO2 follows the people and stays under the limit.", "warning": "The room filled up and CO2 passed the warning limit; ventilate.",
                 "critical": "CO2 passed the critical limit with people present; ventilate and review now."}[var])
        sevf = var
    return X(sensors=[s1, s2], report=r, root_metric="co2", rtype="pair_relation", hops=1, think=None, fam="big_co2:" + var, outdoor=None,
             ctx=("CO2 rising: %s" % nd["place"], st if st != sevf else R.choice(ADJ[sevf]), r["title"], sevf))


def f_pm(R, sc, nd, nd2=None):
    Rs, var = _next(R)
    end = sc["end"]
    no, lo = nd["out"]
    ni, li = nd["aq"]
    out = M.noise(Rs, 144, Rs.uniform(14, 34), 1.0, 1, 1)
    if var == "sensor_fault":
        base = Rs.uniform(14, 32)
        jt = Rs.randrange(100, 140)
        ind = [M.r1(v + (R.uniform(90, 210) if i >= jt else 0), 1) for i, v in enumerate(M.noise(Rs, 144, base, 1.0, 1, 1))]
    else:
        top = {"normal": R.uniform(34, 57), "warning": R.uniform(66, 114), "critical": R.uniform(126, 210), "sensor_fault": 0}[var]
        ind = M.ramp(Rs, Rs.randrange(6, 30), Rs.uniform(12, 26), top, 1.0, 1, lo=1)
        if M.sev_hi(ind[-1], 60, 120) != var:
            return None
    st, wrong = _agent(R, var, "PM2.5", ind[-1])
    s1 = S("S1", "air_quality", "pm25", ni, li, ind, True, head=[M.LIM["pm25"]],
           agent=lambda s: ag("step_increase" if var == "sensor_fault" else "gradual_increase", st, "sensor_fault" if st == "sensor_fault" else "air_pollution_event",
                              round(R.uniform(0.7, 0.9), 2), ["PM2.5 now %s ug/m3 [E1]" % P(s)["last"]]))
    s2 = S("S2", "air_quality", "pm25", no, lo, out, False, "outdoor air at the same building", agent=M.steady_ag("PM2.5"))
    s3 = M.occ_sensor("S3", nd["occ"], end, None)
    p1, p2 = P(s1), P(s2)
    t = "S1 (%s)" % ni
    if var == "sensor_fault":
        obs = [M.o_jump(s1, "Indoor PM2.5"), M.o_now(s1, "Indoor PM2.5"), ob("Outdoor PM2.5 steady around %s ug/m3" % p2["last"], ["S2.E1", "S2.E4"]), ob("Nobody in the room", ["S3.E2", "S3.E1"])]
        chk = _check("S1", st, var, "a %s ug/m3 step in one sample with clean outdoor air and an empty room" % p1["jump"].lstrip("+"), ["S1.E5", "S2.E1", "S3.E2"])
        r = rep("Indoor PM2.5 offset after a step: %s" % nd["place"], "sensor_fault", "sensor_fault",
                "Indoor PM2.5 stepped up in one sample with clean outdoor air and nobody inside: a sensor offset, not pollution.",
                "%s ug/m3 step (S1.E5), outdoor steady (S2.E1), room empty (S3.E2) -> sensor offset" % p1["jump"].lstrip("+"), obs, chk, ["air_quality"], ["S1"], ev_of(obs),
                round(R.uniform(0.8, 0.9), 2), [("check_sensor", t, "Clean the inlet, check for a local dust source"), ("recalibrate_sensor", t, "Compare with a reference monitor")],
                "Reading after the sensor check", "Clean outdoor air and an empty room do not explain the step: a sensor fault.")
        sevf = "sensor_fault"
    else:
        obs = [M.o_tr(s1, "Indoor PM2.5"), M.o_now(s1, "Indoor PM2.5"), ob("Outdoor PM2.5 steady around %s ug/m3" % p2["last"], ["S2.E1", "S2.E4"]), ob("Nobody in the room", ["S3.E2", "S3.E1"])]
        chk = _check("S1", st, var, "PM2.5 %s ug/m3 is %s the %s limit, rising smoothly with clean outdoor air" % (p1["last"], "under" if var == "normal" else "over", "60 ug/m3 warning" if var != "critical" else "120 ug/m3 critical"), ["S1.E1", "S2.E1"])
        lim = {"normal": "stays under the 60 ug/m3 warning limit", "warning": "is over the 60 ug/m3 warning limit, under 120", "critical": "is over the 120 ug/m3 critical limit"}[var]
        title = {"normal": "Indoor PM2.5 %s ug/m3, slightly up, under the limit: %s", "warning": "Indoor PM2.5 %s ug/m3 over the warning limit: %s",
                 "critical": "Indoor PM2.5 %s ug/m3 over the critical limit: %s"}[var] % (p1["last"], nd["place"])
        clist = [M.cl("monitor", s1, "Watch whether PM2.5 nears 60 ug/m3")] if var == "normal" else [M.cl("inspect_ventilation", s1, "Look for an indoor dust or smoke source")]
        if var == "critical":
            clist.append(M.cl("request_facility_review", s1, "PM2.5 beyond the critical limit"))
        r = rep(title, var, "normal_operation" if var == "normal" else "air_pollution_event",
                "Indoor PM2.5 %s (%s ug/m3) while outdoor air stays clean and the room is empty: an indoor source." % (lim, p1["last"]) if var != "normal" else
                "Indoor PM2.5 is a little above its base but %s (%s ug/m3); outdoor air is clean and nothing else moved." % (lim, p1["last"]),
                "indoor PM2.5 up to %s ug/m3 (S1.E1), outdoor steady (S2.E1), room empty (S3.E2)" % p1["last"], obs, chk, ["air_quality"], [], ev_of(obs),
                round(R.uniform(0.78, 0.9), 2), clist, "PM2.5 at the next re-check",
                {"normal": "Under the limit: keep watching.", "warning": "Indoor PM2.5 passed the warning limit; look for the source.", "critical": "Indoor PM2.5 passed the critical limit; act now."}[var])
        sevf = var
    return X(sensors=[s1, s2, s3], report=r, root_metric="pm25", rtype="pair_relation", hops=1, think=None, fam="big_pm:" + var, outdoor=None,
             ctx=("PM2.5 up: %s" % nd["place"], st if st != sevf else R.choice(ADJ[sevf]), r["title"], sevf))


def f_temp(R, sc, nd, nd2=None):
    Rs, var = _next(R)
    end = sc["end"]
    on = Rs.randrange(4, 24)
    b0 = Rs.uniform(23.0, 25.2)
    if var == "sensor_fault":
        hist = M.noise(Rs, 144, b0, 0.1, 1)
        jt = Rs.randrange(100, 136)
        off = R.uniform(8.0, 13.0)
        xs = [M.r1(v + (off if i >= jt else 0), 1) for i, v in enumerate(hist)]
    else:
        top = {"normal": R.uniform(27.4, 29.6), "warning": R.uniform(30.8, 33.4), "critical": R.uniform(34.6, 38.0), "sensor_fault": 0}[var]
        xs = M.ramp(Rs, on + 2, b0, top, 0.08, 1, shape="lin")
        if M.sev_hi(xs[-1], 30, 34) != var:
            return None
    st, wrong = _agent(R, var, "Temperature", xs[-1])
    s1 = S("S1", "air_quality", "temp", nd["aq"][0], nd["aq"][1], xs, True, head=[M.LIM["temp"]],
           agent=lambda s: ag("step_increase" if var == "sensor_fault" else "gradual_increase", st, "sensor_fault" if st == "sensor_fault" else "high_heat_load",
                              round(R.uniform(0.7, 0.9), 2), ["Temperature now %s C, trend %s C/h [E1,E4]" % (P(s)["last"], P(s)["slope"])]))
    ac0 = R.choice([1, 2])
    s2 = S("S2", "hvac", "ac_units_on", nd["ac"][0], nd["ac"][1], [ac0] * 48, False, "AC response", unit_shown="units",
           agent=lambda s: ag("stable", "normal", "hvac_context", 0.8, ["AC units running: now %s [E1,E4]" % P(s)["last"]]))
    p1, p2 = P(s1), P(s2)
    sens = [s1, s2]
    t = "S1 (%s)" % nd["aq"][0]
    if var == "sensor_fault":
        s3 = S("S3", "air_quality", "temp", nd["aq"][0], nd["aq"][1], hist, False, "second temperature sensor in the room", agent=M.steady_ag("Temperature"))
        sens.append(s3)
        p3 = P(s3)
        obs = [M.o_jump(s1, "Room temperature"), ob("Second room sensor steady at %s C" % p3["last"], ["S3.E1", "S3.E4"]), ob("AC units unchanged at %s" % p2["last"], ["S2.E1"])]
        chk = _check("S1", st, var, "a %s C jump in 5 minutes that the second sensor and the AC units do not share" % p1["jump"].lstrip("+"), ["S1.E5", "S3.E1"])
        r = rep("Room temperature jump not seen by the second sensor: %s" % nd["place"], "sensor_fault", "sensor_fault",
                "The room temperature jumped %s C in 5 minutes while the second sensor in the same room and the AC units show nothing: a sensor fault." % p1["jump"].lstrip("+"),
                "%s C jump (S1.E5), second sensor steady (S3.E1), AC unchanged (S2.E1) -> sensor fault" % p1["jump"].lstrip("+"), obs, chk, ["air_quality"], ["S1"], ev_of(obs),
                round(R.uniform(0.8, 0.9), 2), [("check_sensor", t, "Reading disagrees with the room"), ("recalibrate_sensor", t, "Compare with a reference thermometer")],
                "Reading after the sensor check", "A second sensor in the room disagrees: sensor fault.")
        sevf = "sensor_fault"
    else:
        s3 = M.occ_sensor("S3", nd["occ"], end, on)
        sens.append(s3)
        p3 = P(s3)
        obs = [M.o_tr(s1, "Room temperature"), M.o_now(s1, "Room temperature"), M.o_occ(s3)]
        chk = _check("S1", st, var, "Room temperature %s C is %s the %s limit and follows the arrival at %s" % (
            p1["last"], "under" if var == "normal" else "over", "30 C warning" if var != "critical" else "34 C critical", p3["first_on"]), ["S1.E1", "S3.E4"])
        lim = {"normal": "stays under the 30 C warning limit", "warning": "is over the 30 C warning limit, under 34", "critical": "is over the 34 C critical limit"}[var]
        title = {"normal": "Room temperature %s C with people, under the limit: %s", "warning": "Room temperature %s C, over the warning limit: %s",
                 "critical": "Room temperature %s C, over the critical limit: %s"}[var] % (p1["last"], nd["place"])
        clist = [M.cl("monitor", s1, "Watch whether the room nears 30 C")] if var == "normal" else [M.cl("inspect_hvac", s1, "Room warming with the crowd")]
        if var == "critical":
            clist.append(M.cl("request_facility_review", s1, "Temperature beyond the critical limit"))
        r = rep(title, var, "normal_operation" if var == "normal" else "hvac_or_thermal_issue",
                "People arrived at %s and warm the room, which now %s (%s C); the AC units are running." % (p3["first_on"], lim, p1["last"]),
                "arrival at %s (S3.E4) -> room temperature up to %s C (S1.E1)" % (p3["first_on"], p1["last"]), obs, chk, ["air_quality", "occupancy"], [], ev_of(obs),
                round(R.uniform(0.78, 0.9), 2), clist, "Room temperature as the occupancy changes",
                {"normal": "Normal for an occupied room: warmth follows the people and stays under the limit.", "warning": "The room passed the warning limit with people in it; check the AC.",
                 "critical": "The room passed the critical limit; check the AC and review now."}[var])
        sevf = var
    return X(sensors=sens, report=r, root_metric="temp", rtype="pair_relation", hops=1, think=None, fam="big_temp:" + var, outdoor=None,
             ctx=("Room temperature up: %s" % nd["place"], st if st != sevf else R.choice(ADJ[sevf]), r["title"], sevf))


def f_benign(R, sc, nd, nd2):
    """normals that look busy: (a) two occupied rooms, CO2 up in both, each under the limit; (b) AC cycling, temperature steady"""
    end = sc["end"]
    if R.random() < 0.55:
        on1, on2 = R.randrange(4, 20), R.randrange(4, 20)
        c1 = M.ramp(R, on1 + 1, R.uniform(420, 520), R.uniform(800, 960), 6, 0)
        c2 = M.ramp(R, on2 + 1, R.uniform(420, 520), R.uniform(760, 940), 6, 0)
        st = R.choice(["warning", "normal", "normal"])
        s1 = S("S1", "air_quality", "co2", nd["aq"][0], nd["aq"][1], c1, True, head=[M.LIM["co2"]],
               agent=lambda s: ag("gradual_increase", st, "occupancy_load" if st != "normal" else "normal_conditions", 0.8, ["CO2 now %s ppm [E1,E4]" % P(s)["last"]]))
        s2 = S("S2", "air_quality", "co2", nd2["aq"][0], nd2["aq"][1], c2, True, head=[M.LIM["co2"]],
               agent=lambda s: ag("gradual_increase", "normal", "normal_conditions", 0.8, ["CO2 now %s ppm [E1,E4]" % P(s)["last"]]))
        s3 = M.occ_sensor("S3", nd["occ"], end, on1)
        s4 = M.occ_sensor("S4", nd2["occ"], end, on2)
        p1, p2, p3, p4 = P(s1), P(s2), P(s3), P(s4)
        obs = [M.o_now(s1, "CO2 in the first room"), M.o_now(s2, "CO2 in the second room"), M.o_occ(s3), ob("Second room occupied since %s" % p4["first_on"], ["S4.E4", "S4.E1"])]
        chk = []
        if st == "warning":
            chk.append({"ref": "S1", "claim": "status warning", "verdict": "corrected", "fact": "CO2 %s ppm is under the 1000 ppm warning limit and follows the arrival" % p1["last"], "src": ["S1.E1", "S3.E4"]})
        r = rep("Two occupied rooms, CO2 up but under the limit (%s and %s ppm)" % (p1["last"], p2["last"]), "normal", "occupancy_driven_load",
                "People in both rooms raise CO2 (%s and %s ppm); both stay under the 1000 ppm warning limit, so this is ordinary use." % (p1["last"], p2["last"]),
                "arrivals (S3.E4, S4.E4) -> CO2 up in both rooms (S1.E1, S2.E1), under the limit", obs, chk, ["air_quality", "occupancy"], [], ev_of(obs), round(R.uniform(0.8, 0.9), 2),
                [M.cl("monitor", s1, "Watch whether CO2 nears 1000 ppm")], "CO2 as the rooms empty", "Normal: two busy rooms, CO2 under the limit.")
        return X(sensors=[s1, s2, s3, s4], report=r, root_metric="co2", rtype="pair_relation", hops=1, think=None, fam="big_benign:two_rooms", outdoor=None,
                 ctx=("CO2 rising: %s" % nd["place"], "warning", r["title"], "normal"))
    xs = M.noise(R, 144, R.uniform(24.2, 26.0), 0.12, 1)
    a0, a1 = R.choice([1, 2]), R.choice([3, 4])
    cyc = [a0] * R.randrange(8, 20)
    while len(cyc) < 48:
        cyc += [a1] * R.randrange(6, 12) + [a0] * R.randrange(6, 12)
    st = R.choice(["warning", "normal", "normal"])
    s1 = S("S1", "air_quality", "temp", nd["aq"][0], nd["aq"][1], xs, True, head=[M.LIM["temp"]],
           agent=lambda s: ag("stable", st if st == "normal" else "warning", "normal_conditions", 0.75, ["Temperature steady around %s C [E1,E4]" % P(s)["last"]]))
    s2 = S("S2", "hvac", "ac_units_on", nd["ac"][0], nd["ac"][1], cyc[:48], True, "AC response", unit_shown="units",
           agent=lambda s: ag("oscillation", "warning" if st == "warning" else "normal", "hvac_cycling", 0.75, ["AC units switching between %s and %s [E7]" % (a0, a1)]))
    p1, p2 = P(s1), P(s2)
    obs = [ob("Room temperature steady around %s C" % p1["last"], ["S1.E1", "S1.E4"]), ob("AC units now %s, switching with the load" % p2["last"], ["S2.E1", "S2.E7"])]
    chk = [{"ref": "S2", "claim": "hvac_cycling warning", "verdict": "corrected", "fact": "the room temperature stays steady at %s C while the units switch: normal AC control" % p1["last"], "src": ["S1.E4", "S2.E7"]}] if st == "warning" else []
    r = rep("AC units cycling, room temperature steady at %s C: %s" % (p1["last"], nd["place"]), "normal", "normal_operation",
            "The AC units switch on and off to hold the room at %s C; the temperature barely moves, so this is normal control, not a fault." % p1["last"],
            "AC units switching (S2.E7), room temperature steady (S1.E4) -> normal control", obs, chk, ["air_quality", "hvac"], [], ev_of(obs), round(R.uniform(0.78, 0.9), 2),
            [M.cl("monitor", s2, "Watch whether the temperature starts to drift")], "Room temperature over the next hours", "Normal AC control: the room stays steady.")
    return X(sensors=[s1, s2], report=r, root_metric="temp", rtype="pair_relation", hops=0, think=("Room temperature S1 is steady while AC S2 cycles.", "Normal control."),
             fam="big_benign:ac_cycle", outdoor=None, ctx=("AC cycling: %s" % nd["place"], "warning", r["title"], "normal"))


def install_big():
    if any(f[0] == "big_co2" for f in M.FAMS):
        return
    P2.install_p2()
    fns = {"big_co2": f_co2, "big_pm": f_pm, "big_temp": f_temp, "big_benign": f_benign}
    for name, fn in fns.items():
        M.FAMS.append((name, fn, 0.0))
        M.RT_OF[name] = "pair_relation"
