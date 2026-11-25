cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn/data/final_v2
python3 - <<'P'
import json,re
n=0
for l in open('train_new.jsonl',encoding='utf-8'):
    r=json.loads(l)
    if r['tools']=='incident_v4' and '+refine' in r['family'] and 'prev_wrong' in r['family']:
        u=r['messages'][1]['content']; i=u.find('RE-CHECK'); print(r['family']); print(u[i-50:i+500]); g=json.loads(r['messages'][-1]['content'][r['messages'][-1]['content'].find('{'):]); print(g['severity'], '|', g['explanation'], '|', g['causal_chain']); n+=1
        if n>=2: break
P
