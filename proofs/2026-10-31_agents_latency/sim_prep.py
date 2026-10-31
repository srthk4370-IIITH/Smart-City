# Build the agent-request sequence from the board's incidents.jsonl (real app), dedupe revisions, tokenize prompt + generation.
import json,sys,subprocess,os
src=sys.argv[1]; out=sys.argv[2]
seen=set(); reqs=[]
for l in open(src):
    try: d=json.loads(l)
    except Exception: continue
    ags=d.get('agents') or []
    key=(d.get('id'), tuple((a.get('ref'),a.get('raw')) for a in ags))
    if key in seen or not ags: continue
    seen.add(key)
    req=[]
    for a in ags:
        p=a.get('prompt') or ''; r=a.get('raw') or ''
        if not p or not r.startswith('{"pattern": "'): continue
        if not p.endswith('{"pattern": "'): continue
        g=r[len('{"pattern": "'):]
        i=g.find(', "action"')
        if i>=0: g=g[:i+len(', "action"')]
        req.append((d.get('id'),a.get('role'),p,g,a.get('gen_tokens'),a.get('latency_ms'),a.get('ttft_ms')))
    if req: reqs.append(req)
flat=[x for r in reqs for x in r]
blob='\x1e'.join([x[2] for x in flat]+[x[2]+x[3] for x in flat])
T=subprocess.run([os.path.expanduser('~/tok'),os.path.expanduser('~/gpu_work/llama.cpp/models/ggml-vocab-llama-bpe.gguf')],input=blob.encode(),capture_output=True).stdout.decode().splitlines()
n=len(flat); P=[list(map(int,t.split())) for t in T[:n]]; F=[list(map(int,t.split())) for t in T[n:2*n]]
k=0; res=[]; bad=0
for r in reqs:
    rr=[]
    for x in r:
        p,f=P[k],F[k]; k+=1
        if f[:len(p)]!=p: bad+=1; continue
        rr.append({'inc':x[0],'role':x[1],'prompt':p,'gen':f[len(p):],'gen_tokens':x[4],'lat':x[5],'ttft':x[6]})
    if rr: res.append(rr)
json.dump(res,open(out,'w'))
print('requests',len(res),'streams',sum(len(r) for r in res),'prefix-mismatch',bad)
