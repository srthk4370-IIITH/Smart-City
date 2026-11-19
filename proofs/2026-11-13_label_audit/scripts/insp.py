import json, collections, sys, re
P='/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_label_audit/'
rows=[json.loads(l) for l in open(P+'pool_audit.jsonl')]
c=collections.Counter()
for r in rows:
    if r['supported']=='n': c[(r['role'],r['gold'],r['fault_kind'],r['sub'],re.sub(r'[\d.]+','#',r['reason'])[:70])]+=1
for k,v in c.most_common(45): print(v,k)
