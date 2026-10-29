"""speed.sh A/B scoring: v8x3 split-3 (spxa) vs v8x4 row padding (sppa pad 6, sppb pad 5) on the same prompts.
A pad config passes with parse n/n, severity+label identical to v8x3 on >= n-1, mean time <= 0.95 x v8x3."""
import glob
import json
import re
import sys

d = sys.argv[1]


def load(n):
    o = {}
    for p in glob.glob(f"{d}/{n}_q*_*.json"):
        q, k = map(int, re.search(r"_q(\d+)_(\d+)\.json", p).groups())
        if k == 0:
            continue
        for line in open(p, encoding="utf-8"):
            if '"outputs"' not in line:
                continue
            x = json.loads(line)
            j = None
            try:
                j = json.loads(x["outputs"][0]["text"])
            except Exception:
                pass
            o[q] = (j, x.get("total_ms", 0) / 1000)
    return o


base = load("spxa")
mb = sum(t for _, t in base.values()) / max(1, len(base))
print(f"base v8x3: n={len(base)} parse={sum(1 for j, _ in base.values() if j)} mean {mb:.1f} s")
best = None
for name, rows in (("sppa", 6), ("sppb", 5)):
    r = load(name)
    m = sum(t for _, t in r.values()) / max(1, len(r))
    parse = sum(1 for j, _ in r.values() if j)
    same = sum(1 for q, (j, _) in r.items()
               if j and base.get(q, (None,))[0] and (j["severity"], j["label"]) == (base[q][0]["severity"], base[q][0]["label"]))
    ok = len(r) >= 6 and parse == len(r) and same >= len(r) - 1 and m <= 0.95 * mb
    print(f"{name} pad {rows}: n={len(r)} parse={parse} same sev+label={same} mean {m:.1f} s ({100 * (m - mb) / max(mb, 1e-9):+.1f}%) ok={int(ok)}")
    if ok and (best is None or m < best[1]):
        best = (rows, m)
print("BEST", best[0] if best else 0)
