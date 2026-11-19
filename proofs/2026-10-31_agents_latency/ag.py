import json,sys,glob,os
def load(f):
    t=open(f).read().strip().splitlines()
    for l in reversed(t):
        try:
            d=json.loads(l)
            if 'outputs' in d or 'total_ms' in d: return d
        except Exception: pass
    return None
base=None
for f in sys.argv[1:]:
    d=load(f)
    if not d: print(f,'NONE'); continue
    outs=d.get('outputs') or d.get('results') or []
    txt=[o.get('text') for o in outs]
    if base is None: base=(f,txt)
    same=sum(a==b for a,b in zip(base[1],txt))
    toks=[o.get('tokens') for o in outs]
    print(os.path.relpath(f), {k:v for k,v in d.items() if not isinstance(v,(list,dict))}, 'tok',sum(t or 0 for t in toks), 'same_as_first',same,'/',len(txt))
