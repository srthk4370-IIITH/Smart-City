"""v2 top-up dataset: replay of the original v2 train set + targeted rows for the device-eval weak cases.

Targeted rows are made by the EXISTING v2 generator (generate_v2.gen_* + teacher_v2.label through
generate_v2.finish), from the existing series caches (no new raw data), with the original held-out nodes,
E10 thresholds and tank limits. Only the sampling of age (d), window length (n), size and pattern is steered.
Train rows: train months (Jan-Aug) only; targeted dev rows: dev months (Sep-Oct) only; test months never read.

Weak cases (proofs/2026-10-21_v2_research/accuracy): exponential_increase read as gradual_increase at long ages
(power/water), spike read as stable on power bases whose E10 shows 2-9 recent excursions, erratic misread
(power events; air_quality/water erratic = noise sensor fault, frozen teacher semantics), water flow that
stops at 0 after a decline read as gradual_decrease (labelled flatline + idle, as v1/v2 do for a zero flatline),
power role overall at refinement ages.

  python gen_topup.py --out ~/smartcity_runs/agents_v2_topup/data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import random
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
V2 = HERE.parent
sys.path.insert(0, str(V2))
sys.path.insert(0, str(V2.parent))
import features_v2 as V  # noqa: E402
import generate_v2 as GV  # noqa: E402
import generate_dataset as G  # noqa: E402
import hvac_adapter as HA  # noqa: E402
import teacher_v2 as TE  # noqa: E402

SRC = GV.DATA / "sft_v2"
E10 = re.compile(r"recent episodes: (\d+|no) excursion")
REPLAY_N = 4350          # ~68% of 6400 rows = 400 optimizer steps x 16
SEED = 4494


# ---------------------------------------------------------------- steering of n / d
def pick_n(rng, lo=24):
    r = rng.random()
    if r < 0.30:
        n = 48
    elif r < 0.55:
        n = 96
    elif r < 0.80:
        n = 144
    else:
        n = rng.choice([x for x in V.LENGTHS if x not in (48, 96, 144)])
    return max(n, lo) if max(n, lo) in V.LENGTHS else 48


def d_long(rng, n, dmin=3):
    """refinement ages: 60% at the app's refinement placements (18/24/30/36 readings), else 12..min(n, 72)."""
    if rng.random() < 0.6:
        d = rng.choice((18, 24, 30, 36))
    else:
        d = rng.randint(12, max(12, min(n, 72)))
    return max(dmin, min(n, d))


def d_mixed(rng, n, dmin=3):
    """30% young (4..12), 70% refinement ages."""
    if rng.random() < 0.3:
        return max(dmin, min(n, rng.randint(4, 12)))
    return d_long(rng, n, dmin)


class steer:
    """Temporarily replaces generate_v2.sample_d (used inside gen_event / gen_fault) and sample_size."""

    def __init__(self, dfun=None, small_p=None, lo=None, hi=None):
        self.dfun, self.small_p, self.lo, self.hi = dfun, small_p, lo, hi

    def __enter__(self):
        self.d0, self.s0 = GV.sample_d, GV.sample_size
        if self.dfun:
            GV.sample_d = self.dfun
        if self.small_p is not None:
            sp, lo, hi, base = self.small_p, self.lo, self.hi, self.s0
            GV.sample_size = lambda rng, small_p=0.2, lo_=3.0, hi_=12.0: base(rng, sp, lo or lo_, hi or hi_)
        return self

    def __exit__(self, *a):
        GV.sample_d, GV.sample_size = self.d0, self.s0


def e10_count(prompt):
    m = E10.search(prompt)
    if not m:
        return None
    return 0 if m.group(1) == "no" else int(m.group(1))


# ---------------------------------------------------------------- targeted generators
def ev(pattern, dfun, small_p=0.10, lo=3.0, hi=12.0, metric=None, e10=None):
    def f(ctx, n):
        if metric:
            ok0 = ctx.seen
            ctx.seen = [k for k in ok0 if k[2] in metric]
        try:
            with steer(dfun, small_p, lo, hi):
                r = GV.gen_event(ctx, n, pattern=pattern)
        finally:
            if metric:
                ctx.seen = ok0
        if r and e10 and not (e10[0] <= (e10_count(r["prompt"]) or 0) <= e10[1]):
            return None
        return r
    return f


