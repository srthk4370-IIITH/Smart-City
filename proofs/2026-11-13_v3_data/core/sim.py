"""Physics simulator (V3_DESIGN §4.1-3), 5-minute steps, parameters drawn around core/calib_stats.json.

Drivers (per site/host): calendar (workdays, weekends, holidays), occupancy by room use (timetable, exams, events,
random visits), weather (diurnal temperature/RH, heatwave, monsoon rain, wind gusts, dust, winter PM inversion),
AC run state (thermostat cycling, schedules, setback), pump hysteresis.
Channels: CO2 mass balance, room heat balance, indoor RH, PM ingress (lag tau 20-90 min), tank level with pump
refills / demand / night leaks / rain inflow, flow, TDS/pH with stagnation drift, room / panel power, PF, solar,
occupancy 0/1, HVAC unit (room temp + setpoint + run state), and generic drivers for synthetic metric cards.
Fault injectors: stuck, spike/glitch, drift, bias step, impossible values, missing/dropout, saturation, quantised,
noisy, maintenance/replaced (gap + bias). Equipment faults: AC not cooling, unit not starting, pump trip, dry run,
valve stuck, feeder overload, ventilation failure, chiller trip.

API (stable; core/API.md):
  Calendar(seed).is_workday(epoch)
  Drivers(seed, start, L, use, capacity, cal, weather=None, events=()) -> .occ (fraction 0..1), .t_out, .rh_out, .wind,
      .rain, .pm_out, .hour(i), .ac_on (room AC), .sp
  channel(card, drv, rng, **params) -> list[float]   base series for any card (existing or synthetic)
  hvac_ctx(drv, rng, node) -> (xs, ctx)               hvac.py window context for an AC unit
  inject_fault(kind, y, onset, rng, card, s0) -> (y, missing_mask, meta)
  calm_ify(y, k=24) -> y                              remove the slow component (keeps texture)
All functions are deterministic given rng.
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
STEP = 300
CAL = json.loads((HERE / "calib_stats.json").read_text())
CM = CAL["metrics"]


def cq(key, field, i, default):
    try:
        v = CM[key][field][i]
        return default if v is None else v
    except (KeyError, IndexError, TypeError):
        return default


def hour_of(epoch):
    t = datetime.fromtimestamp(epoch, IST)
    return t.hour + t.minute / 60.0


class Calendar:
    def __init__(self, seed):
        r = random.Random(f"cal-{seed}")
        self.holidays = set()
        d0 = datetime(2026, 1, 1, tzinfo=IST)
        for k in range(365):
            if r.random() < 0.035:
                self.holidays.add((d0 + timedelta(days=k)).strftime("%Y-%m-%d"))

    def is_holiday(self, epoch):
        return datetime.fromtimestamp(epoch, IST).strftime("%Y-%m-%d") in self.holidays

    def is_workday(self, epoch):
        t = datetime.fromtimestamp(epoch, IST)
        return t.weekday() < 6 and not self.is_holiday(epoch) and not (t.weekday() == 5 and t.day % 2)  # alt. Saturdays


# --------------------------------------------------------------------------------------------- drivers
def _smooth(x, k):
    out, s = [], 0.0
    a = 1.0 / max(1, k)
    for i, v in enumerate(x):
        s = v if i == 0 else s + a * (v - s)
        out.append(s)
    return out


class Drivers:
    """Per-host drivers over L points ending at start + (L-1)*5 min."""

    def __init__(self, seed, start, L, use="office", capacity=10, cal=None, weather=None, events=()):
        self.rng = r = random.Random(f"drv-{seed}-{start}-{use}")
        self.start, self.L, self.use, self.cap = start, L, use, capacity
        self.cal = cal or Calendar(seed)
        self.events = set(events)
        self.t = [start + i * STEP for i in range(L)]
        self.hours = [hour_of(t) for t in self.t]
        self.work = [self.cal.is_workday(t) for t in self.t]
        self.weather = weather or self._weather(r)
        self.t_out, self.rh_out, self.wind, self.rain, self.pm_out = (self.weather[k] for k in ("t", "rh", "wind", "rain", "pm"))
        self.occ = self._occupancy(r)

    def hour(self, i):
        return self.hours[i]

    # weather: diurnal sinusoid (min ~06:00, max ~14:30), calibrated level / amplitude, plus events
    def _weather(self, r):
        month = datetime.fromtimestamp(self.start, IST).month
        lvl = {1: 21, 2: 24, 3: 28, 4: 31, 5: 33, 6: 29, 7: 27, 8: 26, 9: 26, 10: 25, 11: 22, 12: 20}[month] + r.gauss(0, 1.5)
        amp = r.uniform(3.5, 6.5) if month not in (6, 7, 8, 9) else r.uniform(2.0, 4.0)
        heat = "heatwave" in self.events or (month in (4, 5) and r.random() < 0.15)
        rain_p = 0.25 if month in (6, 7, 8, 9) else 0.03
        rain_on = "rain" in self.events or r.random() < rain_p
        rs = r.randint(0, max(1, self.L - 12)) if rain_on else -1
        rl = r.randint(6, 36)
        dust = "dust" in self.events or r.random() < 0.04
        ds = r.randint(0, max(1, self.L - 6))
        t, rh, wind, rain, pm = [], [], [], [], []
        pm_lvl = cq("pm25_outdoor", "level_q05_q25_q50_q75_q95_median_over_sensors", 2, 30) * r.uniform(0.5, 1.6)
        if month in (11, 12, 1):
            pm_lvl *= 1.6
        w0 = r.uniform(0.8, 3.0)
        gust = 0.0
        rainacc = 0.0
        for i, h in enumerate(self.hours):
            base = lvl + amp * math.cos(2 * math.pi * (h - 14.5) / 24) + (r.uniform(4, 7) if heat else 0)
            raining = rs >= 0 and rs <= i < rs + rl
            rainacc = rainacc * 0.97 + (1.0 if raining else 0.0)
            tt = base - 3.0 * min(1.0, rainacc / 6)
            hum = 60 - 2.2 * (tt - lvl) + (25 * min(1.0, rainacc / 6)) + (8 if month in (6, 7, 8, 9) else -5)
            gust = 0.8 * gust + (r.expovariate(1.0) if r.random() < 0.08 else 0.0)
            ws = max(0.0, w0 * (0.6 + 0.8 * max(0.0, math.sin(math.pi * (h - 8) / 12))) + gust)
            tr = 1.0 + 0.6 * math.exp(-((h - 9) ** 2) / 2.0) + 0.5 * math.exp(-((h - 20) ** 2) / 3.0)
            inv = 1.3 if (month in (11, 12, 1) and (h < 7 or h > 21)) else 1.0
            p = pm_lvl * tr * inv * (0.4 if rainacc > 3 else 1.0) / (1 + 0.15 * ws)
            if dust and ds <= i < ds + 12:
                p *= 3.0
            t.append(tt)
            rh.append(max(15.0, min(100.0, hum)))
            wind.append(ws)
            rain.append(1.0 if raining else 0.0)
            pm.append(p)
        return {"t": t, "rh": rh, "wind": wind, "rain": rain, "pm": _smooth(pm, 3)}

    def _occupancy(self, r):
        use, L = self.use, self.L
        occ = [0.0] * L
        if use in ("lecture_hall", "library", "meeting_room", "lab", "office", "canteen"):
            # timetable: blocks of 1-2 h with breaks, 09-17 (labs/libraries longer), on workdays
            day = None
            plan = {}
            for i in range(L):
                d = datetime.fromtimestamp(self.t[i], IST).date()
                if d != day:
                    day = d
                    blocks = []
                    if self.work[i] or (use == "library" and r.random() < 0.6):
                        h = {"lecture_hall": 9, "lab": 10, "office": 9, "library": 9, "meeting_room": 10, "canteen": 8}[use] + r.uniform(-0.3, 0.6)
                        end_h = {"lecture_hall": 17, "lab": 19.5, "office": 18, "library": 21, "meeting_room": 17, "canteen": 21}[use]
                        while h < end_h:
                            dur = r.uniform(0.8, 2.0)
                            frac = r.uniform(0.5, 1.0) if "exam" not in self.events else 1.0
                            if use == "office":
                                frac = r.uniform(0.3, 0.9)
                            if use == "canteen":
                                frac = 0.9 if (8 <= h < 9.5 or 12.5 <= h < 14 or 19.5 <= h < 21) else 0.25
                                dur = 0.5
                            if r.random() < (0.75 if use != "office" else 0.95):
                                blocks.append((h, min(end_h, h + dur), frac))
                            h += dur + r.choice((0.0, 0.0, 0.25, 0.5, 1.0))
                    elif r.random() < 0.15:
                        h = r.uniform(10, 16)
                        blocks.append((h, h + r.uniform(0.3, 2), r.uniform(0.05, 0.3)))
                    plan[d] = blocks
                h = self.hours[i]
                for a, b, f in plan[d]:
                    if a <= h < b:
                        occ[i] = f
        elif use == "hostel_room":
            for i in range(L):
                h = self.hours[i]
                occ[i] = 1.0 if (h >= 19 or h < 8.5) else (1.0 if r.random() < 0.08 else 0.0)
        elif use == "corridor":
            for i in range(L):
                occ[i] = 0.3 if (self.work[i] and 8.5 <= self.hours[i] < 18 and r.random() < 0.4) else 0.0
        elif use == "server_room" or use == "plant_room":
            for i in range(L):
                occ[i] = 0.5 if r.random() < 0.01 else 0.0
        if "night_presence" in self.events:
            s = r.randint(0, L - 6)
            for i in range(s, min(L, s + r.randint(3, 24))):
                occ[i] = max(occ[i], 0.2)
        return occ


# --------------------------------------------------------------------------------------------- helpers
def ar_noise(L, sigma, rng, phi=0.3):
    e, out = 0.0, []
    for _ in range(L):
        e = phi * e + rng.gauss(0, sigma * math.sqrt(1 - phi * phi))
        out.append(e)
    return out


def calm_ify(y, k=24):
    """Remove the slow component (moving average of +-k points) and keep the texture around the window mean."""
    L = len(y)
    m = sum(y) / L
    out = []
    for i in range(L):
        a, b = max(0, i - k), min(L, i + k + 1)
        out.append(y[i] - sum(y[a:b]) / (b - a) + m)
    return out


def ac_schedule(drv, rng, sp=None, duty="office", fail=None):
    """Room AC: thermostat with hysteresis while scheduled on; returns (on[], room_temp[], sp[])."""
    L = drv.L
    sp0 = sp or rng.choice((22.0, 23.0, 24.0, 24.0, 25.0, 26.0))
    Tr = drv.t_out[0] - rng.uniform(1, 4)
    on, temp, sps = [], [], []
    cap = rng.uniform(1.0, 2.5)  # C per 5 min max pull at full capacity (scaled)
    tau_env = rng.uniform(18, 36)  # points
    gain_occ = rng.uniform(0.02, 0.06)
    state = 0
    for i in range(L):
        h = drv.hour(i)
        sched = (duty == "continuous") or (duty == "office" and drv.work[i] and 9 <= h < 18) or (drv.occ[i] > 0.05 and duty != "idle")
        if fail == "unit_not_starting":
            sched = False
        if sched:
            if Tr > sp0 + 0.6:
                state = 1
            elif Tr < sp0 - 0.6:
                state = 0
        else:
            state = 0
        cool = 0.0
        if state and fail != "ac_not_cooling":
            cool = min(cap * 0.12, max(0.0, (Tr - sp0) * 0.25))
        dT = (drv.t_out[i] + 2.0 - Tr) / tau_env + gain_occ * drv.occ[i] - cool
        Tr += dT
        on.append(state)
        temp.append(Tr)
        sps.append(sp0)
    return on, temp, sps


# --------------------------------------------------------------------------------------------- channels
def channel(card, drv, rng, **p):
    """Base series of one sensor channel (no faults, sensor noise included)."""
    cid = card["rules"].get("type", card["card_id"])
    L = drv.L
    nz = card.get("noise") or 0.0
    n = ar_noise(L, nz, rng)
    occ = drv.occ
    if cid == "co2_indoor":
        V = p.get("volume", max(60.0, drv.cap * rng.uniform(4, 9)))
        cap = max(1, drv.cap)
        Q = p.get("vent", rng.uniform(0.06, 0.2))  # air changes per 5 min
        if "ventilation_failure" in drv.events:
            Q *= 0.25
        g = rng.uniform(0.5, 0.8)
        C = 420 + rng.uniform(0, 60)
        out = []
        for i in range(L):
            N = occ[i] * cap
            C += (g * N * 1000 / V) * 0.9 - Q * (C - 420)
            out.append(C)
        return [max(380.0, v + e) for v, e in zip(out, n)]
    if cid == "temp_indoor":
        on, temp, _ = ac_schedule(drv, rng, fail=p.get("ac_fail"))
        return [v + e for v, e in zip(temp, n)]
    if cid == "rh_indoor":
        on, temp, _ = ac_schedule(drv, rng)
        b = rng.uniform(40, 58)
        return [min(99.0, max(15.0, b + 0.35 * (drv.rh_out[i] - 60) - 9 * _smooth(on, 6)[i] + 6 * occ[i] + n[i])) for i in range(L)]
    if cid == "pm25_indoor" or cid == "pm10_indoor":
        tau = rng.uniform(4, 18)
        ratio = rng.uniform(0.3, 0.7) * (1.6 if cid == "pm10_indoor" else 1.0)
        s = _smooth(drv.pm_out, tau)
        return [max(0.0, ratio * v + 2.0 * occ[i] + n[i]) for i, v in enumerate(s)]
    if cid in ("pm25_outdoor", "pm10_outdoor"):
        k = 1.0 if cid == "pm25_outdoor" else rng.uniform(1.4, 2.0)
        return [max(0.0, k * v + n[i]) for i, v in enumerate(drv.pm_out)]
    if cid == "weather_temp":
        return [v + e for v, e in zip(drv.t_out, n)]
    if cid == "weather_rh":
        return [min(100.0, max(1.0, v + e)) for v, e in zip(drv.rh_out, n)]
    if cid == "weather_wind":
        return [max(0.0, v + 0.3 * e) for v, e in zip(drv.wind, n)]
    if cid == "tank_level":
        return tank(drv, rng, card, **p)["level"]
    if cid == "water_flow":
        return tank(drv, rng, card, **p)["flow"]
    if cid == "water_tds":
        b = rng.uniform(60, 380)
        return [b + 0.002 * i * b * (1 if p.get("stagnant") else 0.1) + n[i] for i in range(L)]
    if cid == "water_ph":
        b = rng.uniform(6.9, 8.0)
        return [b + 0.0004 * i + n[i] for i in range(L)]
    if cid == "power_load":
        return power(drv, rng, p.get("scale", rng.choice((3.0, 10.0, 40.0, 150.0, 450.0))), n)
    if cid == "power_solar":
        capk = p.get("capacity", rng.choice((2.0, 5.0, 20.0, 60.0)))
        return solar(drv, rng, capk, n)
    if cid == "power_pf":
        on, _, _ = ac_schedule(drv, rng)
        sm = _smooth(on, 3)
        b = rng.uniform(0.95, 0.99)
        return [min(1.0, max(0.5, b - rng.uniform(0.04, 0.09) * sm[i] - 0.02 * occ[i] + n[i])) for i in range(L)]
    if cid == "occupancy":
        th = rng.uniform(0.05, 0.2)
        return [1.0 if v > th else 0.0 for v in occ]
    # ---------------- synthetic drivers
    r = card["rules"]
    drv_t = r.get("driver", "slow_walk")
    base = r.get("base", 1.0)
    amp = rng.uniform(*r.get("amp", [1.0, 2.0]))
    if drv_t == "binary":
        return [1.0 if (v > 0.05 and rng.random() < 0.25) else 0.0 for v in occ]
    if drv_t == "traffic":
        return [base + amp * (math.exp(-((drv.hour(i) - 9) ** 2) / 2) + 0.8 * math.exp(-((drv.hour(i) - 19.5) ** 2) / 3)) + n[i] for i in range(L)]
    if drv_t in ("occupancy_mass", "occupancy_linear"):
        s = _smooth(occ, 6 if drv_t == "occupancy_mass" else 1)
        return [base + amp * s[i] + n[i] for i in range(L)]
    if drv_t == "occupancy_count":
        lam = [base + amp * v for v in occ]
        return [float(max(0, round(rng.gauss(l, math.sqrt(max(l, 0.3)) * 0.5)))) for l in lam]
    if drv_t == "events_spiky":
        out = []
        for i in range(L):
            h = drv.hour(i)
            cook = (6 <= h < 10 or 11 <= h < 14 or 18 <= h < 21)
            out.append(max(0.0, base + (amp * rng.random() if cook and rng.random() < 0.05 else 0.0) + n[i]))
        return out
    if drv_t == "daylight":
        out = []
        for i in range(L):
            h = drv.hour(i)
            lights = base if (drv.work[i] and 8.5 <= h < 18.5) else base * 0.05
            day = amp * max(0.0, math.sin(math.pi * (h - 6.2) / 12.0))
            out.append(max(0.0, lights + day + n[i]))
        return out
    if drv_t == "solar":
        return solar(drv, rng, amp, n)
    if drv_t == "weather_follow":
        return [base + amp * (drv.t_out[i] - 25) / 8.0 + n[i] for i in range(L)]
    if drv_t == "equipment_cycle":
        P = rng.randint(6, 18)
        ph = rng.uniform(0, 2 * math.pi)
        return [base + 0.3 * amp * math.sin(2 * math.pi * i / P + ph) + n[i] for i in range(L)]
    if drv_t == "consumption":
        out, v = [], base
        run = "outage" in drv.events
        for i in range(L):
            v = min(100.0, v - (rng.uniform(0.2, 0.5) if run else -0.02))
            out.append(v + n[i])
        return out
    if drv_t == "drawdown":
        out, v, pump = [], base, False
        for i in range(L):
            if rng.random() < 0.03:
                pump = not pump
            v += (0.25 * amp / 6 if pump else -0.15 * amp / 6)
            v = min(base + amp, max(base - 0.2 * amp, v))
            out.append(v + n[i])
        return out
    if drv_t == "rain_events":
        rs = _smooth(drv.rain, 12)
        return [max(0.0, base + amp * 3 * rs[i] + n[i]) for i in range(L)]
    if drv_t == "irrigation":
        out, v = [], base
        for i in range(L):
            h = drv.hour(i)
            v -= 0.004 * amp * (1.5 if 12 <= h < 17 else 0.5)
            out.append(v + n[i])
        return out
    if drv_t == "demand_inverse":
        return [base - 0.5 * amp * occ[i] + n[i] for i in range(L)]
    if drv_t == "sessions":
        out, on = [], 0.0
        for i in range(L):
            if on == 0 and rng.random() < 0.01:
                on = amp
            elif on and rng.random() < 0.02:
                on = 0.0
            out.append(max(0.0, base + on + n[i]))
        return out
    # slow_walk (default): mean-reverting walk
    out, v = [], base
    for i in range(L):
        v += 0.05 * (base - v) + rng.gauss(0, 0.2 * amp / 12)
        out.append(v + n[i])
    return out


def power(drv, rng, scale, n):
    on, _, _ = ac_schedule(drv, rng)
    base = scale * rng.uniform(0.15, 0.35)
    perp = scale * rng.uniform(0.15, 0.35)
    ac = scale * rng.uniform(0.2, 0.45)
    lights = scale * rng.uniform(0.05, 0.15)
    out = []
    for i in range(drv.L):
        lt = lights if (drv.work[i] and 8.5 <= drv.hour(i) < 19) else 0.1 * lights
        v = base + perp * drv.occ[i] + ac * on[i] + lt
        if "power_cut" in drv.events and drv.L // 3 <= i < drv.L // 3 + 12:
            v = 0.0
        out.append(max(0.0, v + n[i] * max(1.0, scale / 20)))
    return out


def solar(drv, rng, capk, n):
    out = []
    cloud = 1.0
    for i in range(drv.L):
        h = drv.hour(i)
        bell = max(0.0, math.sin(math.pi * (h - 6.2) / 12.2)) ** 1.3
        if rng.random() < 0.03:
            cloud = rng.uniform(0.3, 1.0)
        elif rng.random() < 0.05:
            cloud = 1.0
        if drv.rain[i]:
            cloud = 0.2
        v = capk * bell * cloud
        out.append(max(0.0, v + (n[i] if v > 0 else 0.0)))
    return out


def tank(drv, rng, card, **p):
    """Tank with pump hysteresis refill, demand ~ occupancy, optional night leak / pump trip / valve stuck."""
    t = p.get("tank") or card.get("tank") or {"high": 180.0, "overflow": 220.0, "fill_min": 60}
    high, ovf = t["high"], t["overflow"]
    lo_set = high * rng.uniform(0.35, 0.6)
    fill_rate = (high - lo_set) / max(1, t["fill_min"] / 5) * rng.uniform(0.8, 1.2)
    v = rng.uniform(lo_set, high)
    pump = False
    leak = p.get("leak", 0.0)
    level, flow, pon = [], [], []
    dem0 = (high - lo_set) / rng.uniform(40, 120)
    for i in range(drv.L):
        h = drv.hour(i)
        demand = dem0 * (0.15 + 1.2 * drv.occ[i] if True else 1) * (1.0 if 6 <= h < 22 else 0.15) + leak
        if v < lo_set and not p.get("pump_trip"):
            pump = True
        if v >= high * rng.uniform(0.97, 1.0) and not p.get("valve_stuck"):
            pump = False
        inflow = fill_rate if pump else 0.0
        v = max(0.0, min(ovf * 1.05, v + inflow - demand))
        level.append(v)
        flow.append(round(inflow * rng.uniform(0.05, 0.08), 4) if pump else max(0.0, demand * 0.05 * rng.uniform(0.5, 1.5)))
        pon.append(1 if pump else 0)
    nz = card.get("noise") or 0.5
    return {"level": [x + rng.gauss(0, nz) for x in level], "flow": flow, "pump": pon}


def hvac_ctx(drv, rng, node, duty=None, fail=None):
    """(xs, ctx) of an AC unit for training/v2/hvac.py (room temp, setpoint, run state, occupancy)."""
    duty = duty or rng.choice(("office", "office", "office", "continuous", "idle"))
    on, temp, sp = ac_schedule(drv, rng, duty=duty, fail=fail)
    hon = CAL["hvac_on_fraction_by_hour"]["workday"]
    hour_on = [min(1.0, max(0.0, (v or 0) * (8 if duty == "office" else 1) + (0.85 if duty == "continuous" else 0))) for v in hon]
    xs = [round(max(10.0, min(45.0, v + rng.gauss(0, 0.05))), 2) for v in temp]
    ctx = {"sp": sp, "on": on, "thermo": None, "mode": 1, "alarm": [0] * drv.L, "malf": 1, "missing": [False] * drv.L,
           "occ": [1 if v > 0.05 else 0 for v in drv.occ] if rng.random() < 0.6 else None, "duty": duty,
           "hour_on": hour_on, "end": drv.t[-1], "node": node}
    return xs, ctx


# --------------------------------------------------------------------------------------------- faults
def inject_fault(kind, y, o, rng, card, s0):
    """Overlay one sensor fault from index o. Returns (y, missing_mask, meta). kinds: stuck, spike, glitch, drift,
    bias, impossible, impossible_glitch, missing, dropout, saturation, quantised, noise, replaced."""
    y = list(y)
    L = len(y)
    miss = [False] * L
    imp = card.get("impossible") or {}
    meta = {"kind": kind, "onset": o}
    if kind == "stuck":
        for i in range(o, L):
            y[i] = y[o]
    elif kind in ("spike", "glitch"):
        A = rng.uniform(5, 12) * s0
        y[o] += A * rng.choice((1, -1))
    elif kind == "drift":
        A = rng.uniform(12, 20) * s0 * rng.choice((1, -1))
        for i in range(L):
            y[i] += A * i / (L - 1)
        meta["onset"] = 0
    elif kind == "bias":
        ms = card.get("max_step") or 3 * s0
        A = max(1.6 * ms, rng.uniform(5, 12) * s0) * rng.choice((1, -1))
        for i in range(o, L):
            y[i] += A
        meta["delta"] = A
    elif kind in ("impossible", "impossible_glitch"):
        lo, hi = imp.get("below"), imp.get("above")
        if lo is not None and (hi is None or rng.random() < 0.6):
            v = lo - abs(rng.uniform(0.05, 0.5)) * max(abs(lo), 1.0) - 1e-3
        else:
            v = hi + abs(rng.uniform(0.05, 0.5)) * max(abs(hi), 1.0)
        if kind == "impossible_glitch":
            y[o] = v
        else:
            for i in range(o, L):
                y[i] = v + rng.gauss(0, (card.get("noise") or 0) * 0.3)
        meta["value"] = v
    elif kind == "dropout":
        idx = sorted(rng.sample(range(o, L), min(rng.randint(1, 4), L - o)))
        for i in idx:
            y[i] = 0.0
        meta["idx"] = idx
    elif kind == "saturation":
        rail = imp.get("above")
        r = rng.randint(3, 10)
        start = y[o]
        for i in range(o, L):
            f = min(1.0, (i - o + 1) / r)
            y[i] = rail if f >= 1 else start + (rail - start) * f
    elif kind == "quantised":
        q = rng.uniform(3, 6) * s0
        for i in range(o, L):
            y[i] = round(y[i] / q) * q
    elif kind == "noise":
        mult = rng.uniform(2.0, 4.0)
        for i in range(o, L):
            y[i] += rng.gauss(0, s0 * mult)
    elif kind in ("missing", "replaced"):
        g = meta.get("gap") or rng.randint(2, max(3, (L - o) // 2))
        for i in range(o, min(L, o + g)):
            miss[i] = True
            y[i] = y[o - 1] if o > 0 else y[i]
        meta["gap"] = g
        if kind == "replaced":
            ms = card.get("max_step") or 3 * s0
            A = max(1.6 * ms, rng.uniform(5, 10) * s0) * rng.choice((1, -1))
            for i in range(o + g, L):
                y[i] += A
            meta["delta"] = A
    return y, miss, meta


def scatter_missing(L, k, rng, lo=0):
    """k missing points in [lo, L): a few runs; returns mask."""
    m = [False] * L
    left = k
    while left > 0:
        run = min(left, rng.randint(1, max(1, k // 2)))
        s = rng.randint(lo, L - run)
        for i in range(s, s + run):
            if not m[i]:
                m[i] = True
                left -= 1
    return m


def hold_missing(y, mask):
    y = list(y)
    for i in range(len(y)):
        if mask[i] and i > 0:
            y[i] = y[i - 1]
    if mask and mask[0]:
        j = next((i for i, m in enumerate(mask) if not m), 0)
        for i in range(j):
            y[i] = y[j]
    return y
