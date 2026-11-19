import json, collections, re
P='/mnt/c/Users/hp/Desktop/qidk/proofs/'
pool=[json.loads(l) for l in open(P+'2026-10-25_reasoner_final/data/real_pool.jsonl')]
done=collections.Counter()
for r in pool:
    g=r['gold']
    k=(r['role'],g['status'],g.get('fault_kind'))
    if r['role'] in('hvac','occupancy','water','power','weather') and done[k]<1 and (g['status']=='sensor_fault' or done[k]<1):
        done[k]+=1
        print('##',r['role'],r['metric'],g['status'],g['fault_kind'],r['sub'],g['pattern'],'pred=',(r['pred'] or {}).get('status'))
        print('  ',' | '.join(h for h in r['head'] if not h.startswith(('NODE','WINDOW'))))
        for e in r['ev']: print('    ',e[0],e[1])
