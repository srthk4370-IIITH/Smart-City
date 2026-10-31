import json,re,sys,collections
f=sys.argv[1]
n_ag=collections.Counter(); agent_s=[]; rsn=[]; fin=[]; per_call=collections.defaultdict(list)
keys=None; nlines=0
for l in open(f):
    try: d=json.loads(l)
    except Exception: continue
    nlines+=1
    if keys is None: keys=list(d.keys())
    for t in d.get('timeline') or []:
        m=t.get('msg') or ''
        r=re.match(r'Orchestrator: (\d+) sensor\(s\) to NPU agents',m)
        if r: n_ag[int(r.group(1))]+=1
        r=re.search(r'agent done in ([\d.]+)s \(first token ([\d.]+)s, (\d+) tokens',m)
        if r: agent_s.append((float(r.group(1)),float(r.group(2)),int(r.group(3))))
        r=re.match(r'Reasoner v3 report in ([\d.]+)s',m)
        if r: rsn.append(float(r.group(1)))
        r=re.match(r'Finished in ([\d.]+)s, (\d+) NPU',m)
        if r: fin.append(float(r.group(1)))
print('incident lines',nlines,'keys',keys)
print('NPU agents per AI run',sorted(n_ag.items()))
import statistics as S
def q(v): v=sorted(v); return (len(v), round(S.mean(v),2), v[len(v)//2], v[int(len(v)*.9)]) if v else None
print('agent done s (n,mean,med,p90)',q([a[0] for a in agent_s]),'first tok',q([a[1] for a in agent_s]),'tokens',q([a[2] for a in agent_s]))
print('reasoner s',q(rsn)); print('finished s',q(fin))
