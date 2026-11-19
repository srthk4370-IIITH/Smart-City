"""r2 add-on: contrastive heatwave / weather-sensor-fault incident pairs (synthetic only, stdlib python3, CPU).

Why: in the round-1 incident set (kaggle/build/r1/data/incidents3_train.jsonl, 20k rows) there is no weather-only incident
(every row with a flagged weather sensor also flags a building sensor), no weather sensor_fault row, and when the domain
agent says status=sensor_fault the gold severity is critical in only 6 of 2,203 single-flagged rows. On the board the
reasoner then copies the weather agent's "sensor bias" claim for a real 45 C afternoon (HANDBOOK 2.67, INC-0577/0579).

Each pair shares one scenario (date, end time, related sensors):
  heat  : genuine heat, diurnal ramp over hours, smooth (small 5-min changes), corroborated by falling outdoor humidity,
          rising substation (cooling) load, AC units coming on, indoor temperature creeping up (or by its own shape when
          no related sensor is attached). >= 42 C -> critical, 38-42 C -> warning; label weather_driven; first action
          monitor / review_schedule (app validator v3ActionFloor weather-only rule) + request_facility_review / inspect_hvac
          later (round-1 verify.py floor). The weather agent is wrong (says sensor_fault / bias) in ~45 % of heat rows and
          the gold corrects it in agent_checks.
  fault : same place and time, stuck (flatline), impossible one-sample jump (bias), night-time drift, or spikes to a
          sensor ceiling, with the neighbours showing no heat -> sensor_fault, sensor action first. The agent is wrong
          (calls it critical heat) in ~45 % of fault rows.
Prompts are rendered by round-1 lib.render (byte-identical to the app's RenderV3User, golden-tested) in the app's layout
for weather incidents (LIMITS head line, outdoor CONTEXT, related: cooling load / indoor temperature / AC response).
Gold reports are template-written, compacted like gen_incidents_v3 (compact_report) and must pass round-1 verify.py
check_incident; the app's Go gate (checkReportV3For with weatherOnlyIncident) is run by heat_r2_go_check.sh.
Pairs are split train/dev by pair (no scenario in both).

  python3 gen_heat_r2.py [--out ../data/heat_r2] [--pairs 120] [--seed 2611] [--dev-frac 0.2]
  python3 gen_heat_r2.py --mix-into <kaggle/build/RUN/data>   # append heat_r2/train.jsonl to incidents3_train.jsonl there
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V3 = os.path.abspath(os.path.join(HERE, ".."))
R1 = os.path.abspath(os.path.join(V3, "..", "2026-10-25_reasoner_final"))
sys.path.insert(0, os.path.join(R1, "pipeline"))
sys.path.insert(0, os.path.join(V3, "kaggle"))
import lib as L  # noqa: E402
import textbank as T  # noqa: E402
import verify as V  # noqa: E402
from build_mix import fix  # noqa: E402
from prompts import SYSTEM_INCIDENT  # noqa: E402
from gen_incidents_v3 import compact_report  # noqa: E402

L.METRICS.setdefault(("hvac", "ac_units_on"), ("units", 0, None, None, "high"))   # app: AC-KH03 ac_units_on [units]
WE_NODE, WE_LOC = L.WEATHER
SUB_NODE, SUB_LOC = L.SUBSTATION
PLACE = "VN building, level 04"
BLDS = ["KH", "BK", "OB", "NB", "KN"]
OPS = ["ravi", "meena", "arjun", "sana"]
ASK = "Write the cross-domain incident report JSON."


# ---------------------------------------------------------------- series
def hr(end, n, i):
    t = end - dt.timedelta(minutes=5 * (n - 1 - i))
    return t.hour + t.minute / 60.0


def diurnal(h, tmin, amp, peak=14.5):
    """0 before 06:00, sine rise to 1 at `peak`, slow fall after"""
    if h < 6:
        return 0.0
    if h <= peak:
        return math.sin(math.pi / 2 * (h - 6) / (peak - 6))
    return max(0.0, math.cos(math.pi / 2 * (h - peak) / 7.0))


def r1(x, d):
    return round(x, d)


def smooth_noise(R, n, amp, k=6):
    """slow wobble (passing clouds): random walk smoothed over k points"""
    w, v = [], 0.0
    for _ in range(n + k):
        v = 0.85 * v + R.gauss(0, amp)
        w.append(v)
    return [sum(w[i:i + k]) / k for i in range(n)]


def heat_series(R, end, last_target, n=144, cloud=0.0):
    """12 h of outdoor temperature ending at `end` whose last reading is ~last_target; cloud > 0: a passing cloud shades the
    station for 30-60 min inside the window (gradual dip) and clears abruptly (a real +cloud C 5-min step)"""
    for _ in range(300):
        tmin = R.uniform(26.5, 30.5)
        s_end = diurnal(hr(end, n, n - 1), 0, 1)
        amp = (last_target - tmin) / max(0.3, s_end)
        wob = smooth_noise(R, n, R.uniform(0.05, 0.12))
        nz = R.uniform(0.12, 0.28)
        xs = [tmin + amp * diurnal(hr(end, n, i), 0, 1) + wob[i] + R.gauss(0, nz) for i in range(n)]
        if cloud:
            j = n - 48 + R.randrange(14, 40)
            ln = R.randrange(6, 13)
            for i in range(j - ln, j):
                xs[i] -= cloud * min(1.0, (i - (j - ln) + 1) / 4.0)
        xs = [r1(x, 1) for x in xs]
        w = xs[-48:]
        mj = max(abs(w[i] - w[i - 1]) for i in range(1, 48))
        if mj < (1.6 if not cloud else cloud + 0.9) and abs(w[-1] - last_target) < 0.6:
            return xs, tmin
    return xs, tmin


def normal_day(R, end, n=144, peak_t=None):
    """an ordinary day's outdoor temperature (what the stuck/biased sensor should have shown)"""
    tmin = R.uniform(22.0, 26.0)
    pk = peak_t or R.uniform(31.0, 34.5)
    wob = smooth_noise(R, n, 0.08)
    return [r1(tmin + (pk - tmin) * diurnal(hr(end, n, i), 0, 1) + wob[i] + R.gauss(0, 0.18), 1) for i in range(n)]


