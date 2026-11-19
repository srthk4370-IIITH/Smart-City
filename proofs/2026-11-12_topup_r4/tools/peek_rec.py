import json, sys, collections
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
u = collections.defaultdict(set)
for r in rows:
    u[r["kind"]].add(json.dumps(r["gold_calls"]))
print({k: len(v) for k, v in u.items()})
seen = set()
for r in rows:
    if r["kind"] in seen or not r["kind"].startswith("x_"): continue
    seen.add(r["kind"])
    print("##", r["kind"], r["reasoning_type"], r["hops"], r["answer_key"], "| Q:", [m["content"] for m in r["messages"] if m["role"] == "user"][-1])
    print("   A:", r["reference_answer"][:400])
