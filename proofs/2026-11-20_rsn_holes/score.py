import json,re,os,collections,sys
O="/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_holes"
def rep(t):
    t=t if isinstance(t,str) else (t or {}).get("content","") if isinstance(t,dict) else ""
    i=t.find("{")
    while i>=0:
        try: return json.loads(t[i:t.rfind("}")+1])
        except Exception: i=t.find("{",i+1)
def txt(f):
    f=o.get("final"); return (f.get("content") if isinstance(f,dict) else f) or ""
NUM=re.compile(r"\d[\d,.]*")
out=[];bad=collections.defaultdict(list)
for fn in sorted(os.listdir(O+"/res/p2")):
    n=fn[:-6]; rows={json.loads(l)["id"]:json.loads(l) for l in open(f"{O}/sub/{n}.jsonl")}
    S=collections.Counter(); N=0; ws=[];tp=[]
    for l in open(f"{O}/res/p2/{fn}"):
        o=json.loads(l); r=rows[o["id"]]; N+=1; ws.append(o["wall_s"])
        f=txt(o); S["empty"]+=not f.strip(); S["err"]+=isinstance(o.get("final"),dict) and "error" in o["final"]
        for t in o["turns"]:
            if t.get("predicted_ms"): tp.append(t["predicted_n"]/(t["predicted_ms"]/1000))
        gold=r["messages"][-1]["content"]; names=[c["name"] for c in o["calls"]]
        if r.get("gold_calls") is not None and "chat" in n:
            gn=[c["name"] for c in r["gold_calls"]]
            ok=names==gn; S["calls_exact"]+=ok
            if not ok: bad["callmismatch:"+n].append((o["id"],r["messages"][1]["content"][:80],gn,names))
            S["nocall_when_needed"]+=(bool(gn) and not names); S["call_when_none"]+=(not gn and bool(names))
            ctx=r["messages"][0]["content"]+r["messages"][1]["content"]+json.dumps([c["result"] for c in o["calls"]])
            nums=[x.strip(".,") for x in NUM.findall(f)]; hn=[x for x in nums if x and x not in ctx]
            S["halluc_num"]+=bool(hn)
            if hn: bad["halluc:"+n].append((o["id"],f[:150],hn))
            ids=re.findall(r"INC-\d+",f); S["halluc_id"]+=any(i not in ctx for i in ids)
            S["gt3sent"]+=len(re.findall(r"[.!?](\s|$)",f))>3
            S["hasthink"]+=bool(o.get("think"))
        else:
            g=rep(gold); p=rep(o["final"]); 
            if g and "severity" in g:
                S["valid"]+=bool(p); sv=bool(p) and p.get("severity")==g["severity"]; S["sev_ok"]+=sv
                if p and not sv: bad["sev:"+n].append((o["id"],g["severity"],p.get("severity"),str(p.get("title"))[:80]))
                S["sensor_fault_pred_wrong"]+=bool(p) and p.get("severity")=="sensor_fault" and g["severity"]!="sensor_fault"
                S["title_nojudge"]+=bool(p) and bool(re.search(r"data gap|no judg|insufficient",str(p.get("title","")),re.I))
                S["tool_calls"]+=len(names)
            else:
                S["nonjson"]+=1
                bad["other:"+n].append((o["id"],gold[:100],f[:100]))
    out.append((n,N,dict(S),round(sum(ws)/N,1),round(sorted(ws)[int(.9*N)-1],1),round(sum(tp)/max(len(tp),1),1)))
    print(out[-1])
json.dump({k:v[:12] for k,v in bad.items()},open(O+"/bad.json","w"),indent=1)