def follow(R, temps, base, gain, nz, dec, lo=None, hi=None):
    out = []
    for t in temps:
        v = base + gain * t + R.gauss(0, nz)
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        out.append(r1(v, dec))
    return out


# ---------------------------------------------------------------- sensors (dicts in lib.render's case format)
def sensor(ref, role, metric, node, loc, xs, hist, end, flagged, why=None, agent=None, head=None, unit_shown=None):
    ev = L.evidence(role, metric, xs, end, hist)
    s = dict(ref=ref, role=role, metric=metric, node=node, loc=loc, flagged=flagged, why=why, quality="good", head=head or [],
             stale=None, ev=ev, agent=None, unit_shown=unit_shown, rule=("?", "?"))
    s["agent"] = agent(s) if callable(agent) else agent
    return s


def ag(pattern, status, cause, conf, obs):
    return {"pattern": pattern, "status": status, "cause": cause, "conf": conf, "obs": obs}


def P(s):
    return T.parse(s)


def evt(s, eid):
    return T.ev(s, eid)


def related_set(R, kind_hint=None):
    """which related sensors the incident carries (app: cooling load, indoor temperature, AC response; + station humidity)"""
    k = kind_hint or R.choices(["full", "app", "rh", "none"], [0.35, 0.25, 0.2, 0.2])[0]
    return k, {"full": ["rh", "power", "indoor", "ac"], "app": ["power", "indoor", "ac"], "rh": ["rh"], "none": []}[k]


def scenario(R, i):
    month = R.choice([3, 4, 4, 5, 5, 5, 6])
    d = dt.date(2026, month, R.randrange(1, 29))
    end_h = R.choice([12, 13, 13, 14, 14, 15, 16])
    end = dt.datetime(d.year, d.month, d.day, end_h, R.choice(range(0, 60, 5)), tzinfo=L.IST)
    b = R.choice(BLDS)
    fl = R.choice([1, 2, 3, 4])
    return dict(i=i, end=end, b=b, fl=fl, aq_k=R.choice([1, 2, 3, 4, 5]), inc="INC-%04d" % R.randrange(1000, 9999))


def build_related(R, sc, end, which, hot, temps_true):
    """related sensors; hot=True: they follow the heat; hot=False: an ordinary day (no heat signal)"""
    out = []
    n = 144
    w = temps_true[-48:]
    nm = {"rh": None, "power": None, "indoor": None, "ac": None}
    for kind in which:
        ref = "S%d" % (len(out) + 2)
        if kind == "rh":
            if hot:
                base = R.uniform(88, 100)
                xs_all = follow(R, temps_true, base, -R.uniform(1.6, 1.9), 0.5, 1, 8, 99)
            else:
                xs_all = follow(R, temps_true, R.uniform(70, 80), -R.uniform(0.6, 0.9), 0.5, 1, 20, 99)
            s = sensor(ref, "weather", "rh", WE_NODE, WE_LOC, xs_all[-48:], xs_all, end, False, "humidity at the same station",
                       agent=lambda s: ag("gradual_decrease" if hot else "stable", "normal", "diurnal_cycle" if hot else "normal_conditions",
                                          0.8, [fa_trend(s)]))
        elif kind == "power":
            base = R.uniform(430, 620)
            if hot:
                xs = [r1(base + (t - w[0]) * R.uniform(9, 11) + R.gauss(0, 3.0), 2) for t in w]
            else:
                xs = [r1(base + R.gauss(0, 4.5), 2) for _ in w]
            s = sensor(ref, "power", "power_kw", SUB_NODE, SUB_LOC, xs, None, end, False, "cooling load",
                       agent=lambda s: ag("gradual_increase" if hot else "stable", "normal", "cooling_load" if hot else "normal_load", 0.8,
                                          [fa_trend(s) if hot else "Power steady around %s kW [E1,E4]" % P(s)["last"]]))
        elif kind == "indoor":
            node, loc = L.node_aq(sc["b"], sc["fl"], sc["aq_k"])
            if hot:
                xs = [r1(24.6 + (t - w[0]) * R.uniform(0.12, 0.2) + R.gauss(0, 0.1), 1) for t in w]
            else:
                lvl = R.uniform(24.2, 25.4)
                xs = [r1(lvl + R.gauss(0, 0.12), 1) for _ in w]
            s = sensor(ref, "air_quality", "temp", node, loc, xs, None, end, False, "indoor temperature",
                       agent=lambda s: ag("gradual_increase" if hot else "stable", "normal", "high_heat_load" if hot else "normal_conditions", 0.8,
                                          [fa_trend(s) if hot else "Temperature steady around %s C [E1,E4]" % P(s)["last"]]))
        else:
            node, loc = "AC-%s%02d" % (sc["b"], sc["fl"]), "%s building, level %02d, AC units" % (sc["b"], sc["fl"])
            if hot:
                a0, a1 = R.choice([1, 2]), R.choice([3, 4])
                cut = R.randrange(12, 36)
                xs = [a0 if j < cut else a1 for j in range(48)]
            else:
                a0 = R.choice([1, 2])
                xs = [a0] * 48
            s = sensor(ref, "hvac", "ac_units_on", node, loc, xs, None, end, False, "AC response", unit_shown="units",
                       agent=lambda s: ag("step_increase" if hot else "stable", "normal", "hvac_context", 0.8,
                                          ["AC units running: now %s [E1,E4]" % P(s)["last"]]))
        nm[kind] = s
        out.append(s)
    return out, nm


