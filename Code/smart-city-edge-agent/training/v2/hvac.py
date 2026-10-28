"""HVAC domain agent (retrain v2, spec decision #19): role spec, data loading, pattern injection and
deterministic teacher labels for ONE indoor AC unit (= one room).

Imported by the v2 generator (training/v2/). Pure Python, no numpy, deterministic given `rng`.

Why per unit and not the v1 floor aggregate (data/series/hvac/AC-KHxx.csv): setpoints differ per unit,
and short-cycling / stuck states are invisible in a floor count. The per-unit series come from the same
source file (training/v2/extract_hvac_units.py -> data/series/hvac_units/). Facts quoted in the
threshold comments are from training/v2/HVAC_DATA.md.

A HVAC *window* is n consecutive 5-minute points (n = 48 / 96 / 144 for 4 / 8 / 12 h) of one unit:
  xs              room temperature, C (primary series shown to the model)
  ctx["sp"]       setpoint per point, C
  ctx["on"]       run state per point, 0/1 (Start Stop Status)
  ctx["thermo"]   per point fraction 0..1 of "thermo on" (unit calling for cooling) or None if the
                  unit never reports it (only 11 of 87 units do)
  ctx["mode"]     last operating mode: 1 cool, 3 fan, 5 dry
  ctx["alarm"]    per point 0/1;  ctx["malf"]: last malfunction code (1 = none)
  ctx["missing"]  per point bool: no reading in the bucket (value was filled)
  ctx["occ"]      per point 0/1 occupancy of the room, or None (no room-level occupancy exists in the
                  data; the generator may attach a real vacant/occupied sequence, see HVAC_DATA.md)
  ctx["duty"]     "office" | "continuous" | "idle"  (unit's usual schedule, from TRAIN months only)
  ctx["hour_on"]  24 floats: the unit's usual on-fraction per IST hour (TRAIN months only)
  ctx["end"]      epoch of the last point (bucket start)
  ctx["node"]     unit id, e.g. SR-AC-KH02-12
"""
from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
STEP = 300  # s per point

# ------------------------------------------------------------------------------------- thresholds
BAND_HI = 2.0     # C above setpoint = "too warm": normal running error p10..p90 is about -1.6..+1.3 C
BAND_LO = 3.0     # C below setpoint = "too cold": normal units' running error p10 reaches -2.3..-2.9 C
COLD_ABS = 24.0   # too_cold also needs room < 24 C: a unit set to 30-32 C (seen in data) is not overcooling
COLD_HARD = 20.0  # below 20 C while cooling is overcooling regardless of setpoint
HOT_OFF = 34.0    # base filter only: AC-off units read 34-45 C in still air (thermistor in the ceiling unit,
                  # not the room), so an AC-off room is never called too_hot unless occupancy says occupied
HOT_OCC = 30.0    # AC off but room known occupied: 30 C is the v1 indoor temperature warning limit
CRIT_T = 34.0     # critical room temperature (same as the v1 indoor temp critical limit)
MIN_PTS = 3       # a condition must hold >= 3 readings (15 min) before it is a pattern (spec #6 youngest age)
WARN_PTS = 6      # ... and >= 6 readings (30 min) before it is a warning ("too long")
WARN_EXCESS = 1.0  # C beyond the band edge needed for a warning (~3x the 0.3 C floor, spec #11)
RUN_PTS = 12      # 60 min of running before "no cooling"/"slow recovery" can be judged (real pull-down ~45-60 min)
NOCOOL_SLOPE = -0.3  # C/h: above band and falling slower than this after 1 h = no cooling effect
FAST_SLOPE = -1.2    # C/h: falling at least this fast = normal pull-down (real first-30-min median -3.2 C/h)
SC_STARTS = 4     # short cycling: >= 4 starts per 4 h ...
SC_RUN = 3        # ... with median on-run <= 3 readings (15 min); real on-run p10 = 4 readings
SC_CRIT = 8       # >= 8 starts per 4 h is critical
FLAT_PTS = 24     # stuck temperature: 2 h exactly flat while the unit runs (idle rooms sit flat 1-2 h: 0.1 C sensor)
FLAT_EPS = 0.05   # C: "no change" (sensor resolution is 0.1 C)
ERR_NOISE = 0.8   # C per 5 min robust noise (whole window or last hour) = erratic; 98.8% of real windows are below
JUMP_C = 2.0      # C in one 5-min step while the unit runs steadily in cool mode = bias jump (cooling moves
                  # ~0.25 C/5 min). Not applied with the AC off: idle units show real 2-5 C steps (airflow over
                  # the thermistor changes), see HVAC_DATA.md
STUCK_OFF_USUAL = 0.5  # stuck_off: unit normally on >= 50% at this hour (TRAIN months) but off all window
DRIFT_SLOPE = -0.8  # C/h falling with the AC off in daytime (11-18 h) = calibration drift; -0.5 hit 0.6% of real
                    # idle windows (neighbour units cool idle rooms), -0.8 with a 2 C drop is rarer
DRIFT_DROP = 2.0    # C total drop needed for drift
DRIFT_PTS = 30      # over >= 150 min (D7: tightened from 90 min so real idle-room cooling rarely qualifies)
DRIFT_R2 = 0.85     # clean linear decline (D7: tightened from 0.7)
BIAS_HOT = 36.0     # C: a room read >= 36 C after >= 1 h of cooling is a biased sensor (3 real units read 39-45 C
                    # while cooling; healthy running units stay below ~33 C)
GRID_PTS = 12       # quantised: >= 1 h of readings all on a whole-degree grid, >= 2 levels, >= 3 changes
                    # (the real sensor reports 0.1 C steps; tenths are uniformly spread in the data)
DROP_FRAC = 0.25  # >= 25% missing readings = dropout
SAT_PTS = 6       # >= 6 readings pinned at the 10 C / 45 C extraction limits = saturation
VACANT_PTS = 12   # AC on through >= 60 min of vacancy = running in an empty room (30-60 min grace is normal)
SETBACK_SLOPE = 0.25  # C/h rise after switch-off/at night = normal setback drift (ambient re-heating)
SETBACK_RISE = 0.6    # C rise needed to call it a drift rather than stable
STUCK_ON_SP = 0.5     # stuck_on: room already <= setpoint + 0.5 C (no cooling need) during off-hours
TEMP_LO, TEMP_HI = 10.0, 45.0  # extraction limits (readings outside are dropped as glitches)

# ------------------------------------------------------------------------------------- role spec
METRICS = {
    ("hvac", "room_temp"): dict(unit="C", dec=1, warn=30, crit=34, dir="both", floor=0.3, lo=TEMP_LO, hi=TEMP_HI,
                                band_hi=BAND_HI, band_lo=BAND_LO),
    ("hvac", "setpoint"):  dict(unit="C", dec=1, warn=None, crit=None, dir="both", floor=0.0, lo=16, hi=32),
    ("hvac", "ac_on"):     dict(unit="0/1", dec=0, warn=None, crit=None, dir="high", floor=0.0, lo=0, hi=1),
    ("hvac", "thermo"):    dict(unit="", dec=2, warn=None, crit=None, dir="high", floor=0.0, lo=0, hi=1),
}

NORMAL_PATTERNS = ("stable", "normal_cycling", "pull_down", "setback_drift")
EVENT_PATTERNS = ("too_hot", "too_cold", "slow_recovery", "no_cooling_effect", "short_cycling",
                  "stuck_on", "stuck_off", "running_empty_room", "unit_alarm")
FAULT_PATTERNS = ("flatline", "erratic", "bias_jump", "biased_reading", "calibration_drift", "dropout", "saturation",
                  "quantised")
PATTERNS = NORMAL_PATTERNS + EVENT_PATTERNS + FAULT_PATTERNS

FAULT_KIND = {"flatline": "stuck", "erratic": "noise", "bias_jump": "bias", "biased_reading": "bias",
              "calibration_drift": "drift", "dropout": "dropout", "saturation": "saturation", "quantised": "quantised"}

CAUSES = ("normal_operation", "scheduled_off", "high_heat_load", "ac_not_cooling", "overcooling",
          "ac_off_heat_gain", "short_cycling_control", "schedule_or_control_fault", "unit_not_starting",
          "unoccupied_running", "unit_alarm", "sensor_fault")

