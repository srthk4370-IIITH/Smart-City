"""v2 teacher: deterministic labels from the evidence (extends generate_dataset.status_of / cause_of).

Principle: every label is a function of what the prompt shows (window shape, limits, time of day, weekday,
E9/E10), so it is learnable; the generator only chooses shapes. Routine rules (hard negatives) are applied
to EVERY example with that evidence, whatever produced the shape.

Routine rules (status -> normal unless stated), applied after the v1 rules:
  water level   rising shape (step/gradual/exponential increase, throttling)        -> tank_filling
                gradual_decrease 06:00-22:00                                        -> tank_draining
                gradual_decrease off-hours                                          -> possible_leak, WARNING
  water level/flow oscillation: period = 2*window_minutes/crossings (E7)
                >= 50 min -> pump_cycling normal; < 50 min -> pump_cycling WARNING (short-cycling)
  power (EM-, SR-EM)  oscillation -> cyclic_equipment
                step_increase, Mon-Fri, E5 time 07:00-10:30, E5 carries the step   -> equipment_startup
                step_decrease, Mon-Fri, E5 time 17:00-21:00, stays >= 10% of before -> normal_load
  power (SL- solar)   gradual_increase ending 06:00-12:00, gradual_decrease ending 12:00-19:00 -> normal_load
  weather temp  gradual_increase ending 07:00-15:00 (trend <= +3.0 C/h) or gradual_decrease ending
                15:00-07:00 (trend >= -3.0 C/h), below limits                       -> diurnal_cycle
  weather rh    gradual_decrease ending 07:00-15:00 or gradual_increase ending 15:00-07:00, below limits -> diurnal_cycle
  co2           gradual/step increase ending 08:00-20:00 below limits -> occupancy_load; gradual_decrease -> normal_conditions
  pm (AQ- outdoor stations) gradual/step/oscillation below limits                  -> normal_conditions
  indoor temp   oscillation with range <= 2.0 C below limits                        -> normal_conditions (HVAC cycling)
  water level (D2) last >= TANK overflow -> tank_overflow_risk CRITICAL; rising shape reaching the TANK high
                level -> tank_overflow_risk WARNING; rising shape with max at the last reading and the fill running
                (E3 time -> end) >= 2x the node's usual fill -> fill_valve_stuck WARNING; oscillation (repeated
                fills) in an off-hours window -> possible_leak WARNING; any other rise -> tank_filling normal
Sensor-fault rules (status sensor_fault, cause sensor_fault, fault_kind):
  stuck   non-zero flatline (v1)            noise    erratic outside power (v1)
  bias    step whose single 5-min change (E5) exceeds the metric's physical rate RATE[(role, metric)]
  drift   indoor air metric, window ending off-hours, E9 slow drift with r2 >= 0.95, >= 6x normal variation, >= 11 h history
  quantised  injected coarse-resolution staircase (pattern flatline); fault_kind quantised (D6)
  dropout window minimum exactly 0 on a metric where 0 is not physical (DROPOUT_METRICS)
  saturation  plateau exactly at the sensor range limit (metric "hi") on SATURATION_METRICS
Boundary rule: an injected change smaller than 3x the window noise scale is labelled stable/normal with an
observation that notes the small change.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import features_v2 as V  # noqa: E402
import generate_dataset as G  # noqa: E402  (v1 teacher rules, read-only)
import templates_v2 as TP  # noqa: E402

F = V.F
NICE = dict(G.NICE)
BOUNDARY = 3.0          # size (x noise scale) below which a change is labelled stable/normal

# physical max change per 5 min (bias-jump rule; real steps on these metrics are ramped below it)
RATE = {("air_quality", "temp"): 1.0, ("air_quality", "rh"): 5.0, ("air_quality", "co2"): 150.0,
        ("weather", "temp"): 1.5, ("weather", "rh"): 8.0, ("power", "pf"): 0.15,
        ("water", "ph"): 0.3, ("water", "tds"): 50.0}
DROPOUT_METRICS = {("air_quality", "co2"), ("air_quality", "temp"), ("air_quality", "rh"), ("air_quality", "pm25"),
                   ("air_quality", "pm10"), ("weather", "temp"), ("weather", "rh"), ("water", "level"), ("power", "pf")}
SATURATION_METRICS = {("air_quality", "rh"), ("air_quality", "pm25"), ("air_quality", "pm10"), ("air_quality", "co2")}
# calibration-drift rule, tightened 2026-10-17 (D7): >= 11 h of history, r2 >= 0.95, >= 6x normal variation
DRIFT_R2, DRIFT_MIN_PTS, DRIFT_SIGMA = 0.95, 132, 6.0
DRIFT_FAULT_METRICS = {("air_quality", "co2"), ("air_quality", "temp"), ("air_quality", "rh")}
# cause of recurring small spikes (pattern spike, status normal)
RECUR_CAUSE = {("air_quality", "co2"): "occupancy_load", ("air_quality", "pm25"): "indoor_emission_source",
               ("air_quality", "pm10"): "indoor_emission_source", ("air_quality", "temp"): "normal_conditions",
               ("air_quality", "rh"): "normal_conditions", ("water", "level"): "pump_cycling",
               ("water", "flow"): "normal_usage", ("power", "power_kw"): "cyclic_equipment", ("power", "pf"): "normal_load",
               ("weather", "temp"): "normal_weather", ("weather", "rh"): "normal_weather", ("weather", "wind"): "gusty_wind"}
NORMAL_CAUSE = {"air_quality": "normal_conditions", "water": "normal_usage", "power": "normal_load",
                "weather": "normal_weather", "occupancy": "normal_occupancy"}

# ---------------------------------------------------------------- calibration
CAL_PATH = HERE / "calibration.json"
PLACEMENT = HERE.parents[3] / "proofs" / "2026-10-16_placement_study"
DELAYS = (4, 8, 12, 18, 24, 36)
# priors where the placement study has no measurement (documented in calibration.json)
PRIORS = {"stable": 0.75, "boundary": 0.6, "old_shift": 0.75, "long_drift": 0.8, "recurring": 0.35,
          "routine": 0.7, "real_routine": 0.7, "zero_idle": 0.9, "calib_drift": 0.6, "saturation": 0.8,
          "dropout": 0.75, "compound": 0.9}  # compound = multiplier on the dominant pattern
PROXY = {"throttling": "exponential_increase", "stuck": "flatline", "quantised": "flatline", "noise": "erratic",
         "bias": "step_increase", "noise_increase": "erratic"}  # quantised: flatline table (pattern flatline, fault_kind quantised)


def build_calibration():
    """Accuracy by pattern x readings-since-onset, and a size multiplier, from the placement study raw data
    (v1 agent on the QIDK NPU). Writes calibration.json; falls back to it when the raw data is absent."""
    if CAL_PATH.exists():
        return json.loads(CAL_PATH.read_text())
    summ = json.loads((PLACEMENT / "summary.json").read_text())
    acc = {p: {d: summ[p][str(d)]["pattern"]["rate"] for d in DELAYS} for p in summ if p != "ALL"}
    size = None
    try:
        sys.path.insert(0, str(V.TRAIN / "window_study"))
        sys.path.insert(0, str(V.TRAIN / "export"))
        import window_study as W
        cases = {c["id"]: c for c in map(json.loads, open(PLACEMENT / "cases.jsonl", encoding="utf-8"))}
        truth = {(p["id"], p["n"]): p["truth"] for p in map(json.loads, open(PLACEMENT / "prompts.jsonl", encoding="utf-8"))}
        bins = {"4-6": [0, 0], "6-8": [0, 0], "8-10": [0, 0], "10-12": [0, 0]}
        for r in map(json.loads, open(PLACEMENT / "samples.jsonl", encoding="utf-8")):
            c = cases[r["id"]]
            if c["pattern"] in ("flatline", "erratic", "oscillation"):
                continue  # their size parameter is not the event amplitude
            pr = W.parse(r["text"])
            ok = bool(pr and pr["pattern"] == truth[(r["id"], r["n"])]["pattern"])
            A = c["event"]["A"]
            b = "4-6" if A < 6 else "6-8" if A < 8 else "8-10" if A < 10 else "10-12"
            bins[b][0] += ok
            bins[b][1] += 1
        pooled = sum(v[0] for v in bins.values()) / sum(v[1] for v in bins.values())
        size = {b: {"acc": round(v[0] / v[1], 3), "n": v[1], "mult": round(v[0] / v[1] / pooled, 3)} for b, v in bins.items()}
        size["3-4"] = {"acc": None, "n": 0, "mult": round(2 * size["4-6"]["mult"] - size["6-8"]["mult"], 3),
                       "note": "linear extrapolation of the 4-6 and 6-8 bins"}
    except Exception as e:  # noqa: BLE001
        print("calibration: size table unavailable:", e)
    cal = {"source": "proofs/2026-10-16_placement_study (summary.json + raw samples), v1 agent on the QIDK NPU",
           "pattern_by_readings_since_onset": acc, "size_multiplier": size, "priors": PRIORS, "proxy": PROXY,
           "rule": "conf = clip(acc[pattern](d) * size_mult(size), 0.30, 0.95), linear in d between 4..36 readings "
                   "(clamped), rounded to 0.05; priors where unmeasured"}
    CAL_PATH.write_text(json.dumps(cal, indent=1))
    return cal


CAL = None


def calibrated(key, d=None, size=None):
    global CAL
    if CAL is None:
        CAL = build_calibration()
    if key in PRIORS and key != "compound":
        c = PRIORS[key]
    else:
        p = PROXY.get(key, key)
        tab = CAL["pattern_by_readings_since_onset"].get(p)
        if tab is None:
            c = 0.7
        else:
            ds = [int(x) for x in tab]
            vs = [tab[str(x)] if str(x) in tab else tab[x] for x in ds]
            dd = min(max(d if d is not None else 36, ds[0]), ds[-1])
            for i in range(len(ds) - 1):
                if ds[i] <= dd <= ds[i + 1]:
                    w = (dd - ds[i]) / (ds[i + 1] - ds[i])
                    c = vs[i] * (1 - w) + vs[i + 1] * w
                    break
        sm = CAL.get("size_multiplier")
        if size is not None and sm:
            b = "3-4" if size < 4 else "4-6" if size < 6 else "6-8" if size < 8 else "8-10" if size < 10 else "10-12"
            c *= sm[b]["mult"]
    c = min(0.95, max(0.30, c))
    return round(round(c * 20) / 20, 2)


# ---------------------------------------------------------------- evidence strings for templates
def evidence_vals(role, metric, st, info, end_epoch, n, node=None):
    m = V.METRICS[(role, metric)]
    dec, unit = m["dec"], m["unit"]
    sd = max(dec, 1)
    u = f" {unit}" if unit else ""
    T = lambda i: V.idx_time(end_epoch, n, i)
    fm = lambda x: F.fmt(x, dec)
    v = {"M": NICE.get(metric, metric), "u": u, "last": fm(st["last"]), "max": fm(st["max"]), "tmax": T(st["max_idx"]),
         "min": fm(st["min"]), "tmin": T(st["min_idx"]), "slope": f"{st['slope_per_h']:+.{sd}f}{u}/h", "r2": f"{st['r2']:.2f}",
         "jump": f"{st['max_jump_signed']:+.{sd}f}", "tjump": T(st["max_jump_idx"]), "sma": fm(st["sma_1h"]),
         "ema": fm(st["ema_1h"]), "mean": fm(st["mean"]), "h1": fm(st["first_half"]), "h2": fm(st["second_half"]),
         "curv": f"{st['curvature']:+.{sd}f}", "zc": str(st["zero_cross"]), "noise": f"{st['noise']:.{sd + 1}f}",
         "flat": str(st["flat_run"]), "plateau": str(st["plateau_run"]), "hh": f"{info['hist_len'] * 5 / 60:.0f}",
         "k": str(info.get("exc_count", 0)), "peak": f"{info.get('exc_peak', 0.0):.1f}"}
    tl = V.NODE_LIMITS.get(node) if (role, metric) == ("water", "level") else None
    if tl:
        v.update(high=fm(tl["high"]), overflow=fm(tl["overflow"]), fill=str(tl["fill_min"]))
    for f in info.get("long_view") or []:
        if f["kind"] == "level_shift":
            v.update(shift=f"{f['delta']:+.{sd}f}", tshift=f["time"], sig=f"{f['sigma']:.1f}")
        else:
            v.update(drift=f"{f['delta']:+.{sd}f}", tdrift=f["time"], dr2=f"{f['r2']:.2f}", dsig=f"{f['sigma']:.1f}")
    return v


def lv_kinds(info):
    return {f["kind"]: f for f in (info.get("long_view") or [])}


# ---------------------------------------------------------------- routine rules
def _hour(end_epoch):
    d = datetime.fromtimestamp(end_epoch, V.IST)
    return d.hour + d.minute / 60, d.weekday()


def _hm(t):
    h, mm = t.split(":")
    return int(h) + int(mm) / 60


def osc_period_min(st, n):
    zc = st["zero_cross"]
    return (2 * n * 5 / zc) if zc else 1e9


def step_in_window(st):
    half = st["second_half"] - st["first_half"]
    return abs(half) > 0 and abs(st["max_jump"]) >= 0.45 * abs(half) and (st["max_jump_signed"] > 0) == (half > 0)


def fill_minutes(st, end_epoch, n):
    """Length of the current fill as the evidence shows it: from the window minimum (E3 time) to the window
    end, counted only when the maximum is the last reading (E2 at the window end) and the minimum precedes it."""
    if st["max_idx"] < n - 1 or st["min_idx"] >= st["max_idx"]:
        return 0
    return (n - 1 - st["min_idx"]) * 5


DRAIN_PTS = 36  # P1 2026-10-25 (proofs/2026-10-25_domain_plan): 3 h steady drain with no refill = possible leak by day


def long_drain(xs, noise):
    """= app/backend postrules.go postLongDrain: the last 3 h fall by >= max(10x noise, 5% of the level) with no
    rebound above max(3x noise, 10% of the drop)."""
    n = len(xs or [])
    if n < DRAIN_PTS:
        return False
    seg = xs[n - DRAIN_PTS:]
    drop = seg[0] - seg[-1]
    if drop <= 0 or drop < max(10 * noise, 0.05 * abs(seg[0])):
        return False
    lo, rise = seg[0], 0.0
    for v in seg:
        lo = min(lo, v)
        rise = max(rise, v - lo)
    return rise <= max(3 * noise, 0.1 * drop)


def routine_rule(role, metric, node, p, status, st, end_epoch, n, xs=None):
    """(status, cause, why-template key) when the evidence matches a routine, else None.
    xs (the window, optional): enables the P1 daytime long-drain leak (label-definition change 2026-10-25)."""
    hr, wd = _hour(end_epoch)
    m = V.METRICS[(role, metric)]
    below = status == "normal"
    if role == "water" and metric == "level":
        tl = V.NODE_LIMITS.get(node)
        if tl and st["last"] >= tl["overflow"]:
            return "critical", "tank_overflow_risk", "why_overflow"
        if p in ("step_increase", "gradual_increase", "exponential_increase", "throttling"):
            if tl and st["max"] >= tl["high"]:
                return "warning", "tank_overflow_risk", "why_overflow"
            if tl and fill_minutes(st, end_epoch, n) >= 2 * tl["fill_min"]:
                return "warning", "fill_valve_stuck", "why_valve"
            return "normal", "tank_filling", "why_refill"
        if p == "oscillation" and F.is_off_hours(end_epoch):
            return "warning", "possible_leak", "why_night_refills"
        if p == "gradual_decrease":
            if F.is_off_hours(end_epoch):
                return "warning", "possible_leak", "offhours_water"
            if xs is not None and long_drain(xs, st["noise"]):
                return "warning", "possible_leak", "why_day_leak"
            return "normal", "tank_draining", "why_drain"
    if role == "water" and metric in ("level", "flow") and p == "oscillation":
        if osc_period_min(st, n) >= 50:
            return "normal", "pump_cycling", "why_pump"
        return "warning", "pump_cycling", "why_shortcycle"
    if role == "power" and metric == "power_kw":
        solar = node.startswith("SL-")
        if not solar:
            if p == "oscillation":
                return "normal", "cyclic_equipment", "why_loadcycle"
            tj = _hm(V.idx_time(end_epoch, n, st["max_jump_idx"]))
            if wd < 5 and step_in_window(st):
                if p == "step_increase" and 7.0 <= tj <= 10.5:
                    return "normal", "equipment_startup", "why_startup"
                if p == "step_decrease" and 17.0 <= tj <= 21.0 and st["last"] >= 0.1 * max(st["first_half"], 1e-9):
                    return "normal", "normal_load", "why_shutdown"
        else:
            if (p == "gradual_increase" and 6 <= hr < 12) or (p == "gradual_decrease" and 12 <= hr < 19):
                return "normal", "normal_load", "why_solar"
    if role == "weather" and below:
        if metric == "temp":
            if p == "gradual_increase" and 7 <= hr < 15 and st["slope_per_h"] <= 3.0:
                return "normal", "diurnal_cycle", "why_diurnal"
            if p == "gradual_decrease" and (hr >= 15 or hr < 7) and st["slope_per_h"] >= -3.0:
                return "normal", "diurnal_cycle", "why_diurnal"
        if metric == "rh":
            if (p == "gradual_decrease" and 7 <= hr < 15) or (p == "gradual_increase" and (hr >= 15 or hr < 7)):
                return "normal", "diurnal_cycle", "why_diurnal"
    if role == "air_quality" and below:
        if metric == "co2":
            if p in ("gradual_increase", "step_increase") and 8 <= hr < 20:
                return "normal", "occupancy_load", "why_occ_co2"
            if p == "gradual_decrease":
                return "normal", "normal_conditions", "why_co2_decay"
        if metric in ("pm25", "pm10") and node.startswith("AQ-") and p in ("gradual_increase", "gradual_decrease", "step_increase", "oscillation"):
            return "normal", "normal_conditions", "why_outdoor_pm"
        if metric == "temp" and node.startswith("SR-") and p == "oscillation" and st["range"] <= 2.0:
            return "normal", "normal_conditions", "why_hvac_cycle"
    return None


def fault_rule(role, metric, node, p, st, info, end_epoch, zero, hint=None):
    """fault_kind if the evidence shows a sensor fault, else None. hint = the generator's fault family."""
    key = (role, metric)
    m = V.METRICS[key]
    if p == "flatline" and not zero:
        return "quantised" if hint == "quantised" else "stuck"
    if p == "erratic" and role != "power":
        return "dropout" if hint == "dropout" else "noise"
    if p in ("dip", "erratic") and key in DROPOUT_METRICS and st["min"] == 0.0 and hint == "dropout":
        return "dropout"
    if p in ("step_increase", "step_decrease") and key in RATE and abs(st["max_jump_signed"]) > RATE[key]:
        return "bias"
    if p == "throttling" and key in SATURATION_METRICS and st["max"] >= m["hi"]:
        return "saturation"
    lv = lv_kinds(info)
    if (key in DRIFT_FAULT_METRICS and node.startswith("SR-") and "slow_drift" in lv and lv["slow_drift"]["r2"] >= DRIFT_R2
            and info.get("hist_len", 0) >= DRIFT_MIN_PTS and lv["slow_drift"]["sigma"] >= DRIFT_SIGMA
            and F.is_off_hours(end_epoch) and p in ("gradual_increase", "gradual_decrease", "stable")):
        return "drift"
    return None


