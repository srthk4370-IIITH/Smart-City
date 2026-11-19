"""dry-run stand-in for hosteval.py: 'predicts' the gold with a deterministic 10 % status error (no GPU, no server)"""
import argparse, hashlib, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kaggle"))
import rows as RW
ap = argparse.ArgumentParser(); ap.add_argument("--model"); ap.add_argument("--rows"); ap.add_argument("--out")
ap.add_argument("--limit", type=int, default=0); ap.add_argument("--max-new", type=int, default=400); a = ap.parse_args()
rows = [RW.norm(r) for r in RW.read_jsonl(a.rows)][: a.limit or None]
with open(a.out, "w") as f:
    for r in rows:
        g = json.loads(r["completion"][:-len(RW.EOT)])
        if int(hashlib.md5((a.model + r["id"]).encode()).hexdigest(), 16) % 10 == 0:
            g["status"] = "normal" if g["status"] != "normal" else "warning"
        t = json.dumps(g, separators=RW.JSON_SEP)
        s = RW.score(r["gold"], RW.cut_at_action(t) + '"action"'); s.update(id=r["id"], text=t, role=r["role"], family=r["family"])
        f.write(json.dumps(s) + "\n")
print("stub eval", len(rows))
