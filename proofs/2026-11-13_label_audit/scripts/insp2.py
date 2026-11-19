import json, collections, sys, re
P='/mnt/c/Users/hp/Desktop/qidk/proofs/'
A={json.loads(l)['pool_id']:json.loads(l) for l in open(P+'2026-11-13_label_audit/pool_audit.jsonl')}
pool=[json.loads(l) for l in open(P+'2026-10-25_reasoner_final/data/real_pool.jsonl')]
want=[('hvac','warning','running_empty_room'),('hvac','warning','stuck_on'),('weather','warning','exponential_increase'),('air_quality','warning','exponential_increase'),('hvac','sensor_fault','biased_reading'),('weather','sensor_fault','noise_increase'),('water','sensor_fault','quantised'),('air_quality','sensor_fault','stuck'),('water','sensor_fault','dropout'),('air_quality','normal','co2_decay')]
c=collections.Counter()
for r in pool:
    a=A[r['id']]
    k=(r['role'],r['gold']['status'],r['sub'])
    if a['supported']=='n' and k in want and c[k]<2:
        c[k]+=1; print('##',k,r['metric'],r['gold'].get('fault_kind'),'pred',(r['pred'] or {}).get('status'),'|',' '.join(h for h in r['head'] if h.startswith(('LIMITS','TANK','WINDOW'))))
        for e in r['ev']: print('   ',e[0],e[1])
