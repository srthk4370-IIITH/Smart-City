import json, collections
P='/mnt/c/Users/hp/Desktop/qidk/proofs/'
A={}
for l in open(P+'2026-11-13_label_audit/audit.jsonl'):
    r=json.loads(l); A[(r['file'],r['id'])]=r
sm={'rwh':'rwh','rwh2':'rwh2','dev':'dev','test_r2':'test_r2'}
out=[]
for l in open(P+'2026-11-12_agents_holes/raw/B_claims.jsonl'):
    c=json.loads(l)
    if not c['family'].startswith('real_agent'): continue
    a=A.get((sm[c['suite']],c['id']))
    print(c['suite'],c['id'],c['domain'],'gold',c['gold_sev'],'agent',c['agent_status'],'rep',c['rep_sev'],'caught',c['caught'],'->',a['supported'] if a else None,a['metric'] if a else '',a['node'] if a else '',(a['reason'][:90] if a else ''))
