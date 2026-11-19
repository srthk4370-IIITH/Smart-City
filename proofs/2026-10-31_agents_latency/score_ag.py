import json,re,sys,glob,statistics as S
D=sys.argv[1]
ab=open(D+'/ab.log').read()
def rows(n):
    r={}
    for m in re.finditer(rf'  {n} (a\d\d): wall (\d+) ms "prefill_ms":([\d.]+) htpd: draft steps (\d+) proposed (\d+) accepted (\d+)',ab):
        r[m.group(1)]=dict(wall=int(m.group(2)),pf=float(m.group(3)),steps=int(m.group(4)),acc=int(m.group(6)))
    return r
def texts(n,r):
    try: d=json.loads(open(f'{D}/{n}_{r}.json').read().strip().splitlines()[-1])
    except Exception: return None
    return [o.get('text') for o in d.get('outputs',[])], [o.get('tokens') for o in d.get('outputs',[])]
out=[]
R={n:rows(n) for n in ('base','v9e','base2')}
for n in R:
    r=R[n]; w=sum(x['wall'] for x in r.values()); st=sum(x['steps'] for x in r.values()); pf=sum(x['pf'] for x in r.values())
    dec=w-pf
    out.append(f"{n}: {len(r)} requests, wall sum {w/1000:.2f} s (mean {w/len(r):.0f} ms), prefill {pf/1000:.2f} s, after-prefill {dec/1000:.2f} s, draft steps {st}, ms/step after prefill {dec/st:.1f}")
for a,b in (('base','base2'),('base','v9e'),('base2','v9e')):
    same=0; n=0; diff=[]
    for r in sorted(R['base']):
        ta=texts(a,r); tb=texts(b,r); n+=1
        if ta and tb and ta[0]==tb[0]: same+=1
        else: diff.append(r)
    out.append(f"identical outputs {a} vs {b}: {same}/{n} requests  diff {diff}")
for n in ('base','v9e','base2'):
    t=texts(n,'a00b'); out.append(f"{n} a00b (after swap) same as {n} a00: {t[0]==texts(n,'a00')[0] if t else None}")
print('\n'.join(out))
