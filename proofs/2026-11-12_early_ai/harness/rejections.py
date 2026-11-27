import json, collections, re
rows=[json.loads(l) for f in ("raw_v5/rows_s0.jsonl","raw_v5/rows_s1.jsonl") for l in open(f,encoding="utf-8")]
ai=[r for r in rows if r.get("gated") and r.get("source","").startswith("device:")]
rej=[r for r in ai if "rejected" in r.get("source","")]
print("ai",len(ai),"rejected",len(rej))
c=collections.Counter()
for r in rej:
    for e in (r.get("errors") or ["(no error text)"]):
        c[re.sub(r"\d+(\.\d+)?","N",e)[:120]]+=1
for k,n in c.most_common(30): print(n,k)
print("by shape rej/all", {s:(sum(1 for r in rej if r['shape']==s), sum(1 for r in ai if r['shape']==s)) for s in sorted(set(r['shape'] for r in ai))})
print("by k", {k:(sum(1 for r in rej if r['k']==k), sum(1 for r in ai if r['k']==k)) for k in range(3,9)})
print("by role", collections.Counter(r['role'] for r in rej))
w=[r for r in rej if any('inspect_' in e for e in (r.get('errors') or []))]
print("checklist-rejected: severity shown", collections.Counter(r.get('severity') for r in w), "checklist", collections.Counter(tuple(r.get('checklist') or []) for r in w).most_common(8))
print("gold of those", collections.Counter(r.get('gold_status') for r in w))
