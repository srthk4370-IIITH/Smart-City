"""rsn_v3 r2: targeted, synthetic, contrastive incident pairs for the classes the 2B r1 got wrong on the board and in the gate
(proofs/2026-11-02_2b_r2/DIAG.md). stdlib python3, CPU. Same renderer as the app (round-1 lib.render == RenderV3User),
app layout (LIMITS head line, outdoor CONTEXT, AC-<b><fl> hvac sensors, app-style MEMORY / RE-CHECK lines).

Each pair shares one scenario (building, room, time, related sensors) and differs in the physics:
  roomtemp  fault: indoor temperature jumps 10-20 C in one sample (or freezes high / spikes) while the AC's own room sensor,
                   power and outdoor stay ordinary -> sensor_fault, sensor action first
            real : AC units drop out, room temperature AND the AC room sensor climb together over 1-3 h -> warning/critical,
                   hvac_or_thermal_issue, inspect_hvac first
  ph        single: ONE bad sample (spike to 9.4-10.2 or 4.6-5.6) between ordinary readings, back to normal now -> sensor_fault,
                    check_sensor first (never critical)
            held : pH beyond the limit and STAYING there for >= 30 min (step or ramp) -> critical/warning, water_quality_issue,
                   inspect_water_system first (+ check_sensor later to confirm with a manual test); never sensor_fault
  co2       real : people arrive, CO2 climbs smoothly past 1000/1500 ppm with occupancy 1 -> warning/critical, occupancy-driven,
                   inspect_ventilation first
            bias : one-sample +200..+420 ppm step that stays, room empty -> sensor_fault, recalibrate/check first
            drift: occupied room, CO2 rises but stays below 1000 ppm -> normal (no false warning)
The domain agent is wrong in ~45 % of rows (says the opposite class); the gold corrects it in agent_checks.
Refinements (~35 % of rows): mode refine-1.5h / refine-3h with app-style RE-CHECK lines "HH:MM <severity>: <earlier title>"; the
earlier revision may be wrong (copied the agent) and the gold re-judges on the current evidence.
Names: building codes, floors and sensor numbers vary (train codes TRAIN_B; the test split also has unseen codes NOVEL_B).
Every row passes round-1 verify.py check_incident; the app's Go gate is run afterwards by go_gate.sh (build_r2.sh).

  python3 gen_r2_targeted.py --out DIR [--pairs 1500] [--seed 5101] [--test-pairs 150] [--test-seed 5202]
"""
import argparse
import collections
import datetime as dt
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
V3 = os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3")
R1 = os.path.join(QIDK, "proofs", "2026-10-25_reasoner_final")
sys.path.insert(0, os.path.join(R1, "pipeline"))
sys.path.insert(0, os.path.join(V3, "kaggle"))
sys.path.insert(0, os.path.join(V3, "pipeline"))
import lib as L  # noqa: E402
import textbank as T  # noqa: E402
import verify as V  # noqa: E402
from build_mix import fix  # noqa: E402
from prompts import SYSTEM_INCIDENT  # noqa: E402
from gen_incidents_v3 import compact_report  # noqa: E402
import gen_heat_r2 as H  # noqa: E402  (also registers hvac/ac_units_on in L.METRICS)

TRAIN_B = ["KH", "VN", "BK", "OB", "NB", "KN", "PB", "TH", "LB", "HB", "RC", "AB", "CB", "MB", "JC", "SH", "GH", "DB"]
NOVEL_B = ["QX", "ZR", "EL", "WD", "FY", "UV"]          # test only: building codes never seen in training
OPS = ["ravi", "meena", "arjun", "sana", "kiran", "divya"]
ASKS = ["Write the cross-domain incident report JSON."] * 4 + ["Produce the incident report for these findings."]
WE_NODE, WE_LOC = L.WEATHER
r1 = H.r1
P = H.P


def ob(text, src):
    return {"text": text, "src": src}


def ag(pattern, status, cause, conf, obs):
    return {"pattern": pattern, "status": status, "cause": cause, "conf": conf, "obs": obs}


def sensor(ref, role, metric, node, loc, xs, hist, end, flagged, why=None, agent=None, head=None, unit_shown=None):
    return H.sensor(ref, role, metric, node, loc, xs, hist, end, flagged, why=why, agent=agent, head=head, unit_shown=unit_shown)


def noise_series(R, n, level, nz, dec, lo=None, hi=None):
    out = []
    for _ in range(n):
        v = level + R.gauss(0, nz)
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        out.append(r1(v, dec))
    return out


def scen(R, i, novel=False):
    bl = NOVEL_B if novel else TRAIN_B
    month = R.choice(range(1, 13))
    d = dt.date(2026, month, R.randrange(1, 29))
    end = dt.datetime(d.year, d.month, d.day, R.choice(range(8, 20)), R.choice(range(0, 60, 5)), tzinfo=L.IST)
    return dict(i=i, end=end, b=R.choice(bl), fl=R.randrange(0, 7), k=R.randrange(1, 10), occ_k=R.randrange(1, 30),
                inc="INC-%04d" % R.randrange(100, 9999))


def evidence_of(obs, extra=()):
    ev = []
    for o in obs:
        for i in o["src"]:
            if i not in ev:
                ev.append(i)
    for i in extra:
        if i not in ev:
            ev.append(i)
    return ev[:6]


def rep(title, sev, label, rc, chain, obs, checks, domains, suspects, evidence, conf, cl, mon, expl, nmd=False):
    return {"title": title[:80], "severity": sev, "label": label, "root_cause": rc, "causal_chain": chain, "observations": obs[:5],
            "agent_checks": checks[:4], "affected_domains": domains, "suspect_sensors": suspects, "evidence": evidence,
            "confidence": conf, "checklist": [{"action": a, "target": t, "why": y} for a, t, y in cl[:5]], "monitor_next": mon,
            "needs_more_data": nmd, "needs_deeper": False, "explanation": expl}


