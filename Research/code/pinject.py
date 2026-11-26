"""pinject.py: TEST injection generators (written for the paper; separate from the training generators gen5_*/gen_r4_inc).
Each family takes a real held-out time T (all baselines are the real campus windows ending at T) and adds a known multi-domain event to the last
144 samples (12 h). Gold (label, severity, affected domains) is by construction from the injected limits. Returns None when a baseline is missing."""
import random
import pdata as D
import pcore as C

K = {"co2": "SR-AQ-KH03-03/co2", "aqt": "SR-AQ-KH03-03/temp", "rh": "SR-AQ-KH03-03/rh", "pm25": "AQ-KN00-00/pm25", "pm10": "AQ-KN00-00/pm10",
     "flow": "WM-WF-KH98-40/flow", "pw": "SR-EM-KH04-01/power_kw", "feed": "EM-CR-SB00-00/power_kw", "pf": "EM-CR-SB00-00/pf",
     "occ": "SR-OC-GW-KH95-01/occ", "wxt": "WE-VN04-00/temp", "wxrh": "WE-VN04-00/rh", "wind": "WE-VN04-00/wind",
     "ac": "AC-KH03/ac_units_on", "rt": "AC-KH03/room_temp"}
LIM = {"co2": (1000, 1500), "aqt": (30, 34), "wxt": (38, 42), "pm25": (60, 120)}
SEVR = {"normal": 0, "warning": 1, "critical": 2}
ROLE = {k: D.BY_KEY[v]["role"] for k, v in K.items()}


def sev(name, v):
    w, c = LIM[name]
    return "critical" if v > c else ("warning" if v > w else "normal")


def worst(*s):
    return max(s, key=lambda x: SEVR[x])


