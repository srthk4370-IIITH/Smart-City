"""Synthetic incident families with causal ground truth. Each family builds 5-min series per sensor, evidence lines
with the backend wording (lib.evidence), agent findings (correct, or wrong in the ways observed on the live model),
and the truth the writer turns into the gold report."""
import datetime as dt
import math

import lib as L
import textbank as T
from lib import fmt

B_TRAIN = ["KH", "VN", "BK", "KN", "OB", "NB"]
B_HELD = ["TH", "PB"]


# ---------------------------------------------------------------- helpers
def ser(R, n, f, noise, dec, lo=None, hi=None):
    xs = []
    for i in range(n):
        v = f(i) + R.gauss(0, noise)
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        xs.append(round(v, dec))
    return xs


FORCE_END = [None]


def end_time(R, split, hours, day=None):
    if FORCE_END[0] is not None:
        return FORCE_END[0]
    if split == "heldout":
        d0 = dt.date(2026, 10, 1) + dt.timedelta(days=R.randrange(0, 90))
    else:
        d0 = dt.date(2026, 1, 1) + dt.timedelta(days=R.randrange(0, 270))
    if day == "workday":
        while d0.weekday() >= 5 or d0 in L.HOLIDAYS:
            d0 += dt.timedelta(days=1)
    elif day == "off":
        if R.random() < 0.35:
            hs = [h for h in L.HOLIDAYS if (h.year == 2026 and ((split == "heldout") == (h.month >= 10)))]
            d0 = R.choice(hs) if hs else d0
        else:
            while d0.weekday() < 5:
                d0 += dt.timedelta(days=1)
    h = R.choice(hours)
    return dt.datetime(d0.year, d0.month, d0.day, h, R.choice(range(0, 60, 5)), tzinfo=L.IST)


class Case:
    def __init__(self, R, fam, end, split):
        self.R, self.fam, self.end, self.split = R, fam, end, split
        self.sensors, self.extra = [], {}
        self.t = dict(checks=[], suspects=[], obs=[], actions=[], nmd=False, deeper=False, conf=0.85)

    def add(self, role, metric, node, loc, xs, flagged=True, why=None, agent=None, hist=False, quality="good", head=None,
            ac=None, setp=None, stale=None, n_ev=4, rule=("?", "?")):
        ref = "S%d" % (len(self.sensors) + 1)
        s = dict(ref=ref, role=role, metric=metric, node=node, loc=loc, flagged=flagged, why=why, quality=quality,
                 head=head or [], stale=stale, n_ev=n_ev, rule=rule, xs=xs)
        if stale:
            s["ev"] = []
        elif role == "hvac":
            hh = None
            if hist:
                hh = ser(self.R, 96, lambda i: xs[0], 0.1, 1) + xs
            s["ev"] = L.hvac_evidence(xs, ac, setp, self.end, hist=hh)
            s["ac"] = ac
        else:
            hh = None
            if hist is True and role != "occupancy":
                dec = L.METRICS[(role, metric)][1]
                nz = max(L.stdev([xs[i] - xs[i - 1] for i in range(1, len(xs))]) / 1.4, 10 ** -dec)
                hh = ser(self.R, 96, lambda i: xs[0], nz, dec) + xs
            elif isinstance(hist, list):
                hh = hist
            s["ev"] = L.evidence(role, metric, xs, self.end, hh)
        if agent:
            s["agent"] = agent(s) if callable(agent) else agent
        else:
            s["agent"] = None
        self.sensors.append(s)
        return s


def ag(pattern, status, cause, conf, obs):
    return {"pattern": pattern, "status": status, "cause": cause, "conf": conf, "obs": obs}


# agent-style observation strings ([E#] ids, backend agent phrasing)
def a_trend(s):
    p = T.parse(s)
    u = T.unit_of(s)
    ru = u or ("level" if s["metric"] == "level" else "")
    if "slope" not in p:
        return "%s changing [E4]" % T.W(s)
    up = not p["slope"].startswith("-")
    return "%s %s at %s%s/h, now %s%s [E4,E1]" % (T.W(s), "climbing" if up else "falling", p["slope"], (" " + ru) if ru else "",
                                                 p.get("last", "?"), T.uu(s))


def a_limit(s, lim, which):
    p = T.parse(s)
    us = T.uu(s)
    return "%s%s exceeds the %s limit of %s%s [E1]" % (p.get("last", "?"), us, which, T.lim_s(lim), us)


def a_steady(s):
    p = T.parse(s)
    return "%s steady around %s%s [E1,E4]" % (T.W(s), p.get("last", "?"), T.uu(s))


def sev_hi(v, warn, crit):
    return "critical" if v >= crit else ("warning" if v >= warn else "normal")


def place_of(loc):
    parts = [x.strip() for x in loc.split(",")]
    return ", ".join(parts[:2]) if len(parts) > 2 else loc


def bld(R, split):
    return R.choice(B_HELD if split == "heldout" else B_TRAIN)


def obs_add(c, *items):
    for it in items:
        if it and len(c.t["obs"]) < 5:
            c.t["obs"].append(it)


def check(c, s, claim, verdict, fact, src):
    c.t["checks"].append({"ref": s["ref"], "claim": claim, "verdict": verdict, "fact": fact, "src": src})


def lastv(s):
    return T.parse(s).get("last")


# ---------------------------------------------------------------- room families
def room(R, split):
    b = bld(R, split)
    fl = R.choice([0, 1, 2, 3, 4])
    k = R.choice(range(1, 6))
    return b, fl, k


def f_vent_fail(R, split):
    end = end_time(R, split, range(10, 18), "workday")
    c = Case(R, "ventilation_failure", end, split)
    b, fl, k = room(R, split)
    top = R.choice([1050, 1250, 1450, 1600, 1900])
    t0 = R.randrange(8, 20)
    co2 = ser(R, 48, lambda i: 520 if i < t0 else 520 + (top - 520) * ((i - t0) / (47 - t0)) ** 1.4, 12, 0, 380)
    sv = sev_hi(co2[-1], 1000, 1500)
    n, loc = L.node_aq(b, fl, k)
    err = R.random()
    s1 = c.add("air_quality", "co2", n, loc, co2, hist=True,
               agent=lambda s: ag("exponential_increase", sv if err > 0.2 else "normal", "ventilation_insufficient" if err > 0.35 else "occupancy_load",
                                  0.8, [a_trend(s)] + ([a_limit(s, 1000 if sv == "warning" else 1500, sv)] if sv != "normal" else [])))
    an, aloc = L.node_ac(b, fl, k)
    ac = [1] * t0 + [0] * (48 - t0)
    rt = ser(R, 48, lambda i: 24.5 + max(0, i - t0) * 0.06, 0.08, 1)
    s2 = c.add("hvac", "room_temp", an, aloc, rt, False, "AC serving the same room", ac=ac, setp=24.0,
               agent=ag("unit_off", "warning", "unit_tripped", 0.75, ["AC stopped at %s and has not restarted [E5]" % L.idx_time(end, 48, t0)]))
    on, oloc = L.node_occ(b, k)
    s3 = c.add("occupancy", "occ", on, oloc, [1] * 48, False, "occupancy of the same room",
               agent=ag("occupied", "normal", "normal_occupancy", 0.9, ["Room occupied all window [E1,E2]"]))
    if sv == "normal":
        sv = "warning"   # rising fast with ventilation lost: likely to reach the limit
    if err <= 0.2:
        check(c, s1, "status normal", "corrected", "CO2 %s ppm and rising with the AC stopped" % lastv(s1), [s1["ref"] + ".E1", s1["ref"] + ".E4", s2["ref"] + ".E5"])
    c.t.update(label="ventilation_issue", sev=sv, root=s1, domains=["air_quality", "hvac", "occupancy"],
               event=R.choice(["CO2 %s ppm, AC stopped" % lastv(s1), "Ventilation lost, CO2 at %s ppm" % lastv(s1),
                               "CO2 rising after AC stop"]),
               root_cause=R.choice(["The AC/fresh-air unit stopped while the room stayed occupied, so CO2 builds up.",
                                    "Ventilation failure: the unit serving the room stopped and CO2 is accumulating with people present.",
                                    "Air exchange stopped when the AC went off; occupants keep adding CO2."]),
               chain="AC stopped (%s.E5) -> no fresh air while occupied (%s.E1) -> CO2 rising (%s.E4)" % (s2["ref"], s3["ref"], s1["ref"]),
               expl=R.choice(["CO2 keeps rising because the room's AC stopped while people are inside. Restore ventilation.",
                              "The unit that ventilates this room is off and the room is occupied, so CO2 is climbing."]),
               actions=[("inspect_ventilation", s1), ("inspect_hvac", s2)] + ([("request_facility_review", s1)] if sv == "critical" else []),
               mon=("CO2", "AC state"))
    obs_add(c, T.o_trend(R, s1), T.o_now(R, s1) if R.random() < .5 else T.o_path(R, s1), T.o_ac(R, s2), T.o_occ(R, s3))
    return c


def f_class_fills(R, split):
    """§5.8 CO2 + power (occupancy), onsets 0-60 min apart"""
    end = end_time(R, split, range(10, 17), "workday")
    c = Case(R, "occupancy_load", end, split)
    b, fl, k = room(R, split)
    t_occ = R.randrange(4, 20)
    t_pw = t_occ + R.randrange(0, 13)
    rate = R.choice([35, 50, 70, 90])
    co2 = ser(R, 48, lambda i: 450 + max(0, i - t_occ) * rate / 3.0, 14, 0)
    pk = R.choice([3.0, 5.0, 8.0, 12.0])
    pw = ser(R, 48, lambda i: pk + max(0, i - t_pw) * pk * 0.02, pk * 0.02, 2, 0)
    occ = [0] * t_occ + [1] * (48 - t_occ)
    n, loc = L.node_aq(b, fl, k)
    sv = sev_hi(co2[-1], 1000, 1500)
    s1 = c.add("air_quality", "co2", n, loc, co2, hist=True,
               agent=lambda s: ag("gradual_increase", sv, R.choice(["occupancy_load", "ventilation_insufficient"]), 0.75,
                                  [a_trend(s)] + ([a_limit(s, 1000 if sv == "warning" else 1500, sv)] if sv != "normal" else [])))
    en, eloc = L.node_em(b, fl, R.choice([1, 2]))
    s2 = c.add("power", "power_kw", en, eloc, pw, R.random() < 0.5, "energy meter of the same floor",
               agent=lambda s: ag("gradual_increase", "warning", "gradual_load_growth", 0.7, [a_trend(s)]))
    on, oloc = L.node_occ(b, k)
    s3 = c.add("occupancy", "occ", on, oloc, occ, False, "occupancy of the same room",
               agent=ag("arrival", "normal", "arrival", 0.9, ["People arrived at %s [E4]" % L.idx_time(end, 48, t_occ)]))
    if s2["agent"]["status"] == "warning" and sv != "critical":
        check(c, s2, "power status warning", "corrected", "the load rise follows people arriving; it is expected use",
              [s3["ref"] + ".E4", s2["ref"] + ".E4"])
    acts = [("monitor", s1)] if sv == "normal" else [("inspect_ventilation", s1), ("monitor", s2)]
    if sv == "critical":
        acts = [("inspect_ventilation", s1), ("request_facility_review", s1)]
    c.t.update(label="occupancy_driven_load", sev=sv, root=s1, domains=["air_quality", "power", "occupancy"],
               event=R.choice(["CO2 %s ppm as the room fills" % lastv(s1), "Room in use: CO2 and power rising",
                               "Occupancy load, CO2 %s ppm" % lastv(s1)]),
               root_cause=R.choice(["People arrived; their breathing raises CO2 and their equipment raises the power draw.",
                                    "Normal occupancy load: the room filled and CO2 and power rose together.",
                                    "A class or meeting started, driving CO2 and electrical load up."]),
               chain="arrival (%s.E4) -> CO2 rise (%s.E4) and load rise (%s.E4)" % (s3["ref"], s1["ref"], s2["ref"]),
               expl=R.choice(["The room is in use. CO2 and power rose after people arrived; " +
                              ("ventilation should be increased for this many people." if sv != "normal" else "this is expected."),
                              "Both rises follow the arrival of people, so they share one cause: occupancy."]),
               actions=acts, mon=("CO2", "occupancy"), conf=0.85)
    obs_add(c, T.o_occ(R, s3), T.o_trend(R, s1), T.o_now(R, s1), T.o_trend(R, s2))
    return c


