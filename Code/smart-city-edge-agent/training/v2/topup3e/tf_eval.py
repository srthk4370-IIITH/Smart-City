"""GPU screen: teacher-forced decision accuracy (pattern = greedy exactly; status/cause conditioned on gold prefix) of
one or more adapters on the gate sets, per row (paired comparisons), nf4 base as in training.

  python tf_eval.py --adapters v2=/path/adapter c50=/path/ckpt-50 ... --sets eval3e=F mdev=F dev=F[:N] --out DIR
Writes DIR/<tag>/<set>.jsonl (id, ok{field}, slices) and DIR/screen.md (paired vs the first adapter)."""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "topup"))
sys.path.insert(0, str(HERE.parent / "post"))
import common3e as K  # noqa: E402
import decision_eval as DE  # noqa: E402


def mcnemar(b, c):
    from math import comb
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def sl(r):
    s = set(r.get("slices_all") or r.get("slices") or [])
    s |= {"ALL", "role_" + r["role"]}
    if r.get("seen"):
        s.add("seen_" + r["seen"])
    return sorted(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapters", nargs="+", required=True)
    ap.add_argument("--sets", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    sets = {}
    for s in a.sets:
        name, f = s.split("=", 1)
        lim = 0
        if ":" in f:
            f, lim = f.rsplit(":", 1)
        rows = K.read_jsonl(Path(f).expanduser())
        if int(lim):
            rows = random.Random(7).sample(rows, int(lim))
        sets[name] = rows
    tok = model = None
    tags = []
    for spec in a.adapters:
        tag, path = spec.split("=", 1)
        tags.append(tag)
        if all((out / tag / f"{n}.jsonl").exists() for n in sets):
            continue
        from peft import PeftModel
        if model is None:
            tok, model = K.load_model(path)
            model.load_adapter(path, adapter_name=tag)
        else:
            model.load_adapter(path, adapter_name=tag)
        model.set_adapter(tag)
        model.eval()
        (out / tag).mkdir(exist_ok=True)
        for n, rows in sets.items():
            p = out / tag / f"{n}.jsonl"
            if p.exists():
                continue
            res = DE.token_losses(model, tok, rows)
            with open(p.with_suffix(".tmp"), "w") as fh:
                for r, x in zip(rows, res):
                    fh.write(json.dumps({"id": r["id"], "ok": x[3], "slices": sl(r)}) + "\n")
            p.with_suffix(".tmp").rename(p)
            print(tag, n, round(sum(x[3].get("pattern", False) for x in res) / len(res), 4), flush=True)
        model.delete_adapter(tag)
    # paired table vs the first tag
    ref = tags[0]
    md = []
    for n in sets:
        R = {x["id"]: x for x in map(json.loads, open(out / ref / f"{n}.jsonl"))}
        for t in tags[1:]:
            Cd = {x["id"]: x for x in map(json.loads, open(out / t / f"{n}.jsonl"))}
            agg = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))   # slice -> field -> [n, ref, cand, wins-losses]
            W = defaultdict(lambda: defaultdict(lambda: [0, 0]))
            for i, x in R.items():
                y = Cd[i]
                for s in x["slices"]:
                    for f in ("pattern", "status", "likely_cause"):
                        if f in x["ok"] and f in y["ok"]:
                            v = agg[s][f]
                            v[0] += 1; v[1] += x["ok"][f]; v[2] += y["ok"][f]
                            W[s][f][0] += (y["ok"][f] and not x["ok"][f]); W[s][f][1] += (x["ok"][f] and not y["ok"][f])
            md.append(f"\n### {n}: {ref} -> {t}\n\n| slice | n | pattern ref | pattern cand | W/L | p | status ref->cand | W/L | cause ref->cand |\n|---|---|---|---|---|---|---|---|---|")
            for s in sorted(agg):
                p_, st, ca = agg[s]["pattern"], agg[s]["status"], agg[s]["likely_cause"]
                if not p_[0]:
                    continue
                w, l_ = W[s]["pattern"]
                md.append(f"| {s} | {p_[0]} | {100 * p_[1] / p_[0]:.1f} | {100 * p_[2] / p_[0]:.1f} | {w}/{l_} | {mcnemar(w, l_):.3f} | "
                          f"{st[1]}->{st[2]} | {W[s]['status'][0]}/{W[s]['status'][1]} | {ca[1]}->{ca[2]} |")
    (out / "screen.md").write_text("\n".join(md) + "\n")
    print("\n".join(l for l in md if "| ALL |" in l or l.startswith("###")))


if __name__ == "__main__":
    main()
