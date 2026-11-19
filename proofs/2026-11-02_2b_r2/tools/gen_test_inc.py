"""r2 incident TEST set (never trained on): the unchanged round-1 generator on the HELD-OUT split (held-out nodes and held-out
real-agent rows, as RWH / RWH-2), new seed, every family equally weighted (real-agent at the round-1 share), verify.py pass,
no user prompt that occurs in RWH, RWH-2, round-1 dev or the r2 training rows.
  python3 gen_test_inc.py --out FILE --n 600 --seed 6161 --exclude train1.jsonl [train2.jsonl ...]"""
import argparse
import collections
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
R1 = os.path.join(QIDK, "proofs", "2026-10-25_reasoner_final")
sys.path.insert(0, os.path.join(R1, "pipeline"))
import gen_incidents as G  # noqa: E402
import families as F  # noqa: E402
import verify as V  # noqa: E402


def users(p):
    out = set()
    for l in open(p, encoding="utf-8"):
        r = json.loads(l)
        if r.get("tools") == "incident":
            out.add(r["messages"][1]["content"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed", type=int, default=6161)
    ap.add_argument("--exclude", nargs="+", default=[])
    a = ap.parse_args()
    assert a.seed not in (7, 31, 47, 4242)
    D1 = os.path.join(R1, "data")
    ex = set()
    for p in [os.path.join(D1, n) for n in ("incidents_rwh.jsonl", "incidents_rwh.ok.jsonl", "incidents_dev.jsonl", "incidents_dev.ok.jsonl")] + a.exclude:
        ex |= users(p)
    heldpool = [json.loads(l) for l in open(os.path.join(D1, "real_pool.jsonl"), encoding="utf-8")]
    heldpool = [r for r in heldpool if r["split"] == "heldout"]
    fams = list(F.FAMILIES)
    kinds = fams + ["real"]
    wts = [1.0] * len(fams) + [len(fams) * 0.45]
    R = random.Random(a.seed)
    out, tries = [], 0
    while len(out) < a.n and tries < a.n * 30:
        tries += 1
        r = G.make(R, R.choices(kinds, wts)[0], "heldout", heldpool)
        u = r["messages"][1]["content"]
        if u in ex or V.check_incident(r):
            continue
        ex.add(u)
        r["id"] = "t2inc-%05d" % len(out)
        out.append(r)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    c = collections.Counter(r["family"].split(":")[0].split("+")[0] for r in out)
    sev = collections.Counter(json.loads(r["messages"][-1]["content"])["severity"] for r in out)
    print(json.dumps({"rows": len(out), "seed": a.seed, "families": len(c), "severity": dict(sev), "per_family": dict(c.most_common())}))


if __name__ == "__main__":
    main()
