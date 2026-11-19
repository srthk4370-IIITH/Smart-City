import json,sys,re,collections
f=sys.argv[1]
hdr=collections.Counter(); other=collections.Counter(); n=0
ex=None
for l in open(f):
    r=json.loads(l)
    if r.get('tools')!='incident': continue
    n+=1
    if n>4000: break
    u=r['messages'][1]['content']
    for ln in u.split('\n'):
        m=re.match(r'(S\d+) \[([A-Z]+)',ln)
        if m: hdr[m.group(2)]+=1; continue
        if re.match(r'\s+S\d+\.E\d+',ln) or re.match(r'\s+- ',ln): continue
        k=re.sub(r'[\d.:+-]+','#',ln.strip())[:50]
        other[k]+=1
    if 'RELATED' in u and 'RE-CHECK' in u and ex is None: ex=u
print(hdr); 
for k,v in other.most_common(60): print(v,k)
print(ex)
