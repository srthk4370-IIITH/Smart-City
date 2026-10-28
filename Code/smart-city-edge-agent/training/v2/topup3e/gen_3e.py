"""Top-up 3e data: (a) a TEST-month weakness eval set (eval_weak.jsonl), (b) a TRAIN-month mining pool (pool.jsonl).

Buckets = gen_topup3.buckets() (stage-placed events at the app's WindowN, exp, erratic, pump cycling, status, water
causes on/off hours, power drops, calm windows, HVAC, occupancy) + 3e extras: compound (multi-event) shapes,
synthetic routines and real routines (false-alarm checks) and sensor faults at the app lengths.
Same generator + teacher as v2 (generate_v2 / teacher_v2 / hvac_adapter); train months + seen nodes only for the
pool, test months (Nov-Dec, incl. held-out nodes) for the eval; no prompt shared with v2 train/dev/test.
Every row gets slice tags and a learnability flag ("visible", diag_data A2 rule) for d-placed events.

  python gen_3e.py --out ~/smartcity_runs/agents_v2_topup3e/data --eval-scale 1.5 --pool-scale 2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "topup"))
import gen_topup3 as G3  # noqa: E402
import gen_topup as T  # noqa: E402
from gen_topup import GV, V, TE, HA, SRC  # noqa: E402
import diag_data as DD  # noqa: E402

ORIG_BUCKETS = G3.buckets


def extras():
    an = G3.at_n
    return [("compound_power", "power", 40, 12, an(lambda c, n: GV.gen_compound(c, n), (48, 96, 144)), "other"),
            ("compound_water", "water", 35, 10, an(lambda c, n: GV.gen_compound(c, n), (48, 96, 144)), "other"),
            ("compound_aq", "air_quality", 30, 10, an(lambda c, n: GV.gen_compound(c, n), (48, 96, 144)), "other"),
            ("routine_power", "power", 25, 8, an(lambda c, n: GV.gen_routine(c, n), (48, 96, 144)), "other"),
            ("routine_water", "water", 25, 8, an(lambda c, n: GV.gen_routine(c, n), (48, 96, 144)), "other"),
            ("routine_aq", "air_quality", 15, 6, an(lambda c, n: GV.gen_routine(c, n), (48, 96, 144)), "other"),
            ("fault_power", "power", 15, 6, an(lambda c, n: GV.gen_fault(c, n), (48, 96, 144)), "other"),
            ("fault_water", "water", 15, 6, an(lambda c, n: GV.gen_fault(c, n), (48, 96, 144)), "other"),
            ("fault_aq", "air_quality", 15, 6, an(lambda c, n: GV.gen_fault(c, n), (48, 96, 144)), "other")]


def rw_buckets():
    """REALWORLD.md section 5 cases that the existing generator + teacher can label (no new prompt fields, no new
    label rules): #3 post-maintenance shift (bias), #4 slow calibration drift / long drifts, #5 stuck / quantised vs
    genuinely idle zero, #6 dead sensor (bias / saturation), #2 single glitch to 0 (dropout), #9/#10 short windows
    (n 24-36, history truncated), #12 daily cycles (real routines), old level shifts, noise increase."""
    an = G3.at_n
    B = []
    for role, k in (("power", 1.0), ("water", 1.0), ("air_quality", 1.0), ("weather", 0.5)):
        q = lambda x: max(1, round(x * k))
        for kind in ("bias", "calib_drift", "stuck", "quantised", "dropout", "noise_increase", "saturation"):
            B.append((f"rw_fault_{kind}_{role}", role, q(12), q(5), an(lambda c, n, kind=kind: GV.gen_fault(c, n, kind=kind), (48, 96, 144)), "other"))
        B += [(f"rw_old_shift_{role}", role, q(15), q(6), an(lambda c, n: GV.gen_old_shift(c, n), (96, 144)), "other"),
              (f"rw_long_drift_{role}", role, q(15), q(6), an(lambda c, n: GV.gen_long_drift(c, n), (96, 144)), "other"),
              (f"rw_short_event_{role}", role, q(20), q(8), an(lambda c, n: GV.gen_event(c, n), (24, 30, 36)), "other"),
              (f"rw_short_stable_{role}", role, q(10), q(5), an(lambda c, n: GV.gen_stable(c, n), (24, 30, 36)), "other"),
              (f"rw_real_routine_{role}", role, q(15), q(6), an(lambda c, n: GV.gen_real_routine(c, n), (48, 96, 144)), "other")]
    B += [("rw_zero_idle_water", "water", 15, 6, G3.zero_idle_at((48, 96, 144)), "other"),
          ("rw_zero_idle_power", "power", 10, 4, G3.zero_idle_at((48, 96, 144)), "other")]
    return B


