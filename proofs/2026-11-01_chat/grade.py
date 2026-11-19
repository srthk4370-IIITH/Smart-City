import json,sys,statistics as S
rows=[json.loads(l) for l in open(sys.argv[1])]; g=json.load(open(sys.argv[2]))
p=sum(1 for r in rows if g[str(r['i'])][0]=='P'); ms=[r.get('ms') or r['wall_s']*1000 for r in rows]
model=[r['ms'] for r in rows if r.get('ms') and r['ms']>1000]
print('pass %d/%d = %.1f%%; median latency %.2f s; mean %.1f s; model-answered %d (median %.1f s); errors %d busy %d'%(p,len(rows),100*p/len(rows),S.median(ms)/1000,S.mean(ms)/1000,len(model),S.median(model)/1000 if model else 0,sum(bool(r.get('error')) for r in rows),sum(bool(r.get('busy')) for r in rows)))