def fa_trend(s):
    """agent-style trend line with [E#] ids (lib.prefix_ids adds the sensor ref in the prompt)"""
    p = P(s)
    u = T.unit_of(s)
    up = not p["slope"].startswith("-")
    return "%s %s at %s%s/h, now %s%s [E4,E1]" % (wname(s), "climbing" if up else "falling", p["slope"], (" " + u) if u else "",
                                                  p["last"], (" " + u) if u else "")


def wname(s, cap=True):
    nm = {("weather", "temp"): "outdoor temperature", ("weather", "rh"): "outdoor humidity", ("power", "power_kw"): "substation load",
          ("air_quality", "temp"): "indoor temperature", ("hvac", "ac_units_on"): "AC units running"}[(s["role"], s["metric"])]
    return nm[0].upper() + nm[1:] if cap else nm


# ---------------------------------------------------------------- observation helpers (numbers copied from E-lines)
def ob(text, src):
    return {"text": text, "src": src}


def o_trend(s):
    p = P(s)
    sl = p["slope"]
    u = T.uu(s)
    up = not sl.startswith("-")
    vb = "rising" if up else "falling"
    return ob("%s %s %s%s per hour (r2 %s)" % (wname(s), vb, sl.lstrip("+-"), u, p["r2"]), [s["ref"] + ".E4"])


def o_now(s):
    return ob("%s now %s%s" % (wname(s), P(s)["last"], T.uu(s)), [s["ref"] + ".E1"])


def o_path(s):
    p = P(s)
    return ob("%s rose from %s at %s to %s%s at %s" % (wname(s), p["min"], p["min_t"], p["max"], T.uu(s), p["max_t"]),
              [s["ref"] + ".E3", s["ref"] + ".E2"])


def o_smooth(s):
    p = P(s)
    return ob("Largest 5-min change only %s%s: no sudden step" % (p["jump"], T.uu(s)), [s["ref"] + ".E5"])


def o_flat(s):
    p = P(s)
    return ob("Flat at %s%s, flat run %s points, noise %s" % (p["last"], T.uu(s), p["flat"], p["noise"]), [s["ref"] + ".E8"])


def o_jump(s):
    p = P(s)
    return ob("Jumped %s%s within 5 minutes at %s" % (p["jump"], T.uu(s), p["jump_t"]), [s["ref"] + ".E5"])


def o_steady(s):
    p = P(s)
    return ob("%s steady (trend %s%s per hour)" % (wname(s), p["slope"], T.uu(s)), [s["ref"] + ".E4"])


