"""Build the 3e training file from mined.jsonl: preference pairs on v2's own mistakes + 1:1 gold replay.

Filters on pairs (TOPUP_WHY): gold shape not visible yet (diag_data A2 rule) and boundary sizes (2.5-4.5x noise) are
dropped. Rows with md5(id) starting with 0 or 1 (1/8) are held out as "mdev" (gate set, never trained).
Replay: half rows v2 answered correctly from the pool, half rows of the original v2 train set.

  python build_3e.py --data ~/smartcity_runs/agents_v2_topup3e/data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common3e as K  # noqa: E402

SRC = HERE.parents[2] / "data" / "sft_v2"


def mdev(i, chars="01"):
    return hashlib.md5(i.encode()).hexdigest()[0] in chars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--replay-ratio", type=float, default=1.0)
    ap.add_argument("--max-pairs", type=int, default=0)
    ap.add_argument("--out-name", default="train3e.jsonl")
    ap.add_argument("--mdev-chars", default="01")
    ap.add_argument("--amp-hi", type=float, default=4.5, help="drop pairs whose event size is 2.5..amp_hi x noise (boundary)")
    ap.add_argument("--drop-stable-pairs", action="store_true", help="drop pattern pairs where gold or pred is stable (event-vs-calm boundary)")
    ap.add_argument("--drop-confusions", default="", help="comma list of a|b pattern pairs to drop in either direction")
    a = ap.parse_args()
    d = Path(a.data).expanduser()
    pool = {r["id"]: r for r in K.read_jsonl(d / "pool.jsonl")}
    for f in sorted(d.glob("realworld_train*.jsonl")):
        pool.update({r["id"]: r for r in K.read_jsonl(f)})
    mined = []
    for f in sorted(d.glob("mined*.jsonl")):
        mined += K.read_jsonl(f)
    rng = random.Random("3e")
    drop = Counter()
    pairs, correct, dev = [], [], []
    for m in mined:
        r = pool.get(m["id"])
        if r is None:
            continue
        if mdev(m["id"], a.mdev_chars):
            dev.append(r)
            continue
        if "pair" in m:
            if not m.get("learnable", True):
                drop["not_visible"] += 1
                continue
            if m.get("amp") is not None and 2.5 <= m["amp"] <= a.amp_hi:
                drop["boundary_2.5_4.5"] += 1
                continue
            if a.drop_stable_pairs and m["wrong_field"] == "pattern" and "stable" in (m["gold_pattern"], m["pred"]):
                drop["stable_boundary"] += 1
                continue
            if m["wrong_field"] == "pattern" and any({m["gold_pattern"], m["pred"]} == set(x.split("|")) for x in a.drop_confusions.split(",") if x):
                drop["confusion_" + "_".join(sorted((m["gold_pattern"], m["pred"])))] += 1
                continue
            pairs.append({"type": "pair", "id": r["id"], "prompt": r["prompt"], "completion": r["completion"], "pair": m["pair"],
                          "field": m["wrong_field"], "gold": m["gold_" + m["wrong_field"]], "pred": m["pred"], "slices": r.get("slices", [])})
        elif all(m["ok"].values()):
            correct.append(r)
    rng.shuffle(pairs)
    if a.max_pairs:
        pairs = pairs[:a.max_pairs]
    n_rep = int(round(len(pairs) * a.replay_ratio))
    orig = K.read_jsonl(SRC / "train.jsonl")
    rep = rng.sample(correct, min(len(correct), n_rep // 2))
    rep += rng.sample(orig, n_rep - len(rep))
    items = pairs + [{"type": "sft", "id": r["id"], "prompt": r["prompt"], "completion": r["completion"]} for r in rep]
    rng.shuffle(items)
    with open(d / a.out_name, "w", encoding="utf-8") as fh:
        for x in items:
            fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(d / "mdev.jsonl", "w", encoding="utf-8") as fh:
        for r in dev:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    man = {"mined": len(mined), "pairs": len(pairs), "replay": len(rep), "replay_from_pool_correct": min(len(correct), n_rep // 2),
           "mdev": len(dev), "dropped": drop, "pair_field": Counter(p["field"] for p in pairs),
           "pair_gold_pred_top": Counter(f"{p['field']}:{p['gold']}->{p['pred']}" for p in pairs).most_common(25),
           "pair_slices": Counter(s for p in pairs for s in p["slices"]),
           "v2_tf_error_rate_pool": round(sum("wrong_field" in m for m in mined) / max(1, len(mined)), 4),
           "sha256_16": hashlib.sha256((d / a.out_name).read_bytes()).hexdigest()[:16], "args": vars(a)}
    (d / ("manifest_" + a.out_name.replace(".jsonl", ".json"))).write_text(json.dumps(man, indent=1, default=str))
    print(json.dumps({k: man[k] for k in ("mined", "pairs", "replay", "mdev", "dropped", "pair_field", "v2_tf_error_rate_pool")}, default=str))


if __name__ == "__main__":
    main()
