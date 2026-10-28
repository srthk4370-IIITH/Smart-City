"""3g warning-vs-critical anchor pairs (power first). The 1.5 h status losses of every c49 mix are power rows read
warning -> critical (c49's 3e run2 pairs rejected "warning" on gold-critical rows, 26x, and never the reverse).
Rows v2 answers fully right (mined ok on all fields, train months, not mdev, not in run2 / anchors_c49):
  warn  : gold warning, power (+ water oscillation/gradual), rejected = gold completion with status "critical"
  crit  : gold critical, power, rejected = status "warning"  (balance, so the set does not just push critical down)
  water : gold warning, water oscillation, rejected = the model's most likely wrong status (the warning->normal loss)
Chosen = untouched teacher completion; ref log-probs from --adapter (the policy training starts from).
  python anchor_3g.py --out anchors_3g.jsonl --adapter M50 [--n-warn 120 --n-crit 60 --n-water 30]
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
A3F = Path.home() / "smartcity_runs" / "agents_v2_topup3f" / "data" / "anchors_c49.jsonl"
STATUSES = ("normal", "warning", "critical", "sensor_fault")


def mdev(i):
    return hashlib.md5(i.encode()).hexdigest()[0] in "01"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--n-warn", type=int, default=120)
    ap.add_argument("--n-crit", type=int, default=60)
    ap.add_argument("--n-water", type=int, default=30)
    ap.add_argument("--seed", default="3g")
    a = ap.parse_args()
    pool = {}
    for f in ("pool.jsonl", "realworld_train.jsonl"):
        for r in K.read_jsonl(D / f):
            pool[r["id"]] = r
    used = {x["id"] for x in K.read_jsonl(D / "train3e_r2.jsonl")} | {x["id"] for x in K.read_jsonl(A3F)}
    cand = []
    for f in ("mined.jsonl", "mined_rw.jsonl"):
        for m in K.read_jsonl(D / f):
            r = pool.get(m["id"])
            if r is None or mdev(m["id"]) or m["id"] in used or "pair" in m or "wrong_field" in m or not all(m["ok"].values()):
                continue
            cand.append((m, r))
    rng = random.Random(a.seed)
    rng.shuffle(cand)
    # event shapes c49 over-escalates (gradual read as exponential, spike / exp) and the 1.5 h stage first
    pr = lambda m: -((m.get("stage") == "1.5h") * 2 + (m["gold_pattern"] in ("gradual_increase", "spike", "exponential_increase", "step_increase")))
    warn = sorted([x for x in cand if x[0]["gold_status"] == "warning" and x[1]["role"] == "power"], key=lambda x: pr(x[0]))[:a.n_warn]
    crit = sorted([x for x in cand if x[0]["gold_status"] == "critical" and x[1]["role"] == "power"], key=lambda x: pr(x[0]))[:a.n_crit]
    water = [x for x in cand if x[0]["gold_status"] == "warning" and x[1]["role"] == "water"
             and x[0]["gold_pattern"] in ("oscillation", "gradual_increase", "gradual_decrease")][:a.n_water]
    sel = [(m, r, "critical") for m, r in warn] + [(m, r, "warning") for m, r in crit] + [(m, r, None) for m, r in water]
    tok, model = K.load_model(a.adapter)
    model.eval()
    out, stat = [], Counter()
    for m, r, forced in sel:
        p = K.tok_ids(tok, r["prompt"])
        gold = K._RX["status"].search(r["completion"]).group(1)
        best = None
        for alt in ([forced] if forced else STATUSES):
            if alt == gold:
                continue
            pp = K.make_pair(tok, r["completion"], "status", alt)
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
                rr, _ = K.span_logp(model, p, pp["r_ids"], pp["lo"], pp["r_hi"])
            if best is None or float(rr) > best[1]:
                best = (alt, float(rr), pp)
        alt, rr, pp = best
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            rc, _ = K.span_logp(model, p, pp["c_ids"], pp["lo"], pp["c_hi"])
        pp.update(ref_c=float(rc), ref_r=rr)
        stat[f"{r['role']}:{gold}->{alt}"] += 1
        out.append({"type": "pair", "id": r["id"], "prompt": r["prompt"], "completion": r["completion"], "pair": pp,
                    "field": "status", "gold": gold, "pred": alt, "anchor": True, "slices": r.get("slices", []),
                    "bucket": r.get("topup_bucket"), "stage": m.get("stage"), "gold_pattern": m["gold_pattern"]})
    with open(a.out, "w", encoding="utf-8") as fh:
        for x in out:
            fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    man = {"n": len(out), "adapter": a.adapter, "args": vars(a), "gold_to_rejected": stat.most_common(),
           "stages": Counter(x["stage"] for x in out).most_common(), "patterns": Counter(x["gold_pattern"] for x in out).most_common(),
           "mean_ref_margin": sum(x["pair"]["ref_c"] - x["pair"]["ref_r"] for x in out) / max(1, len(out)),
           "n_ref_margin_neg": sum(x["pair"]["ref_c"] < x["pair"]["ref_r"] for x in out)}
    Path(a.out).with_suffix(".manifest.json").write_text(json.dumps(man, indent=1, default=str))
    print(json.dumps(man, default=str)[:1500])


if __name__ == "__main__":
    main()