EXTRA_ACTION = {"tank_overflow_risk": "inspect_water_system", "fill_valve_stuck": "inspect_water_system"}


def action_of(cause, status):
    """v1 generate_dataset.action_of plus the v2 water causes (both map to inspect_water_system)."""
    if cause in EXTRA_ACTION:
        return EXTRA_ACTION[cause]
    return G.action_of(cause, status)


# ---------------------------------------------------------------- the label
def label(ex):
    """ex: dict with role, metric, node, pattern (shape), family, size, d (readings since onset or None),
    onset_idx (window index or None), active, fault_hint, secondary, st, info, end_epoch, n, base_mean, zero.
    Returns (target dict in frozen key order, meta dict)."""
    role, metric, node, n, end = ex["role"], ex["metric"], ex["node"], ex["n"], ex["end_epoch"]
    st, info = ex["st"], ex["info"]
    p = ex["pattern"]
    fam = ex["family"]
    rng = ex["rng"]
    zero = ex.get("zero", False)
    vals = evidence_vals(role, metric, st, info, end, n, node)
    T = lambda i: V.idx_time(end, n, i)
    wstart = T(0)
    m = V.METRICS[(role, metric)]
    lv = lv_kinds(info)
    obs2 = None
    small = ex.get("size") is not None and ex["size"] < BOUNDARY and fam in AMPLITUDE_FAMILIES
    fault = None
    why = None
    if small:
        shape = p
        p = "stable"
    fault = None if small else fault_rule(role, metric, node, p, st, info, end, zero, ex.get("fault_hint"))
    if fault:
        status, cause = "sensor_fault", "sensor_fault"
    else:
        status = G.status_of(role, metric, p, st, ex.get("base_mean", st["mean"]))
        if p == "flatline" and zero:
            status = "normal"
        if fam == "recurring":
            # small recurring excursions are "normal" unless a fixed limit is crossed
            if m["warn"] is None or status == "normal":
                status, cause = "normal", RECUR_CAUSE.get((role, metric), NORMAL_CAUSE[role])
            else:
                cause = G.cause_of(role, metric, "spike", status, F.is_off_hours(end), node.startswith("SR-"), zero)
        else:
            cause = G.cause_of(role, metric, p, status, F.is_off_hours(end), node.startswith("SR-"), zero)
        r = routine_rule(role, metric, node, p, status, st, end, n, ex.get("xs"))
        if r and fam != "recurring":
            status, cause, why = r
    # ---- event_active / onset
    if p == "stable" or (p == "flatline" and zero):
        active, onset = False, wstart
    elif p == "spike" and fam != "recurring":
        active, onset = bool(ex.get("active")), vals["tmax"]
    elif p == "dip" and fault != "dropout":
        active, onset = bool(ex.get("active")), vals["tmin"]
    elif fam in ("old_shift", "real_longrange") and "level_shift" in lv:
        active, onset = True, lv["level_shift"]["time"]
    elif fam == "real_longrange" and "slow_drift" in lv:
        active, onset = True, lv["slow_drift"]["time"]
    elif p in ("step_increase", "step_decrease") and (ex.get("onset_idx") is None or
                                                     abs(st["max_jump_idx"] - ex["onset_idx"]) <= ex.get("ramp", 1) + 1):
        active, onset = True, vals["tjump"]
    elif fam == "recurring":
        active = bool(ex.get("active"))
        onset = T(ex["onset_idx"]) if ex.get("onset_idx") is not None and ex["onset_idx"] >= 0 else ex.get("onset_time", wstart)
    else:
        active = True
        oi = ex.get("onset_idx")
        onset = ex.get("onset_time") or (T(oi) if oi is not None and oi >= 0 else wstart)
    # ---- observations
    if small:
        k = {"spike": "small_blip", "dip": "small_dip", "step_increase": "small_shift", "step_decrease": "small_shift",
             "old_shift": "small_shift"}.get(shape, "small_trend")
        if shape == "oscillation" or fam in ("old_shift", "long_drift"):
            k = "stable"
        obs1 = TP.fill(k, vals, rng)
    else:
        obs1 = TP.fill(obs1_key(p, fam, ex, lv, role, zero, status), vals, rng, contradicting(p, st))
    # second observation (at most one, by priority)
    if fault and fault != "stuck":
        obs2 = TP.fill({"bias": "why_bias", "drift": "why_drift", "noise": "why_noise", "quantised": "why_quantised",
                        "dropout": "why_dropout", "saturation": "why_saturation"}[fault], vals, rng)
    elif fault == "stuck":
        obs2 = TP.fill("why_stuck", vals, rng) if rng.random() < 0.5 else None
    elif status in ("warning", "critical") and m["warn"] is not None:
        obs2 = limit_obs(role, metric, p, status, st, vals, rng)
    elif why:
        av = ("{last}",) if why == "why_overflow" and st["last"] < V.NODE_LIMITS.get(node, {}).get("high", -1e18) else ()
        obs2 = TP.fill(why, vals, rng, av) if why != "offhours_water" or rng.random() < 0.8 else None
    elif fam == "compound" and ex.get("secondary") in ("spike", "dip"):
        obs2 = TP.fill("compound_" + ex["secondary"], vals, rng)
    elif (role == "water" and metric in ("flow", "level") and F.is_off_hours(end) and not zero
          and p in ("stable", "gradual_decrease", "step_increase", "exponential_increase") and status != "normal"):
        obs2 = TP.fill("offhours_water", vals, rng)
    elif fam == "recurring" and ex.get("window_spike"):
        obs2 = TP.fill("recurring_recent", vals, rng) if rng.random() < 0.7 else None
    elif not small and p != "stable" and "level_shift" in lv and fam not in ("old_shift", "real_longrange") and rng.random() < 0.5:
        obs2 = TP.fill("context_shift", vals, rng)
    elif not small and p != "stable" and "slow_drift" in lv and fam not in ("long_drift", "real_longrange") and rng.random() < 0.5:
        obs2 = TP.fill("context_drift", vals, rng)
    elif p in ("spike", "dip") and info.get("exc_count", 0) >= 2 and fam != "recurring" and rng.random() < 0.5:
        obs2 = TP.fill("context_episodes", vals, rng)
    obs = [obs1] + ([obs2] if obs2 else [])
    # ---- confidence
    d = ex.get("d")
    if small:
        conf = calibrated("boundary")
    elif fam in ("routine", "real_routine") or why:
        conf = calibrated("real_routine" if fam == "real_routine" else "routine")
    elif fam == "stable" or p == "stable":
        conf = calibrated("stable")
    elif p == "flatline" and zero:
        conf = calibrated("zero_idle")
    elif fam in ("old_shift", "long_drift", "recurring") or fam == "real_longrange":
        conf = calibrated({"real_longrange": "old_shift" if "level_shift" in lv else "long_drift"}.get(fam, fam))
    elif fault in ("drift", "saturation", "dropout"):
        conf = calibrated({"drift": "calib_drift"}.get(fault, fault))
    elif fault:
        conf = calibrated(ex.get("fault_hint") or fault, d, None)
    else:
        conf = calibrated(p, d, ex.get("size"))
        if fam == "compound":
            conf = round(round(min(0.95, max(0.3, conf * PRIORS["compound"])) * 20) / 20, 2)
    target = {"pattern": p, "status": status, "observations": obs, "likely_cause": cause, "confidence": conf,
              "event_active": active, "onset": onset}
    if status == "sensor_fault":
        target["fault_kind"] = fault or "noise"
    target["action"] = action_of(cause, status)
    meta = {"small": small, "fault_kind": fault, "routine": why}
    return target, meta


