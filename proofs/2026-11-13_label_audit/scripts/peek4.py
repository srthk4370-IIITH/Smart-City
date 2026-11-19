import json,sys
f=sys.argv[1]; k=0
for l in open(f):
    r=json.loads(l)
    if r.get('tools')!='chat': continue
    if sys.argv[2]=='hard' and not r.get('hard'): continue
    if sys.argv[2]=='easy' and (r.get('hard') or len(r['messages'])<5): continue
    print({a:b for a,b in r.items() if a!='messages'})
    for m in r['messages'][1:]: print(json.dumps(m)[:700])
    k+=1
    if k>=1: break
