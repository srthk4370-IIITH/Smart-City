"""Calibration text for llama-imatrix (RETRAIN_V2_SPEC decision #2: importance matrix from OUR prompts).

Picks ~512 rows from the v2 TRAIN split (never dev/test), stratified so every role (incl. HVAC), every family
(events, routines, faults, compound, boundary...), every window-length bucket and every event-age bucket is
present: round-robin over (role, family, window bucket, age bucket) cells. Each sample is the exact device
prompt + its target JSON (so the generation-side activations are covered too), with the special tokens as
text (llama-imatrix --parse-special turns them into the real tokens, as htpd does). Shuffled, so the first
imatrix chunks already cover all strata.

  python calib_prompts.py --out ~/smartcity_runs/agents_v2/post/calib   -> calib.txt, calib_manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common_v2 as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=512)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    cells = defaultdict(list)
    for r in C.read_jsonl(C.DATA / "train.jsonl"):
        cells[(r["role"], r.get("family", ""), C.win_bucket(r), C._age(r.get("d")))].append(r)
    roles = sorted({k[0] for k in cells})
    quota = {ro: a.n // len(roles) + (1 if i < a.n % len(roles) else 0) for i, ro in enumerate(roles)}
    pick = []
    for ro in roles:
        keys = sorted(k for k in cells if k[0] == ro)
        rng.shuffle(keys)
        for k in keys:
            rng.shuffle(cells[k])
        take, i = [], 0
        while len(take) < quota[ro] and any(cells[k] for k in keys):
            k = keys[i % len(keys)]
            if cells[k]:
                take.append(cells[k].pop())
            i += 1
        pick.extend(take)
    rng.shuffle(pick)
    text = "".join(r["prompt"] + r["completion"] + "\n" for r in pick)
    (out / "calib.txt").write_text(text, encoding="utf-8")
    man = {"rows": len(pick), "split": "train", "seed": a.seed, "chars": len(text),
           "approx_tokens": sum(r.get("prompt_tokens", 0) + r.get("completion_tokens", 0) for r in pick),
           "sha256_16": hashlib.sha256(text.encode()).hexdigest()[:16],
           "by_role": Counter(r["role"] for r in pick), "by_family": Counter(r.get("family") for r in pick),
           "by_window": Counter(C.win_bucket(r) for r in pick), "by_age": Counter(C._age(r.get("d")) for r in pick),
           "by_status": Counter(C.gold_of(r)["status"] for r in pick), "ids": [r["id"] for r in pick]}
    (out / "calib_manifest.json").write_text(json.dumps(man, indent=1))
    print(json.dumps({k: v for k, v in man.items() if k != "ids"}, indent=1))


if __name__ == "__main__":
    main()
