"""Error breakdown of B50 (live GGUF, orig variant) by domain: status confusion gold->pred, top pattern/cause confusions,
by family. -> raw/A_holes.json"""
import json, sys, collections
from pathlib import Path
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post")
import common_v2 as C
RAW = Path(__file__).resolve().parent.parent / "raw"
R = {r["id"]: r for r in C.read_jsonl(RAW / "rows_A.jsonl") if r["variant"] == "orig"}
out = {}
for l in open(RAW / "samples_A.jsonl"):
    s = json.loads(l)
    if s["variant"] != "orig": continue
    r = R[s["id"]]; g = C.gold_of(r); p = s.get("pred") or {}; d = r["role"]
    o = out.setdefault(d, {k: collections.Counter() for k in ("status", "pattern", "cause", "family_err", "family_n")})
    o["family_n"][r.get("family")] += 1
    if not s["status"]: o["status"][f'{g["status"]}->{p.get("status")}'] += 1
    if not s["pattern"]: o["pattern"][f'{g["pattern"]}->{p.get("pattern")}'] += 1
    if not s["cause"]: o["cause"][f'{g.get("likely_cause")}->{p.get("likely_cause")}'] += 1
    if not (s["status"] and s["pattern"] and s["cause"]): o["family_err"][r.get("family")] += 1
res = {d: {k: v.most_common(8) for k, v in o.items()} for d, o in out.items()}
(RAW / "A_holes.json").write_text(json.dumps(res, indent=1))
for d in ("power", "water", "air_quality", "weather"):
    print(d); [print("  ", k, v) for k, v in res[d].items()]