def tag(r):
    b = r.get("topup_bucket", "")
    s = set()
    if b.startswith("rw_"):
        s.add("realworld")
        s.add("rw_" + ("fault_" + b.split("_")[2] if b.startswith("rw_fault_") else b.split("_")[1] + "_" + b.split("_")[2]))
    st = r.get("stage")
    if st in ("early", "1.5h", "3h"):
        s.add("stage_" + st)
    for k, v in (("exp_", "exp_vs_gradual"), ("erratic", "erratic"), ("pump_cycle", "pump_cycling"),
                 ("short_cycle", "pump_cycling"), ("status_", "status_power_water"), ("water_offhours", "water_cause"),
                 ("water_dayhours", "water_cause"), ("zero_stop", "water_cause"), ("stuck_flow", "water_cause"),
                 ("compound", "compound"), ("clean_", "calm"), ("zero_idle", "calm"), ("stable_e10", "calm"),
                 ("routine", "routine"), ("fault_", "sensor_fault"), ("hvac", "hvac"), ("occupancy", "occupancy"),
                 ("power_drop", "power_drop"), ("spike_e10", "spike_e10")):
        if k in b:
            s.add(v)
    if r.get("role") in ("power", "water") and r.get("stage") in ("early", "1.5h", "3h"):
        s.add("status_power_water")
    if r.get("pattern") in ("exponential_increase", "gradual_increase") and (r.get("d") or 0) >= 30:
        s.add("exp_vs_gradual")
    return sorted(s)


def learnable(r):
    try:
        if r.get("d") and r.get("hist") and r.get("pattern") not in ("stable", None):
            v = DD.visibility(r)
            return True if v is None else bool(DD.visible(r, v))
    except Exception:  # noqa: BLE001
        return True
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--eval-scale", type=float, default=1.5)
    ap.add_argument("--pool-scale", type=float, default=2.0)
    ap.add_argument("--only", choices=["both", "eval", "pool"], default="both")
    ap.add_argument("--rw", action="store_true", help="REALWORLD.md buckets only -> realworld_eval.jsonl / realworld_train.jsonl")
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
    h = lambda p: hashlib.sha256(p.encode()).hexdigest()
    seen = set()
    for f in ("train.jsonl", "dev.jsonl", "test.jsonl"):
        seen |= {h(json.loads(l)["prompt"]) for l in open(SRC / f, encoding="utf-8")}
    man = {"what": "top-up 3e: test-month weakness eval set + train-month mining pool", "created": datetime.now().isoformat(timespec="seconds"),
           "args": vars(a), "source_config_hash": man0["config_hash"], "heldout_nodes": heldout, "files": {}}
    names = ("realworld_eval.jsonl", "realworld_train.jsonl") if a.rw else ("eval_weak.jsonl", "pool.jsonl")
    for split, scale, name in (("test", a.eval_scale, names[0]), ("train", a.pool_scale, names[1])):
        if a.only != "both" and (a.only == "eval") != (split == "test"):
            continue
        B = [(n, ro, max(1, round(q * scale)), max(2, round(dq * scale)), fn, st) for n, ro, q, dq, fn, st in (rw_buckets() if a.rw else ORIG_BUCKETS() + extras())]
        G3.buckets = lambda B=B: B
        rows, stats = G3.make(split, heldout, kthr, set(), seen)
        for r in rows:
            r["id"] = r["id"].replace("topup3-", "t3e-rw-" if a.rw else "t3e-")
            r["slices"] = tag(r)
            r["learnable"] = learnable(r)
        p = out / name
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        man["files"][name] = {"split": split, "n": len(rows), "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
                              "slices": Counter(s for r in rows for s in r["slices"]), "roles": Counter(r["role"] for r in rows),
                              "learnable": Counter(r["learnable"] for r in rows), "buckets": stats}
        print(name, len(rows), dict(man["files"][name]["slices"]), flush=True)
    man["seconds"] = round(time.time() - t0, 1)
    (out / f"manifest_gen_{a.only}{'_rw' if a.rw else ''}.json").write_text(json.dumps(man, indent=1, default=str))


if __name__ == "__main__":
    main()