# ---------------------------------------------------------------- related sensors (app layout)
def rel_occ(R, sc, ref, end, occupied, n=48, why="people add heat"):
    node, loc = L.node_occ(sc["b"], sc["occ_k"])
    if occupied:
        a = R.randrange(4, 30)
        xs = [0] * a + [1] * (n - a)
    else:
        xs = [0] * n
    s = sensor(ref, "occupancy", "occ", node, loc, xs, None, end, False, why,
               agent=ag("arrival" if occupied else "vacant", "normal", "arrival" if occupied else "vacant", 0.9 if occupied else 0.95,
                        ["Room became occupied at %s and is still occupied [E4,E1]" % L.idx_time(end, n, xs.index(1)) if occupied
                         else "Room unoccupied for the whole 4-hour window [E2,E1]"]))
    return s


def rel_acroom(R, sc, ref, end, xs, why="AC controls room temperature"):
    node, loc = "AC-%s%02d" % (sc["b"], sc["fl"]), "%s building, level %02d, AC units" % (sc["b"], sc["fl"])
    s = sensor(ref, "hvac", "room_temp", node, loc, xs, None, end, False, why, unit_shown="C",
               agent=lambda s: ag("gradual_increase" if float(P(s)["slope"]) > 0.6 else "stable", "normal", "hvac_context", 0.8,
                                  ["Room temperature (AC sensors) %s C, trend %s C/h [E1,E4]" % (P(s)["last"], P(s)["slope"])]))
    return s


def rel_acunits(R, sc, ref, end, xs, why="AC response"):
    node, loc = "AC-%s%02d" % (sc["b"], sc["fl"]), "%s building, level %02d, AC units" % (sc["b"], sc["fl"])
    s = sensor(ref, "hvac", "ac_units_on", node, loc, xs, None, end, False, why, unit_shown="units",
               agent=lambda s: ag("step_decrease" if xs[-1] < xs[0] else "stable", "normal", "hvac_context", 0.8,
                                  ["AC units running: now %s [E1,E4]" % P(s)["last"]]))
    return s


def rel_power(R, sc, ref, end, xs, why="cooling load"):
    node, loc = L.node_em(sc["b"], min(sc["fl"] + 1, 6), 1)
    s = sensor(ref, "power", "power_kw", node, loc, xs, None, end, False, why,
               agent=lambda s: ag("stable", "normal", "normal_load", 0.8, ["Power steady around %s kW [E1,E4]" % P(s)["last"]]))
    return s


def rel_weather(R, sc, ref, end, temp, why="outdoor heat load"):
    xs = noise_series(R, 48, temp, 0.25, 1)
    s = sensor(ref, "weather", "temp", WE_NODE, WE_LOC, xs, None, end, False, why,
               agent=lambda s: ag("stable", "normal", "normal_weather", 0.8, ["Temperature steady around %s C [E1,E4]" % P(s)["last"]]))
    return s


def mk_row(R, sc, fam, sensors, report, root_metric, rid, pair, mode="early", recheck=None, memory=None, outdoor=None, end=None):
    case = {"end": end or sc["end"], "outdoor": outdoor, "inc_id": sc["inc"], "mode": mode, "win_h": "4", "sensors": sensors,
            "recheck": recheck, "memory": memory if memory is not None else [], "notes": None, "missing_note": None, "ask": R.choice(ASKS)}
    user = L.render(case)
    msgs = [{"role": "system", "content": SYSTEM_INCIDENT}, {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(report, ensure_ascii=False)}]
    meta = {"root_ref": "S1", "root_metric": root_metric, "label": report["label"], "severity": report["severity"]}
    return {"id": rid, "family": fam, "tools": "incident", "messages": msgs, "meta": meta, "pair": pair}


def refine_ctx(R, sc, wrong_title, wrong_sev, right_title, right_sev):
    """app RE-CHECK lines: '<HH:MM> <severity>: <title>' of earlier revisions (the early one may be wrong)"""
    stage = R.choice(["refine-1.5h", "refine-3h"])
    t0 = sc["end"] - dt.timedelta(minutes=90 if stage == "refine-1.5h" else 180)
    lines = []
    if R.random() < 0.5:
        lines.append("%s %s: %s" % (L.tstr(t0), wrong_sev, wrong_title))
    else:
        lines.append("%s %s: %s" % (L.tstr(t0), right_sev, right_title))
    if stage == "refine-3h" and R.random() < 0.6:
        lines.append("%s %s: %s" % (L.tstr(t0 + dt.timedelta(minutes=90)), lines[0].split(" ", 1)[1].split(":")[0], lines[0].split(": ", 1)[1]))
    return stage, lines, lines[0].split(" ", 2)[1].rstrip(":") != right_sev


