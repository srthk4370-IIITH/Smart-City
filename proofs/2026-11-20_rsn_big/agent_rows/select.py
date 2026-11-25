import json,glob,re,hashlib,random,collections,os
D="/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/agent_rows"
os.chdir("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn")
H=lambda s:hashlib.md5(s.encode()).hexdigest()
def eh(t):
    L=re.findall(r"^E\d+ .*$",t,re.M); return H("\n".join(L)) if len(L)>=3 else None
bad=set(); pids=set()
for l in open("data/final_v2/work/windows.jsonl"):
    x=json.loads(l); bad.add(H(x["prompt"])); bad.add(eh(x["prompt"])); pids.add(x.get("pool_id"))
for f in glob.glob("data/final_v2/tests/*.jsonl"):
    for l in open(f,encoding="utf-8"):
        s=l.replace("\n","\n"); bad.add(H(l))
        for m in re.finditer(r"(?:E\d+ [^\n\"]*\n){3,}",s):
            bad.add(H("\n".join(re.findall(r"^E\d+ .*$",m.group(0),re.M))))
        try: d=json.loads(l)
        except: continue
        for k in ("prompt","text"):
            if isinstance(d.get(k),str): bad.add(eh(d[k]))
bad.discard(None); pids.discard(None)
R=[json.loads(l) for l in open(D+"/raw_windows.jsonl")]
keep=[];seen=set();dr=0
for x in R:
    e=eh(x["prompt"])
    if e in bad or x.get("pool_id") in pids or e in seen: dr+=1; continue
    seen.add(e); keep.append(x)
print("dropped",dr,"kept",len(keep))
nn=[x for x in keep if x["gold"]["status"]!="normal"]; no=[x for x in keep if x["gold"]["status"]=="normal"]
random.Random(1).shuffle(no)
sel=(nn+no[:max(0,4500-len(nn))])[:4500]; random.Random(2).shuffle(sel)
for i,x in enumerate(sel): x["wid"]="big-%05d"%i
open(D+"/windows.jsonl","w",newline="\n").write("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in sel))
C=collections.Counter
print(len(sel),C(x["src"] for x in sel),C(x["gold"]["status"] for x in sel),C(x["role"] for x in sel))
print(C(("short<48" if x["n"]<48 else "48" if x["n"]==48 else "long>48") for x in sel))
print(C(x["gold"]["pattern"] for x in sel).most_common(40))
print(C("out" if "outdoor" in x["card_id"] or x["role"]=="weather" else "in" for x in sel))