def f_heat_load(R, split):
    end = end_time(R, split, range(12, 17), "workday")
    c = Case(R, "heatwave_cooling_load", end, split)
    b, fl, k = room(R, split)
    ot = R.choice([36.5, 38.5, 40.0, 42.5])
    wt = ser(R, 48, lambda i: ot - 4 + 4 * i / 47, 0.25, 1)
    rmax = R.choice([26.5, 28.0, 30.5])
    rt = ser(R, 48, lambda i: 25 + (rmax - 25) * i / 47, 0.1, 1)
    pk = R.choice([20.0, 32.0, 55.0])
    pw = ser(R, 48, lambda i: pk + pk * 0.5 * i / 47, pk * 0.01, 2)
    c.extra["outdoor"] = (fmt(wt[-1], 1), L.WEATHER[0], L.tstr(end))
    s1 = c.add("weather", "temp", L.WEATHER[0], L.WEATHER[1], wt, True, hist=True,
               agent=lambda s: ag("gradual_increase", sev_hi(wt[-1], 38, 42), "heat_buildup", 0.8, [a_trend(s)]))
    en, eloc = L.node_em(b, fl, 1)
    s2 = c.add("power", "power_kw", en, eloc, pw, True, hist=True,
               agent=lambda s: ag("gradual_increase", "warning", R.choice(["gradual_load_growth", "load_surge"]), 0.7, [a_trend(s)]))
    an, aloc = L.node_ac(b, fl, k)
    s3 = c.add("hvac", "room_temp", an, aloc, rt, False, "AC unit on the same floor", ac=[1] * 48, setp=24.0,
               agent=ag("rising", "warning" if rmax >= 30 else "normal", "high_heat_load", 0.75, ["Room warming with the AC on [E4,E5]"]))
    sv = "critical" if wt[-1] >= 42 else ("warning" if wt[-1] >= 38 or rt[-1] >= 30 else "normal")
    acts = [("monitor", s2), ("review_schedule", s3)] if sv != "critical" else [("inspect_hvac", s3), ("request_facility_review", s2)]
    if rt[-1] >= 30 and sv != "critical":
        acts = [("inspect_hvac", s3), ("monitor", s2)]
    c.t.update(label="weather_driven", sev=sv, root=s1, domains=["weather", "power", "hvac"],
               event=R.choice(["Heat drives cooling load, outdoor %s C" % lastv(s1), "Hot afternoon: AC load up",
                               "Outdoor heat %s C raising power draw" % lastv(s1)]),
               root_cause=R.choice(["Outdoor heat is the shared cause: the AC works harder, so power and room temperature both rise.",
                                    "A hot afternoon raises the cooling load; power and room temperature follow the outdoor temperature."]),
               chain="outdoor heat (%s.E4) -> AC cooling load -> power up (%s.E4), room warming (%s.E4)" % (s1["ref"], s2["ref"], s3["ref"]),
               expl=R.choice(["The power rise is caused by outdoor heat, not by a fault: the AC is working harder.",
                              "Heat outside is pushing the AC load and room temperature up together; both share one cause."]),
               actions=acts, mon=("power", "room temperature"))
    obs_add(c, T.o_trend(R, s1), T.o_now(R, s1), T.o_trend(R, s2), T.o_ac(R, s3))
    return c


def f_ac_fail_hot(R, split):
    """G2: AC on, room heats on a hot weekday afternoon; agent may claim 'stuck on at night/weekend'"""
    end = end_time(R, split, range(12, 18), "workday")
    c = Case(R, "ac_cooling_failure", end, split)
    b, fl, k = room(R, split)
    top = R.choice([28.8, 30.2, 31.5, 34.4])
    rt = ser(R, 48, lambda i: 25.3 + (top - 25.3) * i / 47, 0.1, 1)
    ot = R.choice([33.5, 34.8, 36.2])
    wt = ser(R, 48, lambda i: ot, 0.3, 1)
    c.extra["outdoor"] = (fmt(wt[-1], 1), L.WEATHER[0], L.tstr(end))
    an, aloc = L.node_ac(b, fl, R.randrange(10, 30))
    wrong = R.random() < 0.6
    s1 = c.add("hvac", "room_temp", an, aloc, rt, True, ac=[1] * 48, setp=R.choice([24.0, 25.0, 26.0]), hist=True,
               agent=(ag("stuck_on", "warning", "schedule_or_control_fault", 0.7,
                         ["Unit kept running at night/weekend though room is at setpoint [E5,E8]", "48 of 48 samples on, wasting energy [E5]"])
                      if wrong else ag("rising", "warning", "hvac_cooling_issue", 0.75, ["Room warming while the AC runs [E4,E5]"])))
    s2 = c.add("weather", "temp", L.WEATHER[0], L.WEATHER[1], wt, False, "outdoor conditions", n_ev=2,
               agent=lambda s: ag("stable", "normal", "normal_weather", 0.85, [a_steady(s)]))
    sv = "critical" if rt[-1] >= 34 else "warning"
    if wrong:
        check(c, s1, "running at night/weekend", "contradicted", "it is a %s afternoon (window end %s)" % (end.strftime("%A"), L.tstr(end)),
              [s1["ref"] + ".E8"])
        check(c, s1, "room is at setpoint", "corrected", "room is %s C and rising" % lastv(s1), [s1["ref"] + ".E1", s1["ref"] + ".E4"])
    c.t.update(label="hvac_or_thermal_issue", sev=sv, root=s1, domains=["hvac", "weather"],
               event=R.choice(["AC running but room heating to %s C" % lastv(s1), "Cooling failure: room %s C with AC on" % lastv(s1),
                               "AC not cooling, room temperature rising"]),
               root_cause=R.choice(["The AC runs continuously but cannot hold the setpoint on a hot afternoon: a cooling failure.",
                                    "Cooling failure: the unit is on all window while the room keeps warming.",
                                    "The AC is not delivering cooling (low refrigerant, dirty filter or failed compressor)."]),
               chain="AC on all window (%s.E5) -> room still warming (%s.E4) -> cooling capacity lost" % (s1["ref"], s1["ref"]),
               expl=R.choice(["This is not a schedule problem: it is a weekday afternoon and the room is getting hotter even though the AC is on.",
                              "The AC is running but the room keeps warming, so the unit is not cooling. Get it inspected."]),
               actions=[("inspect_hvac", s1)] + ([("request_facility_review", s1)] if sv == "critical" else [("monitor", s1)]),
               mon=("room temperature", "AC state"))
    obs_add(c, T.o_ac(R, s1), T.o_quote(R, s1, "E1"), T.o_quote(R, s1, "E4"), T.o_now(R, s2))
    return c


def f_ac_after_hours(R, split):
    night = R.random() < 0.5
    end = end_time(R, split, [22, 23, 0, 1, 2, 3, 4] if night else range(10, 17), None if night else "off")
    c = Case(R, "ac_after_hours", end, split)
    b, fl, k = room(R, split)
    sp = R.choice([23.0, 24.0, 25.0])
    rt = ser(R, 48, lambda i: sp + 0.3, 0.1, 1)
    an, aloc = L.node_ac(b, fl, R.randrange(10, 30))
    s1 = c.add("hvac", "room_temp", an, aloc, rt, True, ac=[1] * 48, setp=sp,
               agent=ag("stuck_on", "warning", "schedule_or_control_fault", 0.75, ["Unit running all window with nobody present [E5,E8]"]))
    on, oloc = L.node_occ(b, k)
    s2 = c.add("occupancy", "occ", on, oloc, [0] * 48, False, "occupancy of the same room",
               agent=ag("vacant", "normal", "vacant", 0.9, ["No presence detected [E2]"]))
    dtp = L.day_type(end)
    c.t.update(label="hvac_or_thermal_issue", sev="warning", root=s1, domains=["hvac", "occupancy"],
               event=R.choice(["AC running in an empty room", "AC on after hours, room vacant", "AC left on (%s)" % ("night" if night else dtp.split(":")[-1])]),
               root_cause=R.choice(["The AC runs although the room is empty %s: a schedule or control fault wasting energy." % ("at night" if night else "on a day off"),
                                    "Schedule fault: the unit keeps cooling an unoccupied room."]),
               chain="room vacant (%s.E2) -> AC still on (%s.E5) -> energy wasted" % (s2["ref"], s1["ref"]),
               expl=R.choice(["Nobody is in the room but the AC has run the whole window. Check the timer or controller schedule.",
                              "The AC is cooling an empty room %s; fix the schedule." % ("at night" if night else "on a day off")]),
               actions=[("review_schedule", s1), ("inspect_hvac", s1)], mon=("AC state", "occupancy"))
    obs_add(c, T.o_ac(R, s1), T.o_occ(R, s2), T.o_quote(R, s1, "E8"))
    return c


def f_dust_ingress(R, split):
    """E1 (title must name PM, not wind), E2 (no unit mixing), §5.8 outdoor + indoor PM"""
    end = end_time(R, split, range(9, 19))
    c = Case(R, "pollution_ingress", end, split)
    b = bld(R, split)
    p25 = R.choice([75, 110, 150, 190])
    pm25 = ser(R, 48, lambda i: 30 + (p25 - 30) * i / 47, 3, 1, 0)
    pm10 = ser(R, 48, lambda i: 60 + (p25 * 2.1 - 60) * i / 47, 7, 1, 0)
    wind = ser(R, 48, lambda i: 3 + R.choice([7.5, 9.5, 11.0]) * i / 47 if False else 3 + 9.5 * i / 47, 0.4, 2, 0)
    on, oloc = L.node_out(b)
    sv25, sv10 = sev_hi(pm25[-1], 60, 120), sev_hi(pm10[-1], 100, 250)
    order = ["critical", "warning", "normal"]
    sv = sv25 if order.index(sv25) <= order.index(sv10) else sv10
    mix = R.random() < 0.5
    sw = c.add("weather", "wind", L.WEATHER[0], L.WEATHER[1], wind, True,
               agent=lambda s: ag("gradual_increase", sev_hi(wind[-1], 10, 15), "weather_front", 0.8,
                                  [a_trend(s)] + (["Outdoor pollution moving at %s m/s/h [E4]" % T.parse(s)["slope"]] if mix else [])))
    s1 = c.add("air_quality", "pm25", on, oloc, pm25, True, hist=True,
               agent=lambda s: ag("gradual_increase", sv25, "outdoor_pollution_ingress", 0.8,
                                  [a_trend(s)] + ([a_limit(s, 60 if sv25 == "warning" else 120, sv25)] if sv25 != "normal" else [])))
    s2 = c.add("air_quality", "pm10", on, oloc, pm10, True,
               agent=lambda s: ag("gradual_increase", sv10, "outdoor_pollution_ingress", 0.8, [a_trend(s)]))
    root = s1 if order.index(sv25) <= order.index(sv10) else s2
    s3 = None
    if R.random() < 0.6:
        lag = R.randrange(2, 13)
        ind = ser(R, 48, lambda i: 18 + max(0, i - lag) * (p25 * 0.5 - 18) / (47 - lag), 2, 1, 0)
        an, aloc = L.node_aq(b, R.choice([1, 2, 3]), R.choice([1, 2]))
        s3 = c.add("air_quality", "pm25", an, aloc, ind, False, "indoor air in the same building", n_ev=3,
                   agent=lambda s: ag("gradual_increase", sev_hi(ind[-1], 60, 120), "outdoor_pollution_ingress", 0.7, [a_trend(s)]))
    if mix:
        check(c, sw, "Outdoor pollution moving at %s m/s/h" % T.parse(sw)["slope"], "unsupported",
              "that rate is wind speed in m/s per hour, not a pollution measure", [sw["ref"] + ".E4"])
    acts = [("inspect_ventilation", s3 or root), ("request_facility_review", root)] if sv == "critical" else [("inspect_ventilation", s3 or root), ("monitor", root)]
    c.t.update(label="air_pollution_event", sev=sv, root=root, domains=["air_quality", "weather"],
               event=R.choice(["Dust storm: %s %s ug/m3" % (T.W(root), lastv(root)), "Outdoor dust, %s %s %s" % (T.W(root), sv, ""),
                               "%s at %s ug/m3 with rising wind" % (T.W(root), lastv(root))]).replace("  ", " ").strip(),
               root_cause=R.choice(["Rising wind is lifting dust: outdoor PM2.5 and PM10 climb together%s." % (" and it enters the building" if s3 else ""),
                                    "A dust event driven by strong wind raises outdoor particulates%s." % (", leaking indoors" if s3 else "")]),
               chain="wind rising (%s.E4) -> dust lifted -> PM2.5 (%s.E4), PM10 (%s.E4)%s" % (sw["ref"], s1["ref"], s2["ref"], (" -> indoor PM (%s.E4)" % s3["ref"]) if s3 else ""),
               expl=R.choice(["Wind is lifting dust; outdoor particulate levels are %s. Keep outdoor air out of occupied rooms and check filters." % sv,
                              "Outdoor PM is %s because of a wind-driven dust event%s." % (sv, "; it is reaching indoor air" if s3 else "")]),
               actions=acts, mon=("PM2.5", "wind speed"))
    lim = {"pm25": {"warning": 60, "critical": 120}, "pm10": {"warning": 100, "critical": 250}}[root["metric"]].get(sv)
    obs_add(c, T.o_limit(R, root, lim, sv) if lim else T.o_now(R, root),
            T.o_trend(R, s1), T.o_trend(R, s2), T.o_trend(R, sw), T.o_trend(R, s3) if s3 else None)
    return c