# ---------------------------------------------------------------- room temperature
def roomtemp_pair(R, sc):
    end, n = sc["end"], 144
    b, fl, k = sc["b"], sc["fl"], sc["k"]
    node, loc = L.node_aq(b, fl, k)
    head = ["LIMITS: warning above 30, critical above 34"]
    base = R.uniform(23.5, 26.0)
    out_t = R.uniform(27.0, 33.5)
    rows = []
    # --- fault
    kind = R.choices(["jump", "stuck", "spikes"], [0.6, 0.2, 0.2])[0]
    hist = noise_series(R, n, base, 0.15, 1)
    if kind == "jump":
        jt = R.randrange(100, 140)
        off = R.uniform(10.0, 20.0)
        xs = [r1(v + (off if i >= jt else 0), 1) for i, v in enumerate(hist)]
    elif kind == "stuck":
        v0 = r1(R.uniform(35.5, 48.0), 1)
        k0 = R.randrange(96, 126)
        xs = hist[:k0] + [v0] * (n - k0)
    else:
        xs = list(hist)
        cap = R.choice([50.0, 60.0, 85.0])
        for i in sorted(R.sample(range(100, 143), R.randrange(3, 7))) + [n - 1]:
            xs[i] = cap
    w = xs[-48:]
    wrong_f = R.random() < 0.45

    def ag_f(s):
        p = P(s)
        if wrong_f:
            return ag("step_increase" if kind != "stuck" else "stable", "critical", R.choice(["high_heat_load", "hvac_failure"]), round(R.uniform(0.8, 0.95), 2),
                      ["%s C is over the critical limit (34) [E1]" % p["last"]])
        if kind == "jump":
            return ag("step_increase", "sensor_fault", "sensor_fault", round(R.uniform(0.85, 0.97), 2),
                      ["Temperature jumped %s C at %s and did not return [E5,E1]" % (p["jump"], p["jump_t"]),
                       "One-sample jump of %s C: a bias fault sign [E5]" % p["jump"]])
        if kind == "stuck":
            return ag("flatline", "sensor_fault", "sensor_fault", 0.9, ["Temperature flat at %s C [E1,E8]" % p["last"]])
        return ag("spike", "sensor_fault", "sensor_fault", 0.85, ["Repeated spikes to %s C [E2]" % p["max"]])
    s1 = sensor("S1", "air_quality", "temp", node, loc, w, xs, end, True, agent=ag_f, head=head)
    acx = noise_series(R, 48, base - R.uniform(0.3, 1.5), 0.15, 1)
    rel = [rel_acroom(R, sc, "S2", end, acx), rel_occ(R, sc, "S3", end, R.random() < 0.4)]
    pw = noise_series(R, 48, R.uniform(1.5, 4.5), 0.03, 2)
    rel.append(rel_power(R, sc, "S4", end, pw))
    we = rel_weather(R, sc, "S5", end, out_t) if R.random() < 0.7 else None
    if we:
        rel.append(we)
    sensors = [s1] + rel
    p1, pa = P(s1), P(rel[0])
    if kind == "jump":
        why_s = "a %s C jump within 5 minutes at %s" % (p1["jump"], p1["jump_t"])
        obs = [ob("Room temperature jumped %s C within 5 minutes at %s" % (p1["jump"], p1["jump_t"]), ["S1.E5"]),
               ob("Room temperature now %s C" % p1["last"], ["S1.E1"])]
        src = ["S1.E5"]
        title = R.choice(["Room temperature sensor offset after a %s C jump: %s" % (p1["jump"], L.place(b, fl)),
                          "Suspect room temperature readings (%s)" % L.place(b, fl)])
        acts = R.choice([["check_sensor", "recalibrate_sensor"], ["recalibrate_sensor", "check_sensor"]])
    elif kind == "stuck":
        why_s = "frozen at %s C" % p1["last"]
        obs = [ob("Flat at %s C, flat run %s points" % (p1["last"], p1["flat"]), ["S1.E8"]), ob("Room temperature now %s C" % p1["last"], ["S1.E1"])]
        src = ["S1.E8"]
        title = R.choice(["Room temperature sensor stuck at %s C: %s" % (p1["last"], L.place(b, fl)),
                          "Frozen room temperature reading (%s)" % L.place(b, fl)])
        acts = ["check_sensor", "restart_or_reconnect_sensor"]
    else:
        why_s = "spikes to %s C between ordinary readings" % p1["max"]
        obs = [ob("Spikes to %s C, max at %s" % (p1["max"], p1["max_t"]), ["S1.E2"]), ob("Noise %s, far beyond a real room" % p1["noise"], ["S1.E8"])]
        src = ["S1.E2", "S1.E8"]
        title = R.choice(["Room temperature sensor spiking to %s C: %s" % (p1["max"], L.place(b, fl)),
                          "Room temperature sensor fault (%s)" % L.place(b, fl)])
        acts = ["check_sensor", "restart_or_reconnect_sensor"]
    obs.append(ob("AC room sensor reads %s C, trend %s C per hour" % (pa["last"], pa["slope"]), ["S2.E1", "S2.E4"]))
    checks = []
    if wrong_f:
        checks.append({"ref": "S1", "claim": "status critical (heat)", "verdict": "corrected",
                       "fact": "%s while the AC room sensor stays at %s C" % (why_s, pa["last"]), "src": src + ["S2.E1"]})
    tgt = "S1 (%s)" % node
    whys = {"check_sensor": "Check the sensor, its mounting and nearby heat sources", "recalibrate_sensor": "Compare with a reference thermometer",
            "restart_or_reconnect_sensor": "Restart the node if the reading stays frozen"}
    rc = "The room temperature sensor shows %s while the AC's own room sensor and the load stay ordinary: a sensor fault, not real heat." % why_s
    if len(rc.split()) > 30:
        rc = "The room temperature sensor shows %s; the AC room sensor disagrees: a sensor fault." % why_s
    chain = "%s (%s) vs AC room sensor %s C (S2.E1) -> sensor fault" % (why_s, ",".join(src), pa["last"])
    expl = R.choice(["A sensor problem, not a hot room: the AC's own room sensor still reads %s C. Check the sensor first." % pa["last"],
                     "Do not treat this as heat: one sensor disagrees with the AC room sensor (%s C)." % pa["last"]])
    rf = rep(title, "sensor_fault", "sensor_fault", rc, chain, obs, checks, ["air_quality"], ["S1"], evidence_of(obs, ["S2.E4"]),
             round(R.uniform(0.82, 0.93), 2), [(a, tgt, whys[a]) for a in acts], "Whether room temperature agrees with the AC room sensor after the check", expl)
    wrong_title_f = "Room temperature critical (%s C): %s" % (p1["last"], L.place(b, fl))
    rows.append(("roomtemp:fault_%s%s" % (kind, "+agent_heat" if wrong_f else ""), sensors, rf, "temp", outdoor_of_s(we, end),
                 (wrong_title_f, "critical", title, "sensor_fault")))
    # --- real heat: AC units drop out, room and AC sensor climb together
    sev_want = R.choice(["critical", "critical", "warning"])
    top = R.uniform(34.4, 38.5) if sev_want == "critical" else R.uniform(30.5, 33.6)
    on = R.randrange(4, 28)                      # AC stops at window index `on`
    hist2 = noise_series(R, n - 48 + on, base, 0.12, 1)
    ramp = [base + (top - base) * min(1.0, (j + 1) / (48 - on)) ** R.uniform(0.8, 1.2) + R.gauss(0, 0.12) for j in range(48 - on)]
    xs2 = hist2 + [r1(v, 1) for v in ramp]
    w2 = xs2[-48:]
    sev = "critical" if w2[-1] > 34 else ("warning" if w2[-1] > 30 else None)
    if sev is None:
        return rows
    wrong_r = R.random() < 0.45

    def ag_r(s):
        p = P(s)
        if wrong_r:
            return ag("step_increase", "sensor_fault", "sensor_fault", round(R.uniform(0.85, 0.97), 2),
                      ["Temperature jumped %s C at %s; bias fault sign [E5]" % (p["jump"], p["jump_t"])])
        return ag("gradual_increase", sev, "hvac_failure", 0.85, ["Temperature climbing at %s C/h, now %s C [E4,E1]" % (p["slope"], p["last"])])
    s1r = sensor("S1", "air_quality", "temp", node, loc, w2, xs2, end, True, agent=ag_r, head=head)
    acx2 = [r1(v - R.uniform(0.3, 1.0), 1) for v in w2]
    units0 = R.choice([2, 3, 4])
    units = [units0] * on + [0] * (48 - on)
    rel2 = [rel_acroom(R, sc, "S2", end, acx2), rel_acunits(R, sc, "S3", end, units), rel_occ(R, sc, "S4", end, True)]
    we2 = rel_weather(R, sc, "S5", end, out_t) if we else None
    if we2:
        rel2.append(we2)
    sensors2 = [s1r] + rel2
    p1, pa, pu = P(s1r), P(rel2[0]), P(rel2[1])
    obs2 = [ob("Room temperature rising %s C per hour (r2 %s)" % (p1["slope"].lstrip("+"), p1["r2"]), ["S1.E4"]),
            ob("Room temperature now %s C" % p1["last"], ["S1.E1"]),
            ob("AC room sensor also rising, now %s C" % pa["last"], ["S2.E1", "S2.E4"]),
            ob("AC units running now %s" % pu["last"], ["S3.E1"])]
    checks2 = []
    if wrong_r:
        checks2.append({"ref": "S1", "claim": "status sensor_fault (bias)", "verdict": "corrected",
                        "fact": "gradual rise (r2 %s) confirmed by the AC room sensor at %s C; AC units now %s" % (p1["r2"], pa["last"], pu["last"]),
                        "src": ["S1.E4", "S2.E1", "S3.E1"]})
    lim = "34" if sev == "critical" else "30"
    title2 = R.choice(["Room overheating, AC units off: room temperature %s C at %s" % (p1["last"], L.place(b, fl)),
                       "Room temperature %s C over the %s C limit (%s)" % (p1["last"], lim, L.place(b, fl))])
    tgt_ac = "S3 (AC-%s%02d)" % (b, fl)
    cl2 = [("inspect_hvac", tgt_ac, "AC units stopped and the room is heating up"),
           ("request_facility_review", "S1 (%s)" % node, "Occupied room above the %s C limit" % lim)]
    if sev == "warning":
        cl2 = [("inspect_hvac", tgt_ac, "AC units stopped and the room is heating up"), ("monitor", "S1 (%s)" % node, "Watch for the critical limit")]
    rc2 = "The AC units stopped and the occupied room is heating up; both room sensors agree, so the heat is real."
    chain2 = "AC units to %s (S3.E1) -> room temperature rising (S1.E4, S2.E4) -> %s C over the %s C limit (S1.E1)" % (pu["last"], p1["last"], lim)
    expl2 = R.choice(["Real heat from an AC failure: two independent sensors agree. Inspect the AC units.",
                      "The room is genuinely hot (%s C) because cooling stopped. Inspect the AC." % p1["last"]])
    rr = rep(title2, sev, "hvac_or_thermal_issue", rc2, chain2, obs2, checks2, ["air_quality", "hvac"], [], evidence_of(obs2),
             round(R.uniform(0.82, 0.92), 2), cl2, "Whether room temperature falls once the AC units run again", expl2)
    rows.append(("roomtemp:real_%s%s" % (sev, "+agent_fault" if wrong_r else ""), sensors2, rr, "temp", outdoor_of_s(we2, end),
                 ("Suspect room temperature readings (%s)" % L.place(b, fl), "sensor_fault", title2, sev)))
    return rows


