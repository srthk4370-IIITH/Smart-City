"""noharm.py CAND_DIR S1750_DIR SYN_CAND SYN_S1750 OUT.json: does the top-up harm independence / synthetic sets vs snap_1750?
Per set (unseen_metric, unseen_layout, campus, calm_fault, rename, synthetic slice) and field (status, pattern, cause, dq): paired by
row id, exact two-sided sign test on discordant rows. HARM = candidate worse with p < 0.05 (beyond noise). Exit 0 no harm, 1 harm."""
import json
import math
import sys

cd, sd, syc, sys_, out = sys.argv[1:6]


def rd(p):
    try:
        return {x["id"]: x for x in (json.loads(l) for l in open(p))}
    except FileNotFoundError:
        return None


def p2(w, l):
    n = w + l
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(w, l) + 1)) / 2 ** n)


res, harm = {}, []
pairs = [(s, f"{cd}/{s}_v3.jsonl", f"{sd}/{s}_v3.jsonl") for s in ("unseen_metric", "unseen_layout", "campus", "calm_fault", "rename")]
pairs.append(("synthetic_slice", syc, sys_))
for name, a, b in pairs:
    A, B = rd(a), rd(b)
    if A is None or B is None:
        res[name] = "missing"
        harm.append(name + ":missing")
        continue
    ids = sorted(set(A) & set(B))
    r = {"n": len(ids)}
    for k in ("status", "pattern", "cause", "dq"):
        v = [i for i in ids if A[i].get(k) is not None and B[i].get(k) is not None]
        if not v:
            continue
        w = sum(bool(A[i][k]) and not bool(B[i][k]) for i in v)
        l_ = sum(bool(B[i][k]) and not bool(A[i][k]) for i in v)
        pa, pb = 100 * sum(bool(A[i][k]) for i in v) / len(v), 100 * sum(bool(B[i][k]) for i in v) / len(v)
        p = p2(w, l_)
        r[k] = {"topup": round(pa, 1), "snap_1750": round(pb, 1), "wins": w, "losses": l_, "p": round(p, 4), "harm": l_ > w and p < 0.05}
        if r[k]["harm"]:
            harm.append(f"{name}.{k} {pb:.1f}->{pa:.1f}")
    res[name] = r
json.dump({"no_harm": not harm, "harm": harm, "sets": res}, open(out, "w", newline="\n"), indent=1)
print(json.dumps({"no_harm": not harm, "harm": harm}))
sys.exit(1 if harm else 0)
