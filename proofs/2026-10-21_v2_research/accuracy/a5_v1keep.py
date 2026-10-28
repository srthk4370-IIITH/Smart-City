"""v1 placement study with the same refine.go keep-early-spike/dip rule (apples-to-apples with the app-chain number)."""
import json
from pathlib import Path
from a1_confusion import parse, norm
V1 = Path(__file__).resolve().parents[2] / "2026-10-16_placement_study"
tr = {(p["id"], p["n"]): p["truth"]["pattern"] for p in map(json.loads, open(V1 / "prompts.jsonl", encoding="utf-8"))}
pr = {}
for r in map(json.loads, open(V1 / "samples.jsonl", encoding="utf-8")):
    a = parse(r["text"]); pr[(r["id"], r["n"])] = norm(a.get("pattern", "")) if a else "INVALID"
ids = sorted({k[0] for k in tr})
k = k2 = 0
for i in ids:
    e, p18, p36 = pr[(i, 8)], pr[(i, 18)], pr[(i, 36)]
    t = tr[(i, 36)]
    k += p36 == t
    if e in ("spike", "dip") and p36 == "stable": p36 = e
    k2 += p36 == t
print(f"v1 3h plain {k}/{len(ids)}={k/len(ids):.3f}; with keep-early rule {k2}/{len(ids)}={k2/len(ids):.3f}")