def outdoor_of_s(we, end):
    return (P(we)["last"], WE_NODE, L.tstr(end)) if we else None


# ---------------------------------------------------------------- pH
def ph_pair(R, sc):
    end, n = sc["end"], 144
    b = sc["b"]
    node, loc = L.node_wq(b)
    hi_side = R.random() < 0.7
    head = ["LIMITS: warning above 8.5, critical above 9.0"] if hi_side else ["LIMITS: warning below 6.5, critical below 6.0"]
    base = R.uniform(7.0, 7.6)
    rows = []

    def tds_flow(ref0):
        tds = noise_series(R, 48, R.uniform(120, 420), R.uniform(2, 6), 0)
        fl = noise_series(R, 48, R.uniform(1.5, 8.0), 0.08, 2)
        nt, lt = L.node_wq(b)
        nf, lf = L.node_flow(b)
        s_t = sensor(ref0, "water", "tds", nt, lt, tds, None, end, False, "water quality context",
                     agent=lambda s: ag("stable", "normal", "normal_usage", 0.8, ["TDS steady around %s ppm [E1,E4]" % P(s)["last"]]))
        s_f = sensor("S%d" % (int(ref0[1:]) + 1), "water", "flow", nf, lf, fl, None, end, False, "low flow / stagnation",
                     agent=lambda s: ag("stable", "normal", "normal_usage", 0.8, ["Flow steady around %s m3/h [E1,E4]" % P(s)["last"]]))
        return [s_t, s_f] if R.random() < 0.6 else [s_f, s_t]
    # --- single bad reading
    hist = noise_series(R, n, base, 0.05, 2)
    j = n - R.randrange(3, 13)
    hist[j] = r1(R.uniform(9.4, 10.2) if hi_side else R.uniform(4.6, 5.6), 2)
    w = hist[-48:]
    wrong_s = R.random() < 0.45

    def ag_s(s):
        p = P(s)
        if wrong_s:
            v = p["max"] if hi_side else p["min"]
            return ag("spike", "critical", "water_quality_issue", round(R.uniform(0.85, 0.97), 2),
                      ["%s pH is beyond the critical limit (%s) [E%s]" % (v, "9.0" if hi_side else "6.0", "2" if hi_side else "3")])
        return ag("spike", "sensor_fault", "sensor_fault", 0.85, ["One reading out of line, then back to normal [E2,E1]" if hi_side else
                                                                  "One reading out of line, then back to normal [E3,E1]"])
    s1 = sensor("S1", "water", "ph", node, loc, w, hist, end, True, agent=ag_s, head=head)
    sensors = [s1] + tds_flow("S2")
    p1 = P(s1)
    ext, ext_t, eid = (p1["max"], p1["max_t"], "S1.E2") if hi_side else (p1["min"], p1["min_t"], "S1.E3")
    obs = [ob("A single reading of %s pH at %s" % (ext, ext_t), [eid]), ob("pH back to %s now" % p1["last"], ["S1.E1"]),
           ob("pH trend flat (%s per hour)" % p1["slope"], ["S1.E4"])]
    checks = []
    if wrong_s:
        checks.append({"ref": "S1", "claim": "status critical (water quality)", "verdict": "corrected",
                       "fact": "one sample of %s pH, the next readings are back at %s pH" % (ext, p1["last"]), "src": [eid, "S1.E1"]})
    title = R.choice(["Single bad pH reading (%s): %s" % (ext, L.place(b, 98)), "pH sensor glitch at %s: %s" % (ext_t, L.place(b, 98))])
    tgt = "S1 (%s)" % node
    rs = rep(title, "sensor_fault", "sensor_fault",
             "One out-of-line pH sample between normal readings: a sensor glitch, not a change in the water.",
             "single sample %s pH (%s) -> back to %s pH (S1.E1) -> glitch" % (ext, eid, p1["last"]), obs, checks, ["water"], ["S1"],
             evidence_of(obs), round(R.uniform(0.8, 0.9), 2),
             [("check_sensor", tgt, "Clean the probe and check its wiring"), ("monitor", tgt, "Watch for repeat glitches")],
             "Whether the pH glitch repeats", R.choice(["One bad reading, already back to normal: check the probe, no water action.",
                                                         "A single glitch, not a water problem; the pH is normal again."]))
    rows.append(("ph:single_%s%s" % ("high" if hi_side else "low", "+agent_crit" if wrong_s else ""), sensors, rs, "ph", None,
                 ("Water pH critical (%s): %s" % (ext, L.place(b, 98)), "critical", title, "sensor_fault")))
    # --- held beyond the limit
    sev_want = R.choice(["critical", "critical", "warning"])
    if hi_side:
        lvl = R.uniform(9.2, 9.9) if sev_want == "critical" else R.uniform(8.6, 8.95)
    else:
        lvl = R.uniform(5.2, 5.9) if sev_want == "critical" else R.uniform(6.05, 6.45)
    t0 = R.randrange(14, 40)              # samples held = 48 - t0 >= 8 (40 min)
    shape = R.choice(["step", "ramp"])
    hist2 = noise_series(R, n - 48 + t0, base, 0.05, 2)
    seg = []
    for jj in range(48 - t0):
        f = 1.0 if shape == "step" else min(1.0, (jj + 1) / R.randrange(3, 7))
        seg.append(r1(base + (lvl - base) * f + R.gauss(0, 0.04), 2))
    xs2 = hist2 + seg
    w2 = xs2[-48:]
    last = w2[-1]
    if hi_side:
        sev = "critical" if last > 9.0 else ("warning" if last > 8.5 else None)
    else:
        sev = "critical" if last < 6.0 else ("warning" if last < 6.5 else None)
    if sev is None or sev != sev_want:
        return rows
    wrong_h = R.random() < 0.45

    def ag_h(s):
        p = P(s)
        if wrong_h:
            return ag("step_increase" if hi_side else "step_decrease", "sensor_fault", "sensor_fault", round(R.uniform(0.85, 0.97), 2),
                      ["pH jumped %s at %s; one-sample jump, sensor bias likely [E5]" % (p["jump"], p["jump_t"])])
        return ag("step_increase" if hi_side else "step_decrease", sev, "water_quality_issue", 0.9,
                  ["%s pH is beyond the %s limit [E1]" % (p["last"], sev)])
    s1h = sensor("S1", "water", "ph", node, loc, w2, xs2, end, True, agent=ag_h, head=head)
    sensors2 = [s1h] + tds_flow("S2")
    p1 = P(s1h)
    obs2 = [ob("pH now %s, beyond the %s limit" % (p1["last"], sev), ["S1.E1"]),
            ob("pH moved %s within 5 minutes at %s and stayed there" % (p1["jump"], p1["jump_t"]), ["S1.E5", "S1.E6"]),
            ob("pH max %s at %s, min %s at %s" % (p1["max"], p1["max_t"], p1["min"], p1["min_t"]), ["S1.E2", "S1.E3"])]
    checks2 = []
    if wrong_h:
        checks2.append({"ref": "S1", "claim": "status sensor_fault (one-sample jump)", "verdict": "corrected",
                        "fact": "pH has stayed beyond the limit since %s (now %s pH), not one sample" % (p1["jump_t"], p1["last"]),
                        "src": ["S1.E1", "S1.E5"]})
    lim = {("critical", True): "9.0", ("warning", True): "8.5", ("critical", False): "6.0", ("warning", False): "6.5"}[(sev, hi_side)]
    word_ = "alkaline" if hi_side else "acidic"
    title2 = R.choice(["Water pH %s (%s, beyond %s): %s" % (sev, p1["last"], lim, L.place(b, 98)),
                       "Water turning %s: pH %s at %s" % (word_, p1["last"], L.place(b, 98))])
    tgt = "S1 (%s)" % node
    cl2 = [("inspect_water_system", tgt, "Find the dosing or supply change behind the pH shift"),
           ("request_facility_review", tgt, "Water quality beyond the %s limit" % sev),
           ("check_sensor", tgt, "Confirm with a manual pH test")]
    if sev == "warning":
        cl2 = [("inspect_water_system", tgt, "Find the dosing or supply change behind the pH shift"), ("check_sensor", tgt, "Confirm with a manual pH test"),
               ("monitor", tgt, "Watch for the critical limit")]
    rh = rep(title2, sev, "water_quality_issue",
             "The water pH moved beyond the %s limit and has stayed there: a real water quality change until a manual test says otherwise." % sev,
             "pH shift at %s (S1.E5) -> held at %s pH (S1.E1) beyond %s" % (p1["jump_t"], p1["last"], lim), obs2, checks2, ["water"], [],
             evidence_of(obs2), round(R.uniform(0.82, 0.92), 2), cl2, "pH after the water system inspection",
             R.choice(["The pH has stayed %s for the whole time since the change, so treat it as a real water problem." % word_,
                       "Sustained pH %s beyond the %s limit: inspect the water system, then confirm with a manual test." % (p1["last"], lim)]))
    rows.append(("ph:held_%s_%s%s" % (sev, "high" if hi_side else "low", "+agent_fault" if wrong_h else ""), sensors2, rh, "ph", None,
                 ("Single bad pH reading: %s" % L.place(b, 98), "sensor_fault", title2, sev)))
    return rows