# ---------------------------------------------------------------- heat row
def heat_row(R, sc, sev_want, agent_wrong, rel_kind, short=False):
    end = sc["end"]
    last_t = R.uniform(42.4, 46.4) if sev_want == "critical" else R.uniform(38.3, 41.6)
    cloud = R.uniform(2.0, 3.6) if (agent_wrong and rel_kind != "none" and R.random() < 0.45) else 0.0
    temps, tmin = heat_series(R, end, last_t, cloud=cloud)
    w = temps[-48:]
    sev = "critical" if w[-1] >= 42 else ("warning" if w[-1] >= 38 else None)
    if sev is None:
        return None

    def agent(s):
        p = P(s)
        if agent_wrong:
            return ag(R.choice(["step_increase", "gradual_increase"]), "sensor_fault", "sensor_fault", round(R.uniform(0.9, 0.99), 2),
                      ["Temperature jumped %s C at %s and did not return [E5,E1]" % (p["jump"], p["jump_t"]),
                       R.choice(["The new level appeared instantly; sensor bias likely [E5,E1]", "Reading implausible for this station; sensor bias likely [E5]"])])
        lim = 42 if sev == "critical" else 38
        return ag("gradual_increase", sev, "heat_buildup", 0.8,
                  [fa_trend(s), "%s C exceeds the %s limit of %d C [E1]" % (p["last"], sev, lim)])
    s1 = sensor("S1", "weather", "temp", WE_NODE, WE_LOC, w, temps[-R.randrange(60, 90):] if short else temps, end, True, agent=agent,
                head=["LIMITS: warning above 38, critical above 42"])
    _, which = related_set(R, rel_kind)
    rel, nm = build_related(R, sc, end, which, True, temps)
    sensors = [s1] + rel
    p1 = P(s1)
    rh, pw, ind, acu = nm["rh"], nm["power"], nm["indoor"], nm["ac"]
    corr = [x for x in (rh, pw, acu, ind) if x is not None]
    obs = [o_trend(s1)]
    if agent_wrong or not corr:
        obs.append(o_smooth(s1) if not cloud else ob("One %s C step at %s, inside a steady rise" % (p1["jump"], p1["jump_t"]), ["S1.E5"]))
    for x in corr[:3 - len(obs)]:
        obs.append(o_trend(x) if x is not acu else ob("AC units running now %s" % P(x)["last"], [x["ref"] + ".E1"]))
    if len(obs) < 3:
        obs.append(R.choice([o_now(s1), o_path(s1)]))
    checks = []
    if agent_wrong:
        src = ["S1.E4", "S1.E5"] + ([rh["ref"] + ".E4"] if rh else ([pw["ref"] + ".E4"] if pw else []))
        tail = ""
        if rh:
            tail = "; outdoor humidity falls with it"
        elif pw:
            tail = "; cooling load rises with it"
        checks.append({"ref": "S1", "claim": "status sensor_fault (sensor bias)", "verdict": "corrected",
                       "fact": ("smooth rise over hours (r2 %s), largest 5-min change %s C%s" % (p1["r2"], p1["jump"], tail))
                       if (float(p1["r2"]) >= 0.7 and not cloud) else
                       ("gradual daytime rise in the 12 h view, one %s C step, no lasting offset%s" % (p1["jump"], tail)),
                       "src": src if (float(p1["r2"]) >= 0.7 and not cloud) else src[:1] + ["S1.E9"] + src[1:]})
    lim = "42" if sev == "critical" else "38"
    title = R.choice(["Heatwave: outdoor temperature %s C at %s" % (p1["last"], PLACE),
                      "Outdoor heat %s C (%s %s): %s" % (p1["last"], sev, "limit " + lim, PLACE),
                      "%s: outdoor temperature %s C, real heat" % (PLACE, p1["last"]),
                      "Hot afternoon, outdoor %s C at %s" % (p1["last"], PLACE)])
    if len(title) > 80:
        title = "Heatwave: outdoor %s C at %s" % (p1["last"], PLACE)
    rc = R.choice(["Genuine heat: the outdoor temperature climbed steadily through the day past the %s C %s limit." % (lim, sev),
                   "A real hot spell, not a sensor fault: a smooth daytime rise to %s C, beyond the %s C limit." % (p1["last"], lim)])
    chain_parts = ["daytime heating (S1.E4) -> outdoor %s C over the %s C limit (S1.E1)" % (p1["last"], lim)]
    if rh:
        chain_parts.append("drier air (%s.E4)" % rh["ref"])
    if pw:
        chain_parts.append("more cooling load (%s.E4)" % pw["ref"])
    chain = " -> ".join(chain_parts[:1]) + ("; " + ", ".join(chain_parts[1:]) if len(chain_parts) > 1 else "; smooth rise (S1.E5)")
    domains = ["weather"] + (["power"] if pw else []) + (["hvac"] if acu else []) + (["air_quality"] if ind else [])
    evidence = []
    for o in obs:
        for i in o["src"]:
            if i not in evidence:
                evidence.append(i)
    for x in (rh, pw):
        if x is not None and x["ref"] + ".E4" not in evidence:
            evidence.append(x["ref"] + ".E4")
    tgt1 = "S1 (%s)" % WE_NODE
    if sev == "critical":
        first = R.choice(["review_schedule", "monitor"])
        rest = [("request_facility_review", tgt1, "Check cooling, water and shade readiness for the heat")]
        if acu and R.random() < 0.5:
            rest = [("inspect_hvac", "%s (%s)" % (acu["ref"], acu["node"]), "Make sure cooling keeps up with the heat")] + rest[:1]
        cl = [(first, tgt1, "Move outdoor work and events out of the afternoon heat" if first == "review_schedule"
               else "Watch outdoor temperature at every re-check")] + rest
        if first == "monitor":
            cl.insert(1, ("review_schedule", tgt1, "Move outdoor work and events out of the afternoon heat"))
        else:
            cl.append(("monitor", tgt1, "Watch outdoor temperature at every re-check"))
    else:
        cl = R.choice([[("monitor", tgt1, "Watch whether it reaches the critical limit"),
                        ("review_schedule", tgt1, "Plan outdoor work for the cooler hours")],
                       [("review_schedule", tgt1, "Plan outdoor work for the cooler hours"),
                        ("monitor", tgt1, "Watch whether it reaches the critical limit")]])
    expl = R.choice(["Real heat, not a sensor fault: a smooth rise over hours%s. Reschedule outdoor activity." %
                     (", humidity falling" if rh else (", cooling load following" if pw else "")),
                     "Outdoor temperature is genuinely high (%s C). Reschedule outdoor activity and keep watching." % p1["last"]])
    if not corr:
        expl = "Real heat: a smooth daytime rise to %s C. Reschedule outdoor activity and keep watching." % p1["last"]
    memory, recheck, mode = [], None, "early"
    if R.random() < 0.2:
        dd = end.date() - dt.timedelta(days=R.choice([1, 2, 3]))
        memory = ["%s INC-%04d Outdoor temperature %s on %s, closed: resolved on its own" % (dd.isoformat(), R.randrange(100, 900),
                                                                                             R.choice(["warning", "critical"]), WE_NODE)]
    if sev == "critical" and R.random() < 0.25:
        j = 48 - 1 - 18
        if w[j] >= 38:
            t90 = L.tstr(end - dt.timedelta(minutes=90))
            recheck = ["%s warning: outdoor temperature was %s C (acknowledged by op_%s)" % (t90, L.fmt(w[j], 1), R.choice(OPS))]
            mode = "refine-1.5h"
            expl = "Real heat, worse since the acknowledged warning (R1). Reschedule outdoor activity and keep watching."
            chain += "; worse than R1"
    rep = {"title": title, "severity": sev, "label": "weather_driven", "root_cause": rc, "causal_chain": chain,
           "observations": obs, "agent_checks": checks, "affected_domains": domains, "suspect_sensors": [],
           "evidence": evidence[:6], "confidence": round(R.uniform(0.82, 0.92) if corr else R.uniform(0.72, 0.82), 2),
           "checklist": [{"action": a, "target": t, "why": y} for a, t, y in cl[:5]],
           "monitor_next": R.choice(["Outdoor temperature%s at the next refinement" % (" and humidity" if rh else ""),
                                     "Whether outdoor temperature peaks and falls by evening"]),
           "needs_more_data": False, "needs_deeper": False, "explanation": expl}
    fam = "heat_r2:heat_%s%s%s%s%s" % (sev, "+agent_fault" if agent_wrong else "", "+cloud_step" if cloud else "", "+rel_" + (rel_kind or "x"),
                                       "+short_hist" if short else "")
    return fam, sensors, rep, dict(memory=memory, recheck=recheck, mode=mode, outdoor=(p1["last"], WE_NODE, L.tstr(end)))


