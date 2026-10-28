"""v2 domain-agent prompt builder: any window length N (2-12 h) plus two 12 h history lines (E9, E10).

Spec: training/RETRAIN_V2_SPEC.md. Pure Python (no numpy) so app/backend can mirror it line by line.
The v1 builder (training/features.py) is NOT modified: the deployed model keeps using it.

Differences from v1 features.agent_prompt (everything else is byte-identical, asserted in checks_v2.py):
  WINDOW line     "..., {N} x 5 min"                       (v1: always "48 x 5 min")
  SERIES line     N/2 pairwise 10-min means                 (v1: 24)
  E6              "mean {H}h"                               (v1: "mean 4h")
  E9   (new)      12 h view: level shift / slow drift       (longrange.py stats/decide, params_final.json)
  E10  (new)      recent episodes: excursions beyond 3x normal noise in the history
  system rules    "a {H}-hour window", "(E1..E10)"          (v1: "a 4-hour window", "(E1..E8)")
  schema hint     frozen v2 schema (event_active, onset, fault_kind incl. quantised (D6); observations 1-2);
                  water causes + tank_overflow_risk, fill_valve_stuck (D2); per-role action list (HVAC adds switch_off_ac)
  TANK  (new)     water level only: per-node high / overflow marks and usual fill duration (D2)
with H = N*5/60 printed with Python "%g" (N is a multiple of 6, so H is 2, 2.5, 3, ... 12).

`hist` is up to HIST=144 five-minute values ENDING at the window end (oldest first); the window is hist[-N:].
E9/E10 are computed on hist; when it is shorter than 8 h E9 says so.

STRINGS (exact formats; sd = max(dec, 1); u = " " + unit, or "" for a unitless metric; HH:MM = IST):
  E9  history < 96 points          "12 h view: under 8 h of history"
  E9  no finding                   "12 h view: no level shift or drift"
  E9  finding(s), joined by "; "   "12 h view: " + parts
        level_shift part           "level shift {delta:+.{sd}f}{u} at {HH:MM} ({sigma:.1f}x normal variation)"
                                   HH:MM = time of history point len(h)-1-ago_pts (longrange.stats)
        slow_drift part            "slow drift {total:+.{sd}f}{u} since {HH:MM} (r2 {r2:.2f}, {sigma:.1f}x normal variation)"
                                   HH:MM = time of the first history point
  E10 K = 0                        "recent episodes: no excursions beyond 3x normal noise in the last {Hh} h"
  E10 K = 1                        "recent episodes: 1 excursion beyond 3x normal noise in the last {Hh} h (largest {p:.1f}x)"
  E10 K > 1                        "recent episodes: {K} excursions beyond 3x normal noise in the last {Hh} h (largest {p:.1f}x)"
        Hh = len(h)*5/60 with "%.0f"; excursion = cluster of points whose |x - rolling 13-point median| >= 3*s
        (gap <= 2 points joins a cluster), s = exc_scale = max(longrange.noise_scale, IQR of the first 36 points)
        (IQR = sorted[3L//4] - sorted[L//4], L = min(36, len(h)); for L = 36 this is longrange's ref[27] - ref[9]),
        p = max |residual|/s over the excursion points.
  TANK (water level nodes with a NODE_LIMITS entry; line after METRIC)
                                   "TANK: high level above {high}, overflow risk above {overflow}; usual fill up to {fill_min} min"
                                   high/overflow printed with the metric's decimals (F.fmt); values per node from TRAIN months
                                   (generate_v2.tank_limits -> data/sft_v2/node_limits.json)
  occupancy E9                     "12 h view: occupied fraction {f:.2f} over the last {Hh} h"
  occupancy E10 K = 0              "recent episodes: no occupied periods in the last {Hh} h"
  occupancy E10 K >= 1             "recent episodes: {K} occupied period(s) in the last {Hh} h (longest {L:.1f} h)"
                                   "period" if K == 1 else "periods"
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRAIN = HERE.parent
sys.path.insert(0, str(TRAIN))
sys.path.insert(0, str(TRAIN / "window_study"))
import features as F  # noqa: E402  (v1, read-only)
import longrange as LRM  # noqa: E402  (12 h detectors, mirrored in app/backend/longrange.go)

STEP_MIN = F.STEP_MIN
IST = F.IST
MIN_N, MAX_N, N_STEP = 24, 144, 6
LENGTHS = tuple(range(MIN_N, MAX_N + 1, N_STEP))   # 24, 30, ..., 144 (2 h .. 12 h in 30-min steps)
LADDER = (48, 96, 144)                             # run-time lengths (alert 4 h, refine 8 h / 12 h)
HIST = 144                                         # history points behind E9/E10
LR_MIN_POINTS = LRM.MIN_POINTS                     # 96: below 8 h of history no 12 h verdict
LR_PARAMS = {"kL": 4, "kD": 4, "rD": 0.8, "kE": 99.0, "cE": 999, "kQ": 1.0}  # proofs/2026-10-16_longrange/params_final.json
EXC_K = 3.0       # E10: excursion threshold in units of normal noise
EXC_HALF = 6      # E10: rolling-median half width (13-point median)
EXC_GAP = 2       # E10: points within this gap belong to one excursion

FAULT_KINDS = ("stuck", "bias", "drift", "noise", "dropout", "saturation", "quantised")  # quantised added 2026-10-17 (D6)
STATUSES = ("normal", "warning", "critical", "sensor_fault")
KEY_ORDER = ("pattern", "status", "observations", "likely_cause", "confidence", "event_active", "onset", "fault_kind", "action")

# role registry: v1 roles + HVAC (filled by register_role from training/v2/hvac.py or the stub)
METRICS = dict(F.METRICS)
CAUSES = dict(F.CAUSES)
PATTERNS = {r: (F.OCC_PATTERNS if r == "occupancy" else F.CONT_PATTERNS) for r in F.ROLES}
SYSTEM_PROMPTS = dict(F.SYSTEM_PROMPTS)
ROLES = list(F.ROLES)
ACTIONS = list(F.ACTIONS)                 # every action any role may use (HVAC adds e.g. switch_off_ac)
ROLE_ACTIONS = {r: tuple(F.ACTIONS) for r in F.ROLES}
# Water causes added for abnormal fills (D2, 2026-10-17); backend Causes["water"] must gain them too.
CAUSES["water"] = tuple(CAUSES["water"]) + ("tank_overflow_risk", "fill_valve_stuck")
# Per-node tank limits (water level only), computed from TRAIN months by generate_v2.tank_limits and
# registered here: {node: {"high": float, "overflow": float, "fill_min": int}}. Shown as an extra line
# "TANK: high level above {high}, overflow risk above {overflow}; usual fill up to {fill_min} min"
# right after the METRIC line (water level nodes only; the backend needs the same per-node table).
NODE_LIMITS = {}


def register_role(role, metrics, causes, patterns, system_prompt, actions=None):
    """Add a role (HVAC) to the registry. metrics: {(role, metric): v1-style METRICS dict}."""
    METRICS.update(metrics)
    acts = list(F.ACTIONS)
    for a_ in actions or ():
        if a_ not in acts:
            acts.append(a_)
    ROLE_ACTIONS[role] = tuple(acts)
    for a_ in acts:
        if a_ not in ACTIONS:
            ACTIONS.append(a_)
    CAUSES[role] = tuple(causes)
    PATTERNS[role] = tuple(patterns)
    SYSTEM_PROMPTS[role] = system_prompt
    if role not in ROLES:
        ROLES.append(role)


def hours_str(n):
    """Window length in hours as printed in the prompt ("%g"): 48 -> "4", 30 -> "2.5"."""
    return f"{n * STEP_MIN / 60:g}"


def idx_time(end_epoch, n, idx):
    """Wall time (IST, HH:MM) of point idx in a series of n points whose last point is at end_epoch."""
    t = end_epoch - (n - 1 - idx) * STEP_MIN * 60
    return datetime.fromtimestamp(t, IST).strftime("%H:%M")


# ---------------------------------------------------------------- evidence E1..E8 (v1 text, any N)
def evidence_items(role, metric, st, end_epoch, dec, unit, n):
    u = f" {unit}" if unit else ""
    T = lambda i: idx_time(end_epoch, n, i)
    if role == "occupancy":
        return [
            ("E1", "last", f"current state = {int(st['last'])}"),
            ("E2", "occupied_frac", f"occupied fraction = {st['occupied_frac']:.2f}"),
            ("E3", "toggles", f"state changes = {st['toggles']}"),
            ("E4", "first_on", "first occupied at " + (T(st['first_on']) if st['first_on'] >= 0 else "never")),
            ("E5", "last_on", "last occupied at " + (T(st['last_on']) if st['last_on'] >= 0 else "never")),
            ("E6", "time", "window end " + T(n - 1) + (" (off-hours)" if F.is_off_hours(end_epoch) else "")),
        ]
    sd = max(dec, 1)
    return [
        ("E1", "last", f"last = {F.fmt(st['last'], dec)}{u}"),
        ("E2", "max", f"max = {F.fmt(st['max'], dec)}{u} at {T(st['max_idx'])}"),
        ("E3", "min", f"min = {F.fmt(st['min'], dec)}{u} at {T(st['min_idx'])}"),
        ("E4", "slope", f"trend = {st['slope_per_h']:+.{sd}f}{u}/h (r2 {st['r2']:.2f})"),
        ("E5", "max_jump", f"largest 5-min change = {st['max_jump_signed']:+.{sd}f}{u} at {T(st['max_jump_idx'])}"),
        ("E6", "sma", f"SMA 1h = {F.fmt(st['sma_1h'], dec)}, EMA 1h = {F.fmt(st['ema_1h'], dec)}, mean {hours_str(n)}h = {F.fmt(st['mean'], dec)}{u}"),
        ("E7", "shape", f"halves {F.fmt(st['first_half'], dec)} -> {F.fmt(st['second_half'], dec)}, curvature {st['curvature']:+.{sd}f}/h, oscillation crossings {st['zero_cross']}"),
        ("E8", "flat", f"noise {st['noise']:.{sd + 1}f}, longest flat run {st['flat_run']} pts, plateau at max {st['plateau_run']} pts"),
    ]


# ---------------------------------------------------------------- E9 / E10 (history lines)
def median(v):
    return LRM.median(v)


def long_view(role, metric, h):
    """E9 findings on the history (list of dicts, longrange.decide format + 'idx' of the shift)."""
    if len(h) < LR_MIN_POINTS:
        return None
    st = LRM.stats(role, metric, h)
    out = LRM.decide(st, LR_PARAMS)
    for f in out:
        if f["kind"] == "level_shift":
            f["idx"] = len(h) - 1 - f["ago_pts"]
    return out


def exc_scale(role, metric, h):
    """E10 'normal noise': the same scale as E9 / longrange.go lrScale = max(robust 5-min noise,
    1/2 metric floor, kQ x IQR of the first 3 h) (the IQR term keeps switching sensors from counting
    every routine switch as an excursion)."""
    ref = sorted(h[:36])
    iqr = ref[(3 * len(ref)) // 4] - ref[len(ref) // 4]
    return max(LRM.noise_scale(role, metric, h), LR_PARAMS["kQ"] * iqr)


def excursions(role, metric, h):
    """E10: (count, peak in noise units, [last index of each excursion]) on the history."""
    s = exc_scale(role, metric, h)
    n = len(h)
    thr = EXC_K * s
    c, last, peak, ends = 0, -10, 0.0, []
    for i in range(n):
        r = abs(h[i] - median(h[max(0, i - EXC_HALF):min(n, i + EXC_HALF + 1)]))
        if r >= thr:
            if i - last > EXC_GAP:
                c += 1
                ends.append(i)
            else:
                ends[-1] = i
            last = i
            peak = max(peak, r / s)
    return c, peak, ends


def occ_periods(h):
    """Occupied runs in a binary history: (count, longest run in points)."""
    c, cur, best = 0, 0, 0
    for i, v in enumerate(h):
        if v >= 0.5:
            if cur == 0:
                c += 1
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return c, best


def history_items(role, metric, h, end_epoch, dec, unit):
    """(E9, E10) evidence tuples plus the raw values the teacher needs."""
    u = f" {unit}" if unit else ""
    hh = f"{len(h) * STEP_MIN / 60:.0f}"
    info = {"hist_len": len(h)}
    if role == "occupancy":
        frac = sum(h) / len(h)
        k, best = occ_periods(h)
        info.update({"occ_frac_12h": frac, "occ_periods": k, "occ_longest": best})
        e9 = f"12 h view: occupied fraction {frac:.2f} over the last {hh} h"
        if k == 0:
            e10 = f"recent episodes: no occupied periods in the last {hh} h"
        else:
            e10 = f"recent episodes: {k} occupied period{'' if k == 1 else 's'} in the last {hh} h (longest {best * STEP_MIN / 60:.1f} h)"
        return [("E9", "long_view", e9), ("E10", "episodes", e10)], info
    sd = max(dec, 1)
    lv = long_view(role, metric, h)
    info["long_view"] = lv
    if lv is None:
        e9 = "12 h view: under 8 h of history"
    elif not lv:
        e9 = "12 h view: no level shift or drift"
    else:
        parts = []
        for f in lv:
            if f["kind"] == "level_shift":
                t = idx_time(end_epoch, len(h), f["idx"])
                f["time"] = t
                parts.append(f"level shift {f['delta']:+.{sd}f}{u} at {t} ({f['sigma']:.1f}x normal variation)")
            else:
                t = idx_time(end_epoch, len(h), 0)
                f["time"] = t
                parts.append(f"slow drift {f['delta']:+.{sd}f}{u} since {t} (r2 {f['r2']:.2f}, {f['sigma']:.1f}x normal variation)")
        e9 = "12 h view: " + "; ".join(parts)
    k, peak, ends = excursions(role, metric, h)
    info.update({"exc_count": k, "exc_peak": peak, "exc_ends": ends})
    if k == 0:
        e10 = f"recent episodes: no excursions beyond 3x normal noise in the last {hh} h"
    else:
        e10 = (f"recent episodes: {k} excursion{'' if k == 1 else 's'} beyond 3x normal noise in the last {hh} h"
               f" (largest {peak:.1f}x)")
    return [("E9", "long_view", e9), ("E10", "episodes", e10)], info


# ---------------------------------------------------------------- prompt
SYSTEM_RULES_V1 = F.SYSTEM_RULES


def system_rules(n):
    return (SYSTEM_RULES_V1.replace("a 4-hour window", f"a {hours_str(n)}-hour window")
            .replace("(E1..E8)", "(E1..E10)"))


def output_schema_hint(role):
    causes = "|".join(CAUSES[role])
    pats = "|".join(PATTERNS[role])
    return ('JSON keys: pattern (' + pats + '), status (normal|warning|critical|sensor_fault), '
            'observations (1-2 short strings, each ending with cited ids like [E1,E4]), '
            'likely_cause (' + causes + '), confidence (0-1), event_active (true|false), onset (HH:MM), '
            'fault_kind (' + "|".join(FAULT_KINDS) + ', only if sensor_fault), action (' + "|".join(ROLE_ACTIONS.get(role, F.ACTIONS)) + ').')


def compute_window_stats(role, metric, xs):
    if role == "occupancy":
        return F.occ_stats(xs)
    return F.compute_stats(xs, METRICS[(role, metric)]["dec"])


def build_user_prompt(role, node, location, metric, hist, n, end_epoch, context=""):
    m = METRICS[(role, metric)]
    dec, unit = m["dec"], m["unit"]
    xs = hist[-n:]
    assert len(xs) == n and n % 2 == 0
    end = datetime.fromtimestamp(end_epoch, IST)
    start = end - timedelta(minutes=STEP_MIN * (n - 1))
    lines = [f"NODE: {node} ({location})", f"METRIC: {metric} [{unit or 'ratio'}]"]
    if m["warn"] is not None:
        rel = "below" if m["dir"] == "low" else "above"
        lines.append(f"LIMITS: warning {rel} {m['warn']}, critical {rel} {m['crit']}")
    tl = NODE_LIMITS.get(node) if (role, metric) == ("water", "level") else None
    if tl:
        lines.append(f"TANK: high level above {F.fmt(tl['high'], dec)}, overflow risk above {F.fmt(tl['overflow'], dec)}; "
                     f"usual fill up to {tl['fill_min']} min")
    lines.append(f"WINDOW: {start:%a %d %b %H:%M} -> {end:%H:%M} IST, {n} x 5 min")
    st = compute_window_stats(role, metric, xs)
    if role == "occupancy":
        lines.append("STATES (1=occupied): " + "".join(str(int(v)) for v in xs))
    else:
        lines.append("SERIES (10-min means): " + " ".join(F.fmt(v, dec) for v in F.downsample(xs, n // 2)))
    if context:
        lines.append("CONTEXT: " + context)
    lines.append("EVIDENCE:")
    ev = evidence_items(role, metric, st, end_epoch, dec, unit, n)
    hv, info = history_items(role, metric, hist[-HIST:], end_epoch, dec, unit)
    ev = ev + hv
    for eid, _, text in ev:
        lines.append(f"{eid} {text}")
    return "\n".join(lines), st, ev, info


def agent_prompt(role, node, location, metric, hist, n, end_epoch, context=""):
    """Returns (raw Llama-3 prompt string, window stats, evidence list, history info)."""
    user, st, ev, info = build_user_prompt(role, node, location, metric, hist, n, end_epoch, context)
    system = SYSTEM_PROMPTS[role] + system_rules(n) + " " + output_schema_hint(role)
    return F.llama3_prompt(system, user), st, ev, info


def user_text(prompt):
    """The user turn of a raw prompt (what QA checks numbers against)."""
    a = prompt.index("<|start_header_id|>user<|end_header_id|>\n\n") + len("<|start_header_id|>user<|end_header_id|>\n\n")
    return prompt[a:prompt.index("<|eot_id|>", a)]


def v1_prefix_equal(role, node, location, metric, xs48, end_epoch):
    """At N=48 the v2 user turn up to E8 must equal v1's user turn (asserted by checks_v2)."""
    v1u, _, _ = F.build_user_prompt(role, node, location, metric, xs48, end_epoch)
    v2u, _, _, _ = build_user_prompt(role, node, location, metric, xs48, 48, end_epoch)
    cut = v2u.index("\nE9 ")
    return v1u == v2u[:cut]