# ---------------------------------------------------------------- CO2
def co2_triple(R, sc):
    end, n = sc["end"], 144
    b, fl, k = sc["b"], sc["fl"], sc["k"]
    node, loc = L.node_aq(b, fl, k)
    head = ["LIMITS: warning above 1000, critical above 1500"]
    base = R.uniform(420, 520)
    rows = []

    def ac_units(ref):
        u = R.choice([1, 2, 3])
        return rel_acunits(R, sc, ref, end, [u] * 48, why="AC/ventilation state")
    # --- real rise with people
    which = R.choice(["critical", "warning", "normal"])
    top = {"critical": R.uniform(1520, 1900), "warning": R.uniform(1030, 1450), "normal": R.uniform(650, 960)}[which]
    on = R.randrange(4, 24)
    hist = noise_series(R, n - 48 + on, base, 6, 0)
    ramp = [base + (top - base) * (1 - pow(2.718, -3.0 * (j + 1) / (48 - on))) / (1 - pow(2.718, -3.0)) + R.gauss(0, 7) for j in range(48 - on)]
    xs = hist + [r1(v, 0) for v in ramp]
    w = xs[-48:]
    last = w[-1]
    sev = "critical" if last > 1500 else ("warning" if last > 1000 else "normal")
    if sev != which:
        return rows
    wrong = R.random() < 0.45
    occ_xs = [0] * on + [1] * (48 - on)
    nodeo, loco = L.node_occ(b, sc["occ_k"])

    def ag_r(s):
        p = P(s)
        if wrong:
            if sev == "normal":
                return ag("gradual_increase", "warning", "poor_ventilation", 0.8, ["CO2 climbing at %s ppm/h [E4]" % p["slope"]])
            return ag("step_increase", "sensor_fault", "sensor_fault", round(R.uniform(0.85, 0.95), 2),
                      ["CO2 jumped %s ppm at %s and did not return; bias fault sign [E5,E1]" % (p["jump"], p["jump_t"])])
        return ag("gradual_increase", sev, "occupancy_load" if sev != "normal" else "normal_conditions", 0.85,
                  ["CO2 climbing at %s ppm/h, now %s ppm [E4,E1]" % (p["slope"], p["last"])])
    s1 = sensor("S1", "air_quality", "co2", node, loc, w, xs, end, True, agent=ag_r, head=head)
    so = sensor("S2", "occupancy", "occ", nodeo, loco, occ_xs, None, end, False, "people in the room raise CO2",
                agent=ag("arrival", "normal", "arrival", 0.9, ["Room became occupied at %s and is still occupied [E4,E1]" % L.idx_time(end, 48, on)]))
    sensors = [s1, so, ac_units("S3")]
    p1, po = P(s1), P(so)
    obs = [ob("CO2 rising %s ppm per hour (r2 %s)" % (p1["slope"].lstrip("+"), p1["r2"]), ["S1.E4"]),
           ob("CO2 now %s ppm" % p1["last"], ["S1.E1"]),
           ob("Room occupied since %s" % po["first_on"], ["S2.E4", "S2.E1"])]
    checks = []
    if wrong:
        if sev == "normal":
            checks.append({"ref": "S1", "claim": "status warning", "verdict": "corrected", "fact": "%s ppm is below the 1000 ppm warning limit" % p1["last"],
                           "src": ["S1.E1"]})
        else:
            checks.append({"ref": "S1", "claim": "status sensor_fault (bias)", "verdict": "corrected",
                           "fact": "smooth rise since people arrived at %s, largest 5-min change only %s ppm" % (po["first_on"], p1["jump"]),
                           "src": ["S1.E4", "S1.E5", "S2.E4"]})
    tgt = "S1 (%s)" % node
    if sev == "normal":
        title = R.choice(["CO2 %s ppm with people in the room, below limits: %s" % (p1["last"], L.place(b, fl)),
                          "Occupied-room CO2 rise to %s ppm (%s)" % (p1["last"], L.place(b, fl))])
        rr = rep(title, "normal", "occupancy_driven_load",
                 "People in the room raise CO2 as expected; it stays below the 1000 ppm warning limit.",
                 "arrival at %s (S2.E4) -> CO2 up to %s ppm (S1.E1), under 1000" % (po["first_on"], p1["last"]), obs, checks,
                 ["air_quality", "occupancy"], [], evidence_of(obs), round(R.uniform(0.8, 0.9), 2),
                 [("monitor", tgt, "Watch whether CO2 nears 1000 ppm")], "CO2 against the 1000 ppm limit while occupied",
                 "Normal for an occupied room: CO2 is rising but below the warning limit.")
    else:
        lim = "1500" if sev == "critical" else "1000"
        title = R.choice(["CO2 %s ppm in an occupied room (over %s): %s" % (p1["last"], lim, L.place(b, fl)),
                          "CO2 rising with people in the room: %s" % L.place(b, fl)])
        cl = [("inspect_ventilation", tgt, "Fresh-air supply is not keeping up with the occupancy"),
              ("request_facility_review", tgt, "CO2 beyond the %s limit" % sev) if sev == "critical" else ("monitor", tgt, "Watch for the critical limit")]
        rr = rep(title, sev, "occupancy_driven_load",
                 "People arrived and CO2 climbed smoothly beyond the %s ppm limit: real air, ventilation not keeping up." % lim,
                 "arrival at %s (S2.E4) -> smooth CO2 rise (S1.E4) -> %s ppm (S1.E1) over %s" % (po["first_on"], p1["last"], lim), obs, checks,
                 ["air_quality", "occupancy"], [], evidence_of(obs, ["S1.E5"]), round(R.uniform(0.82, 0.92), 2), cl,
                 "CO2 after ventilation is increased",
                 R.choice(["Real CO2 build-up from the people in the room; increase fresh air.",
                           "Not a sensor fault: the rise is smooth and follows the occupancy. Improve ventilation."]))
    rows.append(("co2:real_%s%s" % (sev, "+agent_wrong" if wrong else ""), sensors, rr, "co2", None,
                 ("Suspect CO2 readings: %s" % L.place(b, fl), "sensor_fault", rr["title"], sev)))
    # --- bias step in an empty room
    hist2 = noise_series(R, n, base, 6, 0)
    jt = R.randrange(100, 140)
    off = R.uniform(200, 420)
    xs2 = [r1(v + (off if i >= jt else 0), 0) for i, v in enumerate(hist2)]
    w2 = xs2[-48:]
    wrong2 = R.random() < 0.45

    def ag_b(s):
        p = P(s)
        if wrong2:
            return ag("step_increase", "warning", "poor_ventilation", 0.8, ["CO2 up to %s ppm [E1]" % p["last"]])
        return ag("step_increase", "sensor_fault", "sensor_fault", 0.9, ["CO2 jumped %s ppm at %s and did not return [E5,E1]" % (p["jump"], p["jump_t"])])
    s1b = sensor("S1", "air_quality", "co2", node, loc, w2, xs2, end, True, agent=ag_b, head=head)
    sob = sensor("S2", "occupancy", "occ", nodeo, loco, [0] * 48, None, end, False, "people in the room raise CO2",
                 agent=ag("vacant", "normal", "vacant", 0.95, ["Room unoccupied for the whole 4-hour window [E2,E1]"]))
    sensors2 = [s1b, sob, ac_units("S3")]
    p1 = P(s1b)
    obs2 = [ob("CO2 jumped %s ppm within 5 minutes at %s" % (p1["jump"], p1["jump_t"]), ["S1.E5"]),
            ob("CO2 now %s ppm" % p1["last"], ["S1.E1"]), ob("Nobody in the room", ["S2.E2", "S2.E1"])]
    checks2 = []
    if wrong2:
        checks2.append({"ref": "S1", "claim": "status warning (poor ventilation)", "verdict": "corrected",
                        "fact": "a %s ppm step in one sample in an empty room" % p1["jump"], "src": ["S1.E5", "S2.E2"]})
    title2 = R.choice(["CO2 sensor offset after a %s ppm step: %s" % (p1["jump"], L.place(b, fl)), "Suspect CO2 readings (%s)" % L.place(b, fl)])
    rb = rep(title2, "sensor_fault", "sensor_fault",
             "A one-sample CO2 step in an empty room: nobody can add that much CO2 in 5 minutes, so it is a sensor offset.",
             "%s ppm step at %s (S1.E5), room empty (S2.E2) -> sensor offset" % (p1["jump"], p1["jump_t"]), obs2, checks2,
             ["air_quality"], ["S1"], evidence_of(obs2), round(R.uniform(0.82, 0.92), 2),
             [("recalibrate_sensor", tgt, "Compare with a reference CO2 meter"), ("check_sensor", tgt, "Check the sensor after the sudden step")],
             "Whether the CO2 offset stays after recalibration",
             "An empty room cannot raise CO2 by that much in 5 minutes; the sensor needs recalibration.")
    rows.append(("co2:bias_step%s" % ("+agent_warn" if wrong2 else ""), sensors2, rb, "co2", None,
                 ("CO2 warning: %s" % L.place(b, fl), "warning", title2, "sensor_fault")))
    return rows


