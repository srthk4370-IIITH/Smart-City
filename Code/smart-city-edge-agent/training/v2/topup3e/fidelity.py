"""CUDA b11815 vs CPU 620d222 (= board 207/208) on the same rows: identical decisions?"""
import json, sys
from pathlib import Path
a = {s["id"]: s for s in map(json.loads, open(sys.argv[1]))}
b = {s["id"]: s for s in map(json.loads, open(sys.argv[2]))}
ids = [i for i in a if i in b]
same = lambda i: all((a[i].get("pred") or {}).get(k) == (b[i].get("pred") or {}).get(k) for k in ("pattern", "status", "likely_cause"))
txt = sum(a[i]["text"] == b[i]["text"] for i in ids)
res = {"n": len(ids), "same_pattern_status_cause": sum(map(same, ids)), "same_text": txt,
       "pattern_ok": [sum(bool(a[i]["pattern"]) for i in ids), sum(bool(b[i]["pattern"]) for i in ids)]}
print(json.dumps(res)); Path(sys.argv[3]).write_text(json.dumps(res, indent=1))
