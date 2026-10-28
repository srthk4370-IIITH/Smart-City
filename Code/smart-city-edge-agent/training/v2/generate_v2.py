"""Build the v2 domain-agent SFT dataset (spec: training/RETRAIN_V2_SPEC.md).

  py -3 generate_v2.py                 # full size (~36k train / 2k dev / 3k test), resumable shards
  py -3 generate_v2.py --scale 0.02    # quick smoke run into data/sft_v2_smoke
  py -3 generate_v2.py --force         # rebuild every shard

Design
  * Bases are REAL windows from data/series (all nodes, all months). A base = up to 144 five-minute values
    (12 h history) ending at the window end; the window is its last N values, N in 24..144 (step 6).
  * Families (continuous roles): stable, event (v1's patterns at any age/size), recurring (small spikes),
    old_shift, long_drift, fault (stuck, bias, calib_drift, noise, dropout, saturation, quantised),
    compound (dominant + second feature), routine (synthetic hard negatives), real_routine (real windows whose
    shape matches a routine rule), real_longrange (real calm windows with an E9 finding), zero_idle.
    Occupancy: real 0/1 windows + edited top-ups (v1 approach), flapping = sensor_fault.
    HVAC: from training/v2/hvac.py through hvac_adapter.py (stubbed until that module exists).
  * Labels: teacher_v2.label (deterministic rules over the evidence). Every target is validated (enums, ids,
    key order) before it is kept.
  * Splits by window end AND history start (IST): train Jan-Aug, dev Sep-Oct, test Nov-Dec; ~15% of nodes per
    role are held out (test only, tagged "unseen").
  * Deterministic: one RNG per (split, role) task seeded from --seed; tasks run in parallel processes and each
    writes a shard (data/sft_v2/shards); a finished shard is reused on rerun (resumable).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import features_v2 as V  # noqa: E402
import generate_dataset as G  # noqa: E402
import teacher_v2 as TE  # noqa: E402
import hvac_adapter as HA  # noqa: E402

F = V.F
ROOT = HERE.parents[1]
DATA = ROOT / "data"
TOKENIZER = ROOT / "models" / "genie_bundle" / "llama_v3_2_3b_instruct-genie-w4a16-qualcomm_snapdragon_8gen3" / "tokenizer.json"
STEP = 300
PREFILL = '{"pattern": "'
VERSION = "v2.0"

QUOTA = {  # examples per split and role (HVAC kept in the plan even while stubbed)
    "train": {"air_quality": 6500, "water": 6500, "power": 6500, "weather": 5000, "occupancy": 5000, "hvac": 6500},
    "dev": {"air_quality": 360, "water": 360, "power": 360, "weather": 280, "occupancy": 280, "hvac": 360},
    "test": {"air_quality": 540, "water": 540, "power": 540, "weather": 420, "occupancy": 420, "hvac": 540},
}
# share of each continuous role's quota per family (re-normalised over the families a role supports)
MIX = {"water_fill": 0.05, "stable": 0.08, "event": 0.40, "recurring": 0.04, "old_shift": 0.05, "long_drift": 0.05, "fault": 0.12,
       "compound": 0.06, "routine": 0.10, "real_routine": 0.06, "real_longrange": 0.02, "zero_idle": 0.02}
EVENT_PATTERNS = ("spike", "dip", "gradual_increase", "gradual_decrease", "step_increase", "step_decrease",
                  "exponential_increase", "oscillation", "throttling", "erratic")
FAULT_KINDS_GEN = ("stuck", "bias", "calib_drift", "noise_increase", "dropout", "saturation", "quantised")
FAULT_WEIGHTS = {"stuck": 3, "bias": 1.5, "calib_drift": 1, "noise_increase": 2, "dropout": 1.5, "saturation": 1, "quantised": 1.5}
LEN_WEIGHTS = {48: 0.25, 96: 0.20, 144: 0.20}
HELDOUT_FRAC = 0.15
UNSEEN_SHARE = 0.35          # share of test examples drawn from held-out nodes (when the role has any)
UNSEEN_SHARE_ROLE = {"water": 0.6}  # water test-month data is thin (mostly noisy flow): lean on held-out sensors
SEPOCT_ROLES = ("water",)    # D8: held-out water sensors also give Sep-Oct test windows (tag unseen_sepoct)


# ================================================================ data
def split_of(epoch):
    mth = datetime.fromtimestamp(epoch, V.IST).month
    return "train" if mth <= 8 else ("dev" if mth <= 10 else "test")


def load_all(cache):
    if cache.exists():
        with open(cache, "rb") as fh:
            return pickle.load(fh)
    t = time.time()
    S = G.load_series()
    S.update(HA.load_series())
    cache.parent.mkdir(parents=True, exist_ok=True)
    with open(cache, "wb") as fh:
        pickle.dump(S, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"series loaded in {time.time() - t:.0f}s ({len(S)} series), cached", flush=True)
    return S


MAX_MISS = {"weather": 72}  # weather logs every 10 min in some months; v1 also accepted half-filled weather windows


def hist_at(s, end, maxlen=V.HIST, max_miss=6):
    """Up to maxlen values ending at `end` (oldest first). Stops at 3 consecutive missing points or more than
    max_miss missing (6; 72 for weather, as v1's min_have=24 of 48); interior gaps linearly interpolated (as v1)."""
    out, miss, run = [], 0, 0
    for i in range(maxlen):
        v = s.get(end - i * STEP)
        if v is None:
            miss += 1
            run += 1
            if run >= 3 or miss > max_miss:
                break
            out.append(None)
        else:
            run = 0
            out.append(v)
    while out and out[-1] is None:
        out.pop()
    out.reverse()
    for i in range(len(out)):
        if out[i] is None:
            j = i
            while out[j] is None:
                j += 1
            a, b = out[i - 1], out[j]
            for k in range(i, j):
                out[k] = a + (b - a) * (k - i + 1) / (j - i + 1)
    return out


def pcalm(role, metric, xs):
    """Calm by v1's training definition in every 4 h slice (whole window when shorter than 4 h)."""
    n = len(xs)
    if n <= 48:
        return G.is_calm(role, metric, xs)
    ends = list(range(n, 47, -48))
    if ends[-1] != 48:
        ends.append(48)
    return all(G.is_calm(role, metric, xs[e - 48:e]) for e in ends)


def rule_pattern_n(role, metric, xs, end):
    old = F.WINDOW
    F.WINDOW = len(xs)
    try:
        return F.rule_pattern(role, metric, xs, end)
    finally:
        F.WINDOW = old


def node_index(S):
    """role -> node -> [series keys]; per key the sorted window-end candidates per split."""
    roles = defaultdict(lambda: defaultdict(list))
    ends = {}
    for k, s in S.items():
        role, node, metric = k
        roles[role][node].append(k)
        bs = sorted(s)
        per = defaultdict(list)
        for b in bs:
            per[split_of(b)].append(b)
        ends[k] = dict(per)
    return roles, ends


def choose_heldout(roles, ends, seed):
    """~15% of nodes per role (round, >= 1 when the role has >= 4 nodes), chosen by a seeded hash among nodes
    with enough test-month data so that the unseen test slice is not empty."""
    out = {}
    for role, nodes in sorted(roles.items()):
        k = round(HELDOUT_FRAC * len(nodes))
        if k == 0 and len(nodes) >= 4:
            k = 1
        elig = [n for n in nodes if sum(len(ends[key].get("test", [])) for key in nodes[n]) >= 2000]
        elig.sort(key=lambda n: hashlib.sha256(f"{seed}|{n}".encode()).hexdigest())
        out[role] = sorted(elig[:k])
    return out


# ================================================================ sampling helpers
def sample_n(rng, lo=V.MIN_N, hi=V.MAX_N):
    r = rng.random()
    acc = 0.0
    for n, w in LEN_WEIGHTS.items():
        acc += w
        if r < acc and lo <= n <= hi:
            return n
    rest = [n for n in V.LENGTHS if n not in LEN_WEIGHTS and lo <= n <= hi]
    return rng.choice(rest) if rest else max(lo, min(hi, 48))


def sample_d(rng, n, dmin=3):
    """Readings since onset: uniform from 3 readings before the end to the window start, plus extra weight
    (35%) on 4-12 readings (20-60 min)."""
    d = rng.randint(4, 12) if rng.random() < 0.35 else rng.randint(3, n)
    return max(dmin, min(n, d))


def sample_size(rng, small_p=0.20, lo=3.0, hi=12.0):
    if rng.random() < small_p:
        return rng.uniform(1.5, 3.0)
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


def clamp(y, m, keep=()):
    return [v if i in keep else min(m["hi"], max(m["lo"], v)) for i, v in enumerate(y)]


def clamped_count(y, m):
    return sum(1 for v in y if v <= m["lo"] + 1e-12 or v >= m["hi"] - 1e-12)


# ================================================================ injections (hist coordinates; o = onset index)
def inj_spike(y, o, w, A, sgn):
    for i in range(o, min(len(y), o + w)):
        y[i] += sgn * A * (1.0 if i == o + w // 2 else 0.7)


def inj_step(y, o, A, sgn, ramp=1):
    for i in range(o, len(y)):
        y[i] += sgn * A * min(1.0, (i - o + 1) / ramp)


def inj_gradual(y, o, A, sgn):
    L = len(y) - o
    for i in range(o, len(y)):
        y[i] += sgn * A * (i - o + 1) / L


def inj_exp(y, o, A, r):
    L = len(y) - o
    for i in range(o, len(y)):
        y[i] += A * 1.4 * (math.exp(r * (i - o + 1) / L) - 1) / (math.exp(r) - 1)


def inj_osc(y, o, A, P, ph, square=False):
    for i in range(o, len(y)):
        s = math.sin(2 * math.pi * (i - o) / P + ph)
        y[i] += A * ((1.0 if s >= 0 else -1.0) if square else s)


def inj_throttle(y, o, A, top, rng, s0):
    n = len(y)
    rise = max(1, n - top - o)
    for i in range(o, n):
        y[i] += min(A * (i - o + 1) / rise, A)
    capv = max(y[n - top:])
    for i in range(n - top, n):
        y[i] = capv - abs(rng.gauss(0, 0.05 * s0))


def ramp_for(role, metric, A):
    r = TE.RATE.get((role, metric))
    return 1 if r is None or A <= 0.8 * r else int(math.ceil(A / (0.8 * r)))


# ================================================================ one example
class Ctx:
    def __init__(self, S, ends, roles, heldout, split, role, kthr, rng):
        self.S, self.ends, self.split, self.role, self.rng = S, ends, split, role, rng
        self.kthr = defaultdict(lambda: 99, kthr)
        nodes = roles[role]
        held = set(heldout.get(role, []))
        self.seen = [k for n, ks in nodes.items() if n not in held for k in ks if len(ends[k].get(split, [])) >= 48]
        self.unseen = [k for n, ks in nodes.items() if n in held for k in ks if len(ends[k].get(split, [])) >= 48] if split == "test" else []
        # D8: water test also draws held-out sensors' Sep-Oct windows (never in train/dev), tagged unseen_sepoct
        self.sepoct = ([k for n, ks in nodes.items() if n in held for k in ks if len(ends[k].get("dev", [])) >= 48]
                       if split == "test" and role in SEPOCT_ROLES else [])
        self.w = {k: math.sqrt(len(ends[k][split])) for k in self.seen + self.unseen}
        self.ws = {k: math.sqrt(len(ends[k]["dev"])) for k in self.sepoct}
        self.share = UNSEEN_SHARE_ROLE.get(role, UNSEEN_SHARE)
        self.cur = split

    def pick_key(self, ok):
        pool, w, tag, self.cur = self.seen, self.w, "seen", self.split
        if (self.unseen or self.sepoct) and self.rng.random() < self.share:
            if self.sepoct and (not self.unseen or self.rng.random() < 0.5):
                pool, w, tag, self.cur = self.sepoct, self.ws, "unseen_sepoct", "dev"
            else:
                pool, tag = self.unseen, "unseen"
        pool = [k for k in pool if ok(k)]
        if not pool:
            return None, tag
        return self.rng.choices(pool, weights=[w[k] for k in pool])[0], tag

    def base(self, key, n, need_hist=0):
        end = self.rng.choice(self.ends[key][self.cur])
        h = hist_at(self.S[key], end, max_miss=MAX_MISS.get(key[0], 6))
        if len(h) < max(n, need_hist) or split_of(end - (len(h) - 1) * STEP) != self.cur:
            return None, None
        return end, h


def quiet_history(role, metric, h, kthr):
    lv = V.long_view(role, metric, h)
    if lv:
        return False
    k, _, _ = V.excursions(role, metric, h)
    return k < kthr


def finish(ctx, key, tag, end, y, n, fam, sub, pattern, extra):
    """Build prompt + target for hist y; returns a row or None (validation failure / family rule not met)."""
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    y = [round(v, 4) for v in y[-V.HIST:]]  # stored as is, so the prompt can be rebuilt exactly (checks_v2)
    prompt, st, ev, info = V.agent_prompt(role, node, G.describe(node), metric, y, n, end)
    ex = dict(role=role, metric=metric, node=node, n=n, end_epoch=end, st=st, info=info, pattern=pattern,
              family=fam, rng=ctx.rng, xs=y[-n:], **extra)
    tgt, meta = TE.label(ex)
    if fam in ("routine", "real_routine") and not meta["routine"]:
        return None
    if fam == "routine" and tgt["status"] != "normal" and sub != "short_cycle":
        return None  # e.g. a synthetic refill that ran past the tank's high mark: that is water_fill's job
    if fam == "water_fill" and (tgt["status"] == "normal" or tgt["likely_cause"] not in WATER_FILL_CAUSE[sub]):
        return None
    if fam == "real_routine" and (tgt["status"] != "normal" or meta["fault_kind"]):
        return None
    if fam == "fault" and tgt["status"] != "sensor_fault":
        return None
    if fam not in ("fault",) and meta["fault_kind"] and not (pattern in ("flatline", "erratic")):
        return None  # a non-fault family that the fault rules read as a fault: ambiguous, skip
    if meta["small"] and (V.long_view(role, metric, y[-V.HIST:]) or []):
        return None  # a small change must not come with a 12 h finding
    validate(role, tgt, [e[0] for e in ev])
    comp = json.dumps(tgt, ensure_ascii=False) + "<|eot_id|>"
    return {"role": role, "node": node, "metric": metric, "split": ctx.split, "seen": tag, "end_epoch": end, "n": n,
            "hist_len": len(y[-V.HIST:]), "family": fam, "sub": sub, "pattern": tgt["pattern"], "status": tgt["status"],
            "likely_cause": tgt["likely_cause"], "fault_kind": tgt.get("fault_kind"), "event_active": tgt["event_active"],
            "onset": tgt["onset"], "confidence": tgt["confidence"], "size": round(extra["size"], 2) if extra.get("size") else None,
            "d": extra.get("d"), "small": meta["small"], "routine": meta["routine"],
            "hist": y, "prompt": prompt, "completion": comp}


def validate(role, t, eids):
    assert tuple(t) == tuple(k for k in V.KEY_ORDER if k in t), list(t)
    assert t["pattern"] in V.PATTERNS[role], (role, t["pattern"])
    assert t["status"] in V.STATUSES
    assert t["likely_cause"] in V.CAUSES[role], (role, t["likely_cause"])
    assert t["action"] in V.ROLE_ACTIONS.get(role, F.ACTIONS), (role, t["action"])
    assert 0 <= t["confidence"] <= 1
    assert isinstance(t["event_active"], bool)
    assert len(t["onset"]) == 5 and t["onset"][2] == ":"
    assert ("fault_kind" in t) == (t["status"] == "sensor_fault")
    if "fault_kind" in t:
        assert t["fault_kind"] in V.FAULT_KINDS
    assert 1 <= len(t["observations"]) <= 2
    for o in t["observations"]:
        ids = o[o.rindex("[") + 1:o.rindex("]")].split(",")
        assert ids and all(i in eids for i in ids), (o, eids)


# ---------------------------------------------------------------- family generators (return row or None)
def gen_stable(ctx, n):
    key, tag = ctx.pick_key(lambda k: True)
    if key is None:
        return None
    role, node, metric = key
    end, h = ctx.base(key, n)
    if h is None:
        return None
    xs = h[-n:]
    if G.is_zero_flat(xs) or not pcalm(role, metric, xs) or not quiet_history(role, metric, h, ctx.kthr[(role, metric)]):
        return None
    return finish(ctx, key, tag, end, h, n, "stable", "stable", "stable", {})


def calm_base(ctx, n, ok=lambda k: True, need_hist=0, end_ok=None):
    key, tag = ctx.pick_key(ok)
    if key is None:
        return None
    role, node, metric = key
    end, h = ctx.base(key, n, need_hist)
    if h is None or (end_ok and not end_ok(end)):
        return None
    xs = h[-n:]
    if G.is_zero_flat(xs) or not pcalm(role, metric, xs) or not quiet_history(role, metric, h, ctx.kthr[(role, metric)]):
        return None
    s0, bst = G.scale_of(role, metric, xs)
    return key, tag, end, list(h), s0, bst


def event_patterns(role):
    return [p for p in EVENT_PATTERNS if p != "erratic" or role == "power"]


def gen_event(ctx, n, pattern=None, fam="event", size=None):
    rng = ctx.rng
    role = ctx.role
    p = pattern or rng.choice(event_patterns(role))
    dmin = {"gradual_increase": 6, "gradual_decrease": 6, "exponential_increase": 6, "oscillation": 8,
            "throttling": 16, "erratic": 6}.get(p, 3)
    if n < dmin:
        return None
    b = calm_base(ctx, n)
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    H = len(y)
    d = sample_d(rng, n, dmin)
    o = H - d
    ow = n - d  # onset index in the window
    size = size or sample_size(rng)
    if p == "throttling":
        size = max(size, 4.0)
    A = size * s0
    extra = {"size": size, "d": d, "onset_idx": ow, "base_mean": bst["mean"]}
    if p in ("spike", "dip"):
        w = min(rng.randint(1, 3), d)
        inj_spike(y, o, w, A, 1 if p == "spike" else -1)
        extra["active"] = o + w - 1 >= H - 1
        extra["w"] = w
    elif p in ("step_increase", "step_decrease"):
        r = ramp_for(role, metric, A)
        if r > max(1, d - 2):
            return None
        inj_step(y, o, A, 1 if p == "step_increase" else -1, r)
        extra["ramp"] = r
    elif p in ("gradual_increase", "gradual_decrease"):
        inj_gradual(y, o, A, 1 if p == "gradual_increase" else -1)
    elif p == "exponential_increase":
        inj_exp(y, o, A, rng.uniform(3.0, 5.0))
    elif p == "oscillation":
        P = rng.uniform(8, 16)
        if d < P:
            return None
        inj_osc(y, o, A / 2, P, rng.uniform(0, 2 * math.pi))
    elif p == "throttling":
        top = rng.randint(10, min(22, d - 4))
        inj_throttle(y, o, A, top, rng, s0)
        extra["size"] = None if size < TE.BOUNDARY else size
    elif p == "erratic":
        for i in range(o, H):
            if rng.random() < 0.45:
                y[i] += rng.gauss(0, s0 * rng.uniform(3, 6))
        extra["size"] = None
    y = clamp(y, m)
    xs = y[-n:]
    if clamped_count(xs, m) > 4:
        return None
    st = F.compute_stats(xs, m["dec"])
    small = extra.get("size") is not None and extra["size"] < TE.BOUNDARY
    if p == "spike" and not (ow <= st["max_idx"] < ow + extra["w"]):
        return None
    if p == "dip" and not (ow <= st["min_idx"] < ow + extra["w"]):
        return None
    if p in ("step_increase", "step_decrease") and not (ow - 1 <= st["max_jump_idx"] <= ow + extra["ramp"]):
        return None
    if p == "oscillation" and not small and st["zero_cross"] < 4:
        return None
    if p == "throttling" and st["plateau_run"] < 6:
        return None
    if p == "erratic" and st["noise"] < 1.5 * bst["noise"]:
        return None
    return finish(ctx, key, tag, end, y, n, fam, p, p, extra)


def gen_old_shift(ctx, n):
    rng = ctx.rng
    b = calm_base(ctx, n, need_hist=V.LR_MIN_POINTS)
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    H = len(y)
    if H - 36 < 30:
        return None
    d = rng.randint(30, H - 36)
    size = sample_size(rng, 0.15, 4.0, 12.0)
    sgn = rng.choice((1, -1))
    p = "step_increase" if sgn > 0 else "step_decrease"
    r = ramp_for(role, metric, size * s0)
    inj_step(y, H - d, size * s0, sgn, r)
    y = clamp(y, m)
    if clamped_count(y[-n:], m) > 4:
        return None
    lv = {f["kind"] for f in (V.long_view(role, metric, y) or [])}
    ow = n - d
    if size >= TE.BOUNDARY and "level_shift" not in lv:
        if ow < 1:
            return None
        st = F.compute_stats(y[-n:], m["dec"])
        if not (ow - 1 <= st["max_jump_idx"] <= ow + r):
            return None
    extra = {"size": size, "d": d, "onset_idx": ow if ow >= 0 else None, "ramp": r, "base_mean": bst["mean"],
             "onset_time": V.idx_time(end, H, H - d)}
    return finish(ctx, key, tag, end, y, n, "old_shift", "old_shift", p, extra)


def gen_long_drift(ctx, n):
    rng = ctx.rng
    ok = lambda k: not (k[0] == "weather" and k[2] in ("temp", "rh"))
    b = calm_base(ctx, n, ok=ok, need_hist=V.LR_MIN_POINTS)
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    H = len(y)
    L = rng.randint(min(72, H), H)
    size = sample_size(rng, 0.15, 4.0, 12.0)
    sgn = rng.choice((1, -1))
    p = "gradual_increase" if sgn > 0 else "gradual_decrease"
    inj_gradual(y, H - L, size * s0, sgn)
    y = clamp(y, m)
    if clamped_count(y[-n:], m) > 4:
        return None
    lv = {f["kind"] for f in (V.long_view(role, metric, y) or [])}
    if size >= TE.BOUNDARY and "slow_drift" not in lv:
        return None
    extra = {"size": size, "d": L, "onset_idx": n - L, "base_mean": bst["mean"], "onset_time": V.idx_time(end, H, H - L)}
    return finish(ctx, key, tag, end, y, n, "long_drift", "long_drift", p, extra)


def gen_recurring(ctx, n):
    rng = ctx.rng
    ok = lambda k: ctx.kthr[(k[0], k[2])] <= 6
    b = calm_base(ctx, max(n, 48), ok=ok, need_hist=48)
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    H = len(y)
    kthr = ctx.kthr[(role, metric)]
    s_e = V.exc_scale(role, metric, y)
    k = rng.randint(kthr, kthr + 3)
    dl = rng.randint(1, min(n, 24))
    pos = [H - dl]
    tries = 0
    while len(pos) < k and tries < 200:
        tries += 1
        q = rng.randint(0, H - dl - 5)
        if all(abs(q - p_) >= 6 for p_ in pos):
            pos.append(q)
    if len(pos) < k:
        return None
    pos.sort()
    for q in pos:
        amp = s_e * rng.uniform(3.4, 4.6) * rng.choice((1, 1, 1, -1))
        y[q] += amp
        if rng.random() < 0.3 and q + 1 < H:
            y[q + 1] += 0.6 * amp
    if m["warn"] is not None and m["dir"] == "high" and max(y) >= m["warn"]:
        return None
    y = clamp(y, m)
    c, peak, ends_ = V.excursions(role, metric, y)
    if c < kthr:
        return None
    st = F.compute_stats(y[-n:], m["dec"])
    win_spike = (n - 1 - st["max_idx"]) == dl - 1 or (n - 1 - st["max_idx"]) == dl - 2
    extra = {"size": None, "d": H - pos[0], "onset_idx": None, "onset_time": V.idx_time(end, H, pos[0]),
             "active": dl <= 6, "window_spike": win_spike, "base_mean": bst["mean"]}
    return finish(ctx, key, tag, end, y, n, "recurring", "recurring", "spike", extra)


def fault_ok(kind, key):
    role, node, metric = key
    if kind == "bias":
        return (role, metric) in TE.RATE
    if kind == "calib_drift":
        return (role, metric) in TE.DRIFT_FAULT_METRICS and node.startswith("SR-")
    if kind == "noise_increase":
        return role != "power"
    if kind == "dropout":
        return (role, metric) in TE.DROPOUT_METRICS
    if kind == "saturation":
        return (role, metric) in TE.SATURATION_METRICS
    if kind == "stuck":
        return True
    if kind == "quantised":
        return True
    return False


def gen_fault(ctx, n, kind=None):
    rng = ctx.rng
    role = ctx.role
    kinds = [k for k in FAULT_KINDS_GEN if any(fault_ok(k, key) for key in ctx.seen)]
    if not kinds:
        return None
    kind = kind or rng.choices(kinds, weights=[FAULT_WEIGHTS[k] for k in kinds])[0]
    need = TE.DRIFT_MIN_PTS if kind == "calib_drift" else 0
    end_ok = (lambda e: F.is_off_hours(e)) if kind == "calib_drift" else None
    b = calm_base(ctx, n, ok=lambda k: fault_ok(kind, k), need_hist=need, end_ok=end_ok)
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    H = len(y)
    dmin = {"stuck": 6, "noise_increase": 6, "saturation": 8, "quantised": 12, "dropout": 3, "bias": 3}.get(kind, 3)
    if n < dmin:
        return None
    d = sample_d(rng, n, dmin)
    o = H - d
    ow = n - d
    keep = set()
    extra = {"size": None, "d": d, "onset_idx": ow, "base_mean": bst["mean"], "fault_hint": kind}
    if kind == "stuck":
        p = "flatline"
        for i in range(o, H):
            y[i] = y[o]
        if abs(y[o]) < 1e-6:
            return None
    elif kind == "bias":
        rate = TE.RATE[(role, metric)]
        A = max(1.6 * rate, rng.uniform(5, 12) * s0)
        sgn = rng.choice((1, -1))
        p = "step_increase" if sgn > 0 else "step_decrease"
        inj_step(y, o, A, sgn, 1)
        extra["ramp"] = 1
    elif kind == "calib_drift":
        sgn = rng.choice((1, -1))
        p = "gradual_increase" if sgn > 0 else "gradual_decrease"
        A = rng.uniform(12, 20) * s0  # must pass the tightened drift rule (teacher_v2.DRIFT_*)
        inj_gradual(y, 0, A, sgn)
        extra.update(d=H, onset_idx=n - H, onset_time=V.idx_time(end, H, 0))
    elif kind == "noise_increase":
        p = "erratic"
        mult = rng.uniform(2.0, 4.0)
        for i in range(o, H):
            y[i] += rng.gauss(0, s0 * mult)
    elif kind == "dropout":
        k = rng.randint(1, 4)
        idx = sorted(rng.sample(range(o, H), min(k, d)))
        if len(idx) >= 2 and max(idx) - min(idx) < 3:
            return None
        p = "dip" if len(idx) == 1 else "erratic"
        for i in idx:
            y[i] = 0.0
            keep.add(i)
        extra["active"] = idx[-1] == H - 1
        extra["w"] = 1
    elif kind == "saturation":
        p = "throttling"
        rail = m["hi"]
        r = rng.randint(3, max(3, min(12, d - 4)))
        start = y[o]
        for i in range(o, H):
            f = min(1.0, (i - o + 1) / r)
            y[i] = start + (rail - start) * f if f < 1 else rail
            if y[i] >= rail:
                keep.add(i)
        y = [min(v, rail) for v in y]
    elif kind == "quantised":
        p = "flatline"
        q = rng.uniform(3, 6) * s0
        for i in range(o, H):
            y[i] = round(y[i] / q) * q
    y = clamp(y, m, keep)
    xs = y[-n:]
    st = F.compute_stats(xs, m["dec"])
    if kind == "quantised" and st["flat_run"] < 6:
        return None
    if kind == "saturation" and (st["max"] < m["hi"] or st["plateau_run"] < 3):
        return None
    if kind == "bias" and not (st["max_jump_idx"] == ow and abs(st["max_jump_signed"]) > TE.RATE[(role, metric)]):
        return None
    if kind == "noise_increase" and st["noise"] < 1.8 * max(bst["noise"], 1e-9):
        return None
    if kind == "dropout" and st["min"] != 0.0:
        return None
    if kind == "calib_drift" and "slow_drift" not in {f["kind"] for f in (V.long_view(role, metric, y) or [])}:
        return None
    return finish(ctx, key, tag, end, y, n, "fault", kind, p, extra)


def gen_compound(ctx, n):
    rng = ctx.rng
    dom = rng.choice(("step_increase", "step_decrease", "gradual_increase", "gradual_decrease"))
    sec = rng.choice(("spike", "dip"))
    b = calm_base(ctx, n)
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    H = len(y)
    d = sample_d(rng, n, 6)
    o, ow = H - d, n - d
    size = rng.uniform(5, 12)
    sgn = 1 if dom.endswith("increase") else -1
    r = ramp_for(role, metric, size * s0)
    if dom.startswith("step"):
        if r > d - 2:
            return None
        inj_step(y, o, size * s0, sgn, r)
    else:
        inj_gradual(y, o, size * s0, sgn)
    q = rng.randint(H - n + 1, H - 2)
    if abs(q - o) <= 3:
        return None
    inj_spike(y, q, 1, rng.uniform(4, 8) * s0 + (size * s0 if (sec == "spike") != (sgn > 0) else 0), 1 if sec == "spike" else -1)
    y = clamp(y, m)
    xs = y[-n:]
    st = F.compute_stats(xs, m["dec"])
    qi = q - (H - n)
    if sec == "spike" and st["max_idx"] != qi or sec == "dip" and st["min_idx"] != qi:
        return None
    if dom.startswith("step") and not (ow - 1 <= st["max_jump_idx"] <= ow + r):
        return None
    extra = {"size": size, "d": d, "onset_idx": ow, "ramp": r, "secondary": sec, "base_mean": bst["mean"]}
    return finish(ctx, key, tag, end, y, n, "compound", dom + "+" + sec, dom, extra)


ROUTINES = {
    "water": ("refill_fast", "refill_slow", "drain_day", "pump_cycle", "short_cycle"),
    "power": ("load_cycle", "startup", "shutdown"),
    "air_quality": ("co2_occupancy", "co2_decay", "hvac_cycle", "outdoor_pm"),
    "weather": (),
}


def routine_ok(sub, key):
    role, node, metric = key
    return {"refill_fast": metric == "level", "refill_slow": metric == "level", "drain_day": metric == "level",
            "pump_cycle": metric in ("level", "flow"), "short_cycle": metric in ("level", "flow"),
            "load_cycle": metric == "power_kw" and not node.startswith("SL-"),
            "startup": metric == "power_kw" and not node.startswith("SL-"),
            "shutdown": metric == "power_kw" and not node.startswith("SL-"),
            "co2_occupancy": metric == "co2", "co2_decay": metric == "co2",
            "hvac_cycle": metric == "temp" and node.startswith("SR-"),
            "outdoor_pm": metric in ("pm25", "pm10") and node.startswith("AQ-")}[sub]


def gen_routine(ctx, n):
    rng = ctx.rng
    subs = [s for s in ROUTINES.get(ctx.role, ()) if any(routine_ok(s, k) for k in ctx.seen)]
    if not subs:
        return None
    sub = rng.choice(subs)
    b = calm_base(ctx, n, ok=lambda k: routine_ok(sub, k))
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    H = len(y)
    d = sample_d(rng, n, 8)
    o, ow = H - d, n - d
    size = rng.uniform(4, 12)
    A = size * s0
    extra = {"size": size, "d": d, "onset_idx": ow, "base_mean": bst["mean"]}
    hr = datetime.fromtimestamp(end, V.IST)
    if sub == "refill_fast":
        p = "step_increase"
        r = rng.randint(1, 3)
        inj_step(y, o, A, 1, r)
        extra["ramp"] = r
    elif sub == "refill_slow":
        p = "gradual_increase"
        inj_gradual(y, o, A, 1)
    elif sub == "drain_day":
        if F.is_off_hours(end):
            return None
        p = "gradual_decrease"
        inj_gradual(y, o, A, -1)
    elif sub in ("pump_cycle", "short_cycle", "load_cycle"):
        p = "oscillation"
        P = rng.uniform(12, 36) if sub == "pump_cycle" else (rng.uniform(4, 8) if sub == "short_cycle" else rng.uniform(6, 30))
        if d < 1.5 * P:
            d = min(n, int(1.5 * P) + 1)
            o, ow = H - d, n - d
            extra.update(d=d, onset_idx=ow)
        if d < 1.5 * P:
            return None
        inj_osc(y, o, A / 2, P, rng.uniform(0, 2 * math.pi), square=rng.random() < 0.6)
    elif sub in ("startup", "shutdown"):
        if hr.weekday() >= 5:
            return None
        lo_h, hi_h = (7.0, 10.5) if sub == "startup" else (17.0, 21.0)
        cand = [i for i in range(H - n + 1, H - 2) if lo_h <= TE._hm(V.idx_time(end, H, i)) <= hi_h]
        if not cand:
            return None
        o = rng.choice(cand)
        d = H - o
        ow = n - d
        p = "step_increase" if sub == "startup" else "step_decrease"
        A = rng.uniform(4, 12) * s0
        if sub == "shutdown":
            A = min(A, 0.85 * max(bst["mean"], 1e-9))
        inj_step(y, o, A, 1 if sub == "startup" else -1, 1)
        extra.update(d=d, onset_idx=ow, ramp=1, size=A / s0)
    elif sub == "co2_occupancy":
        p = rng.choice(("gradual_increase", "step_increase"))
        A = min(A, 0.9 * (m["warn"] - max(y[-n:])))
        if A < 4 * s0:
            return None
        r = max(3, ramp_for(role, metric, A))
        if p == "step_increase":
            inj_step(y, o, A, 1, r)
            extra["ramp"] = r
        else:
            inj_gradual(y, o, A, 1)
        extra["size"] = A / s0
    elif sub == "co2_decay":
        p = "gradual_decrease"
        inj_gradual(y, o, A, -1)
    elif sub == "hvac_cycle":
        p = "oscillation"
        P = rng.uniform(6, 16)
        amp = rng.uniform(0.3, 0.8)
        if d < 1.5 * P:
            return None
        inj_osc(y, o, amp, P, rng.uniform(0, 2 * math.pi), square=rng.random() < 0.3)
        extra["size"] = 2 * amp / s0
    elif sub == "outdoor_pm":
        p = rng.choice(("gradual_increase", "gradual_decrease"))
        if p == "gradual_increase" and m["warn"] is not None:
            A = min(A, 0.9 * (m["warn"] - max(y[-n:])))
            if A < 4 * s0:
                return None
        inj_gradual(y, o, A, 1 if p == "gradual_increase" else -1)
    y = clamp(y, m)
    xs = y[-n:]
    if clamped_count(xs, m) > 4:
        return None
    st = F.compute_stats(xs, m["dec"])
    if p.startswith("step") and not (ow - 1 <= st["max_jump_idx"] <= ow + extra.get("ramp", 1)):
        return None
    if p == "oscillation" and st["zero_cross"] < 3:
        return None
    if extra.get("size") is not None and extra["size"] < TE.BOUNDARY:
        extra["size"] = TE.BOUNDARY  # routine shapes are never boundary cases
    return finish(ctx, key, tag, end, y, n, "routine", sub, p, extra)


REAL_SHAPES = {"step_increase", "step_decrease", "gradual_increase", "gradual_decrease", "oscillation",
               "exponential_increase", "throttling"}


def gen_real_routine(ctx, n):
    key, tag = ctx.pick_key(lambda k: True)
    if key is None:
        return None
    role, node, metric = key
    end, h = ctx.base(key, n)
    if h is None:
        return None
    xs = h[-n:]
    if G.is_zero_flat(xs) or pcalm(role, metric, xs):
        return None
    p = rule_pattern_n(role, metric, xs, end)
    if p not in REAL_SHAPES:
        return None
    return finish(ctx, key, tag, end, list(h), n, "real_routine", "real_" + p, p, {"size": None, "d": None, "onset_idx": None})


def gen_real_longrange(ctx, n):
    ok = lambda k: not (k[0] == "weather" and k[2] in ("temp", "rh"))
    key, tag = ctx.pick_key(ok)
    if key is None:
        return None
    role, node, metric = key
    end, h = ctx.base(key, n, V.LR_MIN_POINTS)
    if h is None:
        return None
    xs = h[-n:]
    if G.is_zero_flat(xs) or not pcalm(role, metric, xs):
        return None
    lv = V.long_view(role, metric, h)
    if not lv:
        return None
    f = next((x for x in lv if x["kind"] == "level_shift"), lv[0])
    if f["kind"] == "level_shift":
        p = "step_increase" if f["delta"] > 0 else "step_decrease"
    else:
        p = "gradual_increase" if f["delta"] > 0 else "gradual_decrease"
    return finish(ctx, key, tag, end, list(h), n, "real_longrange", f["kind"], p, {"size": None, "d": None, "onset_idx": None})


WATER_FILL_CAUSE = {"overflow_fill": ("tank_overflow_risk",), "valve_stuck": ("fill_valve_stuck",),
                    "night_refills": ("possible_leak",)}


def gen_water_fill(ctx, n):
    """D2 abnormal fills on water level: overflow (fill past the node's TANK high mark), stuck valve (a fill
    running >= 2x the node's usual fill), repeated off-hours refills (sawtooth at night). Routine refills stay
    in the 'routine' family (tank_filling, normal)."""
    rng = ctx.rng
    made = ctx.__dict__.setdefault("wf_made", Counter())
    sub = min(WATER_FILL_CAUSE, key=lambda k: (made[k], rng.random()))  # keep the three kinds balanced
    ok = lambda k: k[2] == "level" and k[1] in V.NODE_LIMITS
    if sub == "valve_stuck":
        n = max(n, 48)
    b = calm_base(ctx, n, ok=ok, end_ok=(lambda e: F.is_off_hours(e)) if sub == "night_refills" else None)
    if b is None:
        return None
    key, tag, end, y, s0, bst = b
    role, node, metric = key
    m = V.METRICS[(role, metric)]
    tl = V.NODE_LIMITS[node]
    H = len(y)
    xs0 = y[-n:]
    extra = {"base_mean": bst["mean"], "size": None}
    if sub == "overflow_fill":
        d = sample_d(rng, n, 4)
        o = H - d
        target = tl["high"] + rng.uniform(0.02, 0.6) * max(tl["overflow"] - tl["high"], 2 * s0)
        A = target - y[o - 1]
        if A < 4 * s0:
            return None
        p = rng.choice(("step_increase", "gradual_increase"))
        r = rng.randint(1, 3) if p == "step_increase" else 1
        if p == "step_increase":
            inj_step(y, o, A, 1, r)
        else:
            inj_gradual(y, o, A, 1)
        extra.update(d=d, onset_idx=n - d, ramp=r, size=A / s0)
    elif sub == "valve_stuck":
        L = int(math.ceil(2 * tl["fill_min"] / 5)) + rng.randint(2, 24)
        if L > n:
            return None
        o = H - L
        room = tl["high"] - max(xs0)
        if room < 5 * s0:
            return None
        A = rng.uniform(0.5, 0.95) * room
        p = "gradual_increase"
        inj_gradual(y, o, A, 1)
        extra.update(d=L, onset_idx=n - L, size=A / s0)
    else:
        P = rng.uniform(12, 30)
        if n < int(2.5 * P):
            return None
        d = rng.randint(int(2.5 * P), n)
        o = H - d
        A = rng.uniform(5, 12) * s0
        if max(xs0) + A / 2 >= tl["high"]:
            return None
        p = "oscillation"
        ph = rng.uniform(0, 1)
        for i in range(o, H):  # sawtooth: slow drain over 80% of a cycle, fast refill over 20%
            f = ((i - o) / P + ph) % 1.0
            y[i] += A * (0.5 - f / 0.8) if f < 0.8 else A * (-0.5 + (f - 0.8) / 0.2)
        extra.update(d=d, onset_idx=n - d, size=A / s0)
    y = clamp(y, m)
    st = F.compute_stats(y[-n:], m["dec"])
    if p == "oscillation" and st["zero_cross"] < 3:
        return None
    if p == "step_increase" and not (extra["onset_idx"] - 1 <= st["max_jump_idx"] <= extra["onset_idx"] + extra["ramp"]):
        return None
    extra["size"] = None  # limit-based events, not noise-scaled (sizes would be 10-50x)
    row = finish(ctx, key, tag, end, y, n, "water_fill", sub, p, extra)
    if row:
        made[sub] += 1
    return row


def gen_zero_idle(ctx, n):
    ok = lambda k: k[2] in ("flow", "power_kw")
    key, tag = ctx.pick_key(ok)
    if key is None:
        return None
    end, h = ctx.base(key, n)
    if h is None or not G.is_zero_flat(h[-n:]):
        return None
    return finish(ctx, key, tag, end, list(h), n, "zero_idle", "zero_idle", "flatline", {"size": None, "zero": True})


GEN = {"water_fill": gen_water_fill, "stable": gen_stable, "event": gen_event, "recurring": gen_recurring, "old_shift": gen_old_shift,
       "long_drift": gen_long_drift, "fault": gen_fault, "compound": gen_compound, "routine": gen_routine,
       "real_routine": gen_real_routine, "real_longrange": gen_real_longrange, "zero_idle": gen_zero_idle}


def family_supported(ctx, fam):
    role = ctx.role
    keys = ctx.seen
    if fam == "water_fill":
        return any(k[2] == "level" and k[1] in V.NODE_LIMITS for k in keys)
    if fam == "zero_idle":
        return any(k[2] in ("flow", "power_kw") for k in keys)
    if fam == "routine":
        return bool(ROUTINES.get(role))
    if fam == "recurring":
        return any(ctx.kthr[(k[0], k[2])] <= 6 for k in keys)
    if fam == "real_longrange":
        return any(not (k[0] == "weather" and k[2] in ("temp", "rh")) for k in keys)
    return True


# ---------------------------------------------------------------- occupancy
def gen_occupancy_task(ctx, quota):
    rng = ctx.rng
    rows = []
    pats = list(F.OCC_PATTERNS)
    per = {p: quota // len(pats) for p in pats}
    for p in pats[: quota - sum(per.values())]:
        per[p] += 1
    made = Counter()
    tries = 0
    while sum(made.values()) < quota and tries < quota * 60:
        tries += 1
        n = sample_n(rng)
        key, tag = ctx.pick_key(lambda k: True)
        if key is None:
            break
        end, h = ctx.base(key, n)
        if h is None:
            continue
        h = [1.0 if v >= 0.5 else 0.0 for v in h]
        xs = h[-n:]
        p, st = TE.occ_label(xs, end, n)
        sub = "real"
        if made[p] >= per[p]:
            # top up a rarer class by editing the window of this real sequence (v1 approach)
            want = min(pats, key=lambda q: made[q] / max(1, per[q]))
            if made[want] >= per[want]:
                continue
            xs = edit_occ(want, n, rng)
            if want == "off_hours_presence":
                day = end - (end % 86400)
                end = day + rng.choice([17, 18, 19, 20, 21, 22]) * 3600 - 330 * 60 + rng.randint(0, 11) * STEP
                if split_of(end) != ctx.split:
                    continue
                end_h = hist_at(ctx.S[key], end)
                if len(end_h) < n:
                    continue
                h = [1.0 if v >= 0.5 else 0.0 for v in end_h]
            h = h[:-n] + xs
            p, st = TE.occ_label(xs, end, n)
            if p != want:
                continue
            sub = "edited"
        role, node, metric = key
        prompt, st, ev, info = V.agent_prompt(role, node, G.describe(node), metric, h, n, end)
        tgt = TE.occ_target(p, st, info, end, n, rng)
        try:
            validate(role, tgt, [e[0] for e in ev])
        except AssertionError:
            continue
        made[p] += 1
        rows.append({"role": role, "node": node, "metric": metric, "split": ctx.split, "seen": tag, "end_epoch": end, "n": n,
                     "hist_len": len(h[-V.HIST:]), "family": "occupancy", "sub": sub, "pattern": p, "status": tgt["status"],
                     "likely_cause": tgt["likely_cause"], "fault_kind": tgt.get("fault_kind"), "event_active": tgt["event_active"],
                     "onset": tgt["onset"], "confidence": tgt["confidence"], "size": None, "d": None, "small": False,
                     "routine": None, "hist": h[-V.HIST:], "prompt": prompt,
                     "completion": json.dumps(tgt, ensure_ascii=False) + "<|eot_id|>"})
    return rows, {"tries": tries, "made": dict(made)}


def edit_occ(p, n, rng):
    xs = [0.0] * n
    if p == "arrival":
        k = rng.randint(3, n - 3)
        xs = [0.0] * k + [1.0] * (n - k)
    elif p == "departure":
        k = rng.randint(3, n - 3)
        xs = [1.0] * k + [0.0] * (n - k)
    elif p == "intermittent":
        i = rng.randint(0, 6)
        flips = rng.randint(2, max(3, n // 8)) if rng.random() < 0.75 else rng.randint(n // 6, n // 3)
        for _ in range(flips):
            L = rng.randint(1, 5)
            xs[i:i + L] = [1.0] * len(xs[i:i + L])
            i += L + rng.randint(1, 5)
            if i >= n:
                break
    elif p == "occupied":
        xs = [1.0] * n
        if rng.random() < 0.4:
            xs[rng.randint(3, n - 3)] = 0.0
    elif p == "off_hours_presence":
        k = rng.randint(3, n - 3)
        xs = [0.0] * k + [1.0] * (n - k) if rng.random() < 0.5 else [1.0] * k + [0.0] * (n - k)
    return xs


# ================================================================ tasks
G_S = G_ENDS = G_ROLES = None
G_ROLE = None
G_CACHE = None


def _init(cache):
    global G_CACHE
    G_CACHE = cache
    HA.register()


def _load_role(role):
    """Workers hold ONE role's series at a time (memory: 16 GB laptop, several workers)."""
    global G_S, G_ENDS, G_ROLES, G_ROLE
    if G_ROLE == role:
        return
    G_S = G_ENDS = G_ROLES = None
    p = G_CACHE.parent / f"series_{role}.pkl"
    if p.exists():
        with open(p, "rb") as fh:
            G_S = pickle.load(fh)
    else:
        G_S = {}
    G_ROLES, G_ENDS = node_index(G_S)
    G_ROLE = role


def family_quotas(ctx, quota):
    fams = [f for f in MIX if family_supported(ctx, f)]
    tot = sum(MIX[f] for f in fams)
    q = {f: int(round(quota * MIX[f] / tot)) for f in fams}
    q["event"] += quota - sum(q.values())
    return q


def run_task(args):
    split, role, quota, seed, heldout, kthr, shard, limits = args
    V.NODE_LIMITS.clear()
    V.NODE_LIMITS.update(limits)
    t0 = time.time()
    rng = random.Random(f"{seed}|{split}|{role}")
    _load_role(role)
    ctx = Ctx(G_S, G_ENDS, G_ROLES, heldout, split, role, kthr, rng)
    stats = {"split": split, "role": role, "quota": quota}
    if role == "hvac":
        rows, st = HA.make_examples(ctx, quota, sample_n, sample_d, validate)
        stats.update(st)
    elif role == "occupancy":
        rows, st = gen_occupancy_task(ctx, quota)
        stats.update(st)
    else:
        rows = []
        fq = family_quotas(ctx, quota)
        stats["family_quota"] = fq
        made, tries, rej = Counter(), Counter(), Counter()
        short = 0
        for fam, q in fq.items():
            while made[fam] < q and tries[fam] < q * (1000 if split == "test" else 80) + 200:
                tries[fam] += 1
                n = sample_n(rng)
                try:
                    r = GEN[fam](ctx, n)
                except AssertionError as e:
                    rej["assert:" + fam] += 1
                    r = None
                if r is None:
                    continue
                rows.append(r)
                made[fam] += 1
            short += q - made[fam]
        # shortfall goes to the event family
        tr = 0
        while short > 0 and tr < short * (500 if split == "test" else 80) + 200:
            tr += 1
            r = gen_event(ctx, sample_n(rng))
            if r:
                rows.append(r)
                made["event_topup"] += 1
                short -= 1
        stats.update(made=dict(made), tries=dict(tries), rejected_asserts=dict(rej), unfilled=short)
    # deterministic ids + order
    rng.shuffle(rows)
    for i, r in enumerate(rows):
        r["id"] = f"{split}-{role}-{i:05d}"
    stats["seconds"] = round(time.time() - t0, 1)
    tmp = Path(str(shard) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, shard)
    Path(str(shard) + ".done").write_text(json.dumps(stats))
    return stats


def tank_limits(S):
    """Per water-level node, from TRAIN months only (D2): high = p99 of readings, overflow = max reading, usual fill =
    p90 duration of fills (rises of the 3-point median by > 1/4 floor per reading, one pause allowed, total rise
    >= 5x floor), rounded up to 5 min, at least 30 min. Shown in the prompt's TANK line."""
    out = {}
    for (role, node, metric), s in sorted(S.items()):
        if (role, metric) != ("water", "level"):
            continue
        bs = sorted(b for b in s if split_of(b) == "train")
        if len(bs) < 288:
            continue
        v = sorted(s[b] for b in bs)
        floor = V.METRICS[(role, metric)]["floor"]
        med = {}
        for i in range(1, len(bs) - 1):
            if bs[i + 1] - bs[i - 1] == 600:
                med[bs[i]] = sorted((s[bs[i - 1]], s[bs[i]], s[bs[i + 1]]))[1]
        runs, cur, rise, pause = [], 0, 0.0, 0
        mb = sorted(med)
        for a_, b_ in zip(mb, mb[1:]):
            dlt = med[b_] - med[a_] if b_ - a_ == STEP else None
            if dlt is not None and dlt > 0.25 * floor:
                cur, rise, pause = cur + 1, rise + dlt, 0
            elif dlt is not None and cur and not pause and dlt > -0.25 * floor:
                cur, pause = cur + 1, 1
            else:
                if cur and rise >= 5 * floor:
                    runs.append(cur)
                cur, rise, pause = 0, 0.0, 0
        runs.sort()
        p90 = runs[int(0.9 * (len(runs) - 1))] * 5 if runs else 30
        dec = V.METRICS[(role, metric)]["dec"]
        out[node] = {"high": round(v[int(0.99 * (len(v) - 1))], dec), "overflow": round(v[-1], dec),
                     "fill_min": max(30, int(math.ceil(p90 / 5) * 5)), "fills_seen": len(runs)}
        if out[node]["overflow"] <= out[node]["high"]:
            out[node]["overflow"] = round(out[node]["high"] + 10 ** -dec, dec)
    return out


def compute_kthr(S, ends, roles, heldout, seed):
    """E10 threshold per (role, metric): above the 95th percentile of excursion counts on calm TRAIN bases."""
    rng = random.Random(f"{seed}|kthr")
    out, dist = {}, {}
    by = defaultdict(list)
    for role, nodes in roles.items():
        if role in ("occupancy", "hvac"):
            continue
        for node, ks in nodes.items():
            if node in heldout.get(role, []):
                continue
            for k in ks:
                if ends[k].get("train"):
                    by[(role, k[2])].append(k)
    for rm, ks in sorted(by.items()):
        cnt = []
        tries = 0
        while len(cnt) < 300 and tries < 6000:
            tries += 1
            k = rng.choice(ks)
            e = rng.choice(ends[k]["train"])
            h = hist_at(S[k], e, max_miss=MAX_MISS.get(rm[0], 6))
            if len(h) < 144 or G.is_zero_flat(h[-48:]) or not pcalm(rm[0], rm[1], h[-48:]):
                continue
            cnt.append(V.excursions(rm[0], rm[1], h)[0])
        if not cnt:
            out[rm] = 99
            continue
        cnt.sort()
        p95 = cnt[int(0.95 * (len(cnt) - 1))]
        out[rm] = max(3, p95 + 1)
        dist[f"{rm[0]}/{rm[1]}"] = {"n": len(cnt), "p50": cnt[len(cnt) // 2], "p95": p95, "thr": out[rm]}
    return out, dist


# ================================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DATA / "sft_v2"))
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--scale", type=float, default=1.0, help="multiply all quotas (smoke runs)")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    out = Path(a.out)
    if a.scale != 1.0 and a.out == str(DATA / "sft_v2"):
        out = DATA / "sft_v2_smoke"
    (out / "shards").mkdir(parents=True, exist_ok=True)
    cache = DATA / "sft_v2" / "cache" / "series.pkl"
    S = load_all(cache)
    HA.register()
    roles, ends = node_index(S)
    for role in roles:
        rp = cache.parent / f"series_{role}.pkl"
        if not rp.exists():
            with open(rp, "wb") as fh:
                pickle.dump({k: v for k, v in S.items() if k[0] == role}, fh, protocol=pickle.HIGHEST_PROTOCOL)
    heldout = choose_heldout(roles, ends, a.seed)
    print("held-out nodes:", json.dumps(heldout), flush=True)
    kp = out / "kthr.json"
    if kp.exists() and not a.force:
        kj = json.loads(kp.read_text())
        kthr = {tuple(k.split("/")): v["thr"] for k, v in kj.items()}
        kdist = kj
    else:
        kthr, kdist = compute_kthr(S, ends, roles, heldout, a.seed)
        kp.write_text(json.dumps(kdist, indent=1))
    kthr = defaultdict(lambda: 99, kthr)
    print("E10 thresholds:", {k: v["thr"] for k, v in kdist.items()}, flush=True)
    limits = tank_limits(S)
    (out / "node_limits.json").write_text(json.dumps(limits, indent=1))
    V.NODE_LIMITS.update(limits)
    print("tank limits:", limits, flush=True)
    del S, roles, ends
    TE.build_calibration()
    cfg = {"version": VERSION, "seed": a.seed, "scale": a.scale, "quota": QUOTA, "mix": MIX, "heldout": heldout,
           "kthr": {f"{k[0]}/{k[1]}": v for k, v in kthr.items()}, "hvac": HA.status(), "node_limits": limits,
           "teacher_sha": hashlib.sha256((HERE / "teacher_v2.py").read_bytes() + (HERE / "templates_v2.py").read_bytes()
                                         + (HERE / "features_v2.py").read_bytes() + (HERE / "generate_v2.py").read_bytes()).hexdigest()[:16]}
    cfg_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]
    tasks = []
    for split in ("train", "dev", "test"):
        for role in V.ROLES + ([] if "hvac" in V.ROLES else ["hvac"]):
            q = int(round(QUOTA[split][role] * a.scale))
            shard = out / "shards" / f"{split}_{role}.jsonl"
            done = Path(str(shard) + ".done")
            if not a.force and shard.exists() and done.exists() and json.loads(done.read_text()).get("cfg") == cfg_hash:
                print(f"reuse shard {shard.name}", flush=True)
                continue
            tasks.append((split, role, q, a.seed, heldout, dict(kthr), shard, limits))
    print(f"{len(tasks)} tasks on {a.workers} workers", flush=True)
    if tasks:
        with ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(cache,)) as ex:
            for st in ex.map(run_task, tasks):
                done = Path(str(out / "shards" / f"{st['split']}_{st['role']}.jsonl") + ".done")
                st["cfg"] = cfg_hash
                done.write_text(json.dumps(st))
                print(f"  {st['split']}/{st['role']}: {sum(v for k, v in st.get('made', {}).items())} rows "
                      f"in {st['seconds']}s unfilled={st.get('unfilled', 0)}", flush=True)
    gen_s = time.time() - t0
    write_outputs(out, cfg, cfg_hash, heldout, kdist, gen_s, a)
    print(f"done in {(time.time() - t0) / 60:.1f} min", flush=True)


def write_outputs(out, cfg, cfg_hash, heldout, kdist, gen_s, a):
    splits = {}
    task_stats = []
    for split in ("train", "dev", "test"):
        rows, seen = [], set()
        dups = 0
        for role in V.ROLES + ([] if "hvac" in V.ROLES else ["hvac"]):
            sp = out / "shards" / f"{split}_{role}.jsonl"
            if not sp.exists():
                continue
            task_stats.append(json.loads(Path(str(sp) + ".done").read_text()))
            for l in open(sp, encoding="utf-8"):
                r = json.loads(l)
                h = hashlib.sha256(r["prompt"].encode()).hexdigest()
                if h in seen:
                    dups += 1
                    continue
                seen.add(h)
                rows.append(r)
        random.Random(f"{a.seed}|{split}|final").shuffle(rows)
        splits[split] = (rows, dups)
    tok = None
    try:
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(str(TOKENIZER))
    except Exception as e:  # noqa: BLE001
        print("tokenizer unavailable:", e)
    man = {"version": VERSION, "created": datetime.now().isoformat(timespec="seconds"), "config_hash": cfg_hash,
           "seed": a.seed, "scale": a.scale, "generation_seconds": round(gen_s, 1), "heldout_nodes": heldout,
           "e10_thresholds": kdist, "hvac": cfg["hvac"], "calibration": "training/v2/calibration.json",
           "quota": QUOTA, "mix_weights": MIX, "splits": {}, "tasks": task_stats}
    for split, (rows, dups) in splits.items():
        if tok:
            P = tok.encode_batch([r["prompt"] for r in rows], add_special_tokens=False)
            C = tok.encode_batch([r["completion"] for r in rows], add_special_tokens=False)
            gens = []
            for r in rows:
                c = r["completion"]
                cut = c.find(', "action"')
                gens.append(c[len(PREFILL):cut if cut >= 0 else len(c)])
            Gt = tok.encode_batch(gens, add_special_tokens=False)
            for r, p, c, g in zip(rows, P, C, Gt):
                r["prompt_tokens"], r["completion_tokens"], r["gen_tokens"] = len(p.ids), len(c.ids), len(g.ids)
        path = out / f"{split}.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        man["splits"][split] = summarize(rows, dups, path)
    for st in task_stats:
        if st.get("role") == "hvac" and st.get("heldout_units") is not None:
            man["heldout_nodes"]["hvac"] = st["heldout_units"]
    (out / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    print(json.dumps({s: {"n": v["n"], "sha256_16": v["sha256_16"]} for s, v in man["splits"].items()}), flush=True)


def tstats(v):
    if not v:
        return None
    v = sorted(v)
    return {"mean": round(sum(v) / len(v), 1), "p50": v[len(v) // 2], "p95": v[int(0.95 * (len(v) - 1))], "max": v[-1]}


def summarize(rows, dups, path):
    s = {"n": len(rows), "duplicates_dropped": dups,
         "sha256_16": hashlib.sha256(path.read_bytes()).hexdigest()[:16],
         "roles": Counter(r["role"] for r in rows), "families": Counter(r["family"] for r in rows),
         "role_family": Counter(f"{r['role']}/{r['family']}" for r in rows),
         "patterns": Counter(f"{r['role']}/{r['pattern']}" for r in rows),
         "status": Counter(r["status"] for r in rows), "fault_kind": Counter(r["fault_kind"] for r in rows if r["fault_kind"]),
         "event_active": Counter(str(r["event_active"]) for r in rows), "seen": Counter(r["seen"] for r in rows),
         "window_n": Counter(r["n"] for r in rows), "small_boundary": sum(1 for r in rows if r["small"]),
         "routine": Counter(r["routine"] for r in rows if r["routine"]),
         "confidence": Counter(r["confidence"] for r in rows),
         "nodes": Counter(r["node"] for r in rows)}
    if rows and "prompt_tokens" in rows[0]:
        s["tokens"] = {"prompt": tstats([r["prompt_tokens"] for r in rows]),
                       "completion": tstats([r["completion_tokens"] for r in rows]),
                       "generated_until_action": tstats([r["gen_tokens"] for r in rows]),
                       "by_window": {}}
        byn = defaultdict(list)
        for r in rows:
            byn[r["n"]].append(r)
        for n in sorted(byn):
            R = byn[n]
            s["tokens"]["by_window"][n] = {"n": len(R), "prompt": tstats([r["prompt_tokens"] for r in R]),
                                          "gen": tstats([r["gen_tokens"] for r in R])}
    return s


if __name__ == "__main__":
    main()