def f_indoor_emission(R, split):
    end = end_time(R, split, range(9, 19))
    c = Case(R, "indoor_emission", end, split)
    b, fl, k = room(R, split)
    top = R.choice([70, 95, 140])
    t0 = R.randrange(10, 30)
    ind = ser(R, 48, lambda i: 15 if i < t0 else 15 + (top - 15) * min(1, (i - t0) / 8), 2, 1, 0)
    out = ser(R, 48, lambda i: 28, 2, 1, 0)
    n, loc = L.node_aq(b, fl, k)
    sv = sev_hi(ind[-1], 60, 120)
    s1 = c.add("air_quality", "pm25", n, loc, ind, True, hist=True,
               agent=lambda s: ag("step_increase", sv, R.choice(["indoor_emission_source", "outdoor_pollution_ingress"]), 0.7, [a_trend(s)]))
    on, oloc = L.node_out(b)
    s2 = c.add("air_quality", "pm25", on, oloc, out, False, "outdoor air of the same building",
               agent=lambda s: ag("stable", "normal", "normal_conditions", 0.85, [a_steady(s)]))
    if s1["agent"]["cause"] == "outdoor_pollution_ingress":
        check(c, s1, "cause outdoor pollution ingress", "contradicted", "outdoor PM2.5 is steady at %s ug/m3" % lastv(s2), [s2["ref"] + ".E1"])
    c.t.update(label="air_pollution_event", sev=sv, root=s1, domains=["air_quality"],
               event=R.choice(["Indoor PM2.5 source, %s ug/m3" % lastv(s1), "PM2.5 %s ug/m3 from an indoor source" % lastv(s1)]),
               root_cause=R.choice(["Particulates come from inside the room (cooking, cleaning, printing or works); outdoor air is clean.",
                                    "An indoor emission source: indoor PM2.5 jumped while outdoor PM2.5 stayed low."]),
               chain="indoor source -> PM2.5 step (%s.E5) while outdoor steady (%s.E1)" % (s1["ref"], s2["ref"]),
               expl="Indoor dust or smoke, not outdoor pollution: find the source in the room and ventilate.",
               actions=[("inspect_ventilation", s1)] + ([("request_facility_review", s1)] if sv == "critical" else [("monitor", s1)]),
               mon=("indoor PM2.5", "outdoor PM2.5"))
    obs_add(c, T.o_jump(R, s1), T.o_now(R, s1), T.o_steady(R, s2))
    return c


# ---------------------------------------------------------------- water families
def tank_head(hi, ov):
    return ["TANK: high level above %s, overflow risk above %s; usual fill up to 90 min" % (fmt(hi, 1), fmt(ov, 1))]


def f_slow_leak(R, split):
    night = R.random() < 0.5
    end = end_time(R, split, [23, 0, 1, 2, 3, 4] if night else range(10, 18))
    c = Case(R, "slow_leak", end, split)
    b = bld(R, split)
    start = R.choice([300.0, 260.0, 220.0])
    rate = R.choice([6.0, 9.0, 11.5, 14.0])
    lv = ser(R, 48, lambda i: start - rate * i / 12.0, 1.2, 1, 0)
    fl = ser(R, 48, lambda i: R.choice([0.3]) if night else 5.0, 0.15, 2, 0)
    tn, tloc = L.node_tank(b)
    hi, ov = round(start * 0.62, 1), round(start * 0.75, 1)
    stale = R.random() < 0.55
    s1 = c.add("water", "level", tn, tloc, lv, True, hist=True, head=tank_head(hi, ov),
               agent=lambda s: ag("gradual_decrease", "normal", "tank_draining", 0.7,
                                  ["Tank level keeps falling, %s level/h with r2 %s [E4]" % (T.parse(s)["slope"], T.parse(s)["r2"])] +
                                  (["Level %s level is past the high mark of %s; overflow risk [E2]" % (T.parse(s)["max"], fmt(hi, 1))] if stale else [])))
    fn, floc = L.node_flow(b)
    s2 = c.add("water", "flow", fn, floc, fl, False, "outflow to the building from the same tank",
               agent=lambda s: ag("stable", "normal", "normal_usage", 0.85, [a_steady(s)]))
    on, oloc = L.node_occ(b, 1)
    s3 = c.add("occupancy", "occ", on, oloc, [0] * 48 if night or R.random() < .5 else [1] * 48, False, "occupancy of the building",
               agent=ag("vacant", "normal", "vacant", 0.9, ["No presence detected [E2]"]))
    check(c, s1, "status normal (tank draining)", "corrected",
          "level falls %s per hour with steady outflow; that loss is not explained by use" % T.absn(T.parse(s1)["slope"]),
          [s1["ref"] + ".E4", s2["ref"] + ".E1"])
    if stale:
        check(c, s1, "past the high mark; overflow risk", "stale",
              "%s was the earlier maximum; the level is now %s and falling" % (T.parse(s1)["max"], lastv(s1)), [s1["ref"] + ".E2", s1["ref"] + ".E1"])
    c.t.update(label="water_leak_or_overuse", sev="warning", root=s1, domains=["water"],
               event=R.choice(["Slow tank leak suspected, level falling", "Tank level falling with no matching use",
                               "Possible leak: tank level down to %s" % lastv(s1)]),
               root_cause=R.choice(["Water is lost from the tank faster than the metered outflow explains: a slow leak or open valve.",
                                    "A steady unexplained loss from the tank points to a leak, overflow pipe or valve left open."]),
               chain="tank level falling steadily (%s.E4) while outflow steady (%s.E1)%s -> unmetered loss" % (s1["ref"], s2["ref"], " and building vacant (%s.E2)" % s3["ref"] if s3["xs"][-1] == 0 else ""),
               expl=R.choice(["The tank is losing water steadily but metered use has not changed. Check for a leak or an open valve.",
                              "This is not normal draining: the level keeps falling while outflow is flat. Look for a leak."]),
               actions=[("inspect_water_system", s1), ("monitor", s1)], mon=("tank level", "outflow"), conf=0.8)
    obs_add(c, T.o_trend(R, s1), T.o_path(R, s1), T.o_steady(R, s2), T.o_occ(R, s3))
    return c


def f_demand(R, split):
    end = end_time(R, split, range(8, 14), "workday")
    c = Case(R, "water_demand", end, split)
    b = bld(R, split)
    lv = ser(R, 48, lambda i: 280 - 12 * i / 12.0, 1.2, 1, 0)
    fl = ser(R, 48, lambda i: 9.0, 0.3, 2, 0)
    tn, tloc = L.node_tank(b)
    s1 = c.add("water", "level", tn, tloc, lv, True, head=tank_head(170, 210),
               agent=lambda s: ag("gradual_decrease", "warning", "possible_leak", 0.6, [a_trend(s)]))
    fn, floc = L.node_flow(b)
    s2 = c.add("water", "flow", fn, floc, fl, False, "outflow to the building from the same tank",
               agent=lambda s: ag("stable", "normal", "high_demand", 0.75, ["Outflow high at %s m3/h [E1]" % lastv(s)]))
    on, oloc = L.node_occ(b, 1)
    s3 = c.add("occupancy", "occ", on, oloc, [1] * 48, False, "occupancy of the building",
               agent=ag("occupied", "normal", "normal_occupancy", 0.9, ["Building occupied all window [E1,E2]"]))
    check(c, s1, "possible leak", "contradicted", "outflow is high at %s m3/h with the building occupied" % lastv(s2), [s2["ref"] + ".E1", s3["ref"] + ".E2"])
    c.t.update(label="normal_operation", sev="normal", root=s1, domains=["water", "occupancy"],
               event=R.choice(["Tank level falling with high daytime use", "Tank draining from normal demand"]),
               root_cause="Daytime demand: high outflow with the building occupied explains the falling tank level.",
               chain="occupied (%s.E2) -> high outflow (%s.E1) -> level falling (%s.E4)" % (s3["ref"], s2["ref"], s1["ref"]),
               expl="The tank is emptying because water is being used, not leaking. It should refill when the pump runs.",
               actions=[("monitor", s1)], mon=("tank level", "pump refill"))
    obs_add(c, T.o_trend(R, s1), T.o_now(R, s2), T.o_occ(R, s3))
    return c


def f_supply(R, split):
    end = end_time(R, split, range(6, 20))
    c = Case(R, "supply_interruption", end, split)
    b = bld(R, split)
    end_lv = R.choice([140, 90, 45])
    lv = ser(R, 48, lambda i: 230 - (230 - end_lv) * i / 47, 1.2, 1, 0)
    t0 = R.randrange(2, 12)
    inf = [round(max(0, (8.0 if i < t0 else 0.0) + R.gauss(0, 0.2 if i < t0 else 0)), 2) for i in range(48)]
    tn, tloc = L.node_tank(b)
    s1 = c.add("water", "level", tn, tloc, lv, True, head=tank_head(170, 210),
               agent=lambda s: ag("gradual_decrease", "warning", "tank_draining", 0.7, [a_trend(s)]))
    fn = "WM-WF-%s98-10" % b
    s2 = c.add("water", "flow", fn, "%s building, level 98, water flow meter 10" % b, inf, False, "supply inflow to the same tank",
               agent=lambda s: ag("step_decrease", "warning", "supply_interruption", 0.8, ["Inflow stopped at %s [E5]" % T.parse(s)["jump_t"]]))
    sv = "critical" if end_lv < 60 else "warning"
    c.t.update(label="water_supply_issue", sev=sv, root=s2 if R.random() < .5 else s1, domains=["water"],
               event=R.choice(["Water supply stopped, tank at %s" % lastv(s1), "Inflow stopped, tank level falling",
                               "Supply interruption: no inflow since %s" % T.parse(s2)["jump_t"]]),
               root_cause=R.choice(["The supply inflow stopped, so the tank only drains: pump failure or municipal supply cut.",
                                    "No inflow reaches the tank (pump or inlet valve), while the building keeps drawing water."]),
               chain="inflow stopped (%s.E5) -> no refill -> tank level falling (%s.E4)" % (s2["ref"], s1["ref"]),
               expl="The tank is not being refilled because the inflow stopped. Check the pump and supply before it runs dry.",
               actions=[("inspect_water_system", s2), ("request_facility_review", s1)], mon=("inflow", "tank level"))
    obs_add(c, T.o_jump(R, s2), T.o_trend(R, s1), T.o_now(R, s1))
    return c