GENS = [("roomtemp", roomtemp_pair, 1.0), ("ph", ph_pair, 1.0), ("co2", co2_triple, 1.0)]


def build(R, npairs, prefix, novel_frac=0.0, refine_frac=0.35, memory_frac=0.25):
    rows, fails = [], collections.Counter()
    pair = 0
    tries = 0
    while pair < npairs and tries < npairs * 40:
        tries += 1
        name, fn, _ = R.choices(GENS, [g[2] for g in GENS])[0]
        sc = scen(R, pair, novel=R.random() < novel_frac)
        got = fn(R, sc)
        if not got:
            fails[name + ":no_rows"] += 1
            continue
        out = []
        for j, (fam, sensors, report, rm, outdoor, ctx) in enumerate(got):
            mode, recheck = "early", None
            if R.random() < refine_frac:
                stage, recheck, was_wrong = refine_ctx(R, sc, *ctx)
                mode = stage
                fam += "+%s%s" % (stage, "+prev_wrong" if was_wrong else "")
                if was_wrong:
                    report = dict(report, agent_checks=report["agent_checks"][:3])
                    report["causal_chain"] += "; the earlier revision (R1) is not supported by the current evidence"
            memory = []
            if R.random() < memory_frac:
                dd = sc["end"].date() - dt.timedelta(days=R.choice([3, 9, 16, 40, 75]))
                memory = ["%s INC-%04d %s on %s, closed: %s" % (dd.isoformat(), R.randrange(100, 999), R.choice(
                    ["Suspect readings", "Reading judged normal", "Spike judged normal"]), sensors[0]["node"],
                    R.choice(["resolved_on_its_own (auto)", "no_action_needed", "resolved_on_its_own"]))]
            r = mk_row(R, sc, fam, sensors, report, rm, "%s-%05d%s" % (prefix, pair, "abc"[j]), pair, mode=mode, recheck=recheck,
                       memory=memory, outdoor=outdoor)
            e = V.check_incident(r)
            if e:
                for y in set(z.split(":")[0] for z in e):
                    fails["%s %s" % (fam.split("+")[0], y)] += 1
                continue
            out.append(r)
        if not out:
            continue
        rows += out
        pair += 1
    return rows, fails, tries


