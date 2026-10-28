"""3f status-PRESERVING pairs ("anchors") against DPO likelihood displacement (Razin et al. 2024, arXiv 2410.08847).

3e run2 status pairs were single-token swaps that mostly rejected "normal" (warning->normal 40, critical->normal 10,
sensor_fault->normal 13). DPO pushes the rejected token down everywhere it is similar, so mass moved to warning /
critical on routine power windows (routine status 97.9 -> 85.4). Anchors: rows v2 already answers fully right
(mined ok on all fields, train months, not mdev), chosen = gold completion, rejected = gold completion with status
replaced by the model's most likely WRONG status label (scored by full-label log-prob, teacher-forced on gold
pattern). Mostly gold "normal" rows (routine / calm / step-normal, power + water first), plus some alarm rows so the
anchor set itself does not push the opposite way. Labels are untouched teacher labels (no new label rules).
Reference log-probs come from --adapter (the policy the training run starts from).

  python anchor_3f.py --out anchors_v2.jsonl --adapter V2 [--n-normal 180 --n-alarm 60 --seed 3f]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "topup3e"))
import common3e as K  # noqa: E402

D = Path.home() / "smartcity_runs" / "agents_v2_topup3e" / "data"
STATUSES = ("normal", "warning", "critical", "sensor_fault")


def mdev(i):
    return hashlib.md5(i.encode()).hexdigest()[0] in "01"


def pick(n_normal, n_alarm, seed):
    pool = {}
    for f in ("pool.jsonl", "realworld_train.jsonl"):
        for r in K.read_jsonl(D / f):
            pool[r["id"]] = r
    used = {x["id"] for x in K.read_jsonl(D / "train3e_r2.jsonl")}
    cand = []
    for f in ("mined.jsonl", "mined_rw.jsonl"):
        for m in K.read_jsonl(D / f):
            r = pool.get(m["id"])
            if r is None or mdev(m["id"]) or m["id"] in used or "pair" in m or "wrong_field" in m or not all(m["ok"].values()):
                continue
            cand.append((m, r))
    rng = random.Random(seed)
    rng.shuffle(cand)

    def prio(m, r):
        b = r.get("topup_bucket", "")
        p = 0
        if r["role"] in ("power", "water"):
            p += 2
        if any(k in b for k in ("routine", "clean_", "zero_idle", "stable_e10", "rw_real_routine", "rw_short_stable")):
            p += 2
        if m["gold_pattern"] not in ("stable", "flatline"):
            p += 1          # an event shape with status normal = where alarms leak in
        return -p
    nor = sorted([x for x in cand if x[0]["gold_status"] == "normal"], key=lambda x: prio(*x))[:n_normal]
    ala = [x for x in cand if x[0]["gold_status"] in ("warning", "critical") and x[1]["role"] in ("power", "water")][:n_alarm]
    return nor + ala


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--adapter", default=K.V2_ADAPTER)
    ap.add_argument("--n-normal", type=int, default=180)
    ap.add_argument("--n-alarm", type=int, default=60)
    ap.add_argument("--seed", default="3f")
    ap.add_argument("--ids-from", default=None, help="reuse the row selection of an earlier anchors file")
    a = ap.parse_args()
    if a.ids_from:
        want = [x["id"] for x in K.read_jsonl(a.ids_from)]
        pool = {}
        for f in ("pool.jsonl", "realworld_train.jsonl"):
            for r in K.read_jsonl(D / f):
                pool[r["id"]] = r
        sel = [(None, pool[i]) for i in want]
    else:
        sel = pick(a.n_normal, a.n_alarm, a.seed)
    tok, model = K.load_model(a.adapter)
    model.eval()
    out, stat = [], Counter()
    for m, r in sel:
        p = K.tok_ids(tok, r["prompt"])
        gold = K._RX["status"].search(r["completion"]).group(1)
        best = None
        for alt in STATUSES:
            if alt == gold:
                continue
            pr = K.make_pair(tok, r["completion"], "status", alt)
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
                rr, _ = K.span_logp(model, p, pr["r_ids"], pr["lo"], pr["r_hi"])
            if best is None or float(rr) > best[1]:
                best = (alt, float(rr), pr)
        alt, rr, pr = best
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            rc, _ = K.span_logp(model, p, pr["c_ids"], pr["lo"], pr["c_hi"])
        pr.update(ref_c=float(rc), ref_r=rr)
        stat[f"{r['role']}:{gold}->{alt}"] += 1
        out.append({"type": "pair", "id": r["id"], "prompt": r["prompt"], "completion": r["completion"], "pair": pr,
                    "field": "status", "gold": gold, "pred": alt, "anchor": True, "slices": r.get("slices", []),
                    "bucket": r.get("topup_bucket")})
    with open(a.out, "w", encoding="utf-8") as fh:
        for x in out:
            fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    man = {"n": len(out), "adapter": a.adapter, "args": vars(a), "gold_to_rejected": stat.most_common(),
           "buckets": Counter(x["bucket"] for x in out).most_common(), "mean_ref_margin": sum(x["pair"]["ref_c"] - x["pair"]["ref_r"] for x in out) / max(1, len(out))}
    Path(a.out).with_suffix(".manifest.json").write_text(json.dumps(man, indent=1, default=str))
    print(json.dumps(man, default=str)[:2000])


if __name__ == "__main__":
    main()