def f_tank_fill(R, split):
    end = end_time(R, split, range(5, 22))
    c = Case(R, "tank_filling", end, split)
    b = bld(R, split)
    t0 = R.randrange(10, 30)
    inf = [round(max(0, (0.0 if i < t0 else 9.0) + (R.gauss(0, 0.2) if i >= t0 else 0)), 2) for i in range(48)]
    lv = ser(R, 48, lambda i: 120 + max(0, i - t0 - R.choice([0, 1])) * 3.5, 1.0, 1, 0)
    tn, tloc = L.node_tank(b)
    s1 = c.add("water", "level", tn, tloc, lv, True, head=tank_head(200, 240),
               agent=lambda s: ag("gradual_increase", R.choice(["normal", "warning"]), "tank_filling", 0.75, [a_trend(s)]))
    s2 = c.add("water", "flow", "WM-WF-%s98-10" % b, "%s building, level 98, water flow meter 10" % b, inf, R.random() < .5, "supply inflow to the same tank",
               agent=lambda s: ag("step_increase", R.choice(["normal", "warning"]), "pump_cycling", 0.75, ["Inflow started at %s [E5]" % T.parse(s)["jump_t"]]))
    for s in (s1, s2):
        if s["agent"]["status"] == "warning":
            check(c, s, "status warning", "corrected", "the pump started and the tank is refilling below the high mark", [s2["ref"] + ".E5", s1["ref"] + ".E1"])
    c.t.update(label="normal_operation", sev="normal", root=s1, domains=["water"],
               event=R.choice(["Tank refilling after pump start", "Pump on, tank level rising normally"]),
               root_cause="The supply pump started and the tank is refilling; level and inflow rise together as expected.",
               chain="pump start (%s.E5) -> inflow -> level rising (%s.E4)" % (s2["ref"], s1["ref"]),
               expl="Normal refill: the pump came on and the tank is filling below its high mark.",
               actions=[("monitor", s1)], mon=("tank level", "high mark"))
    obs_add(c, T.o_jump(R, s2), T.o_trend(R, s1), T.o_now(R, s1))
    return c


def f_overflow(R, split):
    end = end_time(R, split, range(0, 24))
    c = Case(R, "overflow_risk", end, split)
    b = bld(R, split)
    lv = ser(R, 48, lambda i: 190 + 60 * i / 47, 1.0, 1, 0)
    inf = ser(R, 48, lambda i: 9.0, 0.2, 2, 0)
    tn, tloc = L.node_tank(b)
    hi, ov = 200.0, 235.0
    s1 = c.add("water", "level", tn, tloc, lv, True, head=tank_head(hi, ov),
               agent=lambda s: ag("gradual_increase", "warning", "tank_filling", 0.7, [a_trend(s)]))
    s2 = c.add("water", "flow", "WM-WF-%s98-10" % b, "%s building, level 98, water flow meter 10" % b, inf, False, "supply inflow to the same tank",
               agent=lambda s: ag("stable", "normal", "normal_usage", 0.8, [a_steady(s)]))
    sv = "critical" if lv[-1] > ov else "warning"
    c.t.update(label="water_supply_issue", sev=sv, root=s1, domains=["water"],
               event=R.choice(["Tank overfilling, level %s" % lastv(s1), "Overflow risk: pump not stopping"]),
               root_cause="The pump keeps filling past the high mark: the level cut-off (float switch or controller) did not stop it.",
               chain="inflow continues (%s.E1) -> level above high mark (%s.E1) -> overflow risk" % (s2["ref"], s1["ref"]),
               expl="The tank is still filling above its high mark%s; the pump cut-off failed. Stop the pump manually after inspection." % (" and past the overflow mark" if sv == "critical" else ""),
               actions=[("inspect_water_system", s1)] + ([("request_facility_review", s1)] if sv == "critical" else [("monitor", s1)]),
               mon=("tank level", "inflow"))
    obs_add(c, T.o_now(R, s1), T.o_trend(R, s1), T.o_steady(R, s2))
    return c


def f_acidic(R, split):
    end = end_time(R, split, range(0, 24))
    c = Case(R, "water_quality_ph", end, split)
    b = bld(R, split)
    endv = R.choice([6.3, 6.08, 5.85, 5.6])
    ph = ser(R, 48, lambda i: 7.2 - (7.2 - endv) * i / 47, 0.03, 2)
    tds = ser(R, 48, lambda i: 150 + 40 * i / 47, 3, 0, 0)
    wn, wloc = L.node_wq(b)
    sv = "critical" if ph[-1] < 6.0 else ("warning" if ph[-1] < 6.5 else "normal")
    if sv == "normal":
        sv = "warning"
    claim_normal = R.random() < 0.5
    s1 = c.add("water", "ph", wn, wloc, ph, True, hist=True,
               agent=lambda s: ag("gradual_decrease", "warning", "water_quality_issue", 0.7,
                                  ["Gradual decline of %s pH/h; last %s pH [E4,E1]" % (T.parse(s)["slope"], lastv(s))] +
                                  (["Normal daily range for this sensor [E4]"] if claim_normal else [])))
    s2 = c.add("water", "tds", wn, wloc, tds, False, "same water quality sensor",
               agent=lambda s: ag("gradual_increase", "normal", "normal_usage", 0.75, [a_trend(s)]))
    if claim_normal:
        check(c, s1, "Normal daily range for this sensor", "contradicted", "pH %s is below the %s limit of %s" % (lastv(s1), sv, "6.0" if sv == "critical" else "6.5"),
              [s1["ref"] + ".E1", s1["ref"] + ".E4"])
    c.t.update(label="water_quality_issue", sev=sv, root=s1, domains=["water"],
               event=R.choice(["Acidic water: pH %s" % lastv(s1), "pH falling to %s in the tank" % lastv(s1), "Water pH below safe range"]),
               root_cause=R.choice(["The stored water is turning acidic (pH below 6.5), with TDS rising: contamination or a dosing fault.",
                                    "Water quality problem: pH keeps falling below the drinking-water range."]),
               chain="pH falling (%s.E4) below the limit (%s.E1), TDS rising (%s.E4) -> water quality issue" % (s1["ref"], s1["ref"], s2["ref"]),
               expl=R.choice(["The water is becoming acidic and is outside the safe drinking range. Get it tested before use.",
                              "pH is %s and still falling; this is a real water-quality problem, not normal variation." % lastv(s1)]),
               actions=[("request_facility_review", s1), ("inspect_water_system", s1)], mon=("pH", "TDS"))
    obs_add(c, T.o_limit(R, s1, "6.0" if sv == "critical" else "6.5", "low_" + sv), T.o_trend(R, s1), T.o_trend(R, s2))
    return c


def f_tds(R, split):
    end = end_time(R, split, range(0, 24))
    c = Case(R, "water_quality_tds", end, split)
    b = bld(R, split)
    top = R.choice([560, 780, 1080])
    tds = ser(R, 48, lambda i: 300 + (top - 300) * i / 47, 8, 0, 0)
    wn, wloc = L.node_wq(b)
    sv = sev_hi(tds[-1], 500, 1000)
    s1 = c.add("water", "tds", wn, wloc, tds, True, hist=True,
               agent=lambda s: ag("gradual_increase", sv, "water_quality_issue", 0.75, [a_trend(s), a_limit(s, 500 if sv == "warning" else 1000, sv)]))
    ph = ser(R, 48, lambda i: 7.4, 0.03, 2)
    s2 = c.add("water", "ph", wn, wloc, ph, False, "same water quality sensor",
               agent=lambda s: ag("stable", "normal", "normal_usage", 0.85, [a_steady(s)]))
    c.t.update(label="water_quality_issue", sev=sv, root=s1, domains=["water"],
               event=R.choice(["TDS %s ppm in stored water" % lastv(s1), "Dissolved solids rising, TDS %s ppm" % lastv(s1)]),
               root_cause="Dissolved solids in the tank water are rising past the limit: source water change or contamination.",
               chain="TDS rising (%s.E4) over the %s limit (%s.E1); pH steady (%s.E1)" % (s1["ref"], sv, s1["ref"], s2["ref"]),
               expl="TDS is above the %s limit; have the water tested and check the source." % sv,
               actions=[("request_facility_review", s1), ("inspect_water_system", s1)], mon=("TDS", "pH"))
    obs_add(c, T.o_limit(R, s1, 500 if sv == "warning" else 1000, sv), T.o_trend(R, s1), T.o_steady(R, s2))
    return c


# ---------------------------------------------------------------- power families
def f_pf_low(R, split):
    end = end_time(R, split, range(8, 20))
    c = Case(R, "power_quality", end, split)
    endv = R.choice([0.82, 0.76, 0.68, 0.62])
    pf = ser(R, 48, lambda i: 0.93 - (0.93 - endv) * i / 47, 0.004, 3, 0, 1)
    pw = ser(R, 48, lambda i: 1450, 12, 2, 0)
    s1 = c.add("power", "pf", L.SUBSTATION[0], L.SUBSTATION[1], pf, True, hist=True,
               agent=lambda s: ag("gradual_decrease", "critical" if pf[-1] < 0.7 else "warning", "power_quality_issue", 0.8, [a_trend(s)]))
    s2 = c.add("power", "power_kw", L.SUBSTATION[0], L.SUBSTATION[1], pw, False, "load on the same feeder",
               agent=lambda s: ag("stable", "normal", "normal_load", 0.85, [a_steady(s)]))
    sv = "critical" if pf[-1] < 0.7 else "warning"
    c.t.update(label="power_quality_issue", sev=sv, root=s1, domains=["power"],
               event=R.choice(["Power factor down to %s" % lastv(s1), "Low power factor on the 11 kV feeder"]),
               root_cause="Power factor is falling at steady load: reactive load grew or the capacitor bank dropped out.",
               chain="power factor falling (%s.E4) below the %s limit (%s.E1) with steady load (%s.E1)" % (s1["ref"], sv, s1["ref"], s2["ref"]),
               expl="The feeder's power factor is %s; check the capacitor bank and large motor loads." % ("critically low" if sv == "critical" else "below the warning limit"),
               actions=[("inspect_electrical", s1)] + ([("request_facility_review", s1)] if sv == "critical" else [("monitor", s1)]),
               mon=("power factor", "feeder load"))
    obs_add(c, T.o_limit(R, s1, "0.7" if sv == "critical" else "0.85", "low_" + sv), T.o_trend(R, s1), T.o_steady(R, s2))
    return c


def f_night_load(R, split):
    end = end_time(R, split, [23, 0, 1, 2, 3])
    c = Case(R, "night_load", end, split)
    b, fl, k = room(R, split)
    pk = R.choice([6.0, 12.0, 20.0])
    pw = ser(R, 48, lambda i: pk, pk * 0.02, 2, 0)
    en, eloc = L.node_em(b, fl, 1)
    s1 = c.add("power", "power_kw", en, eloc, pw, True, hist=True,
               agent=lambda s: ag("stable", R.choice(["normal", "warning"]), "normal_load", 0.7, [a_steady(s)]))
    on, oloc = L.node_occ(b, k)
    s2 = c.add("occupancy", "occ", on, oloc, [0] * 48, False, "occupancy of the same floor",
               agent=ag("vacant", "normal", "vacant", 0.9, ["No presence detected [E2]"]))
    if s1["agent"]["status"] == "normal":
        check(c, s1, "normal load", "corrected", "the floor is empty at night yet draws %s kW" % lastv(s1), [s2["ref"] + ".E2", s1["ref"] + ".E1"])
    c.t.update(label="power_load_anomaly", sev="warning", root=s1, domains=["power", "occupancy"],
               event=R.choice(["Load %s kW at night, floor empty" % lastv(s1), "Night-time load with nobody present"]),
               root_cause="Equipment stays on overnight in an empty area: lighting, AC or plant left running.",
               chain="vacant (%s.E2) -> load still %s kW (%s.E1) -> equipment left on" % (s2["ref"], lastv(s1), s1["ref"]),
               expl="Power use stays high although nobody is present; find what was left on and fix the schedule.",
               actions=[("review_schedule", s1), ("inspect_electrical", s1)], mon=("night load",))
    obs_add(c, T.o_now(R, s1), T.o_occ(R, s2), T.o_quote(R, s1, "E8"))
    return c


