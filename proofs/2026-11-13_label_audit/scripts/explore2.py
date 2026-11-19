import json, collections, re
P='/mnt/c/Users/hp/Desktop/qidk/proofs/'
pool=[json.loads(l) for l in open(P+'2026-10-25_reasoner_final/data/real_pool.jsonl')]
hp=collections.Counter(h.split(':')[0] for r in pool for h in r['head']); print(hp)
seen=set()
for r in pool:
    g=r['gold']
    if g['status']!='sensor_fault' or r['role']!='air_quality': continue
    k=(r['node'],r['metric'],r['end_epoch'])
    if k in seen: continue
    seen.add(k)
    print('##',r['id'],r['metric'],g['fault_kind'],r['sub'],g['pattern'],'pred=',(r['pred'] or {}).get('status'))
    print('  ',' | '.join(h for h in r['head'] if not h.startswith(('NODE','METRIC','WINDOW'))))
    E=dict(r['ev']); print('   E1',E.get('E1'),'| E2',E.get('E2'),'| E3',E.get('E3'),'| E5',E.get('E5'),'| E8',E.get('E8'),'| E9',E.get('E9'),'| E10',E.get('E10'))
