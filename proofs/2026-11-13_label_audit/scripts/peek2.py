import json,sys
f=sys.argv[1]; kind=sys.argv[2]; n=int(sys.argv[3]) if len(sys.argv)>3 else 1
k=0
for l in open(f):
    r=json.loads(l)
    if r.get('tools')!=kind and kind!='any': continue
    print({a:(b if a!='messages' else [(m['role'],len(m.get('content') or ''),list(m.keys())) for m in b]) for a,b in r.items()})
    for m in r['messages']:
        c=m.get('content') or ''
        print('--',m['role'], (c[:700]+' ... '+c[-500:]) if len(c)>1300 else c, m.get('reasoning_content','')[:300] if m.get('reasoning_content') else '')
    k+=1
    if k>=n: break
