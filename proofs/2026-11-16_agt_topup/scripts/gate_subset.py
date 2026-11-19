"""gate_subset.py OUT: small re-gate sets (deterministic md5 order of the pair key) from the full agt_v3 gate sets, + the matching
B50 and snap_1750 samples sliced from the full 2026-11-15 gate run (greedy, same GGUFs -> same outputs), so only the candidate runs.
OUT/rows/<files>, OUT/gate_config.json (same thresholds), OUT/samples_s1750/<set>_{v3,b50}.jsonl, OUT/samples_cand/<set>_b50.jsonl"""
import hashlib
import json
import os
import sys
from pathlib import Path

O = Path(sys.argv[1])
GD = Path("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/agt_v3/gate")
CFG = json.load(open("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt/gate_config.json"))
OLD = Path(os.path.expanduser("~/smartcity_runs/agt_v3/post/gate/final_snap_1750"))
K = {"dev_paired": 400, "e1": 10 ** 9, "unseen_metric": 100, "unseen_layout": 100, "campus": 100, "calm_fault": 100, "rename": 60}
for d in ("rows", "samples_s1750", "samples_cand"):
    (O / d).mkdir(parents=True, exist_ok=True)


def rd(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def wr(p, rows):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def key(r):
    return str(r.get("pair_id") or r.get("base_id") or r["id"])


man = {}
for s, spec in CFG["sets"].items():
    v3 = rd(GD / spec["v3"])
    keys = sorted({key(r) for r in v3}, key=lambda k: hashlib.md5(k.encode()).hexdigest())[:K[s]]
    ks = set(keys)
    v3s = [r for r in v3 if key(r) in ks]
    wr(O / "rows" / spec["v3"], v3s)
    ids = {r["id"] for r in v3s}
    wr(O / "samples_s1750" / f"{s}_v3.jsonl", [x for x in rd(OLD / f"{s}_v3.jsonl") if x["id"] in ids])
    man[s] = {"keys": len(keys), "v3_rows": len(v3s)}
    if spec.get("b50"):
        b = [r for r in rd(GD / spec["b50"]) if key(r) in ks]
        wr(O / "rows" / spec["b50"], b)
        bid = {r["id"] for r in b}
        bs = [x for x in rd(OLD / f"{s}_b50.jsonl") if x["id"] in bid]
        wr(O / "samples_s1750" / f"{s}_b50.jsonl", bs)
        wr(O / "samples_cand" / f"{s}_b50.jsonl", bs)
        man[s].update(b50_rows=len(b), b50_samples=len(bs))
json.dump(dict(CFG, _doc="SUBSET re-gate (2026-11-16 top-up): " + CFG["_doc"], subset=man), open(O / "gate_config.json", "w", newline="\n"), indent=1)
print(json.dumps(man))
