import json,sys
f=sys.argv[1]
for l in open(f):
    if '"real_agent' in l:
        r=json.loads(l); print({k:(v if k!='messages' else [(m['role'],len(m['content'])) for m in v]) for k,v in r.items()})
        print(r['messages'][-1]['content'][:300]); break
