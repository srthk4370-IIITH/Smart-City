"""REALWORLD.md section 5 cases that 3e did not cover, for 3f training (SFT) and for the dev / test gates.

Cases (REALWORLD.md section 5 numbering), each its own slice "rw5_<case>":
  5.1  gap_calm      calm window with 1-3 (n=48) or up to 6 (n>=96) missing buckets, linearly filled exactly as
                     generate_v2.hist_at / the engine's Window() do (runs <= 2, some in the last 4 buckets).
                     Hard negative: teacher label stays stable/normal (never step / flatline).
       gap_event     a v2 event (gen_event) with the same gap fill, gaps kept off the event's defining readings,
                     some right next to it. Original teacher label kept.
  5.2  glitch        ONE reading in a calm CO2/temp/RH/TDS/pH/level window: 15-30 robust sigma (value glitch;
                     above gen_event's 3-12 sigma range so it never contradicts v2's event spikes), or a 0
                     sentinel (co2/temp/rh/ph/tds) or the metric's range rail (co2/temp/tds/ph/level).
                     Label (section 5.2): pattern spike|dip, event_active false; value glitch -> status normal,
                     cause = role's normal cause, action none. 0 / rail -> fault_kind dropout; the v2 schema only
                     allows fault_kind with status sensor_fault (validate()), so 0/rail = sensor_fault + dropout +
                     check_sensor (same as the existing v2 dropout rule). Power and flow are not used (load surges).
  5.6  co2_floor     indoor-air CO2 held / wandering at 150-300 ppm: whole window ("wander", pattern stable),
                     a fresh drop in the last hour ("fresh", step_decrease, teacher bias rule = jump > 150 ppm/5 min),
                     or exactly frozen ("stuck", flatline -> teacher stuck rule). Label: sensor_fault,
                     fault_kind bias (wander/fresh) or stuck, action check_sensor (v2's sensor action).
  5.7  holiday       a weekday power / CO2 window whose values (and 12 h history) come from a SUNDAY of the same
                     node at the same time of day (<= 30 min apart), weekday timestamp kept, Sunday mean <= 60% of
                     the weekday's: label = teacher stable/normal + a "low load" observation.
       hvac_stuck_on HVAC negative: existing HVAC teacher pattern stuck_on (unit running outside its schedule
                     with no cooling need -> warning, schedule_or_control_fault). Single-sensor agents cannot see
                     the HVAC state, so this is the closest teacher-labelled "low load but HVAC on" case.
       hvac_weekend_off  HVAC positive: existing hard negative weekend_off (normal).
  5.9  gap_recovery  newest 4-12 real readings come after a 2-6 h hole; the post-gap level is shifted by 4-12
                     sigma (the event happened during the outage). Window = only real points, gap collapsed
                     (approximation: the prompt's per-index times before the gap are shifted by the gap). Label:
                     teacher step_increase/step_decrease, onset at the jump (first post-gap reading),
                     event_active = (status is warning/critical) as section 5.9 states. Jumps the teacher reads as a
                     sensor bias (RATE rule) are skipped.
  5.11 chatter       the window and its history rescaled so the node's real fluctuation hovers at the WARNING
                     limit +-1-3% (>= 3 crossings). Label: warning, pattern stable, event_active true, cause =
                     teacher cause for (stable, warning). Dev/test rows come in adjacent pairs (window end and end +
                     5 min, id suffix "-next") for the consistency check (both must say warning).
  5.12 daily_cycle   indoor temperature (SR- nodes) or power: a slow half-sine rise over the window ending 10:00-16:00,
                     3-8 sigma, below limits (power: < 30% of base so the v2 relative rule stays "normal"). Label:
                     teacher gradual_increase/normal with cause overridden to the role's normal cause and a
                     "daily cycle" observation; if a limit is crossed the teacher label is kept (warning).
Skipped: 5.8 (reasoner-level).

Rules (section 5): train months only for train (Ctx split "train" = seen nodes only), test months incl. held-out nodes
for dev/test, existing teacher wherever it applies, every window passes hist_at's rule (runs < 3 missing, <= 6 per
window). Overrides of the teacher are only the section-5 labels above (function relabel(), each call commented).

  python gen_rw5.py --out ~/smartcity_runs/agents_v2_topup3f/rw5 [--train-scale 1 --eval-scale 1]
    -> rw5_train.jsonl (split train, seed 4495), rw5_test.jsonl (split test, seed 4495), rw5_dev.jsonl (split test,
       seed 4496), all de-duplicated against each other, v2 data and every 3e/3f file; manifest_rw5.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "topup3e"))
sys.path.insert(0, str(HERE.parent / "topup"))
import gen_3e as E  # noqa: E402,F401  (sets up paths like the 3e generator)
import gen_topup3 as G3  # noqa: E402
import gen_topup as T  # noqa: E402
from gen_topup import GV, V, TE, HA, SRC  # noqa: E402
import templates_v2 as TP  # noqa: E402

F = V.F
G = GV.G
STEP = GV.STEP
EOT = "<|eot_id|>"
R3E = Path.home() / "smartcity_runs" / "agents_v2_topup3e"
R3F = Path.home() / "smartcity_runs" / "agents_v2_topup3f"

# new observation phrasings for the section-5 labels (evidence ids exist in every prompt: E1..E8)
RW5T = {
    "glitch_note": ["A single reading; the series is calm before and after [E6,E1]",
                    "One isolated 5-min point, not a sustained change [E6,E1]",
                    "Only one reading is off; level back at {last}{u} [E1]"],
    "why_rail": ["{max}{u} is the sensor's range limit; a rail reading, not data [E2]",
                 "A jump to the range limit {max}{u} for one reading is a logger artefact [E2]"],
    "why_floor": ["{M} at {min}{u} is below outdoor air (~400 ppm); not physical [E3]",
                  "Indoor CO2 cannot sit below ~400 ppm; {min}{u} points to a sensor fault [E3]",
                  "{min}{u} is under the physical floor for CO2; sensor offset or dead [E3,E1]"],
    "low_load": ["{M} low near {mean}{u} for this hour; a quiet low-use day [E6]",
                 "Low but steady level around {mean}{u}; nothing abnormal [E6,E4]"],
    "chatter": ["{M} hovers at the {status} limit of {lim}{u}, peaking at {max}{u} [E2,E6]",
                "Repeatedly touching the {status} limit ({lim}{u}); max {max}{u} [E2]",
                "{M} keeps crossing {lim}{u}, the {status} limit [E2,E6]"],
    "daily_cycle": ["Rise follows the daytime cycle at this hour [E4]",
                    "Slow daytime rise in step with the daily cycle [E4,E6]",
                    "Expected daily-cycle increase, within limits [E4]"],
}
EID_RX = re.compile(r"^(E\d+) ", re.M)


def fill(key, vals, rng):
    if key in RW5T:
        return rng.choice(RW5T[key]).format(**vals)
    return TP.fill(key, vals, rng)


def vals_of(row):
    role, node, metric, n, end = row["role"], row["node"], row["metric"], row["n"], row["end_epoch"]
    _, st, ev, info = V.agent_prompt(role, node, G.describe(node), metric, row["hist"], n, end)
    return TE.evidence_vals(role, metric, st, info, end, n, node), st


def relabel(row, upd, obs=None):
    """Apply a section-5 label to a teacher row and re-validate (schema, key order, evidence ids)."""
    tgt = json.loads(row["completion"][: -len(EOT)])
    tgt.update(upd)
    if obs is not None:
        tgt["observations"] = obs
    if tgt["status"] != "sensor_fault":
        tgt.pop("fault_kind", None)
    tgt["action"] = TE.action_of(tgt["likely_cause"], tgt["status"])
    tgt = {k: tgt[k] for k in V.KEY_ORDER if k in tgt}
    GV.validate(row["role"], tgt, EID_RX.findall(V.user_text(row["prompt"])))
    row["completion"] = json.dumps(tgt, ensure_ascii=False) + EOT
    for k in ("pattern", "status", "likely_cause", "event_active", "onset", "confidence"):
        row[k] = tgt[k]
    row["fault_kind"] = tgt.get("fault_kind")
    row["rw5_relabel"] = sorted(upd) + (["observations"] if obs is not None else [])
    return row


def wd_hour(e):
    d = datetime.fromtimestamp(e, V.IST)
    return d.weekday(), d.hour + d.minute / 60


# ---------------------------------------------------------------- 5.1 gaps
def punch(y, idxs):
    y = list(y)
    for i in idxs:
        y[i] = None
    for i in range(len(y)):
        if y[i] is None:
            j = i
            while y[j] is None:
                j += 1
            a, b = y[i - 1], y[j]
            for k in range(i, j):
                y[k] = a + (b - a) * (k - i + 1) / (j - i + 1)
    return y


def pick_gaps(rng, H, n, avoid=(), near=()):
    total = rng.randint(1, 3) if n <= 48 else rng.randint(1, 6)
    lo, hi = H - n + 1, H - 2          # interior of the window (the last reading is always real, as in hist_at)
    taken = set()
    tries = 0
    while len(taken) < total and tries < 200:
        tries += 1
        u = rng.random()
        if near and u < 0.4:
            s = rng.choice(list(near))
        elif u < 0.7:
            s = rng.randint(max(lo, H - 5), hi)         # within the last 4 buckets
        else:
            s = rng.randint(lo, hi)
        L = min(rng.choice((1, 1, 2)), total - len(taken))
        run = [s + j for j in range(L)]
        if any(i < lo or i > hi or i in avoid or i in taken for i in run):
            continue
        if any((i - 1 in taken) or (i + 1 in taken) for i in run):   # keep runs <= 2 (hist_at stops at 3)
            continue
        taken.update(run)
    return sorted(taken)


def gen_gap_calm(ctx, n):
    b = GV.calm_base(ctx, n)
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    idxs = pick_gaps(ctx.rng, len(y), n)
    if not idxs:
        return None
    row = GV.finish(ctx, key, tag, end, punch(y, idxs), n, "stable", "gap_calm", "stable", {})
    if row:
        row["gap_idx"] = [i - (len(y) - n) for i in idxs]
    return row


def gen_gap_event(ctx, n):
    orig = GV.finish

    def fin(ctx_, key, tag, end, y, n_, fam, sub, pattern, extra):
        H = len(y)
        o = extra.get("onset_idx")
        avoid, near = set(), set()
        if o is not None and o >= 0:
            oi = H - n_ + o
            w = max(extra.get("w", 1), extra.get("ramp", 1))
            avoid = set(range(oi - 2, oi + w + 2))
            near = {oi - 4, oi - 3, oi + w + 2, oi + w + 3}
        idxs = pick_gaps(ctx_.rng, H, n_, avoid, near)
        if not idxs:
            return None
        row = orig(ctx_, key, tag, end, punch(y, idxs), n_, fam, sub, pattern, extra)
        if row:
            row["gap_idx"] = [i - (H - n_) for i in idxs]
        return row
    GV.finish = fin
    try:
        return GV.gen_event(ctx, n)
    finally:
        GV.finish = orig


# ---------------------------------------------------------------- 5.2 single glitch in a calm window
GL_METRICS = {"air_quality": ("co2", "temp", "rh"), "water": ("tds", "ph", "level")}
ZERO_OK = {("air_quality", "co2"), ("air_quality", "temp"), ("air_quality", "rh"), ("water", "ph"), ("water", "tds")}
RAIL_OK = {("air_quality", "co2"), ("air_quality", "temp"), ("water", "tds"), ("water", "ph"), ("water", "level")}


def gen_glitch(ctx, n):
    rng = ctx.rng
    b = GV.calm_base(ctx, n, ok=lambda k: k[2] in GL_METRICS.get(ctx.role, ()))
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    H = len(y)
    if G.status_of(role, metric, "stable", F.compute_stats(y[-n:], m["dec"]), bst["mean"]) != "normal":
        return None                      # the window without the glitch must itself be normal
    wi = rng.randint(n // 4, n - 2)
    i = H - n + wi
    u = rng.random()
    if u < 0.25 and (role, metric) in ZERO_OK:
        kind, p = "zero", "dip"
        y[i] = 0.0
    elif u < 0.40 and (role, metric) in RAIL_OK:
        kind, p = "rail", "spike"
        y[i] = float(m["hi"])
    else:
        sgn = rng.choice((1, -1))
        v = y[i] + sgn * rng.uniform(15, 30) * s0
        if not (m["lo"] < v < m["hi"]):
            return None
        kind, p = "value", ("spike" if sgn > 0 else "dip")
        y[i] = v
    st = F.compute_stats(y[-n:], m["dec"])
    if (p == "spike" and st["max_idx"] != wi) or (p == "dip" and st["min_idx"] != wi):
        return None
    row = GV.finish(ctx, key, tag, end, y, n, "glitch", kind, p, {"active": False, "w": 1, "onset_idx": wi})
    if row is None:
        return None
    vals, _ = vals_of(row)
    T0 = vals["tmax"] if p == "spike" else vals["tmin"]
    if kind == "value":   # 5.2: a single 5-min point is not an event for these metrics
        return relabel(row, {"pattern": p, "status": "normal", "likely_cause": TE.NORMAL_CAUSE[role], "event_active": False,
                             "onset": T0, "confidence": 0.7}, [fill(p, vals, rng), fill("glitch_note", vals, rng)])
    # 5.2: 0 / rail value -> dropout (schema: fault_kind only with sensor_fault)
    return relabel(row, {"pattern": p, "status": "sensor_fault", "likely_cause": "sensor_fault", "fault_kind": "dropout",
                         "event_active": False, "onset": T0, "confidence": 0.75},
                   [fill(p, vals, rng), fill("why_dropout" if kind == "zero" else "why_rail", vals, rng)])


# ---------------------------------------------------------------- 5.6 CO2 below the physical floor
def gen_co2_floor(ctx, n):
    rng = ctx.rng
    b = GV.calm_base(ctx, n, ok=lambda k: k[2] == "co2")
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    role, node, metric = key
    H = len(y)
    if min(y[-n:]) < 380:
        return None                      # the base must look like real indoor air
    lvl = rng.uniform(150, 300)
    u = rng.random()
    if u < 0.45:
        mode, p, L = "wander", "stable", rng.randint(n, H)
    elif u < 0.75:
        mode, p, L = "fresh", "step_decrease", rng.randint(3, 12)
    else:
        mode, p, L = "stuck", "flatline", rng.randint(max(24, n // 2), H)
    for j in range(H - L, H):
        if mode == "stuck":
            y[j] = float(round(lvl))
        else:
            lvl = min(300.0, max(150.0, lvl + rng.gauss(0, 1.5)))
            y[j] = float(round(lvl + rng.gauss(0, 1.0)))
    ow = n - L
    T = lambda i: V.idx_time(end, n, i)
    if mode == "fresh":
        st = F.compute_stats(y[-n:], 0)
        if abs(st["max_jump_idx"] - ow) > 1 or abs(st["max_jump_signed"]) <= TE.RATE[("air_quality", "co2")]:
            return None                  # teacher bias rule must fire (jump > 150 ppm in 5 min)
        return GV.finish(ctx, key, tag, end, y, n, "fault", "co2_floor_fresh", p, {"onset_idx": ow, "ramp": 1, "d": L})
    if mode == "stuck":
        return GV.finish(ctx, key, tag, end, y, n, "fault", "co2_floor_stuck", p,
                         {"onset_idx": ow if ow >= 0 else None, "d": L, "onset_time": T(ow) if ow >= 0 else T(0)})
    row = GV.finish(ctx, key, tag, end, y, n, "co2_floor", "co2_floor_wander", p, {})
    if row is None:
        return None
    vals, _ = vals_of(row)
    # 5.6: below-physical CO2 = sensor_fault, fault_kind bias, check the sensor
    return relabel(row, {"pattern": "stable", "status": "sensor_fault", "likely_cause": "sensor_fault", "fault_kind": "bias",
                         "event_active": True, "onset": T(max(ow, 0)), "confidence": 0.8},
                   [fill("stable", vals, rng), fill("why_floor", vals, rng)])


# ---------------------------------------------------------------- 5.7 holiday / weekend low load
HOL_CACHE = {}
def gen_holiday(ctx, n):
    rng = ctx.rng
    ok = (lambda k: k[2] == "power_kw" and not k[1].startswith("SL-")) if ctx.role == "power" else \
         (lambda k: k[2] == "co2" and k[1].startswith("SR-"))
    key, tag = ctx.pick_key(ok)
    if key is None:
        return None
    role, node, metric = key
    ck = (key, ctx.cur)
    if ck not in HOL_CACHE:
        ends = ctx.ends[key][ctx.cur]
        wh = [(e, *wd_hour(e)) for e in ends]
        HOL_CACHE[ck] = ([e for e, d, hr in wh if d < 5 and 9 <= hr < 18],
                         [(e, hr) for e, d, hr in wh if d == 6 and 9 <= hr < 18])
    wk, sunh = HOL_CACHE[ck]
    sun = [e for e, _ in sunh]
    if not wk or not sun:
        return None
    e_wd = rng.choice(wk)
    tod = wd_hour(e_wd)[1]
    cand = [e for e, hr in sunh if abs(hr - tod) <= 0.5]
    if not cand:
        return None
    e_sun = rng.choice(cand)
    S = ctx.S[key]
    mm = GV.MAX_MISS.get(role, 6)
    h_sun, h_wd = GV.hist_at(S, e_sun, max_miss=mm), GV.hist_at(S, e_wd, max_miss=mm)
    if len(h_sun) < max(n, 96) or len(h_wd) < n:
        return None
    ms, mw = sum(h_sun[-n:]) / n, sum(h_wd[-n:]) / n
    if mw <= 0 or ms > 0.6 * mw:
        return None
    if G.is_zero_flat(h_sun[-n:]) or not GV.pcalm(role, metric, h_sun[-n:]) or not GV.quiet_history(role, metric, h_sun, ctx.kthr[(role, metric)]):
        return None
    shift = int(round((e_wd - e_sun) / STEP))
    row = GV.finish(ctx, key, tag, e_sun + shift * STEP, list(h_sun), n, "stable", "holiday", "stable", {})
    if row is None or row["status"] != "normal":
        return None
    vals, _ = vals_of(row)
    tgt = json.loads(row["completion"][: -len(EOT)])
    # 5.7: normal/stable with a "low load" note (teacher already says stable/normal)
    return relabel(row, {}, [tgt["observations"][0], fill("low_load", vals, rng)])


def hvac_rows(ctx, quota, pattern):
    H = HA.H
    old = H.INJECTABLE
    H.INJECTABLE = (pattern,)
    try:
        rows, _ = HA.make_examples(ctx, quota, lambda rng, *a_, **k_: 48, GV.sample_d, GV.validate)
    finally:
        H.INJECTABLE = old
    return rows


# ---------------------------------------------------------------- 5.9 recovery right after a 2-6 h gap
def gen_gap_recovery(ctx, n):
    rng = ctx.rng
    key, tag = ctx.pick_key(lambda k: True)
    if key is None:
        return None
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    S = ctx.S[key]
    end = rng.choice(ctx.ends[key][ctx.cur])
    k, gap = rng.randint(4, 12), rng.randint(24, 72)
    post = [S.get(end - j * STEP) for j in range(k - 1, -1, -1)]
    if any(v is None for v in post):
        return None
    if S.get(end - (k + gap) * STEP) is None:
        return None                      # hist_at needs a real reading at its end
    pre = GV.hist_at(S, end - (k + gap) * STEP, max_miss=GV.MAX_MISS.get(role, 6))
    if len(pre) < n:
        return None
    xs = pre[-n:]
    if G.is_zero_flat(xs) or not GV.pcalm(role, metric, xs) or not GV.quiet_history(role, metric, pre, ctx.kthr[(role, metric)]):
        return None
    s0, bst = G.scale_of(role, metric, xs)
    size, sgn = rng.uniform(4, 12), rng.choice((1, -1))
    A = size * s0
    if max(post) - min(post) > 0.5 * A:
        return None                      # the post-gap readings themselves must be a steady new level
    y = (pre + [v + sgn * A for v in post])[-V.HIST:]
    y = GV.clamp(y, m)
    if GV.clamped_count(y[-n:], m) > 4:
        return None
    ow = n - k
    st = F.compute_stats(y[-n:], m["dec"])
    if abs(st["max_jump_idx"] - ow) > 1 or (st["max_jump_signed"] > 0) != (sgn > 0):
        return None
    p = "step_increase" if sgn > 0 else "step_decrease"
    row = GV.finish(ctx, key, tag, end, y, n, "event", "gap_recovery", p,
                    {"size": size, "d": k, "onset_idx": ow, "ramp": 1, "base_mean": bst["mean"]})
    if row is None or row["pattern"] != p:
        return None
    # 5.9: event_active = beyond limits
    return relabel(row, {"event_active": row["status"] in ("warning", "critical")})


# ---------------------------------------------------------------- 5.11 chattering at the warning limit
CH_METRICS = {"air_quality": ("co2", "pm25", "pm10", "temp", "rh"), "power": ("pf",)}   # tds: no calm test/train windows qualify


def chatter_series(h, warn, a):
    mu = sum(h) / len(h)
    dev = [v - mu for v in h]
    mx = max(abs(d) for d in dev) or 1.0
    return [warn + d * a / mx for d in dev]


def gen_chatter(ctx, n, pair=False):
    rng = ctx.rng
    b = GV.calm_base(ctx, n, ok=lambda k: k[2] in CH_METRICS.get(ctx.role, ()))
    if b is None:
        return None
    key, tag, end, h, s0, bst = b
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    warn = float(m["warn"])
    a = rng.uniform(0.01, 0.03) * abs(warn)
    y = chatter_series(h, warn, a)
    xs = y[-n:]
    up = (lambda v: v >= warn) if m["dir"] == "high" else (lambda v: v <= warn)
    cross = sum(1 for i in range(1, n) if up(xs[i]) != up(xs[i - 1]))
    if cross < 3:
        return None
    row = GV.finish(ctx, key, tag, end, y, n, "chatter", "chatter", "stable", {})
    if row is None:
        return None
    rows = [row]
    if pair:   # the adjacent window (end + 5 min), same transform of the real series
        nxt = ctx.S[key].get(end + STEP)
        if nxt is None:
            return None
        h2 = (h + [nxt])[-V.HIST:]
        mu, mx = sum(h) / len(h), max(abs(v - sum(h) / len(h)) for v in h) or 1.0
        y2 = [warn + (v - mu) * a / mx for v in h2]
        row2 = GV.finish(ctx, key, tag, end + STEP, y2, n, "chatter", "chatter", "stable", {})
        if row2 is None:
            return None
        rows.append(row2)
    out = []
    for r in rows:
        vals, st = vals_of(r)
        T = lambda i, e=r["end_epoch"]: V.idx_time(e, n, i)
        first = next((i for i, v in enumerate(r["hist"][-n:]) if up(v)), 0)
        cause = G.cause_of(role, metric, "stable", "warning", F.is_off_hours(r["end_epoch"]), node.startswith("SR-"), False)
        # 5.11: hovering at the limit = warning, event active, consistent across adjacent windows
        out.append(relabel(r, {"status": "warning", "likely_cause": cause, "event_active": True, "onset": T(first), "confidence": 0.7},
                           [fill("stable", vals, rng), fill("chatter", dict(vals, status="warning", lim=F.fmt(warn, m["dec"])), rng)]))
    if pair:
        out[0]["pair_row"] = out[1]
    return out[0]


# ---------------------------------------------------------------- 5.12 weather-driven daily cycle
def gen_daily_cycle(ctx, n):
    rng = ctx.rng
    ok = (lambda k: k[2] == "power_kw" and not k[1].startswith("SL-")) if ctx.role == "power" else \
         (lambda k: k[2] == "temp" and k[1].startswith("SR-"))
    b = GV.calm_base(ctx, n, ok=ok, end_ok=lambda e: 10 <= wd_hour(e)[1] < 16)
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    H = len(y)
    L = min(H, n + rng.randint(0, 24))
    A = rng.uniform(3, 8) * s0
    if role == "power" and A > 0.25 * max(bst["mean"], 1e-9):
        return None                      # keep the v2 relative rule at "normal" (range/base <= 0.3)
    o = H - L
    for i in range(o, H):
        y[i] += A * math.sin(0.5 * math.pi * (i - o + 1) / L)
    y = GV.clamp(y, m)
    row = GV.finish(ctx, key, tag, end, y, n, "daily_cycle", "daily_cycle", "gradual_increase",
                    {"onset_idx": n - L if L <= n else None, "onset_time": V.idx_time(end, H, o), "d": L})
    if row is None or row["pattern"] != "gradual_increase":
        return None
    if row["status"] != "normal":
        if role == "power" or rng.random() < 0.75:
            return None                  # power: no fixed limits, only the below-30% (normal) rise; temp: keep ~25%
        return row                       # beyond limits: teacher label kept (5.12 "unless beyond limits")
    vals, _ = vals_of(row)
    tgt = json.loads(row["completion"][: -len(EOT)])
    # 5.12: daily-cycle rise below limits = normal, the role's normal cause
    return relabel(row, {"likely_cause": TE.NORMAL_CAUSE[role], "confidence": 0.7},
                   [tgt["observations"][0], fill("daily_cycle", vals, rng)])



# ---------------------------------------------------------------- board chaos case: acidic water (low pH)
def gen_acidic(ctx, n):
    """Board weakness (v2 said cause "acidic_condition", off-label): calm pH window that drifts (gradual) or ramps (step,
    ramped under the 0.3 pH / 5 min bias rate) down to pH 5.2-6.4. Pure teacher label: warning (< 6.5) / critical
    (< 6.0), cause water_quality_issue, action request_facility_review (all in the v2 label set and the backend)."""
    rng = ctx.rng
    key, tag = ctx.pick_key(lambda k: k[2] == "ph")   # no pH window passes v1 is_calm: steady = range <= 0.4 pH
    if key is None:
        return None
    # SCRC pH is unusable as a base (railed at 14 or swinging >= 2 pH within 4 h; < 4 h runs of 5-min buckets), so the
    # base is SYNTHETIC: steady level 6.9-8.2 + Gaussian noise sd 0.02-0.08 + a slow +-0.05 wobble, at a real pH node's
    # real window end (documented; small board-chaos slice only).
    ts = [t for t in sorted(ctx.S[key]) if GV.split_of(t) == ctx.cur]
    if not ts:
        return None
    end = rng.choice(ts); end -= end % STEP
    lvl, sd, ph0 = rng.uniform(6.9, 8.2), rng.uniform(0.02, 0.08), rng.uniform(0, 6.3)
    y = [lvl + 0.05 * math.sin(ph0 + i / 20) + rng.gauss(0, sd) for i in range(144)]
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    H = len(y)
    s0, bst = G.scale_of(role, metric, y[-n:])
    if max(y[-n:]) - min(y[-n:]) > 0.4 or not (6.8 <= y[-1] <= 8.4):
        return None
    A = y[-1] - rng.uniform(5.2, 6.4)
    p = rng.choice(("gradual_decrease", "step_decrease"))
    d = rng.randint(6, n - 4) if p == "gradual_decrease" else rng.randint(4, n - 4)
    o = H - d
    if p == "gradual_decrease":
        GV.inj_gradual(y, o, A, -1)
        r = 1
    else:
        r = GV.ramp_for(role, metric, A)
        if r > max(1, d - 2):
            return None
        GV.inj_step(y, o, A, -1, r)
    row = GV.finish(ctx, key, tag, end, y, n, "event", "acidic", p,
                    {"size": A / max(s0, 1e-9), "d": d, "onset_idx": n - d, "ramp": r, "base_mean": bst["mean"]})
    if row is None or row["pattern"] != p or row["likely_cause"] != "water_quality_issue":
        return None
    return row

# ---------------------------------------------------------------- buckets
def pairwise(fn):
    return lambda ctx, n: fn(ctx, n, pair=True)


def at(fn, ns=(48, 96, 144)):
    return lambda ctx, _n: fn(ctx, ctx.rng.choice(ns))


def buckets(eval_pairs):
    ch = pairwise(gen_chatter) if eval_pairs else gen_chatter
    if ONLY_ACIDIC:
        return [("rw5_acidic_water", "water", 30, 12, at(gen_acidic))]
    B = []
    for role in ("power", "water", "air_quality", "weather"):
        B += [(f"rw5_gap_calm_{role}", role, 15, 6, at(gen_gap_calm)),
              (f"rw5_gap_event_{role}", role, 20, 8, at(gen_gap_event)),
              (f"rw5_gap_recovery_{role}", role, 15, 6, at(gen_gap_recovery))]
    B += [("rw5_glitch_air_quality", "air_quality", 40, 15, at(gen_glitch)),
          ("rw5_glitch_water", "water", 30, 12, at(gen_glitch)),
          ("rw5_co2_floor_air_quality", "air_quality", 50, 20, at(gen_co2_floor)),
          ("rw5_holiday_power", "power", 30, 12, at(gen_holiday)),
          ("rw5_holiday_air_quality", "air_quality", 20, 8, at(gen_holiday)),
          ("rw5_chatter_air_quality", "air_quality", 30, 12, at(ch)),
          ("rw5_chatter_power", "power", 12, 5, at(ch)),
          ("rw5_daily_cycle_air_quality", "air_quality", 25, 10, at(gen_daily_cycle)),
          ("rw5_daily_cycle_power", "power", 25, 10, at(gen_daily_cycle))]
    return B


ONLY_ACIDIC = False
CASE = lambda name: re.sub(r"_(power|water|air_quality|weather|hvac)$", "", name)


def make(split, seed, scale, heldout, kthr, seen, prefix):
    G3.SEED = seed
    pairs = split == "test"
    B = [(nm, ro, 0, max(2, round((q if split == "train" else dq) * scale)), fn, "other") for nm, ro, q, dq, fn in buckets(pairs)]
    rows, stats = _make(split, B, heldout, kthr, seen)
    # HVAC (5.7 negatives / positives)
    cache = ({}, *GV.node_index({}))
    import random
    for nm, pat, q, dq in (() if ONLY_ACIDIC else (("rw5_hvac_stuck_on", "stuck_on", 20, 8), ("rw5_hvac_weekend_off", "weekend_off", 15, 6))):
        quota = max(2, round((q if split == "train" else dq) * scale))
        ctx = GV.Ctx(cache[0], cache[2], cache[1], heldout, split, "hvac", kthr, random.Random(f"{seed}|rw5|{split}|{nm}"))
        got = []
        for r in hvac_rows(ctx, quota, pat):
            hh = hashlib.sha256(r["prompt"].encode()).hexdigest()
            if hh in seen:
                continue
            seen.add(hh)
            r["topup_bucket"] = nm
            r["id"] = f"{prefix}-{nm}-{len(got):04d}"
            got.append(r)
        rows += got
        stats[nm] = {"quota": quota, "made": len(got)}
    out = []
    for r in rows:
        r["id"] = r["id"].replace(f"topup3-{split}-", prefix + "-")
        case = CASE(r["topup_bucket"])
        r["slices"] = ["realworld", "rw5", case]
        r["rw5_case"] = case
        r["stage"] = r.get("stage") or "other"
        out.append(r)
        pr = r.pop("pair_row", None)
        if pr is not None:
            pr["id"] = r["id"] + "-next"
            pr["topup_bucket"] = r["topup_bucket"]
            pr["slices"] = r["slices"] + ["rw5_chatter_next"]
            pr["rw5_case"] = case
            pr["stage"] = "other"
            pr["pair_of"] = r["id"]
            out.append(pr)
    return out, stats


def _make(split, B, heldout, kthr, seen):
    """gen_topup3.make for the continuous roles (same loop: quota, 600 tries per row, de-dup by prompt hash)."""
    import random
    rows, stats, cache = [], {}, {}
    for name, role, _q, quota, fn, stage in B:
        if role not in cache:
            cache[role] = T.load_role(role)
        S, roles, ends = cache[role]
        ctx = GV.Ctx(S, ends, roles, heldout, split, role, kthr, random.Random(f"{G3.SEED}|rw5|{split}|{name}"))
        made, tries, rej = 0, 0, Counter()
        t0 = time.time()
        while made < quota and tries < quota * 600:
            tries += 1
            try:
                r = fn(ctx, 48)
            except AssertionError:
                rej["assert"] += 1
                continue
            if r is None:
                continue
            hh = hashlib.sha256(r["prompt"].encode()).hexdigest()
            if hh in seen:
                rej["dup"] += 1
                continue
            seen.add(hh)
            r["topup_bucket"] = name
            r["id"] = f"topup3-{split}-{name}-{made:04d}"
            rows.append(r)
            made += 1
        stats[name] = {"role": role, "quota": quota, "made": made, "tries": tries, "rejected": dict(rej), "seconds": round(time.time() - t0, 1)}
        print(f"  {split}/{name}: {made}/{quota} in {tries} tries, {time.time() - t0:.1f}s", flush=True)
    return rows, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--train-scale", type=float, default=1.0)
    ap.add_argument("--eval-scale", type=float, default=1.0)
    ap.add_argument("--only", default="train,test,dev")
    ap.add_argument("--acidic", action="store_true", help="only the acidic-water case -> rw5x_*.jsonl (appended later)")
    a = ap.parse_args()
    global ONLY_ACIDIC
    ONLY_ACIDIC = a.acidic
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    man0 = json.loads((SRC / "manifest.json").read_text())
    heldout = dict(man0["heldout_nodes"])
    kj = json.loads((SRC / "kthr.json").read_text())
    kthr = defaultdict(lambda: 99, {tuple(k.split("/")): v["thr"] for k, v in kj.items()})
    V.NODE_LIMITS.update(json.loads((SRC / "node_limits.json").read_text()))
    HA.register()
    TE.build_calibration()
    h = lambda p: hashlib.sha256(p.encode()).hexdigest()
    seen = set()
    for f in ("train.jsonl", "dev.jsonl", "test.jsonl"):
        seen |= {h(json.loads(l)["prompt"]) for l in open(SRC / f, encoding="utf-8")}
    for f in list((R3E / "data").glob("*.jsonl")) + [R3E / "eval" / "eval3e.jsonl"] + list((R3F / "dev").glob("*.jsonl")) + list((R3F / "rw5").glob("*.jsonl")):
        for l in open(f, encoding="utf-8"):
            j = json.loads(l)
            if "prompt" in j:
                seen.add(h(j["prompt"]))
    man = {"what": "REALWORLD.md section 5 cases missing from 3e (5.1, 5.2, 5.6, 5.7, 5.9, 5.11, 5.12)",
           "created": datetime.now().isoformat(timespec="seconds"), "args": vars(a), "files": {}}
    for split, seed, scale, prefix, name in (("test", 4495, a.eval_scale, "rw5test", "rw5_test.jsonl"),
                                             ("test", 4496, a.eval_scale, "rw5dev", "rw5_dev.jsonl"),
                                             ("train", 4495, a.train_scale, "rw5train", "rw5_train.jsonl")):
        if a.acidic:
            name = name.replace("rw5_", "rw5x_")
        if prefix.replace("rw5", "") not in a.only.split(","):
            continue
        t0 = time.time()
        rows, stats = make(split, seed, scale, heldout, kthr, seen, prefix)
        p = out / name
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        man["files"][name] = {"split": split, "seed": seed, "n": len(rows), "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
                              "cases": Counter(r["rw5_case"] for r in rows), "roles": Counter(r["role"] for r in rows),
                              "case_status": Counter(f"{r['rw5_case']}:{r['pattern']}/{r['status']}" for r in rows),
                              "seen": Counter(r.get("seen") for r in rows), "buckets": stats, "seconds": round(time.time() - t0, 1)}
        print(name, len(rows), dict(man["files"][name]["cases"]), flush=True)
    (out / ("manifest_rw5x.json" if a.acidic else "manifest_rw5.json")).write_text(json.dumps(man, indent=1, default=str))


if __name__ == "__main__":
    main()