def f_holiday_low(R, split):
    end = end_time(R, split, range(10, 17), "off")
    c = Case(R, "holiday_low_load", end, split)
    b, fl, k = room(R, split)
    pk = R.choice([18.0, 30.0, 45.0])
    t0 = R.randrange(6, 20)
    pw = ser(R, 48, lambda i: pk if i < t0 else pk * 0.25, pk * 0.015, 2, 0)
    en, eloc = L.node_em(b, fl, 1)
    s1 = c.add("power", "power_kw", en, eloc, pw, True, hist=True,
               agent=lambda s: ag("step_decrease", "warning", "load_drop_or_outage", 0.7, ["Load dropped %s kW at %s [E5]" % (T.parse(s)["jump"], T.parse(s)["jump_t"])]))
    on, oloc = L.node_occ(b, k)
    s2 = c.add("occupancy", "occ", on, oloc, [1 if i < t0 - 1 else 0 for i in range(48)], False, "occupancy of the same floor",
               agent=ag("departure", "normal", "departure", 0.9, ["Floor emptied [E5]"]))
    dtp = L.day_type(end)
    check(c, s1, "load drop or outage, warning", "corrected", "it is a %s and the floor emptied; low load is expected" % ("holiday" if dtp.startswith("holiday") else "weekend"),
          [s2["ref"] + ".E5", s1["ref"] + ".E1"])
    c.t.update(label="normal_operation", sev="normal", root=s1, domains=["power", "occupancy"],
               event=R.choice(["Low load on a %s" % ("holiday" if dtp.startswith("holiday") else "weekend"), "Power drop as the floor empties (day off)"]),
               root_cause="People left on a non-working day, so equipment was switched off: expected low load, not an outage.",
               chain="day off (CONTEXT) -> floor emptied (%s.E5) -> load stepped down (%s.E5)" % (s2["ref"], s1["ref"]),
               expl="The drop matches people leaving on a %s. Nothing is wrong." % ("holiday" if dtp.startswith("holiday") else "weekend"),
               actions=[("none", s1)] if R.random() < .5 else [("monitor", s1)], mon=("power draw",))
    obs_add(c, T.o_jump(R, s1), T.o_occ(R, s2), T.o_now(R, s1))
    return c


def f_outage(R, split):
    end = end_time(R, split, range(10, 17), "workday")
    real = R.random() < 0.5
    c = Case(R, "power_outage" if real else "meter_dropout", end, split)
    b, fl, k = room(R, split)
    pk = R.choice([8.0, 15.0, 25.0])
    t0 = R.randrange(25, 44)
    pw = [round(pk + R.gauss(0, pk * .02), 2) if i < t0 else 0.0 for i in range(48)]
    en, eloc = L.node_em(b, fl, 1)
    s1 = c.add("power", "power_kw", en, eloc, pw, True,
               agent=lambda s: ag("step_decrease", "critical", "load_drop_or_outage", 0.75, ["Load fell to 0.00 kW at %s [E5,E1]" % T.parse(s)["jump_t"]]))
    an, aloc = L.node_ac(b, fl, k)
    if real:
        rt = [round(24.2 + max(0, i - t0) * 0.08 + R.gauss(0, .05), 1) for i in range(48)]
        ac = [1 if i < t0 else 0 for i in range(48)]
    else:
        rt = ser(R, 48, lambda i: 24.2, 0.08, 1)
        ac = [1] * 48
    s2 = c.add("hvac", "room_temp", an, aloc, rt, False, "AC on the same floor (same supply)", ac=ac, setp=24.0,
               agent=ag("unit_off" if real else "holding", "warning" if real else "normal", "power_loss" if real else "normal_operation", 0.7,
                        ["AC stopped at %s [E5]" % L.idx_time(end, 48, t0)] if real else ["Room holding at setpoint [E1]"]))
    on, oloc = L.node_occ(b, k)
    s3 = c.add("occupancy", "occ", on, oloc, [1] * 48, False, "occupancy of the same floor",
               agent=ag("occupied", "normal", "normal_occupancy", 0.9, ["Floor occupied [E1,E2]"]))
    if real:
        c.t.update(label="power_load_anomaly", sev="critical", root=s1, domains=["power", "hvac", "occupancy"],
                   event=R.choice(["Power outage on level %02d" % fl, "Supply lost: load 0 kW, AC stopped"]),
                   root_cause="Supply to the floor was lost: the meter and the AC on the same supply stopped together while people are present.",
                   chain="load to zero (%s.E5) and AC stopped (%s.E5) at the same time -> supply loss on an occupied floor" % (s1["ref"], s2["ref"]),
                   expl="A real outage: the meter and the AC lost power together on an occupied floor. Get the electrical team.",
                   actions=[("inspect_electrical", s1), ("request_facility_review", s1)], mon=("power draw", "AC state"))
    else:
        c.t.update(label="sensor_fault", sev="sensor_fault", root=s1, domains=["power"], suspects=[s1["ref"]],
                   event=R.choice(["Energy meter reads 0 kW, AC still running", "Meter dropout: 0 kW with equipment on"]),
                   root_cause="The meter shows zero while the AC on the same supply keeps running: a meter or communication dropout.",
                   chain="meter to 0 (%s.E5) but AC still on (%s.E5) and room held (%s.E1) -> meter fault" % (s1["ref"], s2["ref"], s2["ref"]),
                   expl="The floor still has power (the AC is running), so the 0 kW reading is a meter problem, not an outage.",
                   actions=[("restart_or_reconnect_sensor", s1), ("check_sensor", s1)], mon=("meter readings",))
        check(c, s1, "load drop or outage, critical", "contradicted", "the AC on the same supply kept running", [s2["ref"] + ".E5"])
    obs_add(c, T.o_jump(R, s1), T.o_ac(R, s2), T.o_occ(R, s3))
    return c


def f_daily_cycle(R, split):
    end = end_time(R, split, range(12, 17))
    c = Case(R, "daily_cycle", end, split)
    b, fl, k = room(R, split)
    wt = ser(R, 48, lambda i: 29 + 5.5 * i / 47, 0.25, 1)
    c.extra["outdoor"] = (fmt(wt[-1], 1), L.WEATHER[0], L.tstr(end))
    pk = R.choice([15.0, 25.0])
    pw = ser(R, 48, lambda i: pk + pk * 0.2 * i / 47, pk * 0.01, 2)
    s1 = c.add("weather", "temp", L.WEATHER[0], L.WEATHER[1], wt, R.random() < .5, "outdoor conditions",
               agent=lambda s: ag("gradual_increase", "normal", "diurnal_cycle", 0.8, [a_trend(s)]))
    en, eloc = L.node_em(b, fl, 1)
    s2 = c.add("power", "power_kw", en, eloc, pw, True, hist=True,
               agent=lambda s: ag("gradual_increase", R.choice(["warning", "normal"]), "gradual_load_growth", 0.7, [a_trend(s)]))
    if s2["agent"]["status"] == "warning":
        check(c, s2, "status warning", "corrected", "the rise follows the afternoon temperature cycle (%s C, below the 38 C warning)" % lastv(s1),
              [s1["ref"] + ".E4", s1["ref"] + ".E1"])
    c.t.update(label="weather_driven", sev="normal", root=s2, domains=["weather", "power"],
               event=R.choice(["Afternoon AC load following the heat", "Daily cycle: power up with outdoor %s C" % lastv(s1)]),
               root_cause="The usual afternoon warming raises the cooling load; it stays within limits.",
               chain="outdoor warming (%s.E4) -> AC load -> power up (%s.E4)" % (s1["ref"], s2["ref"]),
               expl="This is the normal daily cycle: power follows the afternoon heat and nothing is beyond a limit.",
               actions=[("monitor", s2)], mon=("power draw",))
    obs_add(c, T.o_trend(R, s1), T.o_trend(R, s2))
    return c


def f_rain_level(R, split):
    end = end_time(R, split, range(0, 24))
    c = Case(R, "rain_level", end, split)
    b = bld(R, split)
    rh = ser(R, 48, lambda i: 80 + 16 * min(1, i / 20), 0.8, 1, 0, 100)
    lv = ser(R, 48, lambda i: 150 + 25 * min(1, max(0, i - 8) / 30), 0.8, 1, 0)
    tn, tloc = L.node_tank(b)
    s1 = c.add("water", "level", tn, tloc, lv, True, head=tank_head(200, 240),
               agent=lambda s: ag("gradual_increase", R.choice(["normal", "warning"]), "tank_filling", 0.65, [a_trend(s)]))
    s2 = c.add("weather", "rh", L.WEATHER[0], L.WEATHER[1], rh, False, "outdoor conditions (rain)",
               agent=lambda s: ag("gradual_increase", sev_hi(rh[-1], 90, 97), "weather_front", 0.75, [a_trend(s)]))
    s3 = c.add("water", "flow", "WM-WF-%s98-10" % b, "%s building, level 98, water flow meter 10" % b, [0.0] * 48, False, "supply inflow to the same tank",
               agent=ag("flatline", "normal", "normal_usage", 0.8, ["No supply inflow [E1]"]))
    if s1["agent"]["status"] == "warning":
        check(c, s1, "status warning", "corrected", "the level rises with rain and stays below the high mark", [s2["ref"] + ".E4", s1["ref"] + ".E1"])
    c.t.update(label="weather_driven", sev="normal", root=s1, domains=["water", "weather"],
               event=R.choice(["Tank level rising with rain", "Rain filling the tank, no pump inflow"]),
               root_cause="Rain (humidity near saturation) feeds rooftop harvesting into the tank; the pump inflow is off.",
               chain="rain (%s.E4) -> rooftop runoff -> level rising (%s.E4) with no pump inflow (%s.E1)" % (s2["ref"], s1["ref"], s3["ref"]),
               expl="The tank is gaining water from rain, not from the pump. Normal while it stays below the high mark.",
               actions=[("monitor", s1)], mon=("tank level", "high mark"))
    obs_add(c, T.o_trend(R, s1), T.o_now(R, s2), T.o_now(R, s3))
    return c


# ---------------------------------------------------------------- sensor faults and data quality
def f_co2_glitch(R, split):
    end = end_time(R, split, range(0, 24))
    c = Case(R, "co2_glitch", end, split)
    b, fl, k = room(R, split)
    lo, hi = R.choice([(230, 2900), (180, 2500), (260, 3200)])
    t0 = R.randrange(30, 42)
    co2 = [round(450 + R.gauss(0, 10)) if i < t0 else (hi if (i - t0) % 2 else lo) for i in range(48)]
    n, loc = L.node_aq(b, fl, k)
    wrong = R.random() < 0.5
    s1 = c.add("air_quality", "co2", n, loc, co2, True,
               agent=lambda s: ag("step_decrease" if wrong else "erratic", "sensor_fault", "sensor_fault", 0.8,
                                  (["Level down from 450 to %s ppm, step at %s [E7,E5]" % (T.parse(s)["max"], T.parse(s)["jump_t"])] if wrong
                                   else ["Readings jump between %s and %s ppm [E2,E3]" % (T.parse(s)["min"], T.parse(s)["max"])])))
    on, oloc = L.node_occ(b, k)
    s2 = c.add("occupancy", "occ", on, oloc, [0] * 48 if R.random() < .5 else [1] * 48, False, "occupancy of the same room",
               agent=ag("stable", "normal", "normal_occupancy", 0.85, ["No change in presence [E3]"]))
    if wrong:
        check(c, s1, "Level down from 450 to %s ppm" % T.parse(s1)["max"], "corrected",
              "the readings alternate between %s and %s ppm, not a step" % (T.parse(s1)["min"], T.parse(s1)["max"]), [s1["ref"] + ".E2", s1["ref"] + ".E3"])
    c.t.update(label="sensor_fault", sev="sensor_fault", root=s1, domains=["air_quality"], suspects=[s1["ref"]],
               event=R.choice(["CO2 sensor glitching (%s-%s ppm)" % (T.parse(s1)["min"], T.parse(s1)["max"]), "Faulty CO2 readings, impossible lows"]),
               root_cause="The CO2 sensor alternates between an impossible low (below 300 ppm) and a very high value: a sensor or wiring fault.",
               chain="alternating readings (%s.E2, %s.E3), minimum below 300 ppm is impossible indoors -> sensor fault" % (s1["ref"], s1["ref"]),
               expl="These readings are not real air quality: indoor CO2 cannot be that low, and it flips every 5 minutes. Check the sensor.",
               actions=[("check_sensor", s1), ("restart_or_reconnect_sensor", s1)], mon=("CO2 readings after the check",))
    obs_add(c, T.o_path(R, s1) if False else (R.choice(["CO2 swings between %s and %s ppm" % (T.parse(s1)["min"], T.parse(s1)["max"]),
                                                        "Readings flip between %s ppm and %s ppm" % (T.parse(s1)["min"], T.parse(s1)["max"])]),
                                              [s1["ref"] + ".E2", s1["ref"] + ".E3"]), T.o_jump(R, s1), T.o_occ(R, s2))
    return c


