# Lab set: the last 24 real app agent requests with 1-2 NPU agents (prompts verbatim from incidents.jsonl), in app order.
# Corpus for the lab arm: token ids of every agent output BEFORE the first lab request (no leakage).
# Deploy corpus: all outputs.
import json,sys,os
reqs=json.load(open(sys.argv[1])); src=sys.argv[2]; out=sys.argv[3]
os.makedirs(out+'/agl',exist_ok=True)
# reload prompts as text from incidents (reqs.json holds ids) in the same order as sim_prep
seen=set(); textreqs=[]
for l in open(src):
    try: d=json.loads(l)
    except Exception: continue
    ags=d.get('agents') or []
    key=(d.get('id'), tuple((a.get('ref'),a.get('raw')) for a in ags))
    if key in seen or not ags: continue
    seen.add(key)
    r=[a.get('prompt') for a in ags if (a.get('prompt') or '').endswith('{"pattern": "') and (a.get('raw') or '').startswith('{"pattern": "')]
    if r: textreqs.append((d.get('id'),r))
assert len(textreqs)==len(reqs), (len(textreqs),len(reqs))
idx=[i for i,r in enumerate(reqs) if len(r)<=2][-24:]
first=idx[0]
man=[]
for j,i in enumerate(idx):
    json.dump({'kind':'agents','prompts':textreqs[i][1]},open(f'{out}/agl/a{j:02d}.json','w'))
    man.append({'file':f'a{j:02d}','incident':textreqs[i][0],'streams':len(textreqs[i][1]),'roles':[x['role'] for x in reqs[i]]})
json.dump(man,open(out+'/agl/manifest.json','w'),indent=1)
def dump(rs,f):
    n=0
    with open(f,'w') as fp:
        for r in rs:
            for x in r:
                if len(x['gen'])>=2: fp.write(' '.join(map(str,x['gen']))+'\n'); n+=1
    return n
print('lab requests',len(idx),'streams',sum(m['streams'] for m in man),'first req index',first)
print('lab corpus outputs',dump(reqs[:first],out+'/agent_corpus_lab.txt'))
print('deploy corpus outputs',dump(reqs,out+'/agent_corpus_all.txt'))
