"""Shared window-feature + prompt specification (training AND on-device app).

Pure Python (no numpy) so the Go backend can mirror it line by line.
Any change here MUST be mirrored in app/backend/features.go and the dataset regenerated.

A *window* is WINDOW (=48) consecutive 5-minute values (4 hours) of ONE metric of ONE node.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

WINDOW = 48            # points per window (4 h at 5 min)
STEP_MIN = 5
DOWNSAMPLE = 24        # values shown to the model (pairwise means)
IST = timezone(timedelta(hours=5, minutes=30))

ROLES = ("air_quality", "water", "power", "occupancy", "weather")

# metric registry: role, unit, decimals, warn/crit thresholds (None = baseline-relative only),
# direction of concern ("high", "low", "both"), noise floor used for pattern scaling
METRICS = {
    ("air_quality", "co2"):   dict(unit="ppm",   dec=0, warn=1000, crit=1500, dir="high", floor=40.0, lo=250, hi=5000),
    ("air_quality", "pm25"):  dict(unit="ug/m3", dec=1, warn=60,   crit=120,  dir="high", floor=6.0,  lo=0,   hi=1000),
    ("air_quality", "pm10"):  dict(unit="ug/m3", dec=1, warn=100,  crit=250,  dir="high", floor=10.0, lo=0,   hi=1000),
    ("air_quality", "temp"):  dict(unit="C",     dec=1, warn=30,   crit=34,   dir="high", floor=0.6,  lo=5,   hi=55),
    ("air_quality", "rh"):    dict(unit="%",     dec=1, warn=70,   crit=85,   dir="high", floor=3.0,  lo=1,   hi=100),
    ("water", "level"):       dict(unit="level", dec=1, warn=None, crit=None, dir="low",  floor=4.0,  lo=0,   hi=500),
    ("water", "flow"):        dict(unit="m3/h",  dec=2, warn=None, crit=None, dir="both", floor=0.4,  lo=0,   hi=40),
    ("water", "tds"):         dict(unit="ppm",   dec=0, warn=500,  crit=1000, dir="high", floor=15.0, lo=0,   hi=1000),
    ("water", "ph"):          dict(unit="pH",    dec=2, warn=8.5,  crit=9.0,  dir="both", floor=0.25, lo=0,   hi=14),
    ("power", "power_kw"):    dict(unit="kW",    dec=2, warn=None, crit=None, dir="both", floor=0.0,  lo=0,   hi=2000),
    ("power", "pf"):          dict(unit="",      dec=3, warn=0.85, crit=0.7,  dir="low",  floor=0.03, lo=0,   hi=1),
    ("weather", "temp"):      dict(unit="C",     dec=1, warn=38,   crit=42,   dir="high", floor=0.8,  lo=5,   hi=50),
    ("weather", "rh"):        dict(unit="%",     dec=1, warn=90,   crit=97,   dir="high", floor=4.0,  lo=1,   hi=100),
    ("weather", "wind"):      dict(unit="m/s",   dec=2, warn=10,   crit=15,   dir="high", floor=0.6,  lo=0,   hi=44),
    ("occupancy", "occ"):     dict(unit="0/1",   dec=0, warn=None, crit=None, dir="high", floor=0.0,  lo=0,   hi=1),
}

CONT_PATTERNS = ("stable", "spike", "dip", "gradual_increase", "gradual_decrease", "step_increase",
                 "step_decrease", "exponential_increase", "oscillation", "throttling", "flatline", "erratic")
OCC_PATTERNS = ("vacant", "occupied", "arrival", "departure", "intermittent", "off_hours_presence")

CAUSES = {
    "air_quality": ("normal_conditions", "occupancy_load", "ventilation_insufficient", "outdoor_pollution_ingress",
                    "indoor_emission_source", "hvac_cooling_issue", "humidity_control_issue", "sensor_fault"),
    "water": ("normal_usage", "high_demand", "possible_leak", "tank_filling", "tank_draining", "supply_interruption",
              "pump_cycling", "water_quality_issue", "sensor_fault"),
    "power": ("normal_load", "load_surge", "equipment_startup", "load_drop_or_outage", "capacity_limit_throttling",
              "gradual_load_growth", "cyclic_equipment", "power_quality_issue", "sensor_fault"),
    "weather": ("normal_weather", "heat_buildup", "cooling_trend", "weather_front", "gusty_wind", "diurnal_cycle",
                "sensor_fault"),
    "occupancy": ("vacant", "normal_occupancy", "arrival", "departure", "intermittent_presence",
                  "off_hours_presence", "sensor_fault"),
}
ACTIONS = ("none", "monitor", "inspect_ventilation", "inspect_hvac", "check_sensor", "inspect_water_system",
           "inspect_electrical", "review_schedule", "request_facility_review")


# ---------------------------------------------------------------- statistics
def mean(xs):
    return sum(xs) / len(xs)


def std(xs):
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def sma(xs, n):
    return mean(xs[-n:])


def ema(xs, n):
    a = 2.0 / (n + 1)
    e = xs[0]
    for x in xs[1:]:
        e = a * x + (1 - a) * e
    return e


def linfit(xs):
    """OLS fit y = a + b*t, t = 0..n-1. Returns (a, b, r2)."""
    n = len(xs)
    tm = (n - 1) / 2.0
    ym = mean(xs)
    sxx = sum((t - tm) ** 2 for t in range(n))
    sxy = sum((t - tm) * (y - ym) for t, y in enumerate(xs))
    b = sxy / sxx
    a = ym - b * tm
    sst = sum((y - ym) ** 2 for y in xs)
    sse = sum((y - (a + b * t)) ** 2 for t, y in enumerate(xs))
    r2 = 1.0 - sse / sst if sst > 1e-12 else 0.0
    return a, b, r2


def quad_curvature(xs):
    """Sign/size of curvature: mean of last-third slope minus mean of first-third slope (per step)."""
    n = len(xs)
    k = n // 3
    s1 = (xs[k - 1] - xs[0]) / (k - 1)
    s3 = (xs[-1] - xs[n - k]) / (k - 1)
    return s3 - s1


def zero_crossings(xs):
    """Sign changes of the linearly detrended series (oscillation indicator)."""
    a, b, _ = linfit(xs)
    r = [y - (a + b * t) for t, y in enumerate(xs)]
    s = std(r)
    if s < 1e-9:
        return 0
    c = 0
    prev = 0
    for v in r:
        sg = 1 if v > 0.3 * s else (-1 if v < -0.3 * s else 0)
        if sg != 0:
            if prev != 0 and sg != prev:
                c += 1
            prev = sg
    return c


def longest_flat_run(xs, eps):
    best = cur = 1
    for i in range(1, len(xs)):
        if abs(xs[i] - xs[i - 1]) <= eps:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def top_plateau_run(xs, tol):
    """Longest run at the END of the window within tol of the window max."""
    mx = max(xs)
    run = 0
    for v in reversed(xs):
        if mx - v <= tol:
            run += 1
        else:
            break
    return run


def downsample(xs, k=DOWNSAMPLE):
    step = len(xs) // k
    return [mean(xs[i * step:(i + 1) * step]) for i in range(k)]


def fmt(v, dec):
    if dec == 0:
        return str(int(round(v)))
    return f"{v:.{dec}f}"


def compute_stats(xs, dec):
    """All statistics shown to the agent. xs: list of WINDOW floats (no gaps)."""
    n = len(xs)
    a, b, r2 = linfit(xs)
    diffs = [xs[i] - xs[i - 1] for i in range(1, n)]
    jumps = [abs(d) for d in diffs]
    j_idx = max(range(len(jumps)), key=lambda i: jumps[i]) + 1
    mx_i = max(range(n), key=lambda i: xs[i])
    mn_i = min(range(n), key=lambda i: xs[i])
    s = std(xs)
    rng_ = max(xs) - min(xs)
    eps = max(1e-9, 10 ** (-dec) * 0.5)
    noise = std(diffs) / math.sqrt(2) if n > 2 else 0.0
    h1, h2 = mean(xs[: n // 2]), mean(xs[n // 2:])
    return {
        "last": xs[-1], "mean": mean(xs), "min": min(xs), "max": max(xs), "std": s,
        "sma_1h": sma(xs, 12), "ema_1h": ema(xs, 12), "sma_4h": mean(xs),
        "slope_per_h": b * 12.0, "r2": r2,
        "first_half": h1, "second_half": h2,
        "curvature": quad_curvature(xs) * 12.0,
        "max_jump": jumps[j_idx - 1], "max_jump_idx": j_idx, "max_jump_signed": diffs[j_idx - 1],
        "max_idx": mx_i, "min_idx": mn_i,
        "noise": noise, "range": rng_,
        "zero_cross": zero_crossings(xs),
        "flat_run": longest_flat_run(xs, eps),
        "plateau_run": top_plateau_run(xs, max(eps, 0.01 * abs(max(xs)) if max(xs) else eps)),
    }


def occ_stats(xs):
    toggles = sum(1 for i in range(1, len(xs)) if xs[i] != xs[i - 1])
    first_on = next((i for i, v in enumerate(xs) if v >= 0.5), -1)
    last_on = max((i for i, v in enumerate(xs) if v >= 0.5), default=-1)
    return {"occupied_frac": mean(xs), "toggles": toggles, "first_on": first_on, "last_on": last_on,
            "last": xs[-1], "first": xs[0]}


def idx_time(end_epoch, idx):
    """Wall time (IST) of point idx in a window ending at end_epoch (bucket start of last point)."""
    t = end_epoch - (WINDOW - 1 - idx) * STEP_MIN * 60
    return datetime.fromtimestamp(t, IST).strftime("%H:%M")


def is_off_hours(end_epoch):
    h = datetime.fromtimestamp(end_epoch, IST).hour
    return h >= 22 or h < 6


# ---------------------------------------------------------------- prompt
SYSTEM_PROMPTS = {
    "air_quality": "You are the Air Quality agent of a smart-campus edge monitor (IIIT Hyderabad).",
    "water": "You are the Water agent of a smart-campus edge monitor (IIIT Hyderabad).",
    "power": "You are the Power agent of a smart-campus edge monitor (IIIT Hyderabad).",
    "occupancy": "You are the Occupancy agent of a smart-campus edge monitor (IIIT Hyderabad).",
    "weather": "You are the Weather agent of a smart-campus edge monitor (IIIT Hyderabad).",
}
SYSTEM_RULES = (
    " You receive a 4-hour window of one sensor metric (5-minute samples) with precomputed statistics."
    " Identify the pattern, judge severity, explain what you notice using only the given numbers, and cite"
    " evidence ids (E1..E8) that support each observation. Never invent values. Never order physical"
    " actuation; recommend at most an inspection action. Reply with one JSON object only."
)


def evidence_items(role, metric, st, end_epoch, dec, unit):
    """Ordered evidence list. Ids E1.. are local to the prompt; the app maps them to
    global ids  ev:{node}:{metric}:{stat}:{end_epoch}."""
    u = f" {unit}" if unit else ""
    if role == "occupancy":
        return [
            ("E1", "last", f"current state = {int(st['last'])}"),
            ("E2", "occupied_frac", f"occupied fraction = {st['occupied_frac']:.2f}"),
            ("E3", "toggles", f"state changes = {st['toggles']}"),
            ("E4", "first_on", "first occupied at " + (idx_time(end_epoch, st['first_on']) if st['first_on'] >= 0 else "never")),
            ("E5", "last_on", "last occupied at " + (idx_time(end_epoch, st['last_on']) if st['last_on'] >= 0 else "never")),
            ("E6", "time", "window end " + idx_time(end_epoch, WINDOW - 1) + (" (off-hours)" if is_off_hours(end_epoch) else "")),
        ]
    return [
        ("E1", "last", f"last = {fmt(st['last'], dec)}{u}"),
        ("E2", "max", f"max = {fmt(st['max'], dec)}{u} at {idx_time(end_epoch, st['max_idx'])}"),
        ("E3", "min", f"min = {fmt(st['min'], dec)}{u} at {idx_time(end_epoch, st['min_idx'])}"),
        ("E4", "slope", f"trend = {st['slope_per_h']:+.{max(dec, 1)}f}{u}/h (r2 {st['r2']:.2f})"),
        ("E5", "max_jump", f"largest 5-min change = {st['max_jump_signed']:+.{max(dec, 1)}f}{u} at {idx_time(end_epoch, st['max_jump_idx'])}"),
        ("E6", "sma", f"SMA 1h = {fmt(st['sma_1h'], dec)}, EMA 1h = {fmt(st['ema_1h'], dec)}, mean 4h = {fmt(st['mean'], dec)}{u}"),
        ("E7", "shape", f"halves {fmt(st['first_half'], dec)} -> {fmt(st['second_half'], dec)}, curvature {st['curvature']:+.{max(dec, 1)}f}/h, oscillation crossings {st['zero_cross']}"),
        ("E8", "flat", f"noise {st['noise']:.{max(dec, 1) + 1}f}, longest flat run {st['flat_run']} pts, plateau at max {st['plateau_run']} pts"),
    ]


def build_user_prompt(role, node, location, metric, xs, end_epoch, context=""):
    m = METRICS[(role, metric)]
    dec, unit = m["dec"], m["unit"]
    end = datetime.fromtimestamp(end_epoch, IST)
    start = end - timedelta(minutes=STEP_MIN * (WINDOW - 1))
    lines = [f"NODE: {node} ({location})", f"METRIC: {metric} [{unit or 'ratio'}]"]
    if m["warn"] is not None:
        rel = "below" if m["dir"] == "low" else "above"
        lines.append(f"LIMITS: warning {rel} {m['warn']}, critical {rel} {m['crit']}")
    lines.append(f"WINDOW: {start:%a %d %b %H:%M} -> {end:%H:%M} IST, 48 x 5 min")
    if role == "occupancy":
        st = occ_stats(xs)
        lines.append("STATES (1=occupied): " + "".join(str(int(v)) for v in xs))
    else:
        st = compute_stats(xs, dec)
        lines.append("SERIES (10-min means): " + " ".join(fmt(v, dec) for v in downsample(xs)))
    if context:
        lines.append("CONTEXT: " + context)
    lines.append("EVIDENCE:")
    ev = evidence_items(role, metric, st, end_epoch, dec, unit)
    for eid, _, text in ev:
        lines.append(f"{eid} {text}")
    return "\n".join(lines), st, ev


def output_schema_hint(role):
    causes = "|".join(CAUSES[role])
    pats = "|".join(OCC_PATTERNS if role == "occupancy" else CONT_PATTERNS)
    return ('JSON keys: pattern (' + pats + '), status (normal|warning|critical|sensor_fault), '
            'observations (1-3 short strings, each ending with cited ids like [E1,E4]), '
            'likely_cause (' + causes + '), confidence (0-1), action (' + "|".join(ACTIONS) + ').')


def llama3_prompt(system, user):
    """Exact raw prompt string fed to Genie on device and to the tokenizer in training
    (tokenized with add_special_tokens=False)."""
    return ("<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n" + system +
            "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n" + user +
            "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n")


def agent_prompt(role, node, location, metric, xs, end_epoch, context=""):
    user, st, ev = build_user_prompt(role, node, location, metric, xs, end_epoch, context)
    system = SYSTEM_PROMPTS[role] + SYSTEM_RULES + " " + output_schema_hint(role)
    return llama3_prompt(system, user), st, ev


# ---------------------------------------------------------------- Mode-1 rule classifier
def window_scale(role, metric, st):
    m = METRICS[(role, metric)]
    floor = m["floor"] if m["floor"] > 0 else max(0.03 * abs(st["mean"]), 0.05)
    return max(floor, 1.5 * min(st["noise"], floor * 1.5), 1e-3)


def robust_noise(xs):
    """Noise from the median absolute deviation of 5-min differences (insensitive to one spike)."""
    d = sorted(xs[i] - xs[i - 1] for i in range(1, len(xs)))
    med = d[len(d) // 2]
    dev = sorted(abs(v - med) for v in d)
    return 1.4826 * dev[len(dev) // 2] / math.sqrt(2)


def rule_pattern(role, metric, xs, end_epoch):
    """Deterministic pattern classifier (Mode 1 baseline, mirrored in the app)."""
    if role == "occupancy":
        st = occ_stats(xs)
        if st["occupied_frac"] == 0: return "vacant"
        if is_off_hours(end_epoch): return "off_hours_presence"
        if st["toggles"] >= 3: return "intermittent"
        if st["first"] == 0 and st["last"] == 1: return "arrival"
        if st["first"] == 1 and st["last"] == 0: return "departure"
        return "occupied" if st["occupied_frac"] >= 0.9 else "intermittent"
    m = METRICS[(role, metric)]
    st = compute_stats(xs, m["dec"])
    s = window_scale(role, metric, st)
    if st["flat_run"] >= 16:
        return "flatline"
    srt = sorted(xs); med = srt[len(srt) // 2]
    if robust_noise(xs) > 2.0 * s and st["r2"] < 0.35 and st["zero_cross"] < 14:
        return "erratic"
    up_dev, dn_dev = st["max"] - med, med - st["min"]
    if up_dev > 4 * s and abs(st["last"] - med) < 2.5 * s and st["max_idx"] < WINDOW - 1 and up_dev > 2 * dn_dev:
        return "spike"
    if dn_dev > 4 * s and abs(st["last"] - med) < 2.5 * s and st["min_idx"] < WINDOW - 1 and dn_dev > 2 * up_dev:
        return "dip"
    if st["plateau_run"] >= 10 and st["slope_per_h"] > 0 and st["second_half"] - st["first_half"] > 2 * s:
        return "throttling"
    if st["zero_cross"] >= 6 and st["range"] > 4 * s and st["r2"] < 0.5:
        return "oscillation"
    half = st["second_half"] - st["first_half"]
    if st["curvature"] > 0 and st["slope_per_h"] > 0 and xs[-1] - xs[WINDOW * 2 // 3] > 0.6 * st["range"] and st["range"] > 3 * s:
        return "exponential_increase"
    if abs(half) > 3 * s and st["max_jump"] > 0.45 * abs(half):
        return "step_increase" if half > 0 else "step_decrease"
    if abs(st["slope_per_h"]) * 4 > 3 * s and st["r2"] > 0.55:
        return "gradual_increase" if st["slope_per_h"] > 0 else "gradual_decrease"
    return "stable"