def stable_e10(lo, hi):
    def f(ctx, n):
        r = GV.gen_stable(ctx, n)
        if r and not (lo <= (e10_count(r["prompt"]) or 0) <= hi):
            return None
        return r
    return f


def fault(kind, dfun, metric=None):
    def f(ctx, n):
        if metric:
            ok0 = ctx.seen
            ctx.seen = [k for k in ok0 if k[2] in metric]
        try:
            with steer(dfun):
                return GV.gen_fault(ctx, n, kind=kind)
        finally:
            if metric:
                ctx.seen = ok0
    return f


def gen_zero_stop(ctx, n):
    """Water flow that declines and then reads exactly 0 for the last d readings (the pump/valve stopped).
    Labelled by the teacher as a zero flatline (pattern flatline, idle -> normal), the same semantics as v1's
    make_example (flatline with last == 0 -> zero) and v2's zero_idle family."""
    rng = ctx.rng
    b = flow_base(ctx, n)
    if b is None:
        return None
    key, tag, end, y, d, s0, bst = b
    H = len(y)
    o = H - d
    k = rng.randint(2, 12)  # decline before the stop
    if n - d - k < 6:
        return None
    v0 = y[o - k - 1]
    if v0 <= max(2 * s0, 1e-2):
        return None
    for j in range(k):
        y[o - k + j] = max(0.0, v0 * (1 - (j + 1) / (k + 1)) + rng.gauss(0, 0.2 * s0))
    for i in range(o, H):
        y[i] = 0.0
    xs = y[-n:]
    if G.is_zero_flat(xs) or max(xs[: n - d]) <= 0:
        return None
    extra = {"size": None, "d": d, "onset_idx": n - d, "base_mean": bst["mean"], "zero": True}
    return GV.finish(ctx, key, tag, end, y, n, "zero_stop", "zero_stop", "flatline", extra)


def flow_base(ctx, n):
    """A real water-flow window with a non-zero, non-flat part before the onset. Flow is rarely calm by the v1
    definition (train months: ~16 calm 4 h windows), so unlike calm_base the pre-onset data is taken as it is."""
    rng = ctx.rng
    key, tag = ctx.pick_key(lambda k: k[2] == "flow")
    if key is None:
        return None
    end, h = ctx.base(key, n)
    if h is None:
        return None
    d = d_long(rng, n, 8) if rng.random() < 0.8 else max(8, min(n, rng.randint(8, 12)))
    pre = h[-n:][: n - d]
    if len(pre) < 12 or G.is_zero_flat(pre) or sum(1 for v in pre if v > 1e-6) < 0.7 * len(pre):
        return None
    s0, bst = G.scale_of(key[0], key[2], pre)
    return key, tag, end, list(h), d, s0, bst


def gen_stuck_flow(ctx, n):
    """Non-zero stuck water-flow meter (teacher: flatline, sensor_fault/stuck), as generate_v2.gen_fault 'stuck'
    but on a real (not necessarily calm) flow base."""
    b = flow_base(ctx, n)
    if b is None:
        return None
    key, tag, end, y, d, s0, bst = b
    H = len(y)
    o = H - d
    if abs(y[o]) < 1e-6:
        return None
    for i in range(o, H):
        y[i] = y[o]
    m = V.METRICS[(key[0], key[2])]
    st = V.F.compute_stats(y[-n:], m["dec"])
    if st["flat_run"] < 6:
        return None
    extra = {"size": None, "d": d, "onset_idx": n - d, "base_mean": bst["mean"], "fault_hint": "stuck"}
    return GV.finish(ctx, key, tag, end, y, n, "fault", "stuck", "flatline", extra)


