"""mix.py DATA_DIR N_TOTAL OUT_DIR: ~50 % real v3-rendered rows + ~50 % family-stratified replay of agt_v3/train.jsonl.
Also writes val_sel.jsonl (REAL VAL, first VAL_N rows), syn_slice.jsonl (synthetic agt_v3 dev, stratified), gendev.jsonl (1 row:
the trainer needs a dev file; selection is done outside on merged Q4_0). Deterministic (seed 16). LAPTOP ONLY."""
import collections
import json
import random
import sys
from pathlib import Path

D, N, O = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
VAL_N = int(sys.argv[4]) if len(sys.argv) > 4 else 400
SYN_N = int(sys.argv[5]) if len(sys.argv) > 5 else 120
V3 = Path("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/agt_v3")
O.mkdir(parents=True, exist_ok=True)
rng = random.Random(16)


def rd(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def wr(p, rows):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def strat(rows, k, key):
    by = collections.defaultdict(list)
    for r in rows:
        by[key(r)].append(r)
    for v in by.values():
        rng.shuffle(v)
    tot = len(rows)
    out = []
    for kk in sorted(by):          # proportional quota per stratum
        out += by[kk][:max(1, round(k * len(by[kk]) / tot))]
    rng.shuffle(out)
    return out[:k]


real = rd(D / "real_train_all.jsonl")
n_real = min(len(real), N // 2)
real_pick = strat(real, n_real, lambda r: (r["role"], r["gold"]["status"])) if n_real < len(real) else real
syn = rd(V3 / "train.jsonl")
syn_pick = strat(syn, N - len(real_pick), lambda r: r["family"])
KEEP = ("id", "prompt", "completion", "gold", "family", "role", "stage", "slices", "synthetic", "source")
mix = [{k: r.get(k) for k in KEEP} for r in real_pick + syn_pick]
rng.shuffle(mix)
wr(O / "mix_train.jsonl", mix)
val = rd(D / "real_val.jsonl")
wr(O / "val_sel.jsonl", val[:VAL_N])
dev = rd(V3 / "dev.jsonl")
wr(O / "syn_slice.jsonl", strat(dev, SYN_N, lambda r: r["family"]))
wr(O / "gendev.jsonl", val[-1:])
man = {"n_total": len(mix), "real": len(real_pick), "real_available": len(real), "replay": len(syn_pick),
       "replay_by_family": dict(collections.Counter(r["family"] for r in syn_pick)),
       "real_by_status": dict(collections.Counter(r["gold"]["status"] for r in real_pick)),
       "real_by_role": dict(collections.Counter(r["role"] for r in real_pick)),
       "val_sel": min(VAL_N, len(val)), "val_sel_by_role": dict(collections.Counter(r["role"] for r in val[:VAL_N])),
       "val_sel_by_status": dict(collections.Counter(r["gold"]["status"] for r in val[:VAL_N])), "syn_slice": SYN_N}
json.dump(man, open(O / "mix_manifest.json", "w", newline="\n"), indent=1)
print(json.dumps({k: man[k] for k in ("n_total", "real", "real_available", "replay", "val_sel")}))