# only existing features.ACTIONS are used (no new action needed)
ACTION_OF = {
    "normal_operation": "none", "scheduled_off": "none", "high_heat_load": "monitor",
    "ac_not_cooling": "inspect_hvac", "overcooling": "review_schedule", "ac_off_heat_gain": "review_schedule",
    "short_cycling_control": "inspect_hvac", "schedule_or_control_fault": "review_schedule",
    "unit_not_starting": "inspect_hvac", "unoccupied_running": "switch_off_ac", "unit_alarm": "inspect_hvac",
    "sensor_fault": "check_sensor",
}
ACTIONS = tuple(sorted(set(ACTION_OF.values())))
# D9: new action value, a RECOMMENDATION that needs human approval (no actuation). The backend action
# whitelist / policy must accept it.
NEW_ACTIONS = ("switch_off_ac",)

SYSTEM_PROMPT = "You are the HVAC agent of a smart-campus edge monitor (IIIT Hyderabad)."

HVAC_ROLE = dict(
    role="hvac", system_prompt=SYSTEM_PROMPT, primary_metric="room_temp", metrics=METRICS,
    patterns=PATTERNS, normal_patterns=NORMAL_PATTERNS, event_patterns=EVENT_PATTERNS,
    fault_patterns=FAULT_PATTERNS, fault_kind=FAULT_KIND, causes=CAUSES, actions=ACTIONS, action_of=ACTION_OF,
    hard_negatives=("normal_cycling", "pull_down", "setback_drift", "night_setback", "weekend_off",
                    "continuous_duty", "fan_mode", "small_excursion", "setpoint_change_ok"),
)


def action_of(cause, status):
    """Backend-derived action (same escalation idea as v1 generate_dataset.action_of)."""
    a = ACTION_OF[cause]
    if a == "none" and status in ("warning", "critical"):
        return "monitor"
    if a == "monitor" and status == "critical":
        return "inspect_hvac"
    return a


# ------------------------------------------------------------------------------------- helpers
def _mean(v):
    return sum(v) / len(v)


