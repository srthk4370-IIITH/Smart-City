#!/usr/bin/env python3
# Host (WSL CPU, q2b base GGUF) check: agent outputs of htpd_v9e (default env, and v9e drafts on) vs htpd_v9d.
import json,os,socket,subprocess,sys,time
D='/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_agents_latency'; O=D+'/host'; os.makedirs(O,exist_ok=True)
M=os.path.expanduser('~/q2bjob/gguf/q2b_base_q4_0.gguf')
REQS=['a%02d'%i for i in range(int(os.environ.get('NREQ','6')))]
def call(port,req):
    s=socket.create_connection(('127.0.0.1',port),timeout=3600); s.sendall((json.dumps(req)+'\n').encode()); f=s.makefile('rb')
    while True:
        l=f.readline()
        if not l: return None
        d=json.loads(l)
        if 'outputs' in d or 'error' in d: return d
cfgs=[('v9d',os.path.expanduser('~/v9host/htpd_v9d'),{}),('v9e_off',os.path.expanduser('~/v9host/htpd_v9e'),{}),
      ('v9e_on1',os.path.expanduser('~/v9host/htpd_v9e'),{'HTPD_AGENT_NGMAX':'8','HTPD_AGENT_RECENT_MAX':'500','HTPD_AGENT_CORPUS':'/tmp/ag_host_corpus.txt'}),
      ('v9e_on2',os.path.expanduser('~/v9host/htpd_v9e'),{'HTPD_AGENT_NGMAX':'8','HTPD_AGENT_RECENT_MAX':'500','HTPD_AGENT_CORPUS':'/tmp/ag_host_corpus.txt'})]
try: os.remove('/tmp/ag_host_corpus.txt')
except OSError: pass
allres={}
for name,b,extra in cfgs:
    env={k:v for k,v in os.environ.items() if not k.startswith('HTPD_')}
    env.update({'HTPD_DRAFT':'1','HTPD_DRAFT_K':'8','HTPD_PREFIX_CACHE':'1','HTPD_AGENT_MAX_NEW':'80','HTPD_JSON_ABORT':'2','HTPD_LEGACY_PREFILL':'1'}); env.update(extra)
    log=open(f'{O}/{name}.log','w')
    p=subprocess.Popen([b,'-m',M,'--device','CPU','-t','4','--agents','2','--agent-ctx','1280','--synth-ctx','1024','--port','18393'],env=env,stdout=log,stderr=log)
    for _ in range(600):
        if 'htpd: ready in' in open(f'{O}/{name}.log',errors='replace').read(): break
        time.sleep(1)
    res=[]
    for r in REQS:
        t=time.time(); d=call(18393,json.load(open(f'{D}/agl/{r}.json'))); w=time.time()-t
        res.append({'req':r,'wall':round(w,1),'texts':[o.get('text') for o in d.get('outputs',[])]})
        print(name,r,round(w,1),flush=True)
    p.terminate(); p.wait(60); log.close()
    allres[name]=res
    json.dump(allres,open(f'{O}/results.json','w'),indent=1)
base=allres['v9d']
for n,res in allres.items():
    same=sum(a['texts']==b['texts'] for a,b in zip(base,res))
    print(n,'identical requests vs v9d',same,'/',len(base),'| total wall',round(sum(x['wall'] for x in res),1))
os.system(f"grep -h 'draft steps\|v9e agent' {O}/*.log")
