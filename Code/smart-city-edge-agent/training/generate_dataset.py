"""Stage 2: build the SFT dataset for the 5 domain agents from the real 5-minute series.

Label strategy (no human labels exist):
  * continuous metrics: take REAL calm windows, inject one known pattern -> exact label.
    'stable' = untouched calm window. Real zero-flat windows (idle flow/solar at night) are
    labelled flatline+normal (idle), injected non-zero flatlines are sensor faults.
  * occupancy (binary, real from the raw zip): labelled directly from the real 0/1 sequence;
    rare classes are topped up by editing real sequences.
Targets are written by deterministic domain rules (teacher rules in this file) and every
target is validated against the prompt's evidence ids and the enums before it is kept.

Split by time of window end (IST): train Jan-Aug, dev Sep-Oct, test Nov-Dec 2025.
Output: data/sft/{train,dev,test}.jsonl + data/sft/stats.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import features as F

ROOT = Path(__file__).resolve().parents[1]
SERIES = ROOT / "data" / "series"

# node file -> (role, metrics)
def node_role(domain_dir, node):
    if domain_dir == "air_quality":
        return "air_quality", ["co2", "pm25", "temp", "rh"]
    if domain_dir == "outdoor_air":
        return "air_quality", ["pm25", "pm10"]
    if domain_dir == "water":
        if node.startswith("WM-WL"):
            return "water", ["level"]
        if node.startswith("WM-WF"):
            return "water", ["flow"]
        if node.startswith("WM-WD"):
            return "water", ["tds", "ph"]
    if domain_dir == "power":
        if node.startswith("EM-"):
            return "power", ["power_kw", "pf"]
        return "power", ["power_kw"]
    if domain_dir == "weather":
        return "weather", ["temp", "rh", "wind"]
    if domain_dir == "occupancy":
        return "occupancy", ["occ"]
    return None, []


def describe(node):
    """Human-readable location used in prompts (mirrored in the app)."""
    p = node.split("-")
    def bl(code):
        return f"{code[:2]} building, level {code[2:]}"
    if node.startswith("SR-AQ"):
        return f"{bl(p[2])}, indoor air sensor {p[3]}"
    if node.startswith("AQ-"):
        return f"{p[1][:2]} building, outdoor air station"
    if node.startswith("WM-WL"):
        return f"{bl(p[2])}, water tank level sensor {p[3]}"
    if node.startswith("WM-WF"):
        return f"{bl(p[2])}, water flow meter {p[3]}"
    if node.startswith("WM-WD"):
        return f"{bl(p[2])}, water quality sensor {p[3]}"
    if node.startswith("SR-EM"):
        return f"{bl(p[2])}, room energy meter {p[3]}"
    if node.startswith("EM-"):
        return f"{p[2]} substation, 11 kV feeder meter"
    if node.startswith("SL-"):
        return f"{bl(p[1])}, LT/solar panel meter {p[2]}"
    if node.startswith("WE-"):
        return f"{bl(p[1])}, rooftop weather station"
    if node.startswith("SR-OC"):
        return f"KH building, room occupancy sensor {p[4]} (gateway {p[3]})"
    return node


def load_series():
    out = {}  # (role,node,metric) -> dict bucket->value
    for d in sorted(SERIES.iterdir()):
        if not d.is_dir():
            continue
        for fpath in sorted(d.glob("*.csv")):
            node = fpath.stem
            role, metrics = node_role(d.name, node)
            if not role:
                continue
            cols = defaultdict(dict)
            with open(fpath, newline="") as fh:
                for r in csv.DictReader(fh):
                    b = int(r["bucket"])
                    for m in metrics:
                        v = r.get(m, "")
                        if v != "":
                            cols[m][b] = float(v)
            for m in metrics:
                if len(cols[m]) >= F.WINDOW * 4:
                    out[(role, node, m)] = cols[m]
    return out


def split_of(end_epoch):
    mth = datetime.fromtimestamp(end_epoch, F.IST).month
    return "train" if mth <= 8 else ("dev" if mth <= 10 else "test")


def windows(series, stride, min_have=F.WINDOW - 3):
    """Yield (end_epoch, values) with >= min_have/48 real points; gaps linearly interpolated."""
    bs = sorted(series)
    if not bs:
        return
    step = F.STEP_MIN * 60
    start, stop = bs[0], bs[-1]
    t = start + (F.WINDOW - 1) * step
    while t <= stop:
        pts = [series.get(t - (F.WINDOW - 1 - i) * step) for i in range(F.WINDOW)]
        have = sum(p is not None for p in pts)
        if have >= min_have and pts[0] is not None and pts[-1] is not None:
            vals = list(pts)
            for i in range(F.WINDOW):
                if vals[i] is None:
                    j = i
                    while vals[j] is None:
                        j += 1
                    a, b = vals[i - 1], vals[j]
                    for k in range(i, j):
                        vals[k] = a + (b - a) * (k - i + 1) / (j - i + 1)
            yield t, vals
            t += stride * step
        else:
            t += step


def scale_of(role, metric, xs):
    m = F.METRICS[(role, metric)]
    st = F.compute_stats(xs, m["dec"])
    floor = m["floor"] if m["floor"] > 0 else max(0.03 * abs(st["mean"]), 0.05)
    return max(floor, 1.5 * st["noise"], 1e-3), st


def is_calm(role, metric, xs):
    s0, st = scale_of(role, metric, xs)
    return (abs(st["slope_per_h"]) * 4 <= 3 * s0 and st["range"] <= 8 * s0
            and st["flat_run"] < 10 and st["noise"] > 0)


def is_zero_flat(xs):
    return max(abs(x) for x in xs) < 1e-6


# ------------------------------------------------------------------ injection
def inject(pattern, xs, s0, rng, lo, hi):
    n = len(xs)
    y = list(xs)
    A = s0 * rng.uniform(4, 10)
    if pattern == "stable":
        return y, 0.0
    if pattern in ("spike", "dip"):
        p = rng.randint(18, n - 5); w = rng.randint(1, 3)
        sgn = 1 if pattern == "spike" else -1
        A = s0 * rng.uniform(5, 12)
        for i in range(p, min(n, p + w)):
            y[i] += sgn * A * (1.0 if i == p + w // 2 else 0.7)
    elif pattern in ("gradual_increase", "gradual_decrease"):
        s = rng.randint(0, 14); sgn = 1 if pattern == "gradual_increase" else -1
        for i in range(s, n):
            y[i] += sgn * A * (i - s) / (n - 1 - s)
    elif pattern in ("step_increase", "step_decrease"):
        p = rng.randint(12, 36); sgn = 1 if pattern == "step_increase" else -1
        for i in range(p, n):
            y[i] += sgn * A
    elif pattern == "exponential_increase":
        s = rng.randint(0, 12); r = rng.uniform(3.0, 5.0); L = n - 1 - s
        for i in range(s, n):
            y[i] += A * 1.4 * (math.exp(r * (i - s) / L) - 1) / (math.exp(r) - 1)
    elif pattern == "oscillation":
        P = rng.uniform(8, 16); ph = rng.uniform(0, 2 * math.pi); A = s0 * rng.uniform(3, 6)
        for i in range(n):
            y[i] += A * math.sin(2 * math.pi * i / P + ph)
    elif pattern == "throttling":
        s = rng.randint(0, 8); top = rng.randint(14, 22)
        cap = A
        for i in range(s, n):
            ramp = A * 1.8 * (i - s) / max(1, (n - 1 - s - top))
            y[i] += min(ramp, cap)
        capv = max(y[n - top:])
        for i in range(n - top, n):
            y[i] = capv - abs(rng.gauss(0, 0.05 * s0))
    elif pattern == "flatline":
        p = rng.randint(0, 30)
        for i in range(p, n):
            y[i] = y[p]
    elif pattern == "erratic":
        for i in range(n):
            if rng.random() < 0.45:
                y[i] += rng.gauss(0, s0 * rng.uniform(3, 6))
    y = [min(hi, max(lo, v)) for v in y]
    return y, A


def verify(pattern, base, y, s0, dec):
    """Reject injections destroyed by clamping or rounding."""
    st = F.compute_stats(y, dec)
    if pattern == "stable":
        return True
    if pattern != "flatline":
        lo_, hi_ = min(base + y), max(base + y)
        clamped = sum(1 for v in y if v <= 1e-9 or abs(v - 100.0) < 1e-9 or (abs(v - 1.0) < 1e-12))
        if clamped > 4:
            return False
    d = [y[i] - base[i] for i in range(len(y))]
    mag = max(abs(v) for v in d)
    if pattern == "flatline":
        return st["flat_run"] >= 16 and abs(y[-1]) > 1e-6
    if pattern == "erratic":
        return st["noise"] > 2.0 * s0
    if mag < 3.0 * s0:
        return False
    if pattern == "throttling":
        return st["plateau_run"] >= 10
    return True


# ------------------------------------------------------------------ teacher rules
THRESH_PATTERNS_UP = {"spike", "gradual_increase", "step_increase", "exponential_increase", "throttling", "oscillation", "erratic", "stable"}


def status_of(role, metric, pattern, st, base_mean):
    m = F.METRICS[(role, metric)]
    if pattern == "flatline":
        return "sensor_fault" if abs(st["last"]) > 1e-6 else "normal"
    if pattern == "erratic" and role != "power":
        return "sensor_fault"
    if m["warn"] is not None:
        if m["dir"] == "low" or (metric in ("ph",) and st["min"] < 6.5 and st["last"] < 7):
            lv = st["min"] if pattern in ("spike", "dip") else st["last"]
            if metric == "ph":
                if lv < 6.0: return "critical"
                if lv < 6.5: return "warning"
            else:
                if lv < m["crit"]: return "critical"
                if lv < m["warn"]: return "warning"
            if metric != "ph":
                return "normal"
        hv = st["max"] if pattern in ("spike",) else st["last"]
        if pattern == "throttling":
            hv = st["max"]
        if hv >= m["crit"]: return "critical"
        if hv >= m["warn"]: return "warning"
        return "normal" if pattern in ("stable", "oscillation", "gradual_decrease", "step_decrease", "dip") else ("warning" if pattern in ("exponential_increase",) else "normal")
    # no fixed limits: relative change vs window start level
    ref = max(abs(base_mean), 1e-6)
    rel = (st["range"]) / ref
    if pattern == "stable":
        return "normal"
    if pattern in ("spike", "step_increase", "step_decrease", "dip", "exponential_increase", "throttling", "erratic"):
        return "critical" if rel > 1.5 else "warning"
    if pattern in ("gradual_increase", "gradual_decrease"):
        return "warning" if rel > 0.3 else "normal"
    if pattern == "oscillation":
        return "warning" if role == "water" else "normal"
    return "normal"


def cause_of(role, metric, pattern, status, off_hours, indoor, zero):
    up = pattern in ("gradual_increase", "step_increase", "exponential_increase", "throttling")
    down = pattern in ("gradual_decrease", "step_decrease", "dip")
    if pattern == "flatline":
        if zero:
            return {"water": "normal_usage", "power": "normal_load"}.get(role, "sensor_fault")
        return "sensor_fault"
    if pattern == "erratic":
        return "power_quality_issue" if role == "power" else "sensor_fault"
    if role == "air_quality":
        if pattern == "stable":
            return "normal_conditions"
        if metric == "co2":
            if pattern in ("exponential_increase", "throttling"): return "ventilation_insufficient"
            if pattern in ("gradual_increase", "step_increase"):
                return "ventilation_insufficient" if status in ("warning", "critical") else "occupancy_load"
            if pattern == "spike": return "occupancy_load"
            if pattern == "oscillation": return "ventilation_insufficient" if status != "normal" else "occupancy_load"
            return "normal_conditions"
        if metric in ("pm25", "pm10"):
            if pattern == "spike": return "indoor_emission_source" if indoor else "outdoor_pollution_ingress"
            if up or pattern == "oscillation": return "outdoor_pollution_ingress"
            return "normal_conditions"
        if metric == "temp":
            if up or pattern in ("oscillation", "spike"): return "hvac_cooling_issue" if indoor else "normal_conditions"
            return "normal_conditions"
        if metric == "rh":
            if up or pattern == "spike": return "humidity_control_issue"
            return "normal_conditions"
    if role == "water":
        if metric == "level":
            if pattern == "stable": return "normal_usage"
            if pattern == "gradual_decrease": return "possible_leak" if off_hours else "tank_draining"
            if pattern in ("step_decrease", "dip"): return "tank_draining"
            if up: return "tank_filling"
            if pattern == "oscillation": return "pump_cycling"
            if pattern == "spike": return "sensor_fault"
        if metric == "flow":
            if pattern == "stable": return "possible_leak" if (off_hours and not zero) else "normal_usage"
            if pattern in ("spike", "gradual_increase", "throttling"): return "high_demand"
            if pattern in ("step_increase", "exponential_increase"): return "possible_leak" if off_hours else "high_demand"
            if down: return "supply_interruption" if status != "normal" else "normal_usage"
            if pattern == "oscillation": return "pump_cycling"
        if metric in ("tds", "ph"):
            if pattern == "stable": return "normal_usage"
            return "water_quality_issue" if status in ("warning", "critical") else "normal_usage"
    if role == "power":
        if metric == "pf":
            if down or (pattern == "oscillation" and status != "normal"): return "power_quality_issue"
            return "normal_load"
        return {"stable": "normal_load", "spike": "load_surge", "step_increase": "equipment_startup",
                "gradual_increase": "gradual_load_growth", "exponential_increase": "load_surge",
                "dip": "load_drop_or_outage", "step_decrease": "load_drop_or_outage",
                "gradual_decrease": "normal_load", "oscillation": "cyclic_equipment",
                "throttling": "capacity_limit_throttling"}[pattern]
    if role == "weather":
        if pattern == "stable": return "normal_weather"
        if metric == "temp":
            if up: return "heat_buildup"
            if pattern == "gradual_decrease": return "cooling_trend"
            if pattern in ("step_decrease", "dip"): return "weather_front"
            if pattern == "spike": return "sensor_fault"
            if pattern == "oscillation": return "weather_front"
        if metric == "rh":
            if up or pattern == "step_decrease": return "weather_front"
            if pattern == "spike": return "sensor_fault"
            return "normal_weather"
        if metric == "wind":
            if pattern in ("spike", "oscillation"): return "gusty_wind"
            if up: return "weather_front"
            return "normal_weather"
    return "sensor_fault"


ACTION_OF = {
    "normal_conditions": "none", "normal_usage": "none", "normal_load": "none", "normal_weather": "none",
    "diurnal_cycle": "none", "vacant": "none", "normal_occupancy": "none", "arrival": "none", "departure": "none",
    "occupancy_load": "monitor", "ventilation_insufficient": "inspect_ventilation",
    "outdoor_pollution_ingress": "inspect_ventilation", "indoor_emission_source": "request_facility_review",
    "hvac_cooling_issue": "inspect_hvac", "humidity_control_issue": "inspect_hvac", "sensor_fault": "check_sensor",
    "high_demand": "monitor", "possible_leak": "inspect_water_system", "tank_filling": "monitor",
    "tank_draining": "monitor", "supply_interruption": "inspect_water_system", "pump_cycling": "inspect_water_system",
    "water_quality_issue": "request_facility_review", "load_surge": "monitor", "equipment_startup": "monitor",
    "load_drop_or_outage": "inspect_electrical", "capacity_limit_throttling": "inspect_electrical",
    "gradual_load_growth": "review_schedule", "cyclic_equipment": "monitor", "power_quality_issue": "inspect_electrical",
    "heat_buildup": "monitor", "cooling_trend": "none", "weather_front": "monitor", "gusty_wind": "monitor",
    "intermittent_presence": "monitor", "off_hours_presence": "request_facility_review",
}


def action_of(cause, status):
    a = ACTION_OF[cause]
    if a == "none" and status in ("warning", "critical"):
        return "monitor"
    if a == "monitor" and status == "critical":
        return {"load_surge": "inspect_electrical", "equipment_startup": "inspect_electrical",
                "high_demand": "inspect_water_system", "occupancy_load": "inspect_ventilation",
                "heat_buildup": "monitor", "gusty_wind": "monitor"}.get(cause, "request_facility_review")
    return a


NICE = {"co2": "CO2", "pm25": "PM2.5", "pm10": "PM10", "temp": "Temperature", "rh": "Humidity", "level": "Tank level",
        "flow": "Flow", "tds": "TDS", "ph": "pH", "power_kw": "Power", "pf": "Power factor", "wind": "Wind speed"}


def observations(role, metric, pattern, status, st, end_epoch, rng, off_hours, zero):
    m = F.METRICS[(role, metric)]
    d, u = m["dec"], (" " + m["unit"] if m["unit"] else "")
    v = lambda x: F.fmt(x, d)
    sd = max(d, 1)
    M = NICE[metric]
    tmax, tmin = F.idx_time(end_epoch, st["max_idx"]), F.idx_time(end_epoch, st["min_idx"])
    tj = F.idx_time(end_epoch, st["max_jump_idx"])
    slope = f"{st['slope_per_h']:+.{sd}f}{u}/h"
    pick = lambda *opts: rng.choice(opts)
    obs = []
    if pattern == "stable":
        obs.append(pick(f"{M} steady around {v(st['mean'])}{u}, ranging only {v(st['min'])}-{v(st['max'])} [E6,E2,E3]",
                        f"{M} stable near {v(st['mean'])}{u} with no meaningful trend ({slope}) [E6,E4]"))
    elif pattern == "spike":
        obs.append(pick(f"{M} spiked to {v(st['max'])}{u} at {tmax} and fell back to {v(st['last'])}{u} [E2,E1]",
                        f"Short spike: {M} peaked at {v(st['max'])}{u} ({tmax}) before returning to normal [E2,E1]"))
        obs.append(f"Largest 5-min change was {st['max_jump_signed']:+.{sd}f}{u} at {tj} [E5]")
    elif pattern == "dip":
        obs.append(pick(f"{M} dropped briefly to {v(st['min'])}{u} at {tmin}, then recovered to {v(st['last'])}{u} [E3,E1]",
                        f"Short dip: {M} fell to {v(st['min'])}{u} ({tmin}) and came back [E3,E1]"))
        obs.append(f"Largest 5-min change was {st['max_jump_signed']:+.{sd}f}{u} at {tj} [E5]")
    elif pattern in ("gradual_increase", "gradual_decrease"):
        w = "rose" if pattern == "gradual_increase" else "fell"
        obs.append(pick(f"{M} {w} steadily from {v(st['first_half'])} to {v(st['second_half'])}{u} (half-window means) [E7]",
                        f"{M} shows a steady {'upward' if w == 'rose' else 'downward'} trend of {slope} [E4]"))
        obs.append(f"Trend {slope} with good linear fit (r2 {st['r2']:.2f}); now {v(st['last'])}{u} vs 1h SMA {v(st['sma_1h'])} [E4,E1,E6]")
    elif pattern in ("step_increase", "step_decrease"):
        w = "up" if pattern == "step_increase" else "down"
        obs.append(pick(f"{M} shifted {w} abruptly by {st['max_jump_signed']:+.{sd}f}{u} at {tj} and stayed there [E5,E7]",
                        f"Level change: {M} stepped {w} at {tj} ({v(st['first_half'])} -> {v(st['second_half'])}{u}) [E5,E7]"))
    elif pattern == "exponential_increase":
        obs.append(pick(f"{M} is rising at an accelerating rate (curvature {st['curvature']:+.{sd}f}/h), now {v(st['last'])}{u} [E7,E1]",
                        f"Accelerating growth: {M} climbed slowly then sharply to {v(st['last'])}{u} [E7,E1]"))
        obs.append(f"Overall trend {slope}; most of the rise is in the last hour (EMA {v(st['ema_1h'])} vs SMA 4h {v(st['mean'])}) [E4,E6]")
    elif pattern == "oscillation":
        obs.append(pick(f"{M} oscillates between {v(st['min'])} and {v(st['max'])}{u} ({st['zero_cross']} crossings of its trend) [E7,E2,E3]",
                        f"Repeating up-down cycle in {M}, swinging {v(st['min'])}-{v(st['max'])}{u} [E2,E3,E7]"))
    elif pattern == "throttling":
        obs.append(pick(f"{M} climbed and then held flat at a ceiling of about {v(st['max'])}{u} for {st['plateau_run']} samples [E2,E8]",
                        f"Rise capped: {M} plateaued near {v(st['max'])}{u} instead of continuing upward [E2,E8]"))
    elif pattern == "flatline":
        if zero:
            obs.append(f"{M} reads 0{u} for {st['flat_run']} consecutive samples, the asset is idle [E8,E1]")
        else:
            obs.append(pick(f"{M} frozen at exactly {v(st['last'])}{u} for {st['flat_run']} consecutive samples [E8,E1]",
                            f"No variation at all: {M} stuck at {v(st['last'])}{u} ({st['flat_run']} samples), typical of a stuck sensor [E8,E1]"))
    elif pattern == "erratic":
        obs.append(pick(f"{M} jumps irregularly (noise {st['noise']:.{sd + 1}f}, largest change {st['max_jump_signed']:+.{sd}f}{u}) [E8,E5]",
                        f"Erratic readings with no consistent trend; 5-min changes up to {abs(st['max_jump_signed']):.{sd}f}{u} [E5,E8]"))
    # limit observation
    if status in ("warning", "critical") and m["warn"] is not None:
        lim = m["crit"] if status == "critical" else m["warn"]
        if m["dir"] == "low" or (metric == "ph" and st["min"] < 6.5):
            val, eid = (st["min"], "E3") if pattern in ("spike", "dip") else (st["last"], "E1")
            obs.append(f"{v(val)}{u} is below the {status} limit of {lim if metric != 'ph' else (6.0 if status == 'critical' else 6.5)}{u} [{eid}]")
        else:
            val, eid = (st["max"], "E2") if pattern in ("spike", "throttling") else (st["last"], "E1")
            obs.append(f"{v(val)}{u} exceeds the {status} limit of {lim}{u} [{eid}]")
    if off_hours and role == "water" and metric in ("flow", "level") and pattern in ("stable", "gradual_decrease", "step_increase", "exponential_increase") and not zero:
        obs.append("Pattern occurs during off-hours (22:00-06:00) when demand should be low [E1]")
    return obs[:3]


def occ_label(xs, end_epoch):
    st = F.occ_stats(xs)
    off = F.is_off_hours(end_epoch)
    if st["occupied_frac"] == 0:
        return "vacant", st
    if off:
        return "off_hours_presence", st
    if st["toggles"] >= 3:
        return "intermittent", st
    if st["first"] == 0 and st["last"] == 1:
        return "arrival", st
    if st["first"] == 1 and st["last"] == 0:
        return "departure", st
    if st["occupied_frac"] >= 0.9:
        return "occupied", st
    return "intermittent", st


def occ_target(pattern, st, end_epoch, rng):
    t = lambda i: F.idx_time(end_epoch, i)
    frac = f"{st['occupied_frac']:.2f}"
    if pattern == "vacant":
        return ("normal", "vacant", [rng.choice(["Room unoccupied for the whole 4-hour window [E2,E1]",
                                                 "No presence detected in any sample [E2]"])], 0.95)
    if pattern == "occupied":
        return ("normal", "normal_occupancy", [f"Room occupied for most of the window (fraction {frac}) [E2]",
                                               f"Currently occupied, {st['toggles']} state changes [E1,E3]"], 0.92)
    if pattern == "arrival":
        return ("normal", "arrival", [f"Room became occupied at {t(st['first_on'])} and is still occupied [E4,E1]"], 0.9)
    if pattern == "departure":
        return ("normal", "departure", [f"Room was occupied until {t(st['last_on'])} and is now empty [E5,E1]"], 0.9)
    if pattern == "intermittent":
        if st["toggles"] >= 12:
            return ("sensor_fault", "sensor_fault", [f"State flips {st['toggles']} times in 4 hours, too often for real movement [E3]",
                                                     "Likely a flapping occupancy sensor [E3,E2]"], 0.75)
        return ("normal", "intermittent_presence", [f"Presence comes and goes: {st['toggles']} state changes, occupied fraction {frac} [E3,E2]"], 0.85)
    if pattern == "off_hours_presence":
        return ("warning", "off_hours_presence", [f"Presence detected during off-hours (occupied fraction {frac}) [E6,E2]",
                                                  f"Last occupied at {t(st['last_on'])} [E5]"], 0.85)
    raise ValueError(pattern)


def validate(role, target, evidence_ids):
    pats = F.OCC_PATTERNS if role == "occupancy" else F.CONT_PATTERNS
    assert target["pattern"] in pats
    assert target["status"] in ("normal", "warning", "critical", "sensor_fault")
    assert target["likely_cause"] in F.CAUSES[role], (role, target["likely_cause"])
    assert target["action"] in F.ACTIONS
    assert 0 <= target["confidence"] <= 1
    assert 1 <= len(target["observations"]) <= 3
    for o in target["observations"]:
        ids = o[o.rindex("[") + 1:o.rindex("]")].split(",")
        assert ids and all(i in evidence_ids for i in ids), (o, evidence_ids)


def make_example(role, node, metric, xs, end_epoch, pattern, A, s0, base_mean, rng, split):
    m = F.METRICS[(role, metric)]
    prompt, st, ev = F.agent_prompt(role, node, describe(node), metric, xs, end_epoch)
    eids = [e[0] for e in ev]
    off = F.is_off_hours(end_epoch)
    if role == "occupancy":
        status, cause, obs, conf = occ_target(pattern, st, end_epoch, rng)
    else:
        zero = is_zero_flat(xs) or (pattern == "flatline" and abs(st["last"]) < 1e-6)
        status = status_of(role, metric, pattern, st, base_mean)
        cause = cause_of(role, metric, pattern, status, off, node.startswith("SR-"), zero)
        obs = observations(role, metric, pattern, status, st, end_epoch, rng, off, zero)
        conf = 0.85 if pattern == "stable" else min(0.95, max(0.6, 0.55 + 0.04 * (A / s0 if s0 else 5)))
        if pattern in ("flatline", "erratic"):
            conf = 0.8
    target = {"pattern": pattern, "status": status, "observations": obs, "likely_cause": cause,
              "confidence": round(conf, 2), "action": action_of(cause, status)}
    validate(role, target, eids)
    completion = json.dumps(target, ensure_ascii=False) + "<|eot_id|>"
    return {"role": role, "node": node, "metric": metric, "split": split, "end_epoch": end_epoch,
            "pattern": pattern, "status": status, "likely_cause": cause, "xs": [round(v, 6) for v in xs],
            "prompt": prompt, "completion": completion}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "sft"))
    ap.add_argument("--train-per-role", type=int, default=1300)
    ap.add_argument("--dev-per-role", type=int, default=120)
    ap.add_argument("--test-per-role", type=int, default=180)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    print("loading series ...", flush=True)
    series = load_series()
    print(f"{len(series)} (role,node,metric) series", flush=True)

    # candidate base windows per role/split
    calm = defaultdict(list)       # (role, split) -> [(node, metric, end, xs)]
    zeroflat = defaultdict(list)
    occw = defaultdict(lambda: defaultdict(list))  # (split) -> pattern -> windows
    for (role, node, metric), s in series.items():
        if role == "occupancy":
            for end, xs in windows(s, stride=6):
                xs = [1.0 if v >= 0.5 else 0.0 for v in xs]
                p, _ = occ_label(xs, end)
                occw[split_of(end)][p].append((node, metric, end, xs))
            continue
        for end, xs in windows(s, stride=12, min_have=24 if role == "weather" else F.WINDOW - 3):
            sp = split_of(end)
            if is_zero_flat(xs):
                zeroflat[(role, sp)].append((node, metric, end, xs))
            elif is_calm(role, metric, xs):
                calm[(role, sp)].append((node, metric, end, xs))

    quota = {"train": a.train_per_role, "dev": a.dev_per_role, "test": a.test_per_role}
    stats = {"calm_windows": {f"{k[0]}/{k[1]}": len(v) for k, v in calm.items()},
             "zero_flat_windows": {f"{k[0]}/{k[1]}": len(v) for k, v in zeroflat.items()},
             "occupancy_real": {sp: {p: len(w) for p, w in d.items()} for sp, d in occw.items()}}
    Path(a.out).mkdir(parents=True, exist_ok=True)
    counts = Counter()
    for split in ("train", "dev", "test"):
        rows = []
        for role in F.ROLES:
            if role == "occupancy":
                per = quota[split] // len(F.OCC_PATTERNS)
                pool = occw[split]
                for p in F.OCC_PATTERNS:
                    cand = pool.get(p, [])
                    made = 0
                    rng.shuffle(cand)
                    for node, metric, end, xs in cand[:per]:
                        rows.append(make_example(role, node, metric, xs, end, p, 0, 0, 0, rng, split)); made += 1
                    # top up rare classes by editing real vacant/occupied windows
                    tries = 0
                    while made < per and tries < per * 20:
                        tries += 1
                        src = pool.get("vacant", []) + pool.get("occupied", [])
                        if not src:
                            break
                        node, metric, end, xs = rng.choice(src)
                        xs = list(xs); n = len(xs)
                        if p == "arrival":
                            k = rng.randint(6, n - 6); xs = [0.0] * k + [1.0] * (n - k)
                        elif p == "departure":
                            k = rng.randint(6, n - 6); xs = [1.0] * k + [0.0] * (n - k)
                        elif p == "intermittent":
                            xs = [0.0] * n; i = rng.randint(0, 6)
                            flips = rng.randint(2, 7) if rng.random() < 0.8 else rng.randint(7, 12)
                            for _ in range(flips):
                                L = rng.randint(1, 5); xs[i:i + L] = [1.0] * len(xs[i:i + L]); i += L + rng.randint(1, 5)
                                if i >= n: break
                        elif p == "occupied":
                            xs = [1.0] * n
                            if rng.random() < 0.4:
                                j = rng.randint(5, n - 5); xs[j] = 0.0
                        elif p == "off_hours_presence":
                            # shift end time into the night, keep real-looking presence
                            day = end - (end % 86400)
                            end = day + rng.choice([17, 18, 19, 20, 21, 22]) * 3600 - 330 * 60 + rng.randint(0, 11) * 300
                            k = rng.randint(4, n - 4); xs = [0.0] * k + [1.0] * (n - k)
                            if rng.random() < 0.5:
                                xs = [1.0] * k + [0.0] * (n - k)
                        elif p == "vacant":
                            xs = [0.0] * n
                        lab, _ = occ_label(xs, end)
                        if lab != p or split_of(end) != split:
                            continue
                        rows.append(make_example(role, node, metric, xs, end, p, 0, 0, 0, rng, split)); made += 1
                continue
            pool = calm[(role, split)]
            if not pool:
                print(f"WARNING no calm windows for {role}/{split}")
                continue
            per = quota[split] // len(F.CONT_PATTERNS)
            for p in F.CONT_PATTERNS:
                made = tries = 0
                while made < per and tries < per * 40:
                    tries += 1
                    if p == "flatline" and zeroflat[(role, split)] and rng.random() < 0.3:
                        node, metric, end, xs = rng.choice(zeroflat[(role, split)])
                        rows.append(make_example(role, node, metric, xs, end, "flatline", 0, 1, 0, rng, split)); made += 1
                        continue
                    node, metric, end, base = rng.choice(pool)
                    m = F.METRICS[(role, metric)]
                    s0, bst = scale_of(role, metric, base)
                    y, A = inject(p, base, s0, rng, m["lo"], m["hi"])
                    if not verify(p, base, y, s0, m["dec"]):
                        continue
                    rows.append(make_example(role, node, metric, y, end, p, A, s0, bst["mean"], rng, split)); made += 1
        rng.shuffle(rows)
        with open(Path(a.out) / f"{split}.jsonl", "w", encoding="utf-8") as o:
            for r in rows:
                o.write(json.dumps(r, ensure_ascii=False) + "\n")
                counts[(split, r["role"], r["pattern"])] += 1
        print(f"{split}: {len(rows)} examples", flush=True)
    stats["examples"] = {f"{s}/{r}/{p}": c for (s, r, p), c in sorted(counts.items())}
    (Path(a.out) / "stats.json").write_text(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
