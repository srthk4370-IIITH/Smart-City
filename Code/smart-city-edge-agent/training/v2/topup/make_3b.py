"""Phase 2b data (agents_v2_topup3b): ~90% replay of the original v2 train set + the phase-2 (topup3) targeted rows
scaled down (stratified by bucket). Dev sets: original dev (byte copy) + topup3's per-stage dev_target (same rows,
so per-stage losses compare with phase 2).

  python make_3b.py --src ~/smartcity_runs/agents_v2_topup3/data --out ~/smartcity_runs/agents_v2_topup3b/data --rows 3200
"""
import argparse
import hashlib
import json
import random
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import gen_topup as T

ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--rows", type=int, default=3200)
ap.add_argument("--replay-share", type=float, default=0.90)
ap.add_argument("--drop-ids", default=None, help="jsonl with id + visible (diag_data a2_rows): drop rows whose early shape is not visible")
a = ap.parse_args()
src, out = Path(a.src).expanduser(), Path(a.out).expanduser()
out.mkdir(parents=True, exist_ok=True)
rng = random.Random("4496|3b")
tg = [json.loads(l) for l in open(src / "train.jsonl", encoding="utf-8")]
tg = [r for r in tg if r.get("topup_bucket") != "replay"]
dropped = set()
if a.drop_ids:
    dropped = {x["id"] for x in map(json.loads, open(a.drop_ids)) if not x["visible"]}
    tg = [r for r in tg if r["id"] not in dropped]
n_t = int(round(a.rows * (1 - a.replay_share)))
by = defaultdict(list)
for r in tg:
    by[r["topup_bucket"]].append(r)
pick = []
for b in sorted(by):
    k = max(1, int(round(n_t * len(by[b]) / len(tg))))
    pick += rng.sample(by[b], min(k, len(by[b])))
orig = [json.loads(l) for l in open(T.SRC / "train.jsonl", encoding="utf-8")]
n_r = a.rows - len(pick)
byr = defaultdict(list)
for r in orig:
    byr[r["role"]].append(r)
replay = []
for role in sorted(byr):
    replay += rng.sample(byr[role], int(round(n_r * len(byr[role]) / len(orig))))
for r in replay:
    r["topup_bucket"], r["stage"] = "replay", "replay"
train = replay + pick
rng.shuffle(train)
with open(out / "train.jsonl", "w", encoding="utf-8") as fh:
    for r in train:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
shutil.copyfile(src / "dev_target.jsonl", out / "dev_target.jsonl")
shutil.copyfile(T.SRC / "dev.jsonl", out / "dev.jsonl")
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()[:16]
man = {"what": "v2 top-up phase 2b: 90% replay + phase-2 targeted rows scaled down", "created": datetime.now().isoformat(timespec="seconds"),
       "source_targeted": str(src), "args": vars(a), "dropped_not_visible_early": len(dropped),
       "splits": {"train": {"n": len(train), "sha256_16": sha(out / "train.jsonl")},
                  "dev_target": {"n": sum(1 for _ in open(out / "dev_target.jsonl")), "sha256_16": sha(out / "dev_target.jsonl")},
                  "dev": {"n": sum(1 for _ in open(out / "dev.jsonl")), "sha256_16": sha(out / "dev.jsonl")}},
       "train_mix": {"replay": len(replay), "targeted": len(pick), "replay_share": round(len(replay) / len(train), 3),
                     "targeted_buckets": Counter(r["topup_bucket"] for r in pick), "targeted_stage": Counter(r["stage"] for r in pick),
                     "replay_roles": Counter(r["role"] for r in replay)}}
(out / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
print(json.dumps(man["splits"]), json.dumps(man["train_mix"]["replay_share"]), len(pick))
