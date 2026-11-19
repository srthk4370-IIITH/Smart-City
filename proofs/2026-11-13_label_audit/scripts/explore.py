import json, collections, re
P='/mnt/c/Users/hp/Desktop/qidk/proofs/'
pool=[json.loads(l) for l in open(P+'2026-10-25_reasoner_final/data/real_pool.jsonl')]
c=collections.Counter()
for r in pool:
    g=r['gold']; c[(r['role'],g['status'],g.get('fault_kind'),r['family'])]+=1
for k,v in sorted(c.items()):
    if k[1]=='sensor_fault': print(k,v)
print(collections.Counter(r['split'] for r in pool))
print(collections.Counter(r['gold']['status'] for r in pool))