def buckets():
    """(name, role, train_rows, generator). dev rows = ~12% of train rows (min 12)."""
    B = []
    # 1. exponential_increase at refinement ages (+ young for balance) and the gradual contrast at the same ages
    B += [("exp_long_power", "power", 230, ev("exponential_increase", d_mixed, metric=("power_kw",))),
          ("exp_long_water", "water", 190, ev("exponential_increase", d_mixed)),
          ("exp_long_aq", "air_quality", 80, ev("exponential_increase", d_long)),
          ("grad_inc_long_power", "power", 80, ev("gradual_increase", d_long, metric=("power_kw",))),
          ("grad_inc_long_water", "water", 60, ev("gradual_increase", d_long)),
          ("grad_inc_long_aq", "air_quality", 70, ev("gradual_increase", d_long)),
          ("grad_dec_long_power", "power", 50, ev("gradual_decrease", d_long)),
          ("grad_dec_long_aq", "air_quality", 40, ev("gradual_decrease", d_long))]
    # 2. spikes on bases that already show recurring excursions (E10 2..9), and calm contrast with the same E10
    B += [("spike_e10_power", "power", 300, ev("spike", d_mixed, lo=4.0, e10=(2, 9))),
          ("spike_e10_water", "water", 60, ev("spike", d_mixed, lo=4.0, e10=(2, 9))),
          ("stable_e10_power", "power", 120, stable_e10(2, 9))]
    # 3. erratic: power events; air_quality / water = noise sensor fault (teacher semantics outside power)
    B += [("erratic_power", "power", 260, ev("erratic", d_mixed)),
          ("erratic_aq", "air_quality", 110, ev("erratic", d_mixed)),
          ("erratic_water", "water", 110, ev("erratic", d_mixed))]
    # 4. water flow stopping at 0 after a decline (+ non-zero stuck flow for contrast)
    B += [("zero_stop_water", "water", 100, gen_zero_stop),
          ("stuck_flow_water", "water", 50, gen_stuck_flow)]
    # 5. power at refinement ages, remaining event patterns
    for p, q in (("dip", 40), ("oscillation", 50), ("step_increase", 30), ("step_decrease", 30), ("throttling", 30)):
        B.append((f"{p}_long_power", "power", q, ev(p, d_long)))
    return B


# ---------------------------------------------------------------- driver
def load_role(role):
    with open(SRC / "cache" / f"series_{role}.pkl", "rb") as fh:
        S = pickle.load(fh)
    roles, ends = GV.node_index(S)
    return S, roles, ends