UP = {"gradual_increase", "step_increase", "exponential_increase", "throttling"}
DOWN = {"gradual_decrease", "step_decrease"}


def contradicting(p, st):
    """Placeholders whose evidence points the other way (young events: the window halves or the whole-window
    trend may not move with the event yet)."""
    if p not in UP and p not in DOWN:
        return ()
    sg = 1 if p in UP else -1
    av = []
    if (st["second_half"] - st["first_half"]) * sg <= 0:
        av += ["{h1}", "{h2}"]
    if st["slope_per_h"] * sg <= 0:
        av += ["{slope}"]
    if st["max_jump_signed"] * sg <= 0:
        av += ["{jump}"]
    if p == "exponential_increase" and st["curvature"] <= 0:
        av += ["{curv}"]
    return tuple(av)


AMPLITUDE_FAMILIES = {"event", "old_shift", "long_drift", "compound"}


def obs1_key(p, fam, ex, lv, role, zero, status):
    if fam == "recurring":
        return "recurring"
    if fam in ("old_shift", "real_longrange") and "level_shift" in lv and p in ("step_increase", "step_decrease"):
        return "old_shift_up" if p == "step_increase" else "old_shift_down"
    if fam in ("long_drift", "real_longrange") and "slow_drift" in lv and p in ("gradual_increase", "gradual_decrease"):
        return "long_drift_up" if p == "gradual_increase" else "long_drift_down"
    if fam == "calib_drift" and "slow_drift" in lv:
        return "long_drift_up" if lv["slow_drift"]["delta"] > 0 else "long_drift_down"
    if p == "spike":
        return "spike_now" if ex.get("active") else "spike"
    if p == "dip":
        return "dip_now" if ex.get("active") else "dip"
    return {"gradual_increase": "gradual_up", "gradual_decrease": "gradual_down", "step_increase": "step_up",
            "step_decrease": "step_down", "exponential_increase": "exp", "oscillation": "osc", "throttling": "throttle",
            "flatline": "flat_idle" if zero else "flat_stuck",
            "erratic": "erratic_power" if role == "power" else "erratic_fault", "stable": "stable"}[p]


