"""3f paired DEV set (selection set; the 1,148-row 3e eval stays untouched for the final decision).

  dev3f = (a) 1,000 random rows of data/sft_v2/test.jsonl that are NOT in host400 (same months/nodes as host400)
        + (b) gen_3e weakness buckets (test months incl. held-out nodes) with a NEW seed (gen_topup3.SEED 4495 -> 4496)
        + (c) gen_3e real-world buckets with the new seed.
  Prompts are de-duplicated against v2 train/dev/test AND the 3e eval/pool/train files, so no row is shared with the
  1,148-row test set or with anything 3e trained on.

  python gen_dev3f.py --out ~/smartcity_runs/agents_v2_topup3f/dev [--weak-scale 2 --rw-scale 1.5 --n-test 1000]
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
sys.path.insert(0, str(HERE.parent / "topup3e"))
sys.path.insert(0, str(HERE.parent / "topup"))
import gen_3e as E  # noqa: E402
import gen_topup3 as G3  # noqa: E402
from gen_topup import V, TE, HA, SRC  # noqa: E402

R3E = Path.home() / "smartcity_runs" / "agents_v2_topup3e"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--weak-scale", type=float, default=2.0)
    ap.add_argument("--rw-scale", type=float, default=1.5)
    ap.add_argument("--n-test", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=4496)
    a = ap.parse_args()
    out = Path(a.out).expanduser(); out.mkdir(parents=True, exist_ok=True)
    G3.SEED = a.seed
    h = lambda p: hashlib.sha256(p.encode()).hexdigest()
    seen = set()
    for f in ("train.jsonl", "dev.jsonl", "test.jsonl"):
        seen |= {h(json.loads(l)["prompt"]) for l in open(SRC / f, encoding="utf-8")}
    n0 = len(seen)
    for f in list((R3E / "data").glob("*.jsonl")) + [R3E / "eval" / "eval3e.jsonl"]:
        for l in open(f, encoding="utf-8"):
            j = json.loads(l)
            if "prompt" in j:
                seen.add(h(j["prompt"]))
    print("dedupe hashes", n0, "->", len(seen), flush=True)
    man0 = json.loads((SRC / "manifest.json").read_text())
    heldout = dict(man0["heldout_nodes"])
    kj = json.loads((SRC / "kthr.json").read_text())
    kthr = defaultdict(lambda: 99, {tuple(k.split("/")): v["thr"] for k, v in kj.items()})
    V.NODE_LIMITS.update(json.loads((SRC / "node_limits.json").read_text()))
    HA.register(); TE.build_calibration()
    rows = []
    # (a) unused v2 test rows
    host400 = set(json.loads((Path.home() / "smartcity_runs/agents_v2/post/eval_set.json").read_text())["ids"])
    rest = [json.loads(l) for l in open(SRC / "test.jsonl", encoding="utf-8")]
    rest = [r for r in rest if r["id"] not in host400]
    random.Random(f"3f-dev|{a.seed}").shuffle(rest)
    for r in rest[:a.n_test]:
        r["evalset"] = "testrest"; rows.append(r)
    # (b) weak + (c) real-world, new seed
    for scale, mk, tagp, es in ((a.weak_scale, lambda: G3.ORIG_BUCKETS_3F() + E.extras(), "t3f-", "weak"),
                                (a.rw_scale, E.rw_buckets, "t3f-rw-", "realworld")):
        B = [(n, ro, max(1, round(q * 0)), max(2, round(dq * scale)), fn, st) for n, ro, q, dq, fn, st in mk()]
        G3.buckets = lambda B=B: B
        got, stats = G3.make("test", heldout, kthr, set(), seen)
        for r in got:
            r["id"] = r["id"].replace("topup3-", tagp)
            r["slices"] = E.tag(r)
            r["learnable"] = E.learnable(r)
            r["evalset"] = es
        rows += got
        print(es, len(got), flush=True)
    sys.path.insert(0, str(HERE.parent / "topup3e"))
    import host_eval3e as HE
    for r in rows:
        r["slices_all"] = HE.slices(r)
    p = out / "dev3f.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    cnt = Counter(s for r in rows for s in r["slices_all"])
    (out / "dev3f_manifest.json").write_text(json.dumps({"n": len(rows), "seed": a.seed, "args": vars(a),
        "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16], "evalset": Counter(r["evalset"] for r in rows),
        "slices": dict(sorted(cnt.items()))}, indent=1))
    print(len(rows), dict(sorted(cnt.items())))


if __name__ == "__main__":
    G3.ORIG_BUCKETS_3F = G3.buckets
    main()
