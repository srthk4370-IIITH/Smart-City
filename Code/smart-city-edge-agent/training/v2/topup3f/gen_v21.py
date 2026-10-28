"""v2.1 (track A) NEW train-month data, same generator + teacher as v2 / 3e / rw5 (no new label rules), new seeds:
  weak  : gen_3e weakness buckets (power status / stages, erratic, water causes, compound, exp-vs-gradual, calm/routine
          negatives), G3.SEED 5021, train months, seen nodes only.
  aug   : unseen-sensor augmentation, G3.SEED 5022: the raw history of a SEEN sensor is rescaled (a = e^U(ln .6, ln 1.7))
          and offset (b = U(-.1, .1) x its median) BEFORE the generator injects the event and the teacher labels it, so the
          label follows the new values (absolute limits are re-applied). Only if the whole transformed history stays
          inside the metric's physical lo..hi (else up to 5 redraws, then the row is left untransformed and dropped).
          Bounded metrics (pf, pH, rh) are not augmented. Unit changes are NOT done (the prompt states the unit; a
          relabelled unit would need new prompt text = a new label rule).
  rw5   : gen_rw5 REALWORLD 5 cases (glitch, chatter, gaps, recovery, holidays, CO2 floor, daily cycle, HVAC) + acidic,
          seed 5021, train months.
Prompts de-duplicated against v2 train/dev/test, every 3e file, dev3f, rw5 (dev/test/train) and each other.
  python gen_v21.py --out ~/smartcity_runs/agents_v21/data [--weak-scale 0.6 --aug-scale 0.35 --rw-scale 1.0]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_rw5 as RW  # noqa: E402  (sets up the 3e / topup paths)
import gen_3e as E  # noqa: E402
import gen_topup3 as G3  # noqa: E402
from gen_topup import GV, V, TE, HA, SRC  # noqa: E402

WEAK = ("stage_", "status_", "erratic_", "water_offhours", "water_dayhours", "zero_stop", "stuck_flow", "compound_",
        "exp_", "spike_e10", "power_drop", "clean_", "routine_", "stable_e10", "zero_idle", "pump_cycle", "short_cycle", "fault_")
NOAUG = {"pf", "ph", "rh"}
AUG = {"on": False, "n": Counter()}
_base0 = GV.Ctx.base


def _base_aug(self, key, n, need_hist=0):
    end, h = _base0(self, key, n, need_hist)
    if not AUG["on"] or h is None:
        return end, h
    role, _node, metric = key
    m = V.METRICS.get((role, metric))
    if m is None or metric in NOAUG:
        AUG["n"]["skip_metric"] += 1
        return None, None
    med = sorted(h)[len(h) // 2]
    for _ in range(5):
        a = math.exp(self.rng.uniform(math.log(0.6), math.log(1.7)))
        b = self.rng.uniform(-0.1, 0.1) * abs(med)
        y = [a * v + b for v in h]
        if min(y) >= m["lo"] and max(y) <= m["hi"]:
            AUG["n"]["ok"] += 1
            return end, y
    AUG["n"]["out_of_range"] += 1
    return None, None


GV.Ctx.base = _base_aug


def seen_hashes():
    h = lambda p: hashlib.sha256(p.encode()).hexdigest()
    seen = set()
    files = [SRC / f for f in ("train.jsonl", "dev.jsonl", "test.jsonl")]
    files += list((RW.R3E / "data").glob("*.jsonl")) + [RW.R3E / "eval" / "eval3e.jsonl"]
    files += list((RW.R3F / "dev").glob("*.jsonl")) + list((RW.R3F / "rw5").glob("*.jsonl"))
    for f in files:
        for l in open(f, encoding="utf-8"):
            j = json.loads(l)
            if "prompt" in j:
                seen.add(h(j["prompt"]))
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--weak-scale", type=float, default=0.6)
    ap.add_argument("--aug-scale", type=float, default=0.35)
    ap.add_argument("--rw-scale", type=float, default=1.0)
    ap.add_argument("--only", default="weak,aug,rw5")
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    man0 = json.loads((SRC / "manifest.json").read_text())
    heldout = dict(man0["heldout_nodes"])
    kj = json.loads((SRC / "kthr.json").read_text())
    kthr = defaultdict(lambda: 99, {tuple(k.split("/")): v["thr"] for k, v in kj.items()})
    V.NODE_LIMITS.update(json.loads((SRC / "node_limits.json").read_text()))
    HA.register()
    TE.build_calibration()
    seen = seen_hashes()
    man = {"args": vars(a), "files": {}, "n_seen_hashes": len(seen)}
    for kind in a.only.split(","):
        t0 = time.time()
        if kind == "rw5":
            rows, stats = RW.make("train", 5021, a.rw_scale, heldout, kthr, seen, "v21rw5")
            RW.ONLY_ACIDIC = True
            r2, s2 = RW.make("train", 5023, a.rw_scale, heldout, kthr, seen, "v21rw5x")
            RW.ONLY_ACIDIC = False
            rows += r2
            stats.update({"acidic_" + k: v for k, v in s2.items()})
        else:
            G3.SEED = 5021 if kind == "weak" else 5022
            sc = a.weak_scale if kind == "weak" else a.aug_scale
            B = [(n, ro, max(1, round(q * sc)), dq, fn, st) for n, ro, q, dq, fn, st in E.ORIG_BUCKETS() + E.extras()
                 if n.startswith(WEAK) and ro in ("power", "water", "air_quality", "weather")]
            G3.buckets = lambda B=B: B
            AUG["on"] = kind == "aug"
            rows, stats = G3.make("train", heldout, kthr, set(), seen)
            AUG["on"] = False
            for r in rows:
                r["id"] = r["id"].replace("topup3-train-", f"v21{kind}-")
                r["slices"] = E.tag(r)
                r["learnable"] = E.learnable(r)
                if kind == "aug":
                    r["seen"] = "aug"
                    r["slices"].append("aug_unseen")
        p = out / f"v21_{kind}.jsonl"
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        man["files"][p.name] = {"n": len(rows), "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
                                "roles": Counter(r["role"] for r in rows), "status": Counter(r.get("status") for r in rows),
                                "slices": Counter(s for r in rows for s in r.get("slices", [])), "buckets": stats,
                                "seconds": round(time.time() - t0, 1)}
        print(p.name, len(rows), round(time.time() - t0), "s", flush=True)
    man["aug_counts"] = dict(AUG["n"])
    (out / "manifest_gen_v21.json").write_text(json.dumps(man, indent=1, default=str))


if __name__ == "__main__":
    main()