def limit_obs(role, metric, p, status, st, vals, rng):
    m = V.METRICS[(role, metric)]
    lim = m["crit"] if status == "critical" else m["warn"]
    if m["dir"] == "low" or (metric == "ph" and st["min"] < 6.5):
        if metric == "ph":
            lim = 6.0 if status == "critical" else 6.5
        val, eid = (vals["min"], "E3") if p in ("spike", "dip") else (vals["last"], "E1")
        return TP.fill("limit_below", dict(vals, val=val, eid=eid, lim=lim, status=status), rng)
    val, eid = (vals["max"], "E2") if p in ("spike", "throttling") else (vals["last"], "E1")
    return TP.fill("limit_above", dict(vals, val=val, eid=eid, lim=lim, status=status), rng)


# ---------------------------------------------------------------- occupancy
def occ_label(xs, end_epoch, n):
    """v1 occ_label with the flapping threshold scaled to the window (v1: >= 12 changes in 4 h = 3 per hour)."""
    st = F.occ_stats(xs)
    if st["occupied_frac"] == 0:
        return "vacant", st
    if F.is_off_hours(end_epoch):
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


def occ_target(pattern, st, info, end_epoch, n, rng):
    T = lambda i: V.idx_time(end_epoch, n, i)
    vals = {"frac": f"{st['occupied_frac']:.2f}", "tog": str(st["toggles"]),
            "fon": T(st["first_on"]) if st["first_on"] >= 0 else "", "lon": T(st["last_on"]) if st["last_on"] >= 0 else "",
            "f12": f"{info['occ_frac_12h']:.2f}"}
    fault = None
    flap = pattern == "intermittent" and st["toggles"] >= 3 * n * 5 / 60
    if pattern == "vacant":
        status, cause, key, conf = "normal", "vacant", "occ_vacant", 0.95
    elif pattern == "occupied":
        status, cause, key, conf = "normal", "normal_occupancy", "occ_occupied", 0.9
    elif pattern == "arrival":
        status, cause, key, conf = "normal", "arrival", "occ_arrival", 0.9
    elif pattern == "departure":
        status, cause, key, conf = "normal", "departure", "occ_departure", 0.9
    elif flap:
        status, cause, key, conf, fault = "sensor_fault", "sensor_fault", "occ_flapping", 0.75, "noise"
    elif pattern == "intermittent":
        status, cause, key, conf = "normal", "intermittent_presence", "occ_intermittent", 0.85
    else:
        status, cause, key, conf = "warning", "off_hours_presence", "occ_offhours", 0.85
    obs = [TP.fill(key, vals, rng)]
    if pattern in ("occupied", "off_hours_presence", "intermittent") and not flap and rng.random() < 0.35:
        obs.append(TP.fill("occ_history", vals, rng))
    active = st["last"] >= 0.5 and pattern != "vacant"
    if pattern == "vacant":
        onset = T(0)
    elif pattern == "departure":
        onset = vals["lon"]
    else:
        onset = vals["fon"] or T(0)
    tgt = {"pattern": pattern, "status": status, "observations": obs, "likely_cause": cause, "confidence": conf,
           "event_active": bool(active), "onset": onset}
    if fault:
        tgt["fault_kind"] = fault
    tgt["action"] = G.action_of(cause, status)
    return tgt