# ---------------------------------------------------------------- fault row
FAULT_ACT = {"stuck": ["check_sensor", "restart_or_reconnect_sensor"], "jump": ["recalibrate_sensor", "check_sensor"],
             "drift": ["recalibrate_sensor", "check_sensor"], "spikes": ["check_sensor", "restart_or_reconnect_sensor"]}


def fault_row(R, sc, kind, agent_wrong, rel_kind, short=False):
    end = sc["end"]
    if kind == "drift":
        d = end.date()
        end = dt.datetime(d.year, d.month, d.day, R.choice([0, 1, 2, 3, 4, 5]), R.choice(range(0, 60, 5)), tzinfo=L.IST)
    true = normal_day(R, end)
    n = 144
    if kind == "stuck":
        v = R.choice([42.5, 43.0, 44.2, 45.0, 45.6, 46.1])
        k0 = R.randrange(60, 96)
        xs = true[:k0] + [v] * (n - k0)
    elif kind == "jump":
        off = R.uniform(10.5, 15.5)
        jt = R.randrange(100, 138)
        xs = [r1(t + (off if i >= jt else 0), 1) for i, t in enumerate(true)]
        if xs[-1] < 42:
            shift = 42.4 - xs[-1] + R.uniform(0, 1.5)
            xs = [r1(t + (off + shift if i >= jt else 0), 1) for i, t in enumerate(true)]
    elif kind == "drift":
        top = R.uniform(42.4, 45.0)
        k0 = 96
        xs = true[:k0] + [r1(true[i] + (top - true[k0]) * ((i - k0) / 47.0) + R.gauss(0, 0.15), 1) for i in range(k0, n)]
    else:   # spikes to the sensor ceiling
        cap = R.choice([55.0, 60.0, 85.0])
        xs = list(true)
        idx = sorted(R.sample(range(100, 143), R.randrange(4, 9))) + [n - 1]
        for i in idx:
            xs[i] = cap
    w = xs[-48:]

    def agent(s):
        p = P(s)
        if agent_wrong:
            if kind in ("stuck",):
                return ag("stable", "critical", "heat_buildup", 0.85, ["%s C exceeds the critical limit of 42 C [E1]" % p["last"]])
            if kind == "drift":
                return ag("gradual_increase", "critical", "heat_buildup", 0.8, [fa_trend(s), "%s C exceeds the critical limit of 42 C [E1]" % p["last"]])
            return ag("step_increase" if kind == "jump" else "spike", "critical", "heat_buildup", 0.75,
                      ["%s C exceeds the critical limit of 42 C [E1]" % p["last"]])
        if kind == "stuck":
            return ag("flatline", "sensor_fault", "sensor_fault", 0.9, ["Temperature flat at %s C for the whole window [E1,E8]" % p["last"]])
        if kind == "jump":
            return ag("step_increase", "sensor_fault", "sensor_fault", 0.9,
                      ["Temperature jumped %s C at %s and did not return [E5,E1]" % (p["jump"], p["jump_t"])])
        if kind == "drift":
            return ag("gradual_increase", "sensor_fault", "sensor_fault", 0.7, ["Rising at night while nothing else changes [E4]"])
        return ag("spike", "sensor_fault", "sensor_fault", 0.85, ["Repeated spikes to %s C [E2]" % p["max"]])
    s1 = sensor("S1", "weather", "temp", WE_NODE, WE_LOC, w, xs[-R.randrange(60, 90):] if short else xs, end, True, agent=agent, head=["LIMITS: warning above 38, critical above 42"])
    if kind == "drift" and rel_kind in ("none", "rh"):
        rel_kind = "full"
    _, which = related_set(R, rel_kind)
    rel, nm = build_related(R, sc, end, which, False, true)
    sensors = [s1] + rel
    p1 = P(s1)
    rh, pw, ind, acu = nm["rh"], nm["power"], nm["indoor"], nm["ac"]
    calm = [x for x in (rh, pw, ind, acu) if x is not None]
    if kind == "stuck":
        obs = [o_flat(s1), o_now(s1)]
        why_s = "frozen at %s C with zero noise" % p1["last"]
        title = R.choice(["Outdoor temperature sensor stuck at %s C: %s" % (p1["last"], PLACE),
                          "Frozen outdoor temperature reading (%s)" % PLACE])
        fact_src = ["S1.E8"]
    elif kind == "jump":
        obs = [o_jump(s1), o_now(s1)]
        why_s = "a %s C step within 5 minutes" % p1["jump"]
        title = R.choice(["Outdoor temperature sensor offset after a %s C step: %s" % (p1["jump"], PLACE),
                          "Suspect outdoor temperature readings (%s)" % PLACE])
        fact_src = ["S1.E5"]
    elif kind == "drift":
        obs = [o_trend(s1), o_now(s1)]
        why_s = "a steady climb to %s C at night" % p1["last"]
        title = R.choice(["Outdoor temperature sensor drifting at night: %s" % PLACE,
                          "Outdoor temperature data unreliable (%s)" % PLACE])
        fact_src = ["S1.E4"]
    else:
        obs = [ob("Repeated readings of %s C, max %s C at %s" % (p1["last"], p1["max"], p1["max_t"]), ["S1.E1", "S1.E2"]),
               ob("Noise %s, oscillation far beyond a real temperature" % p1["noise"], ["S1.E8"])]
        why_s = "spikes to %s C between ordinary readings" % p1["max"]
        title = R.choice(["Outdoor temperature sensor spiking to %s C: %s" % (p1["max"], PLACE),
                          "Outdoor temperature sensor fault (%s)" % PLACE])
        fact_src = ["S1.E2", "S1.E8"]
    for x in calm[:2]:
        if x is acu:
            obs.append(ob("AC units unchanged at %s" % P(x)["last"], [x["ref"] + ".E1", x["ref"] + ".E4"]))
        else:
            obs.append(o_steady(x))
    obs = obs[:5]
    checks = []
    if agent_wrong:
        src = fact_src + ([calm[0]["ref"] + ".E4"] if calm else [])
        checks.append({"ref": "S1", "claim": "status critical, heat buildup", "verdict": "corrected",
                       "fact": "%s%s" % (why_s, "; the neighbouring sensors show no heat" if calm else ""), "src": src})
    nb = ", ".join(wname(x, False) for x in calm[:3])
    rc = "The outdoor temperature sensor shows %s%s: a sensor fault, not a heatwave." % (why_s, (" while %s stay ordinary" % nb) if calm else "")
    if len(rc.split()) > 25:
        rc = "The outdoor temperature sensor shows %s: a sensor fault, not a heatwave." % why_s
    chain = "%s (%s)%s -> sensor fault" % (why_s, ",".join(fact_src), (" vs steady neighbours (%s)" % ",".join(x["ref"] + ".E4" for x in calm[:2])) if calm else "")
    evidence = []
    for o in obs:
        for i in o["src"]:
            if i not in evidence:
                evidence.append(i)
    tgt = "S1 (%s)" % WE_NODE
    acts = list(FAULT_ACT[kind])
    memory = []
    if R.random() < 0.2:
        days = R.choice([6, 12, 20, 27, 45, 70])
        dd = end.date() - dt.timedelta(days=days)
        memory = ["%s INC-%04d temp sensor_fault on %s: recalibrated, closed as repaired" % (dd.isoformat(), R.randrange(100, 900), WE_NODE)]
        evidence.append("M1")
        if days <= 30:
            acts = ["replace_sensor"] + [a for a in acts if a != "replace_sensor"]
            chain += "; repaired %s (M1), fault back within 30 days" % dd.isoformat()
    whys = {"check_sensor": "Check the station sensor and its wiring", "restart_or_reconnect_sensor": "Restart the logger if the reading stays frozen",
            "recalibrate_sensor": "Compare against a reference thermometer and recalibrate", "replace_sensor": "Same fault returned soon after the last repair"}
    cl = [{"action": a, "target": tgt, "why": whys[a]} for a in acts]
    expl = R.choice(["A sensor problem, not real heat: %s. Check the sensor before acting on it." % why_s,
                     ("The outdoor reading cannot be trusted (%s); nothing else shows heat." if calm else
                      "The outdoor reading cannot be trusted (%s). Check the sensor first.") % why_s])
    rep = {"title": title[:80], "severity": "sensor_fault", "label": "sensor_fault", "root_cause": rc, "causal_chain": chain,
           "observations": obs, "agent_checks": checks, "affected_domains": ["weather"], "suspect_sensors": ["S1"],
           "evidence": evidence[:6], "confidence": round(R.uniform(0.82, 0.93), 2), "checklist": cl,
           "monitor_next": "Whether outdoor temperature readings vary normally after the sensor check",
           "needs_more_data": False, "needs_deeper": False, "explanation": expl}
    fam = "heat_r2:fault_%s%s+rel_%s%s" % (kind, "+agent_heat" if agent_wrong else "", rel_kind, "+short_hist" if short else "")
    return fam, sensors, rep, dict(memory=memory, recheck=None, mode="early", outdoor=(p1["last"], WE_NODE, L.tstr(end)), end=end)


