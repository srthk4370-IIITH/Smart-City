"""Round 2: borderline-severity incidents (owner priority: severity consistency) -> data/incidents_border.jsonl"""
import json, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import families as F, gen_incidents as G
F.FAMILIES["borderline"] = F.f_borderline
R = random.Random(77)
rows = []
for i in range(int(sys.argv[1]) if len(sys.argv) > 1 else 600):
    ex = G.make(R, "borderline", "train", [])
    ex["id"] = "border-%05d" % i
    rows.append(ex)
with open(os.path.join(HERE, "..", "data", "incidents_border.jsonl"), "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
import collections
print("border", len(rows), collections.Counter(json.loads(r["messages"][-1]["content"])["severity"] for r in rows))