def make(out, split, heldout, kthr, test_hashes, seen_hashes, tscale=1.0):
    rows, stats = [], {}
    cache = {}
    for name, role, q, fn in buckets():
        quota = max(1, int(round(q * tscale))) if split == "train" else max(12, int(round(q * 0.12)))  # dev quotas never scaled
        if role not in cache:
            cache[role] = load_role(role)
        S, roles, ends = cache[role]
        rng = random.Random(f"{SEED}|topup|{split}|{name}")
        ctx = GV.Ctx(S, ends, roles, heldout, split, role, kthr, rng)
        made, tries, rej = 0, 0, Counter()
        t0 = time.time()
        while made < quota and tries < quota * 400:
            tries += 1
            n = pick_n(rng)
            try:
                r = fn(ctx, n)
            except AssertionError:
                rej["assert"] += 1
                continue
            if r is None:
                continue
            h = hashlib.sha256(r["prompt"].encode()).hexdigest()
            if h in test_hashes or h in seen_hashes:
                rej["dup"] += 1
                continue
            seen_hashes.add(h)
            r["topup_bucket"] = name
            r["id"] = f"topup-{split}-{name}-{made:04d}"
            rows.append(r)
            made += 1
        stats[name] = {"role": role, "quota": quota, "made": made, "tries": tries, "rejected": dict(rej),
                       "seconds": round(time.time() - t0, 1)}
        print(f"  {split}/{name}: {made}/{quota} in {tries} tries, {time.time() - t0:.1f}s", flush=True)
    return rows, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--replay", type=int, default=REPLAY_N)
    ap.add_argument("--target-scale", type=float, default=1.0, help="multiply the targeted TRAIN quotas")
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    man0 = json.loads((SRC / "manifest.json").read_text())
    heldout = {k: v for k, v in man0["heldout_nodes"].items()}
    kj = json.loads((SRC / "kthr.json").read_text())
    kthr = defaultdict(lambda: 99, {tuple(k.split("/")): v["thr"] for k, v in kj.items()})
    V.NODE_LIMITS.update(json.loads((SRC / "node_limits.json").read_text()))
    HA.register()
    TE.build_calibration()

    def rows_of(p):
        return [json.loads(l) for l in open(p, encoding="utf-8")]

    orig_train, orig_dev = rows_of(SRC / "train.jsonl"), rows_of(SRC / "dev.jsonl")
    test_hashes = {hashlib.sha256(json.loads(l)["prompt"].encode()).hexdigest() for l in open(SRC / "test.jsonl", encoding="utf-8")}
    seen = {hashlib.sha256(r["prompt"].encode()).hexdigest() for r in orig_train + orig_dev}

    tgt_train, st_train = make(out, "train", heldout, kthr, test_hashes, seen, a.target_scale)
    tgt_dev, st_dev = make(out, "dev", heldout, kthr, test_hashes, seen)

    # replay: stratified by role (proportional to the original train mix), random within role
    rng = random.Random(f"{SEED}|replay")
    by = defaultdict(list)
    for r in orig_train:
        by[r["role"]].append(r)
    tot = len(orig_train)
    replay = []
    for role in sorted(by):
        k = int(round(a.replay * len(by[role]) / tot))
        replay += rng.sample(by[role], k)
    for r in replay:
        r["topup_bucket"] = "replay"
    train = replay + tgt_train
    random.Random(f"{SEED}|shuffle").shuffle(train)

    def dump(name, rows):
        p = out / name
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return {"n": len(rows), "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16]}

    sp = {"train": dump("train.jsonl", train), "dev_target": dump("dev_target.jsonl", tgt_dev)}
    # the ORIGINAL dev set is used as is for the forgetting check (copied for a self-contained run dir)
    shutil.copyfile(SRC / "dev.jsonl", out / "dev.jsonl")  # byte-identical
    sp["dev"] = {"n": len(orig_dev), "sha256_16": hashlib.sha256((out / "dev.jsonl").read_bytes()).hexdigest()[:16]}
    gen_hash = hashlib.sha256(b"".join((V2 / f).read_bytes() for f in
                                       ("generate_v2.py", "teacher_v2.py", "templates_v2.py", "features_v2.py"))).hexdigest()[:16]
    man = {"what": "v2 top-up LoRA data: replay of the original v2 train set + targeted weak-case rows",
           "created": datetime.now().isoformat(timespec="seconds"), "seed": SEED, "args": {"replay": a.replay, "target_scale": a.target_scale},
           "source_dataset": {"dir": str(SRC), "config_hash": man0["config_hash"], "splits": {k: v["sha256_16"] for k, v in man0["splits"].items()}},
           "generator_files_sha256_16": gen_hash, "gen_topup_sha256_16": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16],
           "heldout_nodes": heldout, "splits": sp,
           "train_mix": {"replay": len(replay), "targeted": len(tgt_train), "replay_share": round(len(replay) / len(train), 3),
                         "replay_roles": Counter(r["role"] for r in replay), "targeted_roles": Counter(r["role"] for r in tgt_train)},
           "buckets": {"train": st_train, "dev_target": st_dev},
           "steering": {"n": "48 30%, 96 25%, 144 25%, other 24..144 step 6 20%",
                        "d_long": "60% in {18,24,30,36}, else uniform 12..min(n,72)", "d_mixed": "30% 4..12, 70% d_long",
                        "size": "generate_v2.sample_size with small_p 0.10 (spikes: 4..12x noise)"},
           "seconds": round(time.time() - t0, 1)}
    (out / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    print(json.dumps({"splits": sp, "mix": man["train_mix"]}, indent=1, default=str))


if __name__ == "__main__":
    main()
