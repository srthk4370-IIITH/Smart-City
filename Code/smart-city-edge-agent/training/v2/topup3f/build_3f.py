"""3f training files.
  r3  (from v2):  3e run2 file (259 pairs + 518 gold replay, unchanged) + status-preserving anchors (ref = v2).
  rep (from c49): anchors (ref = c49) + the same number of gold replay rows from run2's replay (repair top-up).
  python build_3f.py --kind r3 --anchors anchors_v2.jsonl --out train3f_r3.jsonl
  python build_3f.py --kind rep --anchors anchors_c49.jsonl --out train3f_rep.jsonl [--replay-ratio 1]
"""
import argparse, hashlib, json, random, sys
from collections import Counter
from pathlib import Path
D = Path.home() / "smartcity_runs" / "agents_v2_topup3e" / "data"
rd = lambda p: [json.loads(l) for l in open(p, encoding="utf-8")]
ap = argparse.ArgumentParser()
ap.add_argument("--kind", choices=["r3", "rep"], required=True)
ap.add_argument("--anchors", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--replay-ratio", type=float, default=1.0)
ap.add_argument("--max-anchors", type=int, default=0)
a = ap.parse_args()
r2 = rd(D / "train3e_r2.jsonl")
anc = rd(a.anchors)
if a.max_anchors:
    anc = anc[:a.max_anchors]
rng = random.Random("3f-" + a.kind)
if a.kind == "r3":
    items = r2 + anc
else:
    rep = [x for x in r2 if x["type"] == "sft"]
    items = anc + rng.sample(rep, min(len(rep), int(round(len(anc) * a.replay_ratio))))
rng.shuffle(items)
with open(a.out, "w", encoding="utf-8") as fh:
    for x in items:
        fh.write(json.dumps(x, ensure_ascii=False) + "\n")
man = {"kind": a.kind, "rows": len(items), "types": Counter(x["type"] for x in items),
       "pairs_by_field": Counter((x.get("field"), bool(x.get("anchor"))) for x in items if x["type"] == "pair").most_common(),
       "status_pairs_gold_to_rej": Counter(f"{x['gold']}->{x['pred']}" for x in items if x["type"] == "pair" and x["field"] == "status").most_common(),
       "anchors": a.anchors, "sha256_16": hashlib.sha256(Path(a.out).read_bytes()).hexdigest()[:16], "args": vars(a)}
Path(a.out).with_suffix(".manifest.json").write_text(json.dumps(man, indent=1, default=str))
print(json.dumps(man, default=str))
