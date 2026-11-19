"""v2 restart (coordinator 2026-10-30): keep run-1 rows of easy records and of hard records with >= 1 verified sample;
hard records without a pass are dropped so v2 (think budget 384 + compression pass) redoes them. Originals kept as
raw_<set>.run1.jsonl (written once)."""
import json, os, shutil, sys
D = os.path.dirname(os.path.abspath(__file__))
for n in ("dev", "train"):
    p = os.path.join(D, "raw_%s.jsonl" % n); b = os.path.join(D, "raw_%s.run1.jsonl" % n)
    if not os.path.exists(p):
        continue
    if not os.path.exists(b):
        shutil.copy(p, b)
    keep, drop = [], 0
    for l in open(b, encoding="utf-8"):
        o = json.loads(l)
        if not o["hard"] or any((s.get("v") or {}).get("pass") for s in o["samples"]):
            keep.append(l)
        else:
            drop += 1
    open(p + ".part", "w", encoding="utf-8").writelines(keep); os.replace(p + ".part", p)
    print(n, "kept", len(keep), "dropped (hard, no pass) ->redo", drop)