def compact_row(r):
    orig = r["messages"][-1]["content"]
    new = json.dumps(compact_report(json.loads(orig)), ensure_ascii=False)
    r2 = dict(r, messages=r["messages"][:-1] + [dict(r["messages"][-1], content=new)])
    return r if (new == orig or V.check_incident(r2)) else r2


def finish(rows):
    out = []
    for r in rows:
        r = compact_row(r)
        fr = fix(dict(r))
        fr["pair"] = r["pair"]
        fr["meta"] = r["meta"]
        if V.check_incident(fr):
            continue
        out.append(fr)
    return out


def write(p, rows):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def comp(rows):
    c = collections.Counter()
    for r in rows:
        rp = json.loads(r["messages"][-1]["content"])
        c["family:" + r["family"].split("+")[0]] += 1
        c["sev:" + rp["severity"]] += 1
        c["first_action:" + rp["checklist"][0]["action"]] += 1
        c["mode:" + ("refine" if "+refine" in r["family"] else "early")] += 1
        c["agent_wrong"] += 1 if "+agent" in r["family"] else 0
    return dict(sorted(c.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--pairs", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=5101)
    ap.add_argument("--test-pairs", type=int, default=150)
    ap.add_argument("--test-seed", type=int, default=5202)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tr, ftr, ttr = build(random.Random(a.seed), a.pairs, "r2t")
    te, fte, tte = build(random.Random(a.test_seed), a.test_pairs, "r2tt", novel_frac=0.35)
    tr, te = finish(tr), finish(te)
    tu = {r["messages"][1]["content"] for r in te}
    tr = [r for r in tr if r["messages"][1]["content"] not in tu]
    random.Random(a.seed + 1).shuffle(tr)
    write(os.path.join(a.out, "train.jsonl"), tr)
    write(os.path.join(a.out, "test.jsonl"), te)
    man = {"generator": "proofs/2026-11-02_2b_r2/tools/gen_r2_targeted.py", "seed": a.seed, "test_seed": a.test_seed, "synthetic_only": True,
           "rows": {"train": len(tr), "test": len(te)}, "train": comp(tr), "test": comp(te),
           "verify_fail": {"train": dict(ftr), "test": dict(fte)}, "tries": {"train": ttr, "test": tte},
           "test_novel_building_codes": NOVEL_B}
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    print("r2 targeted: train %d, test %d rows; verify drops %s / %s" % (len(tr), len(te), dict(ftr.most_common(6)), dict(fte.most_common(6))))


if __name__ == "__main__":
    main()