def f_co2_low(R, split):
    end = end_time(R, split, range(0, 24))
    c = Case(R, "impossible_low", end, split)
    b, fl, k = room(R, split)
    v = R.choice([160, 210, 260, 285])
    co2 = ser(R, 48, lambda i: v, 6, 0, 0)
    n, loc = L.node_aq(b, fl, k)
    s1 = c.add("air_quality", "co2", n, loc, co2, True, hist=True,
               agent=lambda s: ag("stable", R.choice(["normal", "sensor_fault"]), R.choice(["normal_conditions", "sensor_fault"]), 0.7, [a_steady(s)]))
    if s1["agent"]["status"] == "normal":
        check(c, s1, "status normal", "corrected", "indoor CO2 of %s ppm is below the outdoor background and physically impossible" % lastv(s1), [s1["ref"] + ".E1"])
    c.t.update(label="sensor_fault", sev="sensor_fault", root=s1, domains=["air_quality"], suspects=[s1["ref"]],
               event=R.choice(["CO2 sensor reads impossible %s ppm" % lastv(s1), "Impossible low CO2 (%s ppm)" % lastv(s1)]),
               root_cause="Indoor CO2 below 300 ppm is impossible (outdoor air is about 420 ppm): the sensor is faulty or uncalibrated.",
               chain="CO2 %s ppm (%s.E1) below the physical floor -> sensor fault" % (lastv(s1), s1["ref"]),
               expl="The CO2 sensor reports a value that cannot occur indoors. Its data should not be trusted until it is checked.",
               actions=[("check_sensor", s1), ("recalibrate_sensor", s1)], mon=("CO2 after recalibration",))
    obs_add(c, T.o_now(R, s1), T.o_e9(R, s1) or T.o_noise(R, s1))
    return c


