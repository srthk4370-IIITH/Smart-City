"""Fidelity of LoRA-scaling screening: per pair of tags on the same rows -> identical text %, same predicted pattern /
status %, pattern/status accuracy of each. One line per pair.   python fid_cmp.py SET_DIR A:B [A:B ...]"""
import json, sys
from pathlib import Path
E = Path(sys.argv[1]).expanduser()
load = lambda t: {s["id"]: s for s in map(json.loads, open(E / "eval" / t / "samples.jsonl", encoding="utf-8"))}
for pair in sys.argv[2:]:
    a, b = pair.split(":"); A, B = load(a), load(b); ids = [i for i in A if i in B]; n = len(ids)
    pp = lambda s, k: (s.get("pred") or {}).get(k)
    same_t = sum(A[i]["text"] == B[i]["text"] for i in ids)
    same_p = sum(pp(A[i], "pattern") == pp(B[i], "pattern") for i in ids)
    same_s = sum(pp(A[i], "status") == pp(B[i], "status") for i in ids)
    acc = lambda D, k: sum(bool(D[i].get(k)) for i in ids)
    print(f"{a} vs {b} n={n}: text= {100*same_t/n:.1f}% pat= {100*same_p/n:.1f}% stat= {100*same_s/n:.1f}% | "
          f"p {acc(A,'pattern')}/{acc(B,'pattern')} s {acc(A,'status')}/{acc(B,'status')} json {acc(A,'json')}/{acc(B,'json')}")