# ---------------------------------------------------------------- row assembly
def make_row(R, sc, fam, sensors, rep, extra, rid, pair):
    end = extra.get("end", sc["end"])
    case = {"end": end, "outdoor": extra["outdoor"], "inc_id": sc["inc"], "mode": extra["mode"], "win_h": "4",
            "sensors": sensors, "recheck": extra["recheck"], "memory": extra["memory"], "notes": None, "missing_note": None, "ask": ASK}
    user = L.render(case)
    msgs = [{"role": "system", "content": SYSTEM_INCIDENT}, {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(rep, ensure_ascii=False)}]
    meta = {"root_ref": "S1", "root_metric": "temp", "root_role": "weather", "label": rep["label"], "severity": rep["severity"]}
    return {"id": rid, "family": fam, "tools": "incident", "messages": msgs, "meta": meta, "pair": pair}


def compact_row(r):
    orig = r["messages"][-1]["content"]
    new = json.dumps(compact_report(json.loads(orig)), ensure_ascii=False)
    if new == orig:
        return r, "unchanged"
    r2 = dict(r, messages=r["messages"][:-1] + [dict(r["messages"][-1], content=new)])
    if V.check_incident(r2):
        return r, "kept_original"
    return r2, "compacted"


def generate(a):
    R = random.Random(a.seed)
    rows, fails = [], collections.Counter()
    faults = ["stuck", "jump", "drift", "spikes"]
    fw = [0.3, 0.3, 0.2, 0.2]
    pair = 0
    tries = 0
    while pair < a.pairs and tries < a.pairs * 30:
        tries += 1
        sc = scenario(R, pair)
        rel_kind, _ = related_set(R)
        sev_want = "critical" if R.random() < 0.7 else "warning"
        short = R.random() < 0.25          # app: "12 h view: under 8 h of history" after a restart or gap
        h = heat_row(R, sc, sev_want, R.random() < 0.45, rel_kind, short)
        f = fault_row(R, sc, R.choices(faults, fw)[0], R.random() < 0.45, rel_kind, short)
        if h is None:
            fails["heat_series"] += 1
            continue
        out = []
        for j, x in enumerate((h, f)):
            r = make_row(R, sc, x[0], x[1], x[2], x[3], "heat2-%04d%s" % (pair, "hf"[j]), pair)
            e = V.check_incident(r)
            if e:
                for y in set(z.split(":")[0] for z in e):
                    fails[("heat " if j == 0 else "fault ") + y] += 1
                if a.show:
                    print(r["id"], r["family"], e[:4])
                break
            out.append(r)
        if len(out) != 2:
            continue
        rows += out
        pair += 1
    return rows, fails, tries


