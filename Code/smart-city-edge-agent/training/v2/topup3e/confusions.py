"""Pattern flips ref -> cand on the host eval (losses and wins), top confusions.  python confusions.py REF CAND"""
import collections
import json
import sys
from pathlib import Path

E = Path.home() / "smartcity_runs/agents_v2_topup3e/eval/eval"
a = {s["id"]: s for s in map(json.loads, open(E / sys.argv[1] / "samples.jsonl"))}
b = {s["id"]: s for s in map(json.loads, open(E / sys.argv[2] / "samples.jsonl"))}
pp = lambda s: (s.get("pred") or {}).get("pattern")
loss, win = collections.Counter(), collections.Counter()
for i in a:
    if i in b and a[i]["pattern"] != b[i]["pattern"]:
        (loss if a[i]["pattern"] else win)[(pp(a[i]), pp(b[i]))] += 1
print("losses ref->cand", loss.most_common(10))
print("wins   ref->cand", win.most_common(10))
