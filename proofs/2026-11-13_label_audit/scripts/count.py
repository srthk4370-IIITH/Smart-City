import json, glob, collections
P='/mnt/c/Users/hp/Desktop/qidk/proofs/'
fs=glob.glob(P+'2026-11-06_4b_local/data/final/*.jsonl')+glob.glob(P+'2026-10-25_reasoner_final/data/incidents_*.jsonl')+[P+'2026-10-29_rsn_v3/kaggle/build/r1/heldout/incidents_rwh2.jsonl']+glob.glob(P+'2026-11-12_topup_r4/data/final/*.jsonl')
for f in fs:
    c=collections.Counter(); n=0
    for l in open(f):
        if '"real_agent' not in l: n+=1; continue
        r=json.loads(l); n+=1
        if str(r.get('family','')).startswith('real_agent'): c[(r.get('meta') or {}).get('severity','?')]+=1
    if c: print(f.replace(P,''), n, dict(c))