def f_stuck(R, split):
    end = end_time(R, split, range(0, 24))
    c = Case(R, "stuck_sensor", end, split)
    b, fl, k = room(R, split)
    v = R.choice([24.0, 26.5, 23.1])
    tt = [v] * 48
    n, loc = L.node_aq(b, fl, k)
    s1 = c.add("air_quality", "temp", n, loc, tt, True, hist=[v] * 144,
               agent=ag("flatline", R.choice(["normal", "sensor_fault"]), R.choice(["normal_conditions", "sensor_fault"]), 0.7,
                        ["Temperature flat at %s C [E1,E8]" % fmt(v, 1)]))
    an, aloc = L.node_ac(b, fl, k)
    ac = [1 if (i // 6) % 2 == 0 else 0 for i in range(48)]
    rt = [round(24 + (1.2 if a == 0 else -0.5) * 0.5 + R.gauss(0, .15) + (i % 6) * 0.15 * (1 if a == 0 else -1), 1) for i, a in enumerate(ac)]
    s2 = c.add("hvac", "room_temp", an, aloc, rt, False, "AC unit in the same room", ac=ac, setp=24.0,
               agent=ag("cycling", "normal", "normal_operation", 0.8, ["AC cycling, room varying around setpoint [E5,E2]"]))
    if s1["agent"]["status"] == "normal":
        check(c, s1, "status normal", "corrected", "zero noise for the whole window while the AC unit's own reading varies", [s1["ref"] + ".E8", s2["ref"] + ".E2"])
    c.t.update(label="sensor_fault", sev="sensor_fault", root=s1, domains=["air_quality"], suspects=[s1["ref"]],
               event=R.choice(["Room temperature sensor stuck at %s C" % fmt(v, 1), "Frozen temperature reading"]),
               root_cause="The air sensor's temperature has not changed at all while the AC cycles and the room varies: the reading is stuck.",
               chain="no variation (%s.E8) while the same room varies (%s.E4) -> stuck sensor" % (s1["ref"], s2["ref"]),
               expl="Real temperatures always vary slightly; this one is frozen. The sensor needs checking.",
               actions=[("check_sensor", s1), ("restart_or_reconnect_sensor", s1)], mon=("temperature noise after restart",))
    obs_add(c, T.o_flat(R, s1), T.o_quote(R, s2, "E4"), T.o_ac(R, s2))
    return c


def f_idle_flow(R, split):
    end = end_time(R, split, [0, 1, 2, 3, 4])
    c = Case(R, "idle_genuine", end, split)
    b = bld(R, split)
    fn, floc = L.node_flow(b)
    s1 = c.add("water", "flow", fn, floc, [0.0] * 48, True,
               agent=ag("flatline", R.choice(["sensor_fault", "warning"]), "sensor_fault", 0.6, ["Flow flat at 0.00 m3/h for the whole window [E1,E8]"]))
    tn, tloc = L.node_tank(b)
    lv = ser(R, 48, lambda i: 210, 0.6, 1, 0)
    s2 = c.add("water", "level", tn, tloc, lv, False, "tank feeding this pipe", head=tank_head(220, 260),
               agent=lambda s: ag("stable", "normal", "normal_usage", 0.85, [a_steady(s)]))
    on, oloc = L.node_occ(b, 1)
    s3 = c.add("occupancy", "occ", on, oloc, [0] * 48, False, "occupancy of the building",
               agent=ag("vacant", "normal", "vacant", 0.9, ["No presence detected [E2]"]))
    check(c, s1, "flatline sensor fault", "corrected", "zero flow at night with a steady tank and nobody present is genuine idle",
          [s2["ref"] + ".E4", s3["ref"] + ".E2"])
    c.t.update(label="normal_operation", sev="normal", root=s1, domains=["water"],
               event=R.choice(["Zero water flow at night (idle)", "No flow overnight, building empty"]),
               root_cause="No water is drawn at night in an empty building; the steady tank confirms zero flow is real.",
               chain="building vacant (%s.E2) and tank steady (%s.E4) -> zero flow is genuine (%s.E1)" % (s3["ref"], s2["ref"], s1["ref"]),
               expl="Zero flow at night is expected here. The meter is not stuck: the tank level agrees.",
               actions=[("none", s1)] if R.random() < 0.5 else [("monitor", s1)], mon=("flow at the morning start",))
    obs_add(c, T.o_now(R, s1), T.o_trend(R, s2), T.o_occ(R, s3))
    return c


def f_single_glitch(R, split):
    end = end_time(R, split, range(0, 24))
    c = Case(R, "single_glitch", end, split)
    b = bld(R, split)
    wn, wloc = L.node_wq(b)
    gi = R.randrange(10, 46)
    base = R.choice([180, 240, 310])
    tds = [round(base + R.gauss(0, 4)) if i != gi else R.choice([0, 1000, base * 6]) for i in range(48)]
    s1 = c.add("water", "tds", wn, wloc, tds, True, quality="uncertain (one-reading glitch at %s ignored by the alarm gate)" % L.idx_time(end, 48, gi),
               agent=lambda s: ag("spike", R.choice(["warning", "normal"]), "water_quality_issue", 0.6,
                                  ["Spike to %s ppm at %s [E2]" % (T.parse(s)["max"], T.parse(s)["max_t"])] if tds[gi] > base else
                                  ["Drop to %s ppm at %s [E3]" % (T.parse(s)["min"], T.parse(s)["min_t"])]))
    if s1["agent"]["status"] == "warning":
        check(c, s1, "status warning", "corrected", "a single reading at %s; the rest of the window is steady" % L.idx_time(end, 48, gi),
              [s1["ref"] + ".E6", s1["ref"] + ".E5"])
    c.t.update(label="normal_operation", sev="normal", root=s1, domains=["water"],
               event=R.choice(["One-reading TDS glitch, water steady", "Single bad TDS reading ignored"]),
               root_cause="One isolated bad reading; every other reading is steady, so there is no water-quality event.",
               chain="single glitch (quality line) -> rest steady (%s.E6) -> no event" % s1["ref"],
               expl="A single bad reading, already ignored by the alarm gate. The water readings are otherwise steady.",
               actions=[("monitor", s1)], mon=("TDS for repeat glitches",), conf=0.8)
    obs_add(c, T.o_quote(R, s1, "E6"), T.o_jump(R, s1))
    return c


def f_replaced_shift(R, split):
    end = end_time(R, split, range(8, 20))
    c = Case(R, "replaced_shift", end, split)
    b, fl, k = room(R, split)
    have = R.randrange(20, 40)
    t0 = 48 - have
    off = R.choice([120, -110, 160])
    co2 = ser(R, 48, lambda i: 520 if i < t0 else 520 + off, 9, 0, 300)
    n, loc = L.node_aq(b, fl, k)
    s1 = c.add("air_quality", "co2", n, loc, co2, True, quality="bad (sensor replaced: %d of 48 readings since the swap)" % have,
               agent=lambda s: ag("step_increase" if off > 0 else "step_decrease", "warning", "occupancy_load", 0.6,
                                  ["CO2 step of %s ppm at %s [E5]" % (T.parse(s)["jump"], T.parse(s)["jump_t"])]))
    on, oloc = L.node_occ(b, k)
    s2 = c.add("occupancy", "occ", on, oloc, [1] * 48 if R.random() < .5 else [0] * 48, False, "occupancy of the same room",
               agent=ag("stable", "normal", "normal_occupancy", 0.85, ["No change in presence [E3]"]))
    check(c, s1, "CO2 step from occupancy, warning", "corrected", "the step coincides with the sensor swap; presence did not change",
          [s1["ref"] + ".E5", s2["ref"] + ".E3"])
    c.t.update(label="sensor_fault", sev="sensor_fault", root=s1, domains=["air_quality"], suspects=[s1["ref"]],
               event=R.choice(["CO2 offset after sensor replacement", "New CO2 sensor reads a different level"]),
               root_cause="The level shift starts at the sensor replacement with no change in the room: an offset between old and new sensor.",
               chain="sensor swapped (quality) -> step (%s.E5) without presence change (%s.E3) -> calibration offset" % (s1["ref"], s2["ref"]),
               expl="The jump is the new sensor's offset, not real air quality. Calibrate it before trusting alarms.",
               actions=[("recalibrate_sensor", s1), ("monitor", s1)], mon=("new sensor vs neighbours",), conf=0.75)
    obs_add(c, T.o_jump(R, s1), T.o_occ(R, s2))
    return c


def f_stale_related(R, split):
    end = end_time(R, split, range(9, 18), "workday")
    c = Case(R, "stale_related", end, split)
    b, fl, k = room(R, split)
    top = R.choice([1100, 1300, 1600])
    co2 = ser(R, 48, lambda i: 500 + (top - 500) * i / 47, 12, 0)
    n, loc = L.node_aq(b, fl, k)
    sv = sev_hi(co2[-1], 1000, 1500)
    s1 = c.add("air_quality", "co2", n, loc, co2, True, hist=True,
               agent=lambda s: ag("gradual_increase", sv, R.choice(["occupancy_load", "ventilation_insufficient"]), 0.6, [a_trend(s), a_limit(s, 1000 if sv == "warning" else 1500, sv)]))
    on, oloc = L.node_occ(b, k)
    mins = R.choice([45, 95, 180])
    s2 = c.add("occupancy", "occ", on, oloc, None, False, "occupancy of the same room", quality="stale (no reading for %d min (sensor or gateway offline))" % mins,
               stale="no reading for %d min (sensor or gateway offline)" % mins)
    an, aloc = L.node_ac(b, fl, k)
    s3 = c.add("hvac", "room_temp", an, aloc, ser(R, 48, lambda i: 24.4, 0.1, 1), False, "AC serving the same room", ac=[1] * 48, setp=24.0,
               agent=ag("holding", "normal", "normal_operation", 0.8, ["AC running, room at setpoint [E1,E5]"]))
    c.t.update(label="unknown", sev=sv, root=s1, domains=["air_quality"], nmd=True, conf=0.5,
               event=R.choice(["CO2 %s ppm, cause unclear (occupancy feed offline)" % lastv(s1), "CO2 above limit; occupancy data missing"]),
               root_cause="CO2 is over the %s limit, but the occupancy feed is offline, so crowding and poor ventilation cannot be told apart." % sv,
               chain="CO2 rising (%s.E4) with AC running (%s.E5); occupancy stale -> cause undetermined" % (s1["ref"], s3["ref"]),
               expl="CO2 is genuinely high. Insufficient data to say why: the occupancy sensor has not reported. Ventilate and reconnect the feed.",
               actions=[("inspect_ventilation", s1), ("restart_or_reconnect_sensor", s2)] + ([("request_facility_review", s1)] if sv == "critical" else []),
               mon=("CO2", "occupancy feed"))
    obs_add(c, T.o_now(R, s1), T.o_trend(R, s1), ("Occupancy sensor silent for %d min" % mins, [s2["ref"]]), T.o_ac(R, s3))
    return c


def f_insufficient(R, split):
    end = end_time(R, split, range(0, 24))
    c = Case(R, "insufficient_data", end, split)
    b = bld(R, split)
    miss = R.choice([6, 9, 14, 20])
    pw = ser(R, 48, lambda i: 20, 0.6, 2)
    en, eloc = L.node_em(b, R.choice([1, 2]), 1)
    s1 = c.add("power", "power_kw", en, eloc, pw, True, quality="bad (%d of 48 readings missing in the 4 h window)" % miss,
               agent=lambda s: ag("erratic", "warning", "load_surge", 0.5, ["Load jumped %s kW at %s [E5]" % (T.parse(s)["jump"], T.parse(s)["jump_t"])]),
               rule=("erratic", "warning"))
    check(c, s1, "load surge, warning", "unsupported", "%d of 48 readings are missing, so the window cannot support an event" % miss, [s1["ref"]])
    c.t.update(label="unknown", sev="normal", root=s1, domains=["power"], nmd=True, conf=0.4,
               event=R.choice(["Insufficient data from the power meter", "Power meter data gaps; no judgement possible"]),
               root_cause="Too many readings are missing (%d of 48) to judge the load; the alarm may come from gaps, not from the load." % miss,
               chain="data gaps (quality) -> window not usable -> insufficient data",
               expl="Insufficient data: the meter missed %d of 48 readings. Reconnect it; no event is confirmed." % miss,
               actions=[("restart_or_reconnect_sensor", s1), ("monitor", s1)], mon=("meter feed completeness",))
    obs_add(c, ("%d of 48 readings missing in the 4 h window" % miss, [s1["ref"]]), T.o_now(R, s1), T.o_jump(R, s1))
    return c


def f_maintenance(R, split):
    end = end_time(R, split, range(9, 18))
    c = Case(R, "maintenance", end, split)
    b, fl, k = room(R, split)
    why = R.choice(["filter change", "calibration", "AC servicing", "sensor relocation"])
    co2 = ser(R, 48, lambda i: 450 + (R.choice([0]) if i < 30 else 600), 10, 0)
    n, loc = L.node_aq(b, fl, k)
    s1 = c.add("air_quality", "co2", n, loc, co2, True, quality="maintenance (out of service: %s)" % why,
               agent=lambda s: ag("step_increase", "warning", "ventilation_insufficient", 0.6, ["CO2 jumped %s ppm at %s [E5]" % (T.parse(s)["jump"], T.parse(s)["jump_t"])]))
    check(c, s1, "ventilation insufficient, warning", "unsupported", "the sensor is out of service for %s; its readings are not valid" % why, [s1["ref"]])
    c.t.update(label="normal_operation", sev="normal", root=s1, domains=["air_quality"],
               event=R.choice(["CO2 sensor in maintenance (%s)" % why, "CO2 readings during %s, not an alarm" % why]),
               root_cause="The CO2 sensor is out of service for %s; readings taken during maintenance are not valid evidence." % why,
               chain="maintenance window (quality) -> readings ignored -> no event",
               expl="This alarm comes from a sensor under maintenance (%s). No action unless it persists after maintenance ends." % why,
               actions=[("none", s1)], mon=("CO2 after maintenance ends",), conf=0.85)
    obs_add(c, ("Sensor out of service: %s" % why, [s1["ref"]]), T.o_jump(R, s1))
    return c


def f_rh_impossible(R, split):
    end = end_time(R, split, range(0, 24))
    c = Case(R, "impossible_value", end, split)
    if R.random() < 0.5:
        b, fl, k = room(R, split)
        n, loc = L.node_aq(b, fl, k)
        xs = ser(R, 48, lambda i: R.choice([104.0, 112.5]), 0.5, 1)
        s1 = c.add("air_quality", "rh", n, loc, xs, True, agent=lambda s: ag("stable", "critical", "humidity_control_issue", 0.7, [a_limit(s, 85, "critical")]))
        what, lim = "humidity above 100 %", "RH cannot exceed 100 %"
    else:
        b = bld(R, split)
        n, loc = L.node_flow(b)
        xs = ser(R, 48, lambda i: -2.4, 0.1, 2)
        s1 = c.add("water", "flow", n, loc, xs, True, agent=lambda s: ag("step_decrease", "warning", "supply_interruption", 0.6, [a_steady(s)]))
        what, lim = "negative water flow", "flow cannot be negative"
    check(c, s1, "%s, %s" % (s1["agent"]["cause"].replace("_", " "), s1["agent"]["status"]), "contradicted", "%s; the value is physically impossible" % lim, [s1["ref"] + ".E1"])
    c.t.update(label="sensor_fault", sev="sensor_fault", root=s1, domains=[s1["role"]], suspects=[s1["ref"]],
               event=R.choice(["Impossible %s reading (%s)" % (T.W(s1, False), lastv(s1)), "%s sensor fault: %s" % (T.W(s1), what)]),
               root_cause="The sensor reports %s, which is physically impossible: a sensor or scaling fault." % what,
               chain="%s (%s.E1) -> impossible -> sensor fault" % (what, s1["ref"]),
               expl="This reading cannot be real (%s). Treat the sensor as faulty until it is checked." % lim,
               actions=[("check_sensor", s1), ("recalibrate_sensor", s1)], mon=("readings after the check",))
    obs_add(c, T.o_now(R, s1), T.o_noise(R, s1))
    return c


def f_drift_low(R, split):
    end = end_time(R, split, [1, 2, 3, 4, 5])
    c = Case(R, "drift_low", end, split)
    b, fl, k = room(R, split)
    hist = ser(R, 144, lambda i: 440 - 110 * i / 143, 4, 0)
    xs = hist[-48:]
    n, loc = L.node_aq(b, fl, k)
    s1 = c.add("air_quality", "co2", n, loc, xs, True, hist=hist,
               agent=lambda s: ag("gradual_decrease", "normal", "normal_conditions", 0.7, [a_trend(s)]))
    on, oloc = L.node_occ(b, k)
    s2 = c.add("occupancy", "occ", on, oloc, [0] * 48, False, "occupancy of the same room", agent=ag("vacant", "normal", "vacant", 0.9, ["No presence [E2]"]))
    check(c, s1, "normal conditions", "corrected", "an empty room cannot fall below outdoor air (about 420 ppm); now %s ppm" % lastv(s1), [s1["ref"] + ".E1", s1["ref"] + ".E9"])
    c.t.update(label="sensor_fault", sev="sensor_fault", root=s1, domains=["air_quality"], suspects=[s1["ref"]],
               event=R.choice(["CO2 sensor drifting low (%s ppm)" % lastv(s1), "CO2 calibration drift below outdoor level"]),
               root_cause="CO2 drifts steadily below the outdoor background in an empty room: calibration drift, not real air.",
               chain="slow drift over 12 h (%s.E9) to %s ppm (%s.E1), room vacant (%s.E2) -> drift fault" % (s1["ref"], lastv(s1), s1["ref"], s2["ref"]),
               expl="Indoor CO2 cannot be lower than outdoor air; the sensor is drifting and needs recalibration.",
               actions=[("recalibrate_sensor", s1), ("check_sensor", s1)], mon=("CO2 baseline after recalibration",))
    obs_add(c, T.o_e9(R, s1), T.o_now(R, s1), T.o_occ(R, s2))
    return c


def f_recovery_gap(R, split):
    end = end_time(R, split, range(6, 22))
    c = Case(R, "recovery_after_gap", end, split)
    b = bld(R, split)
    have = R.randrange(12, 30)
    lv = ser(R, have, lambda i: 95 - i * 0.4, 0.8, 1, 0)
    lv = [lv[0]] * (48 - have) + lv
    tn, tloc = L.node_tank(b)
    s1 = c.add("water", "level", tn, tloc, lv, True, quality="uncertain (%d of 48 readings in the 4 h window filled in)" % (48 - have), head=tank_head(200, 240),
               agent=lambda s: ag("flatline", "sensor_fault", "sensor_fault", 0.5, ["Level flat at %s for a long run [E8]" % lv[0]]))
    s2 = c.add("water", "flow", "WM-WF-%s98-10" % b, "%s building, level 98, water flow meter 10" % b, [0.0] * 48, False, "supply inflow to the same tank",
               agent=ag("flatline", "warning", "supply_interruption", 0.7, ["No inflow all window [E1,E8]"]))
    check(c, s1, "flatline sensor fault", "corrected", "the flat part is filled-in gap data, not real readings", [s1["ref"] + ".E8"])
    c.t.update(label="water_supply_issue", sev="warning", root=s1, domains=["water"], conf=0.6,
               event=R.choice(["Tank low after feed outage, no inflow", "Tank level %s after a data gap, supply off" % lastv(s1)]),
               root_cause="During the feed outage the tank drained to a low level and the supply inflow is still zero.",
               chain="gap filled in (quality) -> real readings low and falling (%s.E1) -> inflow zero (%s.E1)" % (s1["ref"], s2["ref"]),
               expl="The flat part is missing data, not a stuck sensor. The real readings show a low tank with no inflow; check the supply.",
               actions=[("inspect_water_system", s2), ("monitor", s1)], mon=("tank level", "inflow"))
    obs_add(c, T.o_now(R, s1), T.o_now(R, s2))
    return c


def f_chatter(R, split):
    end = end_time(R, split, range(9, 18), "workday")
    c = Case(R, "chatter_limit", end, split)
    b, fl, k = room(R, split)
    co2 = ser(R, 48, lambda i: 1005 + 25 * math.sin(i / 2.0), 10, 0)
    n, loc = L.node_aq(b, fl, k)
    s1 = c.add("air_quality", "co2", n, loc, co2, True, hist=True,
               agent=lambda s: ag("oscillation", R.choice(["warning", "normal"]), "occupancy_load", 0.6, [a_steady(s)]))
    on, oloc = L.node_occ(b, k)
    s2 = c.add("occupancy", "occ", on, oloc, [1] * 48, False, "occupancy of the same room", agent=ag("occupied", "normal", "normal_occupancy", 0.9, ["Occupied [E1]"]))
    if s1["agent"]["status"] == "normal":
        check(c, s1, "status normal", "corrected", "CO2 hovers around the 1000 ppm warning limit (max %s ppm)" % T.parse(s1)["max"], [s1["ref"] + ".E2", s1["ref"] + ".E6"])
    c.t.update(label="occupancy_driven_load", sev="warning", root=s1, domains=["air_quality", "occupancy"],
               event=R.choice(["CO2 hovering at the 1000 ppm limit", "CO2 around %s ppm in an occupied room" % lastv(s1)]),
               root_cause="An occupied room keeps CO2 at the warning limit: ventilation is just short of the load.",
               chain="occupied (%s.E1) -> CO2 around the limit (%s.E6)" % (s2["ref"], s1["ref"]),
               expl="CO2 keeps touching the warning limit while the room is in use. Slightly more fresh air would fix it.",
               actions=[("inspect_ventilation", s1), ("monitor", s1)], mon=("CO2 peaks",))
    obs_add(c, T.o_quote(R, s1, "E6"), T.o_quote(R, s1, "E2"), T.o_occ(R, s2))
    return c


def f_contradict(R, split):
    end = end_time(R, split, range(0, 24))
    c = Case(R, "contradicting_sensors", end, split)
    b, fl, _ = room(R, split)
    top = R.choice([1250, 1450, 1700])
    xs = ser(R, 48, lambda i: 480 + (top - 480) * i / 47, 10, 0)
    ys = ser(R, 48, lambda i: 470, 8, 0)
    n1, l1 = L.node_aq(b, fl, 1)
    n2, l2 = L.node_aq(b, fl, 2)
    sv = sev_hi(xs[-1], 1000, 1500)
    s1 = c.add("air_quality", "co2", n1, l1, xs, True, hist=True,
               agent=lambda s: ag("gradual_increase", sv, "ventilation_insufficient", 0.75, [a_trend(s), a_limit(s, 1000 if sv == "warning" else 1500, sv)]))
    s2 = c.add("air_quality", "co2", n2, l2, ys, False, "second CO2 sensor on the same floor",
               agent=lambda s: ag("stable", "normal", "normal_conditions", 0.85, [a_steady(s)]))
    on, oloc = L.node_occ(b, 1)
    s3 = c.add("occupancy", "occ", on, oloc, [0] * 48, False, "occupancy of the same floor", agent=ag("vacant", "normal", "vacant", 0.9, ["No presence [E2]"]))
    check(c, s1, "ventilation insufficient, %s" % sv, "contradicted", "the second sensor on the floor stays at %s ppm and nobody is present" % lastv(s2),
          [s2["ref"] + ".E1", s3["ref"] + ".E2"])
    c.t.update(label="sensor_fault", sev="sensor_fault", root=s1, domains=["air_quality"], suspects=[s1["ref"]], conf=0.75,
               event=R.choice(["CO2 sensor disagrees with its neighbour", "Suspect CO2 reading %s ppm on an empty floor" % lastv(s1)]),
               root_cause="Only one CO2 sensor rises; the neighbour on the same floor is steady and the floor is empty, so the rising sensor is suspect.",
               chain="S1 rising (%s.E4) vs neighbour steady (%s.E1), vacant (%s.E2) -> single-sensor fault" % (s1["ref"], s2["ref"], s3["ref"]),
               expl="One sensor says CO2 is high, but its neighbour and the empty floor say otherwise. Check that sensor.",
               actions=[("check_sensor", s1), ("recalibrate_sensor", s1)], mon=("both CO2 sensors",))
    obs_add(c, T.o_trend(R, s1), T.o_steady(R, s2), T.o_occ(R, s3))
    return c


def f_agent_miss(R, split):
    end = end_time(R, split, range(9, 18), "workday")
    c = Case(R, "agent_miss", end, split)
    b, fl, k = room(R, split)
    top = R.choice([1150, 1350, 1650])
    co2 = ser(R, 48, lambda i: 600 + (top - 600) * i / 47, 12, 0)
    n, loc = L.node_aq(b, fl, k)
    sv = sev_hi(co2[-1], 1000, 1500)
    s1 = c.add("air_quality", "co2", n, loc, co2, True, hist=True,
               agent=lambda s: ag("stable", "normal", "normal_conditions", 0.7, ["CO2 within the usual range [E6]"]))
    on, oloc = L.node_occ(b, k)
    s2 = c.add("occupancy", "occ", on, oloc, [1] * 48, False, "occupancy of the same room", agent=ag("occupied", "normal", "normal_occupancy", 0.9, ["Occupied [E1]"]))
    check(c, s1, "CO2 within the usual range", "contradicted", "CO2 %s ppm is over the %s limit and rising" % (lastv(s1), sv), [s1["ref"] + ".E1", s1["ref"] + ".E4"])
    c.t.update(label="occupancy_driven_load", sev=sv, root=s1, domains=["air_quality", "occupancy"],
               event=R.choice(["CO2 %s ppm missed by the agent" % lastv(s1), "CO2 over the %s limit in an occupied room" % sv]),
               root_cause="The occupied room's CO2 rose past the %s limit; the agent's 'usual range' reading is wrong." % sv,
               chain="occupied (%s.E1) -> CO2 rising (%s.E4) past the limit (%s.E1)" % (s2["ref"], s1["ref"], s1["ref"]),
               expl="CO2 is above the %s limit even though the agent called it normal. Increase ventilation for the occupants." % sv,
               actions=[("inspect_ventilation", s1)] + ([("request_facility_review", s1)] if sv == "critical" else [("monitor", s1)]),
               mon=("CO2",))
    obs_add(c, T.o_limit(R, s1, 1000 if sv == "warning" else 1500, sv), T.o_trend(R, s1), T.o_occ(R, s2))
    return c


def f_coincidence(R, split):
    c0 = f_class_fills(R, split) if R.random() < .5 else f_pf_low(R, split)
    FORCE_END[0] = c0.end
    try:
        c1 = f_pf_low(R, split) if c0.fam == "occupancy_load" else f_slow_leak(R, split)
    finally:
        FORCE_END[0] = None
    c = Case(R, "coincidence", c0.end, split)
    order = ["critical", "warning", "sensor_fault", "normal"]
    for src in (c0, c1):
        for s in src.sensors:
            s = dict(s)
            old = s["ref"]
            s["ref"] = "S%d" % (len(c.sensors) + 1)
            s["_old"] = old
            c.sensors.append(s)
    off = len(c0.sensors)

    def remap(t, base):
        import re as _re
        return _re.sub(r"\bS(\d+)", lambda m: "S%d" % (int(m.group(1)) + base), t)
    a, bb = (c0, c1) if order.index(c0.t["sev"]) <= order.index(c1.t["sev"]) else (c1, c0)
    ba = 0 if a is c0 else off
    bb_ = 0 if bb is c0 else off
    c.t.update(label=a.t["label"], sev=a.t["sev"], root=c.sensors[int(a.t["root"]["ref"][1:]) - 1 + ba],
               domains=sorted(set(a.t["domains"]) | set(bb.t["domains"])),
               event=a.t["event"], conf=0.75,
               root_cause=a.t["root_cause"].rstrip(".") + "; the %s event is unrelated." % T.W(c.sensors[int(bb.t["root"]["ref"][1:]) - 1 + bb_], False),
               chain=remap(a.t["chain"], ba) + "; separately " + remap(bb.t["chain"], bb_),
               expl=R.choice(["Two unrelated events at once. ", "These are two independent problems. "]) + a.t["expl"],
               actions=[(x, c.sensors[int(r["ref"][1:]) - 1 + ba]) for x, r in a.t["actions"][:2]] + [(x, c.sensors[int(r["ref"][1:]) - 1 + bb_]) for x, r in bb.t["actions"][:1]],
               mon=a.t["mon"], suspects=[remap(x, ba) for x in a.t["suspects"]] + [remap(x, bb_) for x in bb.t["suspects"]])
    for ch in a.t["checks"] + bb.t["checks"]:
        base = ba if ch in a.t["checks"] else bb_
        c.t["checks"].append({"ref": remap(ch["ref"], base), "claim": ch["claim"], "verdict": ch["verdict"], "fact": ch["fact"],
                              "src": [remap(x, base) for x in ch["src"]]})
    c.t["checks"] = c.t["checks"][:4]
    for o in a.t["obs"][:3]:
        c.t["obs"].append((remap(o[0], ba), [remap(x, ba) for x in o[1]]))
    for o in bb.t["obs"][:2]:
        c.t["obs"].append((remap(o[0], bb_), [remap(x, bb_) for x in o[1]]))
    c.extra = dict(c0.extra)
    return c


FAMILIES = {f.__name__[2:]: f for f in [f_vent_fail, f_class_fills, f_heat_load, f_ac_fail_hot, f_ac_after_hours, f_dust_ingress,
                                         f_indoor_emission, f_slow_leak, f_demand, f_supply, f_tank_fill, f_overflow, f_acidic, f_tds,
                                         f_pf_low, f_night_load, f_holiday_low, f_outage, f_daily_cycle, f_rain_level, f_co2_glitch,
                                         f_co2_low, f_stuck, f_idle_flow, f_single_glitch, f_replaced_shift, f_stale_related,
                                         f_insufficient, f_maintenance, f_rh_impossible, f_drift_low, f_recovery_gap, f_chatter,
                                         f_contradict, f_agent_miss, f_coincidence]}


# ---------------------------------------------------------------- round 2: borderline severity (owner priority 2026-10-27)
BORDER = [("air_quality", "co2", 1000, "ppm", 0), ("air_quality", "pm25", 60, "ug/m3", 1), ("air_quality", "temp", 30, "C", 1),
          ("water", "tds", 500, "ppm", 0)]


def f_borderline(R, split):
    """Severity exactly as the backend rule (rules.go StatusOf, high-side metrics): the value judged is the LAST reading,
    or the PEAK for a spike/throttling pattern; >= critical limit -> critical, >= warning limit -> warning, else normal
    (exponential_increase -> warning). No duration rule exists in the backend (the ISA-18.2 deadband/off-delay only gate
    alarm episodes), so none is used here."""
    end = end_time(R, split, range(8, 20), "workday")
    c = Case(R, "borderline_severity", end, split)
    role, metric, lim, unit, dec = R.choice(BORDER)
    crit = {"co2": 1500, "pm25": 120, "temp": 34, "tds": 1000}[metric]
    b, fl, k = room(R, split)
    n, loc = L.node_wq(b) if role == "water" else L.node_aq(b, fl, k)
    mode = R.choice(["over_now", "dropped_below", "spike_touch", "just_below"])
    span = R.choice([0.01, 0.02, 0.04])
    hi, lo = lim * (1 + span), lim * (1 - span)
    pattern = {"over_now": "gradual_increase", "dropped_below": "step_decrease", "spike_touch": "spike", "just_below": "gradual_increase"}[mode]
    f = {"over_now": lambda i: lo + (hi - lo) * i / 47,
         "dropped_below": lambda i: hi if i < 36 else lo,
         "spike_touch": lambda i: hi if i == 40 else lo,
         "just_below": lambda i: lo + (lim * 0.995 - lo) * i / 47}[mode]
    xs = ser(R, 48, f, lim * 0.003, dec, 0)
    if mode == "spike_touch":
        xs[40] = round(hi, dec)
    hv = max(xs) if pattern == "spike" else xs[-1]
    sev = "critical" if hv >= crit else ("warning" if hv >= lim else "normal")
    ag_sev = R.choice(["normal", "warning"])
    s1 = c.add(role, metric, n, loc, xs, True, hist=True, rule=(pattern, sev),
               agent=lambda s: ag(pattern, ag_sev, "occupancy_load" if metric == "co2" else ("water_quality_issue" if role == "water" else "normal_conditions"),
                                  0.6, [a_steady(s)]))
    p = T.parse(s1)
    judged = ("its peak %s %s" % (p["max"], unit)) if pattern == "spike" else ("its latest reading %s %s" % (p["last"], unit))
    why = "%s is %s the %s %s warning limit" % (judged, "at or over" if sev != "normal" else "below", T.lim_s(lim), unit)
    if ag_sev != sev:
        check(c, s1, "status %s" % ag_sev, "corrected", why, [s1["ref"] + (".E2" if pattern == "spike" else ".E1")])
    lab = "normal_operation" if sev == "normal" else ("water_quality_issue" if role == "water" else
                                                       ("occupancy_driven_load" if metric == "co2" else ("air_pollution_event" if metric == "pm25" else "hvac_or_thermal_issue")))
    c.t.update(label=lab, sev=sev, root=s1, domains=[role], conf=0.8,
               event=("%s at the %s %s limit" % (T.W(s1), T.lim_s(lim), unit)) if sev != "normal" else ("%s near but below its limit" % T.W(s1)),
               root_cause=("Borderline: %s, so it is a %s." % (why, sev)) if sev != "normal" else ("Borderline: %s, so it is not a warning." % why),
               chain="limit rule on %s (%s) -> %s" % ("the peak" if pattern == "spike" else "the latest value", s1["ref"] + (".E2" if pattern == "spike" else ".E1"), sev),
               expl="Severity follows the app's limit rule (latest value, or the peak for a spike): %s." % why,
               actions=[("monitor", s1)] if sev == "normal" else ([("inspect_ventilation", s1), ("monitor", s1)] if role == "air_quality" else
                                                                  [("request_facility_review", s1), ("monitor", s1)]),
               mon=(T.W(s1, False), "the limit"))
    obs_add(c, T.o_now(R, s1), T.o_quote(R, s1, "E2"), T.o_trend(R, s1))
    return c


FAMILIES_R2 = {"borderline": f_borderline}