class Inj:
    def __init__(self, T, need, optional=()):
        self.T = T; self.rr = random.Random(T * 7 + 1); self.s = {}; self.flagged = []; self.params = {}
        for n in need:
            w = D.window(D.BY_KEY[K[n]]["node"], D.BY_KEY[K[n]]["metric"], T, 144)
            if w is None:
                raise KeyError(n)
            self.s[K[n]] = [float(v) for v in w]
        for n in optional:
            w = D.window(D.BY_KEY[K[n]]["node"], D.BY_KEY[K[n]]["metric"], T, 144)
            if w is not None:
                self.s[K[n]] = [float(v) for v in w]

    def x(self, n):
        return self.s[K[n]]

    def flag(self, *names):
        for n in names:
            if K[n] not in self.flagged:
                self.flagged.append(K[n])

    def ramp(self, n, onset, top, shape=1.0):
        """move the series so that it ends at `top`: smooth rise from `onset` (the real noise stays on top)"""
        b = self.x(n); d = top - b[-1]
        m = 143 - onset
        for i in range(onset, 144):
            f = ((i - onset + 1) / (m + 1)) ** shape
            b[i] += d * f

    def step(self, n, at, delta, noise=0.0):
        b = self.x(n)
        for i in range(at, 144):
            b[i] += delta + (self.rr.gauss(0, noise) if noise else 0.0)

    def level(self, n, v, upto=None):
        """re-base: shift the whole window so its pre-event median is v (for sensors whose real level is physically implausible)"""
        b = self.x(n); pre = sorted(b[:96]); off = v - pre[len(pre) // 2]
        for i in range(144):
            b[i] += off

    def hold(self, n, at, vals):
        b = self.x(n)
        for i in range(at, 144):
            b[i] = vals[i - at] if isinstance(vals, list) else vals

    def done(self, fam, gold):
        out = {k: C.rnd(v, D.BY_KEY[k]["role"], D.BY_KEY[k]["metric"]) for k, v in self.s.items()}
        return dict(family=fam, series=out, flagged=list(self.flagged), gold=gold, params=self.params)


def gold_of(inj, label, severity, aff=None):
    doms = []
    for k in inj.flagged:
        r = D.BY_KEY[k]["role"]
        if r not in doms:
            doms.append(r)
    return dict(label=label, severity=severity, affected_domains=aff or doms, n_domains=len(doms), n_sensors=len(inj.flagged))


def _onset(R, lo=36, hi=100):
    return 144 - R.randint(lo, hi)


# ---- N = 2
def f_heat_room(R, T):
    i = Inj(T, ["wxt", "aqt"], ["pw", "ac", "rt", "wxrh"])
    o = _onset(R)
    wx = R.uniform(42.5, 46) if R.random() < .4 else R.uniform(38.6, 41.6)
    aq = R.uniform(34.4, 37) if R.random() < .4 else R.uniform(30.6, 33.6)
    i.ramp("wxt", o, wx); i.ramp("aqt", o + 6, aq); i.flag("wxt", "aqt")
    if K["ac"] in i.s: i.hold("ac", o, [min(4, 1 + (j // 8)) for j in range(144 - o)])
    i.params = dict(onset=o, wx=round(wx, 1), aq=round(aq, 1))
    return i.done("heat_room", gold_of(i, "weather_driven", worst(sev("wxt", wx), sev("aqt", aq))))


def f_crowd_co2(R, T):
    i = Inj(T, ["co2", "pw"], ["occ", "aqt", "ac"])
    a = _onset(R, 40, 100); top = R.uniform(1560, 1950) if R.random() < .4 else R.uniform(1060, 1450)
    i.level("co2", R.uniform(430, 520)); i.ramp("co2", a, top)
    i.step("pw", a, R.uniform(1.2, 3.5)); i.flag("co2", "pw")
    i.s[K["occ"]] = [0.0] * a + [1.0] * (144 - a)
    i.params = dict(arrival=a, co2=round(top))
    return i.done("crowd_co2", gold_of(i, "occupancy_driven_load", sev("co2", top), ["air_quality", "power", "occupancy"]))


def f_pm_ingress(R, T):
    i = Inj(T, ["pm25", "pm10", "wind"], ["wxt", "wxrh"])
    o = _onset(R, 30, 90); top = R.uniform(150, 260)
    i.ramp("pm25", o, top); i.ramp("pm10", o, top * R.uniform(1.1, 1.4)); i.ramp("wind", o, R.uniform(4.5, 9))
    i.flag("pm25", "wind"); i.params = dict(onset=o, pm25=round(top))
    return i.done("pm_ingress", gold_of(i, "air_pollution_event", "critical"))


def f_ac_fail(R, T):
    i = Inj(T, ["aqt", "pw", "ac", "rt"], ["wxt"])
    o = _onset(R, 30, 80); a0 = R.choice([3, 4])
    i.s[K["ac"]] = [float(a0)] * o + [0.0] * (144 - o)
    top = R.uniform(34.4, 36.5) if R.random() < .35 else R.uniform(30.6, 33.6)
    i.ramp("aqt", o, top); i.ramp("rt", o, top + R.uniform(0, 1.0))
    i.step("pw", o, -R.uniform(1.0, 2.2)); i.flag("aqt", "pw")
    i.params = dict(onset=o, aq=round(top, 1))
    return i.done("ac_fail", gold_of(i, "hvac_or_thermal_issue", sev("aqt", top), ["air_quality", "power", "hvac"]))


def f_fault_vs_event(R, T):
    i = Inj(T, ["co2", "pw"], ["occ", "ac"])
    a = _onset(R, 40, 100); f0 = 144 - R.randint(20, 40)
    i.level("co2", R.uniform(430, 520)); i.ramp("co2", a, R.uniform(700, 900))
    i.hold("co2", f0, [round(R.uniform(60, 240) + R.gauss(0, 3)) for _ in range(144 - f0)])
    i.step("pw", a, R.uniform(1.2, 3.0)); i.flag("co2", "pw")
    i.s[K["occ"]] = [0.0] * a + [1.0] * (144 - a)
    i.params = dict(arrival=a, fault_from=f0)
    return i.done("fault_vs_event", gold_of(i, "sensor_fault", "sensor_fault", ["air_quality"]))


def f_heat_feeder(R, T):
    i = Inj(T, ["wxt", "feed"], ["aqt", "ac", "pw"])
    o = _onset(R); wx = R.uniform(42.5, 46) if R.random() < .4 else R.uniform(38.6, 41.6)
    i.ramp("wxt", o, wx); i.ramp("feed", o + 4, i.x("feed")[-1] + R.uniform(120, 220)); i.flag("wxt", "feed")
    i.params = dict(onset=o, wx=round(wx, 1))
    return i.done("heat_feeder", gold_of(i, "weather_driven", sev("wxt", wx), ["weather", "power", "hvac"]))


# ---- N = 3-4
def f_heat_ac3(R, T):
    i = Inj(T, ["wxt", "aqt", "pw"], ["ac", "rt"])
    o = _onset(R); wx = R.uniform(42.5, 46) if R.random() < .4 else R.uniform(38.6, 41.6)
    aq = R.uniform(34.4, 37) if R.random() < .4 else R.uniform(30.6, 33.6)
    i.ramp("wxt", o, wx); i.ramp("aqt", o + 6, aq); i.step("pw", o + 8, R.uniform(1.5, 4.5)); i.flag("wxt", "aqt", "pw")
    if K["ac"] in i.s: i.hold("ac", o, [min(4, 1 + (j // 6)) for j in range(144 - o)])
    i.params = dict(onset=o, wx=round(wx, 1), aq=round(aq, 1))
    return i.done("heat_ac3", gold_of(i, "weather_driven", worst(sev("wxt", wx), sev("aqt", aq)), ["weather", "air_quality", "power", "hvac"]))


def f_heat_ac_water(R, T):
    i = Inj(T, ["wxt", "aqt", "pw", "flow"], ["ac"])
    o = _onset(R); wx = R.uniform(42.5, 46) if R.random() < .4 else R.uniform(38.6, 41.6)
    aq = R.uniform(34.4, 37) if R.random() < .4 else R.uniform(30.6, 33.6)
    i.ramp("wxt", o, wx); i.ramp("aqt", o + 6, aq); i.step("pw", o + 8, R.uniform(1.5, 4.5)); i.step("flow", o + 12, R.uniform(2.0, 5.0), 0.35)
    i.flag("wxt", "aqt", "pw", "flow")
    if K["ac"] in i.s: i.hold("ac", o, [min(4, 1 + (j // 6)) for j in range(144 - o)])
    i.params = dict(onset=o, wx=round(wx, 1), aq=round(aq, 1))
    return i.done("heat_ac_water", gold_of(i, "weather_driven", worst(sev("wxt", wx), sev("aqt", aq)), ["weather", "air_quality", "power", "water", "hvac"]))


def f_crowd_heat(R, T):
    i = Inj(T, ["co2", "aqt", "pw"], ["occ", "ac"])
    a = _onset(R, 40, 100); top = R.uniform(1560, 1950) if R.random() < .4 else R.uniform(1060, 1450)
    i.level("co2", R.uniform(430, 520)); i.ramp("co2", a, top)
    at = R.uniform(30.6, 33.6); i.ramp("aqt", a, at); i.step("pw", a, R.uniform(1.5, 4.0))
    i.s[K["occ"]] = [0.0] * a + [1.0] * (144 - a)
    i.flag("co2", "pw", "occ"); i.params = dict(arrival=a, co2=round(top), aq=round(at, 1))
    return i.done("crowd_heat", gold_of(i, "occupancy_driven_load", worst(sev("co2", top), sev("aqt", at)), ["air_quality", "power", "occupancy"]))


# ---- N = 5+
def f_heat_crowd_water(R, T, with_hvac=False):
    i = Inj(T, ["wxt", "aqt", "co2", "pw", "flow"], ["ac", "rt", "occ"])
    o = _onset(R, 40, 100); wx = R.uniform(42.5, 46) if R.random() < .5 else R.uniform(38.6, 41.6)
    aq = R.uniform(34.4, 37) if R.random() < .4 else R.uniform(30.6, 33.6)
    top = R.uniform(1060, 1700)
    i.level("co2", R.uniform(430, 520)); i.ramp("co2", o, top)
    i.ramp("wxt", o, wx); i.ramp("aqt", o + 6, aq); i.step("pw", o + 8, R.uniform(1.5, 4.5)); i.step("flow", o + 12, R.uniform(2.0, 5.0), 0.35)
    i.s[K["occ"]] = [0.0] * o + [1.0] * (144 - o)
    i.hold("ac", o, [min(4, 1 + (j // 6)) for j in range(144 - o)]) if K["ac"] in i.s else None
    i.flag("wxt", "aqt", "co2", "pw", "flow", "occ")
    if with_hvac and K["ac"] in i.s:
        i.flag("ac")
    i.params = dict(onset=o, wx=round(wx, 1), aq=round(aq, 1), co2=round(top), hvac=with_hvac)
    return i.done("heat_crowd_water", gold_of(i, "weather_driven", worst(sev("wxt", wx), sev("aqt", aq), sev("co2", top))))


def f_heat_crowd_water_hvac(R, T):
    return f_heat_crowd_water(R, T, True)


FAMS_B = {  # name: (fn, N stratum, weather needed, count)
    "heat_room": (f_heat_room, "2", 14), "crowd_co2": (f_crowd_co2, "2", 20), "pm_ingress": (f_pm_ingress, "2", 10), "ac_fail": (f_ac_fail, "2", 14),
    "fault_vs_event": (f_fault_vs_event, "2", 10), "heat_feeder": (f_heat_feeder, "2", 4),
    "heat_ac3": (f_heat_ac3, "3-4", 20), "heat_ac_water": (f_heat_ac_water, "3-4", 20), "crowd_heat": (f_crowd_heat, "3-4", 20),
    "heat_crowd_water": (f_heat_crowd_water, "5+", 15), "heat_crowd_water_hvac": (f_heat_crowd_water_hvac, "5+", 15),
}


# ---- single-domain injected cases (forced-single, gold by construction)
def s_co2_crit(R, T):
    i = Inj(T, ["co2"]); a = _onset(R, 30, 90); top = R.uniform(1560, 1950)
    i.level("co2", R.uniform(430, 520)); i.ramp("co2", a, top); i.flag("co2")
    return i.done("single_co2_crit", gold_of(i, "ventilation_issue", "critical"))


def s_co2_warn(R, T):
    i = Inj(T, ["co2"]); a = _onset(R, 30, 90); top = R.uniform(1060, 1450)
    i.level("co2", R.uniform(430, 520)); i.ramp("co2", a, top); i.flag("co2")
    return i.done("single_co2_warn", gold_of(i, "ventilation_issue", "warning"))


def s_flow_leak(R, T):
    i = Inj(T, ["flow"]); a = _onset(R, 20, 70); i.step("flow", a, R.uniform(3.0, 7.0), 0.4); i.flag("flow")
    return i.done("single_flow_leak", gold_of(i, "water_leak_or_overuse", "critical"))


def s_power_surge(R, T):
    i = Inj(T, ["pw"]); a = _onset(R, 20, 70); i.step("pw", a, R.uniform(8, 20)); i.flag("pw")
    return i.done("single_power_surge", gold_of(i, "power_load_anomaly", "critical"))


def s_pm_crit(R, T):
    i = Inj(T, ["pm25", "pm10"]); a = _onset(R, 20, 70); top = R.uniform(150, 260)
    i.ramp("pm25", a, top); i.ramp("pm10", a, top * 1.2); i.flag("pm25")
    return i.done("single_pm_crit", gold_of(i, "air_pollution_event", "critical"))


def s_temp_fault(R, T):
    i = Inj(T, ["aqt"]); f0 = 144 - R.randint(20, 40); v = round(i.x("aqt")[f0 - 1], 1)
    i.hold("aqt", f0, [v] * (144 - f0)); i.flag("aqt")
    return i.done("single_temp_flatline", gold_of(i, "sensor_fault", "sensor_fault"))


def s_rh_jump(R, T):
    i = Inj(T, ["rh"]); a = 144 - R.randint(20, 40); i.hold("rh", a, 100.0); i.flag("rh")
    return i.done("single_rh_saturation", gold_of(i, "sensor_fault", "sensor_fault"))


FAMS_S = {"single_co2_crit": s_co2_crit, "single_co2_warn": s_co2_warn, "single_flow_leak": s_flow_leak, "single_power_surge": s_power_surge,
          "single_pm_crit": s_pm_crit, "single_temp_flatline": s_temp_fault, "single_rh_saturation": s_rh_jump}
