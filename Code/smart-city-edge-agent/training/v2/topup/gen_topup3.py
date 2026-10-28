"""v2 top-up phase 2 (run agents_v2_topup3) data: ~80% replay of the original v2 train set + ~20% targeted rows that
mirror how the app calls the agent (features_v2.go WindowN), plus the known weaknesses.

Stages (d = readings since onset, n = window length as the app picks it):
  early  d 3..9  (15-45 min after onset), n = 48 (LadderAlert)
  1.5h   d 15..21, n by family: trend 48, transient 96, step 48, noisy 48, flat 144, sensor_fault 96 (flat/noisy 144),
         occupancy/HVAC 48; n grown to cover onset + 12 baseline readings (rounded up to 6)
  3h     d 33..39, n: trend 48 (54 when onset+12 needs it), transient 96, step 96, noisy 144, flat 144, fault 96/144
Weakness buckets: exponential vs gradual at long ages, spikes on bases with recurring excursions (E10), erratic,
flow stopping at 0 (idle) vs stuck flow, pump cycling on tank level at 48/96/144, power/water status across sizes
(warning/critical boundaries), water cause on/off hours, power load drops, HVAC and occupancy at the stage ages,
clean calm windows at 48/96/144 (power incl. pf, water, air quality, zero-idle).
All rows: existing series, existing generator + teacher (generate_v2 / teacher_v2 / hvac_adapter), train months
only for train, Sep-Oct for the stage dev set, held-out nodes excluded (Ctx). Every targeted row carries
"stage" (early / 1.5h / 3h / other) for per-stage dev losses.

  python gen_topup3.py --out ~/smartcity_runs/agents_v2_topup3/data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_topup as T  # noqa: E402  (also sets up the v2 import paths)
from gen_topup import GV, G, V, TE, HA, SRC  # noqa: E402

SEED = 4495
STAGES = {"early": (3, 9), "1.5h": (15, 21), "3h": (33, 39)}
FAMILY = {"flatline": "flat", "spike": "transient", "dip": "transient", "erratic": "noisy", "oscillation": "noisy",
          "gradual_increase": "trend", "gradual_decrease": "trend", "exponential_increase": "trend",
          "step_increase": "step", "step_decrease": "step", "throttling": "step"}


def policy_n(stage, pattern, fault, d):
    """features_v2.go WindowN for the refinement stages (early = 48)."""
    if stage == "early":
        return 48
    fam = FAMILY.get(pattern, "other")
    n = 48
    if fault:
        n = 144 if fam in ("flat", "noisy") else 96
    elif fam == "flat":
        n = 144
    elif fam == "transient":
        n = 96
    elif fam == "step" and stage == "3h":
        n = 96
    elif fam == "noisy" and stage == "3h":
        n = 144
    need = d + 12
    need += (6 - need % 6) % 6
    return max(n, min(need, 144))


def d_stage(stage):
    lo, hi = STAGES[stage]
    return lambda rng, n, dmin=3: max(dmin, min(n, rng.randint(lo, hi)))


# pattern weights per role (weak patterns up-weighted, from window_study.md A2 + calibration/analytics.md)
W_EVENT = {"spike": 1.2, "dip": 1.0, "gradual_increase": 1.2, "gradual_decrease": 1.2, "step_increase": 0.7,
           "step_decrease": 0.8, "exponential_increase": 1.4, "oscillation": 1.4, "erratic": 1.5, "flatline": 1.2,
           "throttling": 0.4}


def stage_event(stage):
    """One stage-placed event on the ctx role: pattern by W_EVENT, d in the stage range, n by the app policy."""
    def f(ctx, _n):
        rng = ctx.rng
        role = ctx.role
        pats = [p for p in W_EVENT if not (stage == "early" and p == "throttling")]
        if role == "weather":
            pats = [p for p in pats if p not in ("throttling",)]
        p = rng.choices(pats, weights=[W_EVENT[x] for x in pats])[0]
        d_guess = rng.randint(*STAGES[stage])
        dfun = lambda r_, n_, dmin=3: max(dmin, min(n_, d_guess))
        if p == "flatline":
            n = policy_n(stage, p, True, d_guess)
            with T.steer(dfun):
                return GV.gen_fault(ctx, n, kind="stuck")
        fault = p == "erratic" and role != "power"
        n = policy_n(stage, p, fault, d_guess)
        with T.steer(dfun, 0.12, 3.0, 12.0):
            return GV.gen_event(ctx, n, pattern=p)
    return f


def at_n(fn, ns):
    """Run a (ctx, n) generator with n drawn from ns."""
    return lambda ctx, _n: fn(ctx, ctx.rng.choice(ns))


def stage_any(fn_stage):
    """Wrap a per-stage generator factory: stage drawn uniformly, returns (row) with r['stage'] set."""
    def f(ctx, _n):
        st = ctx.rng.choice(list(STAGES))
        r = fn_stage(st)(ctx, _n)
        if r:
            r["stage"] = st
        return r
    return f


def ev_stage(pattern, role_fault=False):
    def mk(stage):
        def f(ctx, _n):
            d_guess = ctx.rng.randint(*STAGES[stage])
            with T.steer(lambda r_, n_, dmin=3: max(dmin, min(n_, d_guess)), 0.12, 3.0, 12.0):
                return GV.gen_event(ctx, policy_n(stage, pattern, role_fault, d_guess), pattern=pattern)
        return f
    return mk


def pump_cycle(sub):
    def f(ctx, _n):
        old = GV.ROUTINES["water"]
        GV.ROUTINES["water"] = (sub,)
        try:
            return GV.gen_routine(ctx, ctx.rng.choice((48, 96, 144)))
        finally:
            GV.ROUTINES["water"] = old
    return f


def offhours(fn, want=True):
    def f(ctx, n):
        r = fn(ctx, n)
        if r and bool(V.F.is_off_hours(r["end_epoch"])) != want:
            return None
        return r
    return f


def stable_at(ns, metric=None):
    def f(ctx, _n):
        if metric:
            ok0 = ctx.seen
            ctx.seen = [k for k in ok0 if k[2] in metric]
        try:
            return GV.gen_stable(ctx, ctx.rng.choice(ns))
        finally:
            if metric:
                ctx.seen = ok0
    return f


def zero_idle_at(ns):
    return lambda ctx, _n: GV.gen_zero_idle(ctx, ctx.rng.choice(ns))


def hvac_stage(ctx, quota):
    """HVAC rows at the stage ages, n = 48 (WindowN 'other' family)."""
    # hvac.py places its own events (sample_d is not used by it), so the rows are tagged "other", n = 48
    rows, _ = HA.make_examples(ctx, quota, lambda rng, *a_, **k_: 48, GV.sample_d, GV.validate)
    for x in rows:
        x["stage"] = "other"
    return rows


def occ48(ctx, quota):
    old = GV.sample_n
    GV.sample_n = lambda rng, lo=24, hi=144: 48
    try:
        rows, _ = GV.gen_occupancy_task(ctx, quota)
    finally:
        GV.sample_n = old
    for x in rows:
        x["stage"] = "other"
    return rows


def buckets():
    """(name, role, train quota, dev quota, generator, stage tag or None (= generator sets it))."""
    B = []
    # stage-placed events, all continuous roles
    for st in STAGES:
        for role, q, dq in (("power", 60, 22), ("water", 50, 18), ("air_quality", 45, 16), ("weather", 15, 6)):
            B.append((f"stage_{st}_{role}", role, q, dq, stage_event(st), st))
    # known weaknesses (stage drawn uniformly where it applies)
    B += [("exp_power", "power", 30, 6, stage_any(ev_stage("exponential_increase")), None),
          ("exp_water", "water", 25, 6, stage_any(ev_stage("exponential_increase")), None),
          ("spike_e10_power", "power", 50, 8, T.ev("spike", T.d_mixed, lo=4.0, e10=(2, 9)), "other"),
          ("stable_e10_power", "power", 30, 6, T.stable_e10(2, 9), "other"),
          ("erratic_power", "power", 30, 6, stage_any(ev_stage("erratic")), None),
          ("erratic_aq", "air_quality", 15, 4, stage_any(ev_stage("erratic", True)), None),
          ("erratic_water", "water", 15, 4, stage_any(ev_stage("erratic", True)), None),
          ("zero_stop_water", "water", 30, 6, T.gen_zero_stop, "other"),
          ("stuck_flow_water", "water", 20, 4, T.gen_stuck_flow, "other"),
          ("pump_cycle_level", "water", 30, 6, pump_cycle("pump_cycle"), "other"),
          ("short_cycle_water", "water", 15, 4, pump_cycle("short_cycle"), "other"),
          ("status_power", "power", 35, 6, at_n(lambda c, n: GV.gen_event(c, n), (48, 96, 144)), "other"),
          ("status_water", "water", 30, 6, at_n(lambda c, n: GV.gen_event(c, n), (48, 96, 144)), "other"),
          ("water_offhours", "water", 30, 6, offhours(at_n(lambda c, n: GV.gen_event(c, n), (48, 96, 144)), True), "other"),
          ("water_dayhours", "water", 15, 4, offhours(at_n(lambda c, n: GV.gen_event(c, n), (48, 96, 144)), False), "other"),
          ("power_drop", "power", 30, 6, stage_any(ev_stage("step_decrease")), None),
          # clean calm windows at the app's lengths (false alarms)
          ("clean_power", "power", 50, 8, stable_at((48, 96, 144)), "other"),
          ("clean_power_pf", "power", 20, 4, stable_at((48, 96, 144), ("pf",)), "other"),
          ("clean_water", "water", 50, 8, stable_at((48, 96, 144)), "other"),
          ("clean_aq", "air_quality", 30, 6, stable_at((48, 96, 144)), "other"),
          ("zero_idle", "water", 10, 2, zero_idle_at((48, 96, 144)), "other"),
          ("zero_idle_power", "power", 10, 2, zero_idle_at((48, 96, 144)), "other")]
    return B


def make(split, heldout, kthr, test_hashes, seen_hashes):
    rows, stats, cache = [], {}, {}
    for name, role, q, dq, fn, stage in buckets():
        quota = q if split == "train" else dq
        if role not in cache:
            cache[role] = T.load_role(role)
        S, roles, ends = cache[role]
        rng = random.Random(f"{SEED}|topup3|{split}|{name}")
        ctx = GV.Ctx(S, ends, roles, heldout, split, role, kthr, rng)
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
            h = hashlib.sha256(r["prompt"].encode()).hexdigest()
            if h in test_hashes or h in seen_hashes:
                rej["dup"] += 1
                continue
            seen_hashes.add(h)
            r["topup_bucket"] = name
            r.setdefault("stage", stage)
            if r["stage"] is None:
                r["stage"] = stage
            r["id"] = f"topup3-{split}-{name}-{made:04d}"
            rows.append(r)
            made += 1
        stats[name] = {"role": role, "quota": quota, "made": made, "tries": tries, "rejected": dict(rej),
                       "seconds": round(time.time() - t0, 1)}
        print(f"  {split}/{name}: {made}/{quota} in {tries} tries, {time.time() - t0:.1f}s", flush=True)
    # HVAC + occupancy (own generators)
    for name, role, q, dq, fn in (("hvac_stages", "hvac", 60, 15, hvac_stage), ("occupancy48", "occupancy", 40, 8, occ48)):
        quota = q if split == "train" else dq
        if role not in cache:
            cache[role] = T.load_role(role) if role != "hvac" else ({}, *GV.node_index({}))
        S, roles, ends = cache[role]
        ctx = GV.Ctx(S, ends, roles, heldout, split, role, kthr, random.Random(f"{SEED}|topup3|{split}|{name}"))
        t0 = time.time()
        got = []
        for r in fn(ctx, quota):
            h = hashlib.sha256(r["prompt"].encode()).hexdigest()
            if h in test_hashes or h in seen_hashes:
                continue
            seen_hashes.add(h)
            r["topup_bucket"] = name
            r["id"] = f"topup3-{split}-{name}-{len(got):04d}"
            got.append(r)
        rows += got
        stats[name] = {"role": role, "quota": quota, "made": len(got), "seconds": round(time.time() - t0, 1)}
        print(f"  {split}/{name}: {len(got)}/{quota}, {time.time() - t0:.1f}s", flush=True)
    return rows, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--replay-share", type=float, default=0.80)
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    man0 = json.loads((SRC / "manifest.json").read_text())
    heldout = dict(man0["heldout_nodes"])
    kj = json.loads((SRC / "kthr.json").read_text())
    kthr = defaultdict(lambda: 99, {tuple(k.split("/")): v["thr"] for k, v in kj.items()})
    V.NODE_LIMITS.update(json.loads((SRC / "node_limits.json").read_text()))
    HA.register()
    TE.build_calibration()
    rd = lambda p: [json.loads(l) for l in open(p, encoding="utf-8")]
    orig_train, orig_dev = rd(SRC / "train.jsonl"), rd(SRC / "dev.jsonl")
    test_hashes = {hashlib.sha256(json.loads(l)["prompt"].encode()).hexdigest() for l in open(SRC / "test.jsonl", encoding="utf-8")}
    seen = {hashlib.sha256(r["prompt"].encode()).hexdigest() for r in orig_train + orig_dev}
    tgt_train, st_train = make("train", heldout, kthr, test_hashes, seen)
    tgt_dev, st_dev = make("dev", heldout, kthr, test_hashes, seen)
    n_replay = int(round(len(tgt_train) * a.replay_share / (1 - a.replay_share)))
    rng = random.Random(f"{SEED}|replay3")
    by = defaultdict(list)
    for r in orig_train:
        by[r["role"]].append(r)
    replay = []
    for role in sorted(by):
        replay += rng.sample(by[role], int(round(n_replay * len(by[role]) / len(orig_train))))
    for r in replay:
        r["topup_bucket"] = "replay"
        r["stage"] = "replay"
    train = replay + tgt_train
    random.Random(f"{SEED}|shuffle3").shuffle(train)

    def dump(name, rows):
        p = out / name
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return {"n": len(rows), "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16]}

    sp = {"train": dump("train.jsonl", train), "dev_target": dump("dev_target.jsonl", tgt_dev)}
    shutil.copyfile(SRC / "dev.jsonl", out / "dev.jsonl")
    sp["dev"] = {"n": len(orig_dev), "sha256_16": hashlib.sha256((out / "dev.jsonl").read_bytes()).hexdigest()[:16]}
    man = {"what": "v2 top-up phase 2 (agents_v2_topup3): replay + app-stage-placed targeted rows + weaknesses",
           "created": datetime.now().isoformat(timespec="seconds"), "seed": SEED, "args": vars(a),
           "source_dataset": {"dir": str(SRC), "config_hash": man0["config_hash"]},
           "gen_topup3_sha256_16": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16],
           "heldout_nodes": heldout, "splits": sp, "stages": {k: f"d {v[0]}..{v[1]}" for k, v in STAGES.items()},
           "window_policy": "features_v2.go WindowN (see policy_n)",
           "train_mix": {"replay": len(replay), "targeted": len(tgt_train), "replay_share": round(len(replay) / len(train), 3),
                         "replay_roles": Counter(r["role"] for r in replay), "targeted_roles": Counter(r["role"] for r in tgt_train),
                         "targeted_stage": Counter(r["stage"] for r in tgt_train)},
           "dev_target_stage": Counter(r["stage"] for r in tgt_dev),
           "buckets": {"train": st_train, "dev_target": st_dev}, "seconds": round(time.time() - t0, 1)}
    (out / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    print(json.dumps({"splits": sp, "mix": man["train_mix"], "dev_stage": man["dev_target_stage"]}, indent=1, default=str))


if __name__ == "__main__":
    main()