def _median(v):
    s = sorted(v)
    k = len(s)
    return s[k // 2] if k % 2 else 0.5 * (s[k // 2 - 1] + s[k // 2])


def _slope_h(v):
    """OLS slope in C/h of 5-min samples, and r2."""
    k = len(v)
    if k < 2:
        return 0.0, 0.0
    tm = (k - 1) / 2
    ym = _mean(v)
    sxx = sum((t - tm) ** 2 for t in range(k))
    sxy = sum((t - tm) * (y - ym) for t, y in enumerate(v))
    b = sxy / sxx
    sst = sum((y - ym) ** 2 for y in v)
    sse = sum((y - (ym + b * (t - tm))) ** 2 for t, y in enumerate(v))
    return b * 12.0, (1 - sse / sst) if sst > 1e-12 else 0.0


def robust_noise(xs):
    d = [xs[i] - xs[i - 1] for i in range(1, len(xs))]
    md = _median(d)
    return 1.4826 * _median([abs(x - md) for x in d]) / math.sqrt(2)


def scale_of(xs):
    """Event-size unit s0: the 0.3 C floor (3 sensor steps) or 1.5x the robust noise if larger."""
    return max(METRICS[("hvac", "room_temp")]["floor"], 1.5 * robust_noise(xs))


def idx_time(end, n, i):
    return datetime.fromtimestamp(end - (n - 1 - i) * STEP, IST).strftime("%H:%M")


def local(end):
    return datetime.fromtimestamp(end, IST)


def off_hours(end):
    """Night (22:00-06:00) or Sunday at the window end. Saturday is a working day on this campus:
    floor on-fraction Sat 0.35 vs Mon-Fri 0.41-0.46, Sunday 0.10 (HVAC_DATA.md)."""
    t = local(end)
    return t.hour >= 22 or t.hour < 6 or t.weekday() == 6


def working_hours(end):
    t = local(end)
    return t.weekday() < 6 and 9 <= t.hour < 19


def fmt1(v):
    return f"{v:.1f}"


def sample_onset(n, rng):
    """Spec #6: onset uniformly from 3 readings before the end back to the window start, with extra
    weight on 20-60 min (4-12 readings) before the end. Returns the onset index."""
    if rng.random() < 0.35:
        age = rng.randint(4, 12)
    else:
        age = rng.randint(3, n)
    return max(0, n - age)


def _runs(bits):
    """List of (value, start, length) runs."""
    out = []
    i = 0
    while i < len(bits):
        j = i
        while j < len(bits) and bits[j] == bits[i]:
            j += 1
        out.append((bits[i], i, j - i))
        i = j
    return out


def _trailing(mask):
    k = 0
    for v in reversed(mask):
        if not v:
            break
        k += 1
    return k


# ------------------------------------------------------------------------------------- data
def _f(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load_hvac_series(series_dir, train_months=(1, 2, 3, 4, 5, 6, 7, 8)):
    """Load data/series/hvac_units/*.csv. Returns {node: unit} with
    unit = {"rows": {bucket: (on, thermo, temp|None, sp|None, mode|None, alarm, malf)},
            "has_thermo", "duty", "hour_on", "hot_sensor", "faulty"}.
    The schedule profile (duty, hour_on) uses TRAIN months only so dev/test windows do not leak."""
    d = Path(series_dir)
    d = d / "hvac_units" if (d / "hvac_units").is_dir() else d
    units = {}
    for p in sorted(d.glob("SR-AC-*.csv")):
        rows = {}
        on_h = [0] * 24
        n_h = [0] * 24
        th_any = 0
        temps_on = []
        alarms = 0
        with open(p, newline="") as fh:
            for r in csv.DictReader(fh):
                b = int(r["bucket"])
                on = 1 if r["on"] == "1" else 0
                th = _f(r["thermo"]) or 0.0
                t = _f(r["room_temp"])
                sp = _f(r["setpoint"])
                md = int(r["mode"]) if r["mode"] not in ("", None) else None
                al = 1 if r["alarm"] == "1" else 0
                mc = int(r["malf"]) if r["malf"] else 1
                rows[b] = (on, th, t, sp, md, al, mc)
                lt = local(b)
                if lt.month in train_months:
                    on_h[lt.hour] += on
                    n_h[lt.hour] += 1
                th_any += th > 0
                alarms += al
                if on and t is not None:
                    temps_on.append(t)
        hour_on = [on_h[h] / n_h[h] if n_h[h] else 0.0 for h in range(24)]
        tot = sum(on_h) / max(1, sum(n_h))
        night = _mean(hour_on[0:6])
        duty = "idle" if tot < 0.01 else ("continuous" if night >= 0.5 else "office")
        hot = bool(temps_on) and _median(temps_on) >= 36.0  # 3 units read 39-45 C while cooling: sensor bias
        units[p.stem] = dict(rows=rows, has_thermo=th_any > 100, duty=duty, hour_on=hour_on, hot_sensor=hot,
                             faulty=hot or alarms > 1000)  # SR-AC-KH01-15: alarm 37 for 26,858 buckets
    return units


def hvac_windows(unit, node, n=48, stride=6, min_have=None, months=None, on_stride=None):
    """Yield (xs, ctx) windows of one unit: >= min_have real temperature points (default n-3), first and
    last point real; temperature gaps linearly interpolated, setpoint forward/back filled, missing state = off.
    D12: windows whose last 4 h are >= 25% "on" advance by `on_stride` (dense, overlapping), others by `stride`."""
    rows = unit["rows"]
    if not rows:
        return
    min_have = n - 3 if min_have is None else min_have
    bs = sorted(rows)
    t = bs[0] + (n - 1) * STEP
    stop = bs[-1]
    while t <= stop:
        if months is not None and local(t).month not in months:
            t += stride * STEP
            continue
        pts = [rows.get(t - (n - 1 - i) * STEP) for i in range(n)]
        temps = [p[2] if p else None for p in pts]
        have = sum(v is not None for v in temps)
        if have < min_have or temps[0] is None or temps[-1] is None:
            t += STEP
            continue
        xs = list(temps)
        i = 0
        while i < n:
            if xs[i] is None:
                j = i
                while xs[j] is None:
                    j += 1
                a, b = xs[i - 1], xs[j]
                for k in range(i, j):
                    xs[k] = a + (b - a) * (k - i + 1) / (j - i + 1)
                i = j
            i += 1
        sp = [p[3] if p and p[3] is not None else None for p in pts]
        last = next((v for v in sp if v is not None), 24.0)
        for i in range(n):
            if sp[i] is None:
                sp[i] = last
            last = sp[i]
        modes = [p[4] for p in pts if p and p[4] is not None]
        ctx = dict(node=node, end=t, sp=sp, on=[p[0] if p else 0 for p in pts],
                   thermo=[p[1] if p else 0.0 for p in pts] if unit["has_thermo"] else None,
                   mode=modes[-1] if modes else 1, alarm=[p[5] if p else 0 for p in pts],
                   malf=next((p[6] for p in reversed(pts) if p and p[6] != 1), 1),
                   missing=[v is None for v in temps], occ=None, duty=unit["duty"], hour_on=unit["hour_on"],
                   faulty=unit.get("faulty", False))
        yield [round(v, 2) for v in xs], ctx
        running = sum(ctx["on"][-48:]) >= 0.25 * min(n, 48)
        t += (on_stride if (running and on_stride) else stride) * STEP


def base_kind(xs, ctx):
    """Classify a real window as an injection base: 'on' (running, in band), 'off' (idle, calm), or None.
    D11: windows of faulty units (hot thermistors, KH01-15 alarm 37) are never bases."""
    n = len(xs)
    if ctx.get("faulty") or any(ctx["alarm"]) or sum(ctx["missing"]) > 3:
        return None
    if all(ctx["on"]) and ctx["mode"] == 1:
        if all(ctx["sp"][i] - BAND_LO <= xs[i] <= ctx["sp"][i] + BAND_HI for i in range(n)) and robust_noise(xs) < 0.3:
            return "on"
        return None
    if not any(ctx["on"]) and max(xs) - min(xs) <= 2.0 and max(xs) < HOT_OFF - 1 and robust_noise(xs) < 0.3:
        return "off"
    return None


def is_ambiguous_real(xs, ctx):
    """Real windows the rules cannot label honestly; the generator should not use them as untouched
    examples: a >= 2 C 5-min step with the unit off (idle-thermistor airflow artefact, 2.6% of windows),
    or any reading >= 34 C with the unit off (thermistor in still ceiling air, not the room)."""
    for i in range(1, len(xs)):
        if abs(xs[i] - xs[i - 1]) >= JUMP_C and not (ctx["on"][i] and ctx["on"][i - 1]):
            return True
    return any(v >= HOT_OFF and not o for v, o in zip(xs, ctx["on"]))


def window_ends(unit, months, n=144, stride_off=12, stride_on=2, min_on=0.25):
    """D12 sampler: window ends (same acceptance rule as hvac_windows: >= n-3 real temperatures, first and last
    real) every `stride_on` readings (10 min) when the last 4 h are >= min_on running, else every `stride_off`
    readings. Returns [(end, running)]. Prefix sums, so it is fast on a full year."""
    rows = unit["rows"]
    if not rows:
        return []
    b0, b1 = min(rows), max(rows)
    L = (b1 - b0) // STEP + 1
    have, on = [0] * (L + 1), [0] * (L + 1)
    for i in range(L):
        r = rows.get(b0 + i * STEP)
        have[i + 1] = have[i] + (1 if r is not None and r[2] is not None else 0)
        on[i + 1] = on[i] + (r[0] if r is not None else 0)
    out, i = [], n - 1
    k = min(n, 48)
    while i < L:
        b = b0 + i * STEP
        ok = (local(b).month in months and local(b - (n - 1) * STEP).month in months
              and have[i + 1] - have[i + 1 - n] >= n - 3 and have[i + 1] - have[i] == 1
              and have[i - n + 2] - have[i - n + 1] == 1)
        running = on[i + 1] - on[i + 1 - k] >= min_on * k
        if ok:
            out.append((b, running))
            i += stride_on if running else stride_off
        else:
            i += 1
    return out


def split_units(nodes, frac=0.15, seed=7):
    """Spec #21 hold-out: ~15% of units never seen in training, stratified by duty (running vs idle)."""
    import random
    r = random.Random(seed)
    out = set()
    for group in (sorted(k for k, v in nodes.items() if v != "idle"), sorted(k for k, v in nodes.items() if v == "idle")):
        g = list(group)
        r.shuffle(g)
        out.update(g[:max(1, round(frac * len(g)))])
    return out


# ------------------------------------------------------------------------------------- statistics
def hvac_stats(xs, ctx):
    n = len(xs)
    sp, on = ctx["sp"], ctx["on"]
    above = [xs[i] > sp[i] + BAND_HI and xs[i] >= COLD_ABS for i in range(n)]  # a room below 24 C is never too warm
    below = [(xs[i] < sp[i] - BAND_LO and xs[i] < COLD_ABS) or xs[i] < COLD_HARD for i in range(n)]
    runs = _runs(on)
    starts = [s for v, s, L in runs if v == 1 and s > 0]
    stops = [s for v, s, L in runs if v == 0 and s > 0]
    on_runs = [L for v, s, L in runs if v == 1]
    inner = [L for v, s, L in runs if v == 1 and s > 0 and s + L < n]  # complete runs only
    # recovery start: last off->on, or a setpoint drop >= 1 C while running
    sp_changes = [(i, sp[i - 1], sp[i]) for i in range(1, n) if abs(sp[i] - sp[i - 1]) >= 0.5]
    run_start = 0
    for i in range(1, n):
        if on[i] and not on[i - 1]:
            run_start = i
        elif on[i] and on[i - 1] and sp[i] <= sp[i - 1] - 1.0:
            run_start = i
    trail_on = _trailing([v == 1 for v in on])
    since = n - run_start if trail_on else 0
    s12, _ = _slope_h(xs[-min(RUN_PTS, n):])
    s_all, r2 = _slope_h(xs)
    seg = xs[run_start:] if since >= 2 else xs[-2:]
    s_run, _ = _slope_h(seg[:RUN_PTS])
    flat_best, flat_start, cur = 1, 0, 1
    for i in range(1, n):
        if abs(xs[i] - xs[i - 1]) <= FLAT_EPS:
            cur += 1
            if cur > flat_best:
                flat_best, flat_start = cur, i - cur + 1
        else:
            cur = 1
    flat_on = _mean(on[flat_start:flat_start + flat_best]) if flat_best > 1 else 0.0
    diffs = [xs[i] - xs[i - 1] for i in range(1, n)]
    j = max(range(n - 1), key=lambda i: abs(diffs[i])) + 1
    quiet = all(on[k] == 1 and abs(sp[k] - sp[j]) < 0.5 for k in range(max(0, j - 2), min(n, j + 3)))
    pre, post = xs[max(0, j - 6):j], xs[j:min(n, j + 6)]
    th = ctx.get("thermo")
    th_bits = [1 if v >= 0.5 else 0 for v in th] if th else None
    occ = ctx.get("occ")
    return dict(
        n=n, last=xs[-1], mx=max(xs), mn=min(xs), mx_i=max(range(n), key=lambda i: xs[i]),
        mn_i=min(range(n), key=lambda i: xs[i]), sp_last=sp[-1], above=above, below=below,
        trail_above=_trailing(above), trail_below=_trailing(below), above_total=sum(above), below_total=sum(below),
        on_frac=_mean(on), on_now=on[-1], starts=starts, stops=stops, on_runs=on_runs,
        run_med=_median(inner) if inner else (max(on_runs) if on_runs else 0), shortest=min(on_runs) if on_runs else 0,
        trail_on=trail_on, run_start=run_start, since=since, slope=s_all, r2=r2, slope12=s12, slope_run=s_run,
        sp_changes=sp_changes, flat_best=flat_best, flat_start=flat_start, flat_on=flat_on,
        noise=max(robust_noise(xs), robust_noise(xs[-RUN_PTS:])), jump=diffs[j - 1], jump_i=j, jump_quiet=quiet,
        jump_shift=(_mean(post) - _mean(pre)) if pre and post else 0.0,
        thermo_frac=_mean(th) if th else None, thermo_changes=sum(1 for i in range(1, n) if th_bits[i] != th_bits[i - 1]) if th else None,
        missing=sum(ctx["missing"]), first_missing=next((i for i, m in enumerate(ctx["missing"]) if m), -1),
        sat=sum(1 for v in xs if v <= TEMP_LO + 1e-6 or v >= TEMP_HI - 1e-6),
        sat_i=next((i for i, v in enumerate(xs) if v <= TEMP_LO + 1e-6 or v >= TEMP_HI - 1e-6), -1),
        alarm=any(ctx["alarm"]), alarm_i=next((i for i, a in enumerate(ctx["alarm"]) if a), -1), malf=ctx.get("malf", 1),
        mode=ctx.get("mode", 1), occ=occ, trail_vacant=_trailing([v == 0 for v in occ]) if occ else None,
        trail_occupied=_trailing([v == 1 for v in occ]) if occ else None,
        off_hours=off_hours(ctx["end"]), working=working_hours(ctx["end"]), hour=local(ctx["end"]).hour,
        duty=ctx.get("duty", "office"), usual_on=ctx["hour_on"][local(ctx["end"]).hour] if ctx.get("hour_on") else None,
        zc=_zero_cross(xs), grid=_grid(xs),
    )


def _grid(xs):
    """(trailing run on a whole-degree grid, distinct levels in it, level changes in it)."""
    k = _trailing([abs(v - round(v)) < 0.01 for v in xs])
    tail = [round(v) for v in xs[len(xs) - k:]] if k else []
    return k, len(set(tail)), sum(1 for i in range(1, len(tail)) if tail[i] != tail[i - 1])


def _zero_cross(xs):
    m = _mean(xs)
    c, prev = 0, 0
    for v in xs:
        s = 1 if v > m + 0.1 else (-1 if v < m - 0.1 else 0)
        if s and prev and s != prev:
            c += 1
        if s:
            prev = s
    return c


# ------------------------------------------------------------------------------------- teacher rules
def classify_hvac(xs, ctx, st=None):
    """Deterministic pattern rule (first match wins). Returns (pattern, onset_index, event_active)."""
    st = st or hvac_stats(xs, ctx)
    n = st["n"]
    on = ctx["on"]
    # 1-2 data faults that make the rest unreadable
    if st["sat"] >= SAT_PTS:
        return "saturation", st["sat_i"], xs[-1] <= TEMP_LO + 1e-6 or xs[-1] >= TEMP_HI - 1e-6
    if st["missing"] >= DROP_FRAC * n:
        return "dropout", st["first_missing"], ctx["missing"][-1]
    # 3 the unit itself reports an alarm
    if st["alarm"]:
        return "unit_alarm", st["alarm_i"], bool(ctx["alarm"][-1])
    # 4-7 temperature sensor faults
    fb, fs = st["flat_best"], st["flat_start"]
    if fb >= FLAT_PTS and st["flat_on"] >= 0.5 and st["mode"] == 1:
        return "flatline", fs, fs + fb == n
    gk, glev, gch = st["grid"]
    if gk >= GRID_PTS and glev >= 2 and gch >= 3:
        return "quantised", n - gk, True
    if st["noise"] >= ERR_NOISE:
        return "erratic", 0, True
    if abs(st["jump"]) >= JUMP_C and st["jump_quiet"] and st["mode"] == 1 and abs(st["jump_shift"]) >= 0.75 * JUMP_C \
            and n - st["jump_i"] >= MIN_PTS:
        return "bias_jump", st["jump_i"], True
    if st["mode"] == 1 and st["trail_on"] >= RUN_PTS and _median(xs[-st["trail_on"]:]) >= BIAS_HOT:
        return "biased_reading", n - st["trail_on"], True
    t = st["hour"]
    if st["on_frac"] == 0 and 11 <= t < 18 and not st["off_hours"]:
        k = DRIFT_PTS
        while k < n:  # longest trailing segment that is still a clean decline
            s, r2 = _slope_h(xs[-(k + 1):])
            if s > DRIFT_SLOPE or r2 < DRIFT_R2:
                break
            k += 1
        s, r2 = _slope_h(xs[-k:])
        if k <= n and s <= DRIFT_SLOPE and r2 >= DRIFT_R2 and xs[-k] - xs[-1] >= DRIFT_DROP:
            return "calibration_drift", n - k, True
    # 8-11 run-state behaviour
    per4h = len(st["starts"]) * 48.0 / n
    if per4h >= SC_STARTS and st["run_med"] <= SC_RUN:
        return "short_cycling", st["starts"][0], True
    if st["occ"] is not None and st["on_now"] and st["trail_vacant"] >= VACANT_PTS and st["trail_on"] >= VACANT_PTS:
        return "running_empty_room", n - min(st["trail_vacant"], st["trail_on"]), True
    if st["trail_on"] == n and st["off_hours"] and st["duty"] == "office" and st["last"] <= st["sp_last"] + STUCK_ON_SP \
            and (st["usual_on"] is None or st["usual_on"] < 0.2 or local(ctx["end"]).weekday() == 6):
        return "stuck_on", 0, True
    # stuck_off: off all window when the unit normally runs at this hour, room above band.
    # (Setpoint edits while off are NOT evidence: never-run units log hundreds of setpoint changes a year.)
    if st["on_frac"] == 0 and st["working"] and st["duty"] != "idle" and (st["usual_on"] or 0) >= STUCK_OFF_USUAL \
            and st["trail_above"] >= MIN_PTS:
        return "stuck_off", n - st["trail_above"], True
    # 12-13 temperature vs band while cooling
    cooling = st["on_now"] and st["mode"] == 1
    if cooling and st["trail_below"] >= MIN_PTS:
        return "too_cold", n - st["trail_below"], True
    if cooling and st["trail_above"] >= MIN_PTS:
        ta = st["trail_above"]
        if min(st["since"], ta) >= RUN_PTS:
            if st["slope12"] >= NOCOOL_SLOPE:
                return "no_cooling_effect", n - min(st["since"], ta), True
            if st["slope12"] > FAST_SLOPE:
                return "slow_recovery", st["run_start"], True
            return "pull_down", st["run_start"], True
        if st["run_start"] > 0 and st["since"] >= MIN_PTS and st["slope_run"] <= FAST_SLOPE:
            return "pull_down", st["run_start"], True
        return "too_hot", n - ta, True
    if cooling and st["run_start"] > 0 and st["since"] >= MIN_PTS and xs[st["run_start"]] > ctx["sp"][st["run_start"]] + BAND_HI:
        return "pull_down", st["run_start"], False  # reached the band again: recovery finished
    # 14 AC off: absolute heat, else setback drift / stable
    if not st["on_now"]:
        if st["occ"] is not None and st["trail_occupied"] >= WARN_PTS:
            hot = [v >= HOT_OCC for v in xs]
            if _trailing(hot) >= MIN_PTS:
                return "too_hot", n - _trailing(hot), True
        k = n - (st["stops"][-1] if st["stops"] and not st["trail_on"] else 0)
        s, _ = _slope_h(xs[-k:]) if k >= RUN_PTS else (0.0, 0.0)
        if k >= RUN_PTS and s >= SETBACK_SLOPE and xs[-1] - min(xs[-k:]) >= SETBACK_RISE \
                and (k < n or st["off_hours"] or not st["working"]):
            return "setback_drift", n - k, True
    # 15 normal thermostat cycling while running in band
    if cooling and st["on_frac"] >= 0.9 and not st["trail_above"]:
        if (st["thermo_changes"] or 0) >= 4 or (st["zc"] >= 6 and st["mx"] - st["mn"] >= 0.4):
            return "normal_cycling", 0, True
    return "stable", 0, False


def status_of(pattern, xs, ctx, st, onset):
    n = st["n"]
    age = n - onset
    if pattern in FAULT_PATTERNS:
        return "sensor_fault"
    if pattern in NORMAL_PATTERNS:
        return "normal"
    if pattern == "too_hot":
        if st["on_now"]:
            excess = max(xs[i] - ctx["sp"][i] - BAND_HI for i in range(onset, n))
        else:
            excess = max(xs[onset:]) - HOT_OCC + WARN_EXCESS  # occupied room, AC off, >= 30 C
        if age >= RUN_PTS and (max(xs[onset:]) >= CRIT_T + 1 or excess >= 4.0):
            return "critical"
        return "warning" if age >= WARN_PTS and excess >= WARN_EXCESS else "normal"
    if pattern == "too_cold":
        if age >= WARN_PTS and min(xs[onset:]) <= 18.0:
            return "critical"
        deficit = max(min(ctx["sp"][i] - BAND_LO, COLD_ABS) - xs[i] for i in range(onset, n))
        return "warning" if age >= WARN_PTS and (deficit >= WARN_EXCESS or min(xs[onset:]) < COLD_HARD) else "normal"
    if pattern == "no_cooling_effect":
        return "critical" if st["last"] >= 32.0 or st["slope12"] >= 0.5 else "warning"
    if pattern == "short_cycling":
        return "critical" if len(st["starts"]) * 48.0 / n >= SC_CRIT else "warning"
    if pattern == "stuck_off":
        return "critical" if st["last"] >= CRIT_T else "warning"
    if pattern == "unit_alarm":
        return "warning"
    return "warning"  # slow_recovery, stuck_on, running_empty_room


def cause_of(pattern, st):
    if pattern in FAULT_PATTERNS:
        return "sensor_fault"
    return {
        "stable": "normal_operation" if st["on_frac"] > 0 else "scheduled_off",
        "normal_cycling": "normal_operation", "pull_down": "normal_operation", "setback_drift": "scheduled_off",
        "too_hot": "high_heat_load" if st["on_now"] else "ac_off_heat_gain",
        "too_cold": "overcooling", "slow_recovery": "high_heat_load", "no_cooling_effect": "ac_not_cooling",
        "short_cycling": "short_cycling_control", "stuck_on": "schedule_or_control_fault",
        "stuck_off": "unit_not_starting", "running_empty_room": "unoccupied_running", "unit_alarm": "unit_alarm",
    }[pattern]


BASE_CONF = {"stable": 0.92, "normal_cycling": 0.85, "pull_down": 0.85, "setback_drift": 0.8, "too_hot": 0.8,
             "too_cold": 0.8, "slow_recovery": 0.75, "no_cooling_effect": 0.82, "short_cycling": 0.85,
             "stuck_on": 0.7, "stuck_off": 0.7, "running_empty_room": 0.75, "unit_alarm": 0.95,
             "flatline": 0.85, "erratic": 0.85, "bias_jump": 0.8, "biased_reading": 0.85, "calibration_drift": 0.65,
             "dropout": 0.9, "saturation": 0.92, "quantised": 0.8}


def confidence_of(pattern, age, n):
    """Placeholder calibration (spec #15): young events are less certain. The v2 generator should replace
    this with the placement-study accuracy table once HVAC is in that study."""
    c = BASE_CONF[pattern]
    if pattern not in ("stable", "unit_alarm", "dropout"):
        c -= 0.25 * max(0.0, 1.0 - age / 12.0)  # up to -0.25 at 3 readings, none after 60 min
    return round(min(0.97, max(0.4, c)), 2)


# ------------------------------------------------------------------------------------- evidence + prompt
def evidence_items(xs, ctx, st=None):
    """E1..E8 for a HVAC window (E9/E10 history lines are added by the v2 generator)."""
    st = st or hvac_stats(xs, ctx)
    n, end = st["n"], ctx["end"]
    T = lambda i: idx_time(end, n, i)
    sp = st["sp_last"]
    ev = [("E1", "last", f"room now {fmt1(st['last'])} C, setpoint {fmt1(sp)} C (band {fmt1(sp - BAND_LO)}-{fmt1(sp + BAND_HI)})"),
          ("E2", "range", f"max {fmt1(st['mx'])} C at {T(st['mx_i'])}, min {fmt1(st['mn'])} C at {T(st['mn_i'])}")]
    if st["trail_above"]:
        e3 = f"above band for last {5 * st['trail_above']} min (since {T(n - st['trail_above'])})"
    elif st["trail_below"]:
        e3 = f"below band for last {5 * st['trail_below']} min (since {T(n - st['trail_below'])})"
    else:
        e3 = f"inside band now; above band {5 * st['above_total']} min, below {5 * st['below_total']} min in window"
    ev.append(("E3", "band", e3))
    e4 = f"trend {st['slope']:+.1f} C/h (r2 {st['r2']:.2f}), last hour {st['slope12']:+.1f} C/h"
    if st["run_start"] > 0 and st["trail_on"]:
        e4 += f", since start {T(st['run_start'])} (from {fmt1(xs[st['run_start']])} C) {st['slope_run']:+.1f} C/h"
    ev.append(("E4", "trend", e4))
    mode = {1: "cool", 3: "fan", 5: "dry"}.get(st["mode"], "cool")
    on_pts = sum(ctx["on"])
    e5 = f"AC on {on_pts}/{n} samples, mode {mode}, starts {len(st['starts'])}, stops {len(st['stops'])}"
    if st["starts"]:
        e5 += f", last start {T(st['starts'][-1])}"
    if st["trail_on"]:
        e5 += f", running {5 * st['since']} min"
    ev.append(("E5", "run", e5))
    if st["on_runs"] and on_pts:
        e6 = f"on-runs shortest {5 * st['shortest']} min, median {int(5 * st['run_med'])} min"
    else:
        e6 = "no on-runs"
    e6 += f"; thermo on {st['thermo_frac']:.0%}, {st['thermo_changes']} changes" if st["thermo_frac"] is not None else "; thermo n/a"
    ev.append(("E6", "cycles", e6))
    if st["sp_changes"]:
        i, a, b = st["sp_changes"][-1]
        e7 = f"setpoint changes {len(st['sp_changes'])}, last {fmt1(a)} -> {fmt1(b)} C at {T(i)}"
    else:
        e7 = f"setpoint unchanged at {fmt1(sp)} C"
    e7 += f"; temp flat {5 * st['flat_best']} min max, largest 5-min step {st['jump']:+.1f} C at {T(st['jump_i'])}"
    if st["grid"][0] >= GRID_PTS:
        e7 += f"; whole-degree readings for last {5 * st['grid'][0]} min"
    ev.append(("E7", "setpoint", e7))
    if st["occ"] is None:
        occ = "occupancy n/a"
    elif st["trail_vacant"]:
        occ = f"room vacant for last {5 * st['trail_vacant']} min"
    else:
        occ = f"room occupied {sum(st['occ']) / n:.0%} of window"
    usual = f"usually on {st['usual_on']:.0%} at this hour" if st["usual_on"] is not None else "schedule n/a"
    tday = local(end)
    e8 = (f"{occ}; {usual} ({st['duty']} unit); end {tday:%a} {T(n - 1)}" + (" off-hours" if st["off_hours"] else "")
          + f"; missing {st['missing']}/{n}; alarm " + (f"code {st['malf']}" if st["alarm"] else "none"))
    ev.append(("E8", "context", e8))
    return ev


def series_lines(xs, ctx):
    """D10: same format as the other roles: 10-min means (N/2 values for any N), AC state per 10 min."""
    n = len(xs)
    step = 2
    k = n // step
    ds = [_mean(xs[i * step:(i + 1) * step]) for i in range(k)]
    st_ = "".join("1" if _mean(ctx["on"][i * step:(i + 1) * step]) >= 0.5 else "0" for i in range(k))
    return [f"ROOM TEMP ({5 * step}-min means): " + " ".join(fmt1(v) for v in ds),
            f"AC STATE ({5 * step}-min, 1=on): " + st_]


def user_prompt(node, location, xs, ctx):
    """User-message body for one HVAC window (the generator may add CONTEXT/E9/E10 lines)."""
    n = len(xs)
    end = local(ctx["end"])
    start = end - timedelta(minutes=5 * (n - 1))
    st = hvac_stats(xs, ctx)
    lines = [f"NODE: {node} ({location})", "METRIC: room_temp [C] with AC state and setpoint",
             f"LIMITS: comfort band setpoint -{BAND_LO:g}/+{BAND_HI:g} C; warning above {METRICS[('hvac', 'room_temp')]['warn']},"
             f" critical above {METRICS[('hvac', 'room_temp')]['crit']}",
             f"WINDOW: {start:%a %d %b %H:%M} -> {end:%H:%M} IST, {n} x 5 min"]
    lines += series_lines(xs, ctx)
    lines.append("EVIDENCE:")
    ev = evidence_items(xs, ctx, st)
    lines += [f"{e} {t}" for e, _, t in ev]
    return "\n".join(lines), st, ev


def describe(node):
    p = node.split("-")  # SR-AC-KH02-12
    return f"{p[2][:2]} building, level {p[2][2:]}, AC indoor unit {p[3]}"


# ------------------------------------------------------------------------------------- observations
def _pick(rng, *opts):
    return rng.choice(opts)


def observations(pattern, status, xs, ctx, st, onset, rng):
    """At most 2 short observations (~14 words), numbers only from the evidence lines, ids cited."""
    n, end = st["n"], ctx["end"]
    T = lambda i: idx_time(end, n, i)
    L, sp = fmt1(st["last"]), fmt1(st["sp_last"])
    hi = fmt1(st["sp_last"] + BAND_HI)
    ta, tb = 5 * st["trail_above"], 5 * st["trail_below"]
    on_pts = sum(ctx["on"])
    o = []
    if pattern == "stable":
        if st["on_frac"] > 0:
            o.append(_pick(rng, f"Room steady at {L} C, inside the band around setpoint {sp} C [E1,E3]",
                           f"Temperature holds near setpoint {sp} C, now {L} C [E1,E3]",
                           f"No band excursion; room {L} C with setpoint {sp} C [E1,E3]"))
        else:
            o.append(_pick(rng, f"AC off; room steady between {fmt1(st['mn'])} and {fmt1(st['mx'])} C [E5,E2]",
                           f"Unit idle and room temperature stable at {L} C [E5,E1]",
                           f"AC not running; room {L} C, trend {st['slope']:+.1f} C/h [E5,E4]"))
        if st["mode"] != 1 and st["on_now"]:
            o.append("Unit runs in fan or dry mode, so no cooling is expected [E5]")
    elif pattern == "normal_cycling":
        o.append(_pick(rng, f"Room cycles {fmt1(st['mn'])}-{fmt1(st['mx'])} C around setpoint {sp} C, normal thermostat action [E2,E1]",
                       f"Normal on/off cooling cycles keep the room near {sp} C [E6,E1]",
                       f"Small regular swings inside the band; setpoint {sp} C [E2,E3,E6]"))
    elif pattern == "pull_down" and not (st["run_start"] > 0 and st["trail_on"] and st["slope_run"] < 0):
        o.append(_pick(rng, f"Recovery done: room {L} C is back inside the band [E1,E3]",
                       f"Cooling brought the room back to {L} C, setpoint {sp} C [E1,E3]"))
    elif pattern == "pull_down":
        o.append(_pick(rng, f"AC started at {T(st['run_start'])}; room falling {st['slope_run']:+.1f} C/h toward {sp} C [E5,E4]",
                       f"Normal pull-down since {T(st['run_start'])}, cooling at {st['slope_run']:+.1f} C/h [E4,E5]",
                       f"Cooling recovery from {fmt1(xs[st['run_start']])} C to {L} C since {T(st['run_start'])} [E4,E1]"))
    elif pattern == "setback_drift":
        o.append(_pick(rng, f"AC off; room warming slowly at {st['slope12']:+.1f} C/h, normal setback [E5,E4]",
                       f"Unit switched off, room drifting up to {L} C as expected [E5,E1]",
                       f"Off-hours drift: room rises {st['slope12']:+.1f} C/h with the AC off [E4,E8]"))
    elif pattern == "too_hot":
        if st["on_now"]:
            o.append(_pick(rng, f"Room {L} C, above the {hi} C band edge for {ta} min [E1,E3]",
                           f"AC running but room is {L} C against setpoint {sp} C [E1,E5]",
                           f"Too warm: {L} C, band top {hi} C, since {T(onset)} [E1,E3]"))
        else:
            o.append(_pick(rng, f"AC off and room has reached {L} C [E5,E1]",
                           f"Room {L} C with the unit off since the window start [E1,E5]",
                           f"Hot room: {L} C at {T(n - 1)}, no cooling running [E1,E5]"))
    elif pattern == "too_cold":
        o.append(_pick(rng, f"Room {L} C, well below setpoint {sp} C for {tb} min [E1,E3]",
                       f"Overcooling: {L} C while the unit keeps cooling [E1,E5]",
                       f"Below the comfort band since {T(onset)}, now {L} C [E3,E1]"))
    elif pattern == "slow_recovery":
        o.append(_pick(rng, f"Cooling since {T(st['run_start'])} but only {st['slope12']:+.1f} C/h, still {L} C [E4,E1]",
                       f"Slow recovery: room {L} C, still above band after {5 * st['since']} min [E1,E3,E5]",
                       f"Room falling too slowly ({st['slope12']:+.1f} C/h) toward setpoint {sp} C [E4,E1]"))
    elif pattern == "no_cooling_effect":
        o.append(_pick(rng, f"AC running {5 * st['since']} min but room not falling ({st['slope12']:+.1f} C/h) [E5,E4]",
                       f"No cooling effect: room {L} C, setpoint {sp} C, trend {st['slope12']:+.1f} C/h [E1,E4]",
                       f"Unit on, room stuck above band at {L} C for {ta} min [E5,E3,E1]"))
    elif pattern == "short_cycling":
        o.append(_pick(rng, f"Unit started {len(st['starts'])} times; median run only {int(5 * st['run_med'])} min [E5,E6]",
                       f"Short-cycling: {len(st['starts'])} starts, shortest run {5 * st['shortest']} min [E5,E6]",
                       f"AC switches on and off repeatedly, {len(st['starts'])} starts in window [E5]"))
    elif pattern == "stuck_on":
        o.append(_pick(rng, f"AC on all {n} samples during off-hours; room already {L} C [E5,E8,E1]",
                       f"Unit kept running at night/weekend though room is at setpoint {sp} C [E5,E8]",
                       f"Running outside its usual schedule with no cooling need, room {L} C [E8,E1]"))
    elif pattern == "stuck_off":
        u = f"{st['usual_on']:.0%}" if st["usual_on"] is not None else "often"
        o.append(_pick(rng, f"Unit off all window though it is usually on {u} at this hour [E5,E8]",
                       f"No start in working hours; room {L} C above the {hi} C band edge [E5,E1,E3]",
                       f"Expected to run now but stays off, room {L} C [E8,E5,E1]"))
    elif pattern == "running_empty_room":
        v = 5 * st["trail_vacant"]
        o.append(_pick(rng, "AC running in an empty room - recommend switching it off [E5,E8]",
                       f"AC running in an empty room for {v} min - recommend switching it off [E8,E5]",
                       f"Room vacant {v} min with the AC on - recommend switching it off [E8,E5]"))
    elif pattern == "unit_alarm":
        o.append(_pick(rng, f"Unit reports alarm code {st['malf']} [E8]",
                       f"Indoor unit raised malfunction code {st['malf']} [E8]",
                       f"Alarm active on the unit (code {st['malf']}) [E8]"))
    elif pattern == "flatline":
        o.append(_pick(rng, f"Room reading frozen for {5 * st['flat_best']} min while the unit runs [E7,E5]",
                       f"Temperature unchanged {5 * st['flat_best']} min despite AC operation, likely stuck sensor [E7,E5]"))
    elif pattern == "erratic":
        o.append(_pick(rng, f"Readings jump irregularly; 5-min steps up to {abs(st['jump']):.1f} C [E7]",
                       f"Noisy room sensor, swings {fmt1(st['mn'])}-{fmt1(st['mx'])} C without a trend [E2,E4]"))
    elif pattern == "bias_jump":
        o.append(_pick(rng, f"Reading jumped {st['jump']:+.1f} C at {T(st['jump_i'])} with no AC or setpoint change [E7,E5]",
                       f"Sudden {st['jump']:+.1f} C offset at {T(st['jump_i'])}, unit state unchanged [E7,E5]"))
    elif pattern == "biased_reading":
        o.append(_pick(rng, f"Reads {L} C while the unit has been cooling, implausible for a room [E1,E5]",
                       f"Room value {L} C despite steady cooling; sensor reads high [E1,E5]"))
    elif pattern == "quantised":
        o.append(_pick(rng, f"Readings move only in whole-degree steps for the last {5 * st['grid'][0]} min [E7]",
                       f"Temperature quantised to whole degrees, now {L} C [E7,E1]"))
    elif pattern == "calibration_drift":
        o.append(_pick(rng, f"Room reading falls {st['slope12']:+.1f} C/h in daytime with the AC off [E4,E5]",
                       f"Implausible cooling drift to {L} C while the unit is idle [E4,E5,E1]"))
    elif pattern == "dropout":
        o.append(_pick(rng, f"{st['missing']} of {n} readings missing [E8]",
                       f"Data gaps: {st['missing']}/{n} samples absent from the unit [E8]"))
    elif pattern == "saturation":
        o.append(_pick(rng, f"Reading pinned at {L} C, the sensor limit [E1,E2]" if st["sat"] else "Reading pinned at the sensor limit [E2]",
                       f"Room value stuck at {fmt1(st['mx'] if st['mx'] >= TEMP_HI - 1e-6 else st['mn'])} C limit, sensor saturated [E2,E3]"))
    # second observation: severity / context evidence
    if status in ("warning", "critical") and pattern in ("too_hot", "no_cooling_effect", "slow_recovery") and st["last"] >= 30:
        o.append(f"Room {L} C exceeds the {30 if st['last'] < CRIT_T else 34} C {'warning' if st['last'] < CRIT_T else 'critical'} limit [E1]")
    elif pattern == "stuck_on" and len(o) < 2:
        o.append(f"{on_pts} of {n} samples on, {_pick(rng, 'wasting energy', 'avoidable cooling load')} [E5]")
    elif pattern in EVENT_PATTERNS and status == "normal":
        o.append(_pick(rng, "Still young; worth watching before acting [E3]", "Small and recent so far, keep monitoring [E3]"))
    return o[:2]


# ------------------------------------------------------------------------------------- label
def label_hvac(xs, ctx, rng, injected=None):
    """Teacher target for one window. Returns dict in frozen v2 key order (action is backend-derived).
    `injected` (the requested pattern) is only used to report agreement; labels come from the rules."""
    st = hvac_stats(xs, ctx)
    pattern, onset, active = classify_hvac(xs, ctx, st)
    status = status_of(pattern, xs, ctx, st, onset)
    cause = cause_of(pattern, st)
    n = st["n"]
    out = {"pattern": pattern, "status": status,
           "observations": observations(pattern, status, xs, ctx, st, onset, rng),
           "likely_cause": cause, "confidence": confidence_of(pattern, n - onset, n),
           "event_active": bool(active), "onset": idx_time(ctx["end"], n, onset)}
    if status == "sensor_fault":
        out["fault_kind"] = FAULT_KIND[pattern]
    out["action"] = action_of(cause, status)
    if injected is not None:
        out["_agrees"] = pattern == injected
    return out


# ------------------------------------------------------------------------------------- injection
def _copy_ctx(ctx):
    c = dict(ctx)
    for k in ("sp", "on", "thermo", "alarm", "missing", "occ"):
        if c.get(k) is not None:
            c[k] = list(c[k])
    return c


def _clip(v):
    return round(min(TEMP_HI, max(TEMP_LO, v)), 2)


def _shift_end(ctx, rng, hours, weekend=None):
    """Move the window end to a chosen IST hour on the same week (keeps month -> keeps split)."""
    t = local(ctx["end"])
    day = t.replace(hour=0, minute=0, second=0, microsecond=0)
    if weekend is not None:
        wd = t.weekday()
        target = 6 if weekend else rng.choice((0, 1, 2, 3, 4, 5))  # Sunday vs Mon-Sat (Saturday is a work day)
        day = day + timedelta(days=target - wd)
        if day.month != t.month:
            day = day - timedelta(days=7) if day > t else day + timedelta(days=7)
    h = rng.choice(hours)
    ctx["end"] = int((day + timedelta(hours=h, minutes=5 * rng.randint(0, 11))).timestamp())


def _jit(rng, s=0.05):
    return rng.gauss(0, s)


RAMP = 0.5  # C per 5 min: max injected rate of change for physical (non-fault) shapes (< JUMP_C, ~2x real pull-down)


def _ramp(ys, p, tgt, rng, hold_slope=0.0):
    """Move ys toward tgt starting so the band is crossed near p, at <= RAMP C per step; hold after."""
    n = len(ys)
    base = ys[max(0, p - 1)]
    steps = max(1, int(math.ceil(abs(tgt - base) / RAMP)))
    p0 = max(0, p - steps // 2)
    for i in range(p0, n):
        f = min(1.0, (i - p0 + 1) / steps)
        ys[i] = base + (tgt - base) * f + hold_slope * max(0, i - p0 - steps) / 12.0 + _jit(rng)
    return ys


MIN_AGE = {"slow_recovery": RUN_PTS, "no_cooling_effect": RUN_PTS, "short_cycling": 16, "flatline": FLAT_PTS,
           "erratic": RUN_PTS, "running_empty_room": VACANT_PTS, "calibration_drift": DRIFT_PTS + 2,
           "setback_drift": RUN_PTS, "night_setback": RUN_PTS, "saturation": SAT_PTS, "dropout": 13,
           "quantised": GRID_PTS + 2}
# shortest window (readings) in which a pattern can be shown at all; the generator should not request it below
MIN_LEN = {"calibration_drift": DRIFT_PTS + 2}


def inject_hvac(pattern, xs, ctx, rng, onset=None, size=None):
    """Inject one HVAC pattern (or a hard negative) into a real base window.
    Returns (ys, ctx2, meta) or None when the base does not fit. meta = {onset, size, base}.
    Hard negatives are requested by name: night_setback, weekend_off, continuous_duty, fan_mode,
    small_excursion, setpoint_change_ok (they come back labelled as normal patterns)."""
    n = len(xs)
    kind = base_kind(xs, ctx)
    if kind is None:
        return None
    s0 = scale_of(xs)
    x = rng.uniform(1.5, 12.0) if size is None else size  # spec #11: 1.5-12x noise
    A = x * s0
    p = sample_onset(n, rng) if onset is None else onset
    # some patterns only exist after a minimum age (e.g. "no cooling" needs 1 h of running)
    p = max(0, min(p, n - MIN_AGE.get(pattern, MIN_PTS)))
    ys, c = list(xs), _copy_ctx(ctx)
    sp_now = c["sp"][-1]

    def warm_room(T0):  # an "off" base becomes a warm room by shifting its level, keeping its texture
        d = T0 - _mean(ys[:max(1, p)])
        return [v + d for v in ys]

    def start_at(i):
        for k in range(n):
            c["on"][k] = 1 if k >= i else 0
        c["mode"] = 1

    if pattern == "stable":
        pass
    elif pattern == "normal_cycling":
        if kind != "on":
            return None
        th, cyc, k = [], [], 0
        while k < n:
            on_L, off_L = rng.randint(2, 4), rng.randint(2, 5)
            th += [1.0] * on_L + [0.0] * off_L
            k += on_L + off_L
        th = th[:n]
        amp = rng.uniform(0.15, 0.25)
        lvl = sp_now + rng.uniform(-0.5, 0.8)
        v = lvl
        for i in range(n):
            v += -amp if th[i] else amp * 0.8
            v = min(max(v, lvl - 1.0), lvl + 1.0)
            ys[i] = v + _jit(rng)
        c["thermo"] = th
        c["sp"] = [sp_now] * n
    elif pattern in ("pull_down", "setpoint_change_ok", "slow_recovery", "no_cooling_effect"):
        L = n - p
        tau = 6 + 9 * (x / 12.0)                 # pull-down time constant 30-75 min (real median ~1 h)
        r_slow = rng.uniform(0.35, 0.9)          # C/h, slower than the 1.2 C/h fast-pull-down cut
        r_nc = rng.uniform(-0.2, 0.8)            # C/h, flat or rising: no cooling effect
        # temperature excess over the new setpoint needed at the onset so the end state is as intended
        need = {"slow_recovery": BAND_HI + A + r_slow * L / 12.0, "no_cooling_effect": BAND_HI + A}.get(pattern)
        if pattern == "setpoint_change_ok" or (kind == "on" and rng.random() < 0.5):
            if kind != "on":
                return None
            # setpoint lowered at p while running (the "slow recovery after a setpoint change" case)
            old = sp_now
            T0 = _mean(ys[max(0, p - 3):p + 1])
            if need is None:
                new = old - rng.choice((1.0, 2.0, 3.0, 4.0))
                T0 = max(T0, new + BAND_HI + 0.5)
            else:
                new = math.floor((T0 - need) * 2) / 2
            if new < 16.0 or new > old - 1.0:
                return None
            c["sp"] = [old] * p + [new] * (n - p)
            c["on"] = [1] * n
            c["mode"] = 1
        else:
            if kind != "off":
                return None
            new = rng.choice((22.0, 23.0, 24.0, 25.0))
            T0 = new + (need if need is not None else BAND_HI + rng.uniform(1.0, 5.0))
            if T0 > 40.0:
                return None
            ys = warm_room(T0)
            c["sp"] = [new] * n
            start_at(p)
        tgt = new + rng.uniform(-0.3, 0.6)       # where a normal pull-down settles
        for i in range(p, n):
            t = i - p
            if pattern in ("pull_down", "setpoint_change_ok"):
                ys[i] = tgt + (T0 - tgt) * math.exp(-t / tau) + _jit(rng)
            elif pattern == "slow_recovery":
                ys[i] = T0 - r_slow * t / 12.0 + _jit(rng)
            else:
                ys[i] = T0 + r_nc * t / 12.0 + _jit(rng)
    elif pattern == "too_hot":
        if kind == "on":
            # running but above band; only young (< 1 h), older is no_cooling_effect / slow_recovery
            p = max(p, n - (RUN_PTS - 1))
            ys = _ramp(ys, p, c["sp"][-1] + BAND_HI + A, rng)
        else:
            # AC off in an occupied room (needs occupancy: idle thermistors read hot in still air)
            ys = warm_room(min(ys[0], HOT_OCC - 1.5))
            ys = _ramp(ys, p, HOT_OCC + max(0.3, A / 2.0), rng, hold_slope=0.2)
            c["occ"] = [1] * n
    elif pattern == "too_cold":
        if kind != "on":
            return None
        ys = _ramp(ys, p, min(sp_now - BAND_LO, COLD_ABS) - A / 2.0, rng)
    elif pattern == "short_cycling":
        c["mode"] = 1
        bits = [1 if kind == "on" else 0] * p
        while len(bits) < n:
            bits += [1] * rng.randint(1, 2) + [0] * rng.randint(1, 3)
        c["on"] = bits[:n]
        for i in range(p, n):
            ys[i] = ys[i] + (-0.15 if c["on"][i] else 0.12) * ((i - p) % 3) + _jit(rng)
    elif pattern in ("stuck_on", "continuous_duty"):
        if kind != "on":
            return None
        if any(ys[i] > c["sp"][i] + STUCK_ON_SP for i in range(n)):
            d = max(ys[i] - c["sp"][i] for i in range(n)) - STUCK_ON_SP + 0.1
            ys = [v - d for v in ys]
        if rng.random() < 0.5:
            _shift_end(c, rng, (0, 1, 2, 3, 4, 5, 23))
        else:
            _shift_end(c, rng, tuple(range(10, 20)), weekend=True)
        c["duty"] = "continuous" if pattern == "continuous_duty" else "office"
        if pattern == "stuck_on":
            c["hour_on"] = [min(h, 0.1) if (h_ < 8 or h_ >= 20) else h for h_, h in enumerate(c["hour_on"])]
        p = 0
    elif pattern == "stuck_off":
        if kind != "off":
            return None
        sp = rng.choice((22.0, 23.0, 24.0, 25.0, 26.0))
        c["sp"] = [sp] * n
        ys = warm_room(sp + BAND_HI - 0.6)
        ys = _ramp(ys, p, sp + BAND_HI + max(0.5, A / 2.0), rng, hold_slope=0.2)
        c["on"] = [0] * n
        _shift_end(c, rng, tuple(range(10, 18)), weekend=False)
        c["duty"] = "office"
        usual = rng.uniform(0.6, 0.9)  # this unit normally runs at this hour
        c["hour_on"] = [max(h, usual) if 9 <= k < 19 else h for k, h in enumerate(c["hour_on"])]
    elif pattern == "running_empty_room":
        if kind != "on":
            return None
        k = min(n, max(VACANT_PTS, n - p))
        p = n - k
        c["occ"] = [1] * p + [0] * k
    elif pattern == "unit_alarm":
        code = rng.choice((37, 154, 146, 152, 118, 109))  # codes seen in the data
        c["alarm"] = [0] * p + [1] * (n - p)
        c["malf"] = code
    elif pattern == "flatline":
        if kind != "on" or n - p < FLAT_PTS:
            p = max(0, n - FLAT_PTS - rng.randint(0, n - FLAT_PTS))
            if kind != "on":
                return None
        v = round(ys[p], 1)
        for i in range(p, n):
            ys[i] = v
        if c.get("thermo") is None:
            c["thermo"] = None
    elif pattern == "erratic":
        sd = rng.uniform(1.2, 2.5)
        for i in range(p, n):
            if rng.random() < 0.8:
                ys[i] += rng.gauss(0, sd)
    elif pattern == "bias_jump":
        if kind != "on":
            return None  # only judged while the unit runs steadily (see JUMP_C)
        sgn = rng.choice((-1, 1))
        d = sgn * max(JUMP_C + 0.5, A / 2.0)
        for i in range(p, n):
            ys[i] += d
    elif pattern == "biased_reading":
        if kind != "on":
            return None
        d = BIAS_HOT + 0.5 + A / 4.0 - min(ys)  # whole window reads hot while cooling (like the 3 real units)
        ys = [min(44.0, v + d) for v in ys]
        p = 0
    elif pattern == "quantised":
        amp, P = rng.uniform(0.8, 1.3), rng.uniform(8, 16)
        for i in range(p, n):
            ys[i] = float(round(ys[i] + amp * math.sin(2 * math.pi * (i - p) / P)))
    elif pattern == "calibration_drift":
        if kind != "off" or n < DRIFT_PTS + 2:
            return None
        _shift_end(c, rng, (15, 16, 17), weekend=False)
        k = max(DRIFT_PTS + 2, n - p)
        p = n - k
        r = rng.uniform(1.0, 2.5)
        r = max(r, (DRIFT_DROP + 0.3) * 12.0 / k)
        for i in range(p, n):
            ys[i] -= r * (i - p) / 12.0
    elif pattern == "dropout":
        k = max(int(DROP_FRAC * n) + 1, n - p)
        k = min(k, n - 1)
        p = n - k
        hold = ys[p - 1]
        for i in range(p, n - 1):
            c["missing"][i] = True
            ys[i] = hold  # gateway repeats the last value while the unit is silent
    elif pattern == "saturation":
        k = max(SAT_PTS, n - p)
        p = n - k
        lim = TEMP_HI if rng.random() < 0.7 else TEMP_LO
        for i in range(p, n):
            ys[i] = lim
    elif pattern in ("setback_drift", "night_setback", "weekend_off"):
        if pattern == "weekend_off" or kind == "off":
            if kind != "off":
                return None
            if pattern == "weekend_off":
                _shift_end(c, rng, tuple(range(10, 20)), weekend=True)
            else:
                _shift_end(c, rng, (22, 23, 0, 1, 2, 3, 4, 5))
            p = 0
        else:
            stop = min(p, n - RUN_PTS)
            p = stop
            c["on"] = [1] * stop + [0] * (n - stop)
            _shift_end(c, rng, (19, 20, 21, 22, 23))
        r = rng.uniform(0.35, 1.2)
        for i in range(p, n):
            ys[i] += r * (i - p) / 12.0
    elif pattern == "fan_mode":
        if kind != "off":
            return None
        c["on"] = [1] * n
        c["mode"] = 3
        p = 0
    elif pattern == "small_excursion":
        if kind != "on":
            return None
        a = rng.uniform(0.3, 0.9) * s0 * 2
        w = rng.randint(1, 2)
        q = rng.randint(n // 3, n - 4)
        for i in range(q, q + w):
            ys[i] += a
        p = q
    else:
        raise ValueError(pattern)
    ys = [_clip(v) for v in ys]
    if any(v != v for v in ys):
        return None
    return ys, c, {"onset": p, "size": x, "base": kind}


EXPECTED_LABEL = {"night_setback": "setback_drift", "weekend_off": "setback_drift",
                  "continuous_duty": ("stable", "normal_cycling"),
                  "fan_mode": "stable", "small_excursion": ("stable", "normal_cycling"), "setpoint_change_ok": "pull_down"}
INJECTABLE = PATTERNS + tuple(EXPECTED_LABEL)


def make_case(pattern, xs, ctx, rng, tries=1, **kw):
    """Inject + label + agreement check. Returns (ys, ctx2, label) or None.
    A case is kept only when the rule label equals the requested pattern (or the hard negative's expected
    normal label), the same keep/reject idea as v1 generate_dataset.verify."""
    if ctx.get("faulty"):
        return real_fault_case(xs, ctx, rng, want=pattern)
    want = EXPECTED_LABEL.get(pattern, pattern)
    want = want if isinstance(want, tuple) else (want,)
    for _ in range(tries):
        r = inject_hvac(pattern, xs, ctx, rng, **kw)
        if r is None:
            return None
        ys, c, meta = r
        lab = label_hvac(ys, c, rng)
        if lab["pattern"] in want:
            lab["_meta"] = meta
            return ys, c, lab
    return None


def real_fault_case(xs, ctx, rng, want=None):
    """D11: an untouched window of a faulty unit, kept only when the rules label it a sensor fault or a unit
    alarm (and, if `want` is given, exactly that pattern). Never used as a normal/stable example."""
    lab = label_hvac(xs, ctx, rng)
    if lab["status"] != "sensor_fault" and lab["pattern"] != "unit_alarm":
        return None
    if want is not None and lab["pattern"] != want:
        return None
    _, onset, _ = classify_hvac(xs, ctx)
    lab["_meta"] = {"onset": onset, "size": None, "base": "real_fault"}
    return list(xs), _copy_ctx(ctx), lab