def md5f(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def write(p, rows):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def mix_into(data_dir, src):
    """append heat_r2 train rows to <data_dir>/incidents3_train.jsonl (deterministic interleave), re-verify, refresh manifest/MD5SUMS"""
    p = os.path.join(data_dir, "incidents3_train.jsonl")
    base = [l for l in open(p, encoding="utf-8")]
    if any('"family": "heat_r2:' in l for l in base):
        sys.exit("already mixed: %s holds heat_r2 rows" % p)
    add = [l if l.endswith("\n") else l + "\n" for l in open(src, encoding="utf-8")]
    for l in add:
        if V.check_incident(json.loads(l)):
            sys.exit("a heat_r2 row fails verify.py; regenerate")
    R = random.Random(2612)
    out = list(base)
    for l in add:
        out.insert(R.randrange(0, len(out) + 1), l)
    before = md5f(p)
    with open(p + ".part", "w", encoding="utf-8", newline="\n") as f:
        f.writelines(out)
    os.replace(p + ".part", p)
    after = md5f(p)
    mp = os.path.join(data_dir, "manifest.json")
    if os.path.exists(mp):
        m = json.load(open(mp))
        m["files"]["incidents3_train.jsonl"] = {"bytes": os.path.getsize(p), "md5": after, "rows": len(out)}
        m["heat_r2"] = {"rows_added": len(add), "source": os.path.relpath(src, V3).replace("\\", "/"), "source_md5": md5f(src),
                        "incidents3_md5_before": before}
        json.dump(m, open(mp, "w"), indent=1)
    sp = os.path.join(data_dir, "MD5SUMS")
    if os.path.exists(sp):
        lines = []
        for ln in open(sp):
            name = ln.split()[1].lstrip("./") if len(ln.split()) > 1 else ""
            if name in ("incidents3_train.jsonl", "manifest.json") and os.path.exists(os.path.join(data_dir, name)):
                ln = "%s  ./%s\n" % (md5f(os.path.join(data_dir, name)), name)
            lines.append(ln)
        open(sp, "w").writelines(lines)
    print("mixed %d heat_r2 rows into %s: %d rows, md5 %s -> %s" % (len(add), p, len(out), before, after))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(V3, "data", "heat_r2"))
    ap.add_argument("--pairs", type=int, default=120)
    ap.add_argument("--seed", type=int, default=2611)
    ap.add_argument("--dev-frac", type=float, default=0.2)
    ap.add_argument("--no-compact", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--mix-into", default="", help="kaggle/build/<RUN>/data dir: append <out>/train.jsonl to its incidents3_train.jsonl")
    a = ap.parse_args()
    if a.mix_into:
        mix_into(a.mix_into, os.path.join(a.out, "train.jsonl"))
        return
    assert a.seed not in (7, 31), "seeds 7/31 belong to the round-1 / rsn_v3 r1 incident sets"
    rows, fails, tries = generate(a)
    cst = collections.Counter()
    final = []
    for r in rows:
        if not a.no_compact:
            r, st = compact_row(r)
            cst[st] += 1
        assert not V.check_incident(r), r["id"]
        fr = fix(dict(r))           # short deployed system prompt, as every r1 incident row
        fr["pair"] = r["pair"]
        assert not V.check_incident(dict(fr, meta=r["meta"])), r["id"]
        final.append(fr)
    pairs = sorted({r["pair"] for r in final})
    R = random.Random(a.seed + 1)
    R.shuffle(pairs)
    ndev = int(round(len(pairs) * a.dev_frac))
    devp = set(pairs[:ndev])
    train = [r for r in final if r["pair"] not in devp]
    dev = [r for r in final if r["pair"] in devp]
    R.shuffle(train)
    os.makedirs(a.out, exist_ok=True)
    pt, pd = os.path.join(a.out, "train.jsonl"), os.path.join(a.out, "dev.jsonl")
    write(pt, train)
    write(pd, dev)

    def comp(rs):
        c = collections.Counter()
        for r in rs:
            rep = json.loads(r["messages"][-1]["content"])
            c["%s/%s" % (rep["severity"], rep["label"])] += 1
            c["first_action:" + rep["checklist"][0]["action"]] += 1
            c["family:" + r["family"].split(":")[1].split("+")[0]] += 1
            c["agent_wrong"] += int("+agent_" in r["family"])
        return dict(sorted(c.items()))
    man = {"generator": "proofs/2026-10-29_rsn_v3/pipeline/gen_heat_r2.py", "seed": a.seed, "pairs": len(pairs), "dev_frac": a.dev_frac,
           "split": "by pair (a heat row and its fault twin are always in the same split)", "synthetic_only": True,
           "rows": {"train": len(train), "dev": len(dev)}, "train": comp(train), "dev": comp(dev),
           "verify_py": "all rows pass round-1 verify.py check_incident (%d generation attempts, failures dropped: %s)" % (tries, dict(fails)),
           "compact": dict(cst), "system_prompt": "SYSTEM_INCIDENT_SHORT (build_mix.fix)",
           "md5": {"train.jsonl": md5f(pt), "dev.jsonl": md5f(pd), "gen_heat_r2.py": md5f(os.path.abspath(__file__))},
           "go_gate": "run pipeline/heat_r2_go_check.sh (writes go_gate.json here)"}
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    print(json.dumps({"rows": man["rows"], "train": man["train"], "fails": dict(fails), "compact": dict(cst)}, indent=1))


if __name__ == "__main__":
    main()
