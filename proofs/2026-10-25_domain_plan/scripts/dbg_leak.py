import sys, random, json
sys.argv=["x","--out","/tmp/e1dbg"]
sys.path.insert(0,"/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts")
import e1_stories as E
from collections import Counter, defaultdict
from e1_stories import GV, V, TE, HA, SRC, T
man0=json.loads((SRC/"manifest.json").read_text()); heldout=dict(man0["heldout_nodes"])
kj=json.loads((SRC/"kthr.json").read_text()); kthr=defaultdict(lambda:99,{tuple(k.split("/")):v["thr"] for k,v in kj.items()})
V.NODE_LIMITS.update(json.loads((SRC/"node_limits.json").read_text())); HA.register(); TE.build_calibration()
S,roles,ends=T.load_role("water")
lv=[k for k in S if k[2]=="level"]; print("level keys",len(lv),"with limits",sum(k[1] in V.NODE_LIMITS for k in lv))
for tag in ("seen","unseen"):
  for when in ("day","night"):
    ctx=E.SCtx(S,ends,roles,heldout,"test","water",kthr,random.Random(1)).setup(tag,when,E.lvl)
    k,t=ctx.pick_key(lambda k:k[1] in V.NODE_LIMITS); print(tag,when,"key",k,t, len(ctx._ends(k)) if k else 0)
    c=Counter()
    orig=GV.finish
    def fin(*a,**kw):
        r=orig(*a,**kw); c["fin_ok" if r else "fin_none"]+=1; return r
    GV.finish=fin
    ob=GV.calm_base
    def cb(*a,**kw):
        r=ob(*a,**kw); c["cb_ok" if r else "cb_none"]+=1; return r
    GV.calm_base=cb
    for i in range(500):
        try: E.leak(24,40,4,8)(ctx,48)
        except AssertionError: c["assert"]+=1
    GV.finish=orig; GV.calm_base=ob
    print(dict(c))
ctx=E.SCtx(S,ends,roles,heldout,"test","water",kthr,random.Random(1)).setup("seen","night",E.lvl)
c=Counter()
for i in range(300):
    b=GV.calm_base(ctx,48,ok=lambda k:k[1] in V.NODE_LIMITS)
    if not b: continue
    key,tag,end,y,s0,bst=b; tl=V.NODE_LIMITS[key[1]]
    c[(key[1], max(y[-48:])>=tl["high"], round(max(y[-48:])), tl["high"], round(s0,2))]+=1
print(c.most_common(8)); print({k:len(v.get("test",[])) for k,v in ends.items() if k[2]=="level"}); print({k:len(v.get("dev",[])) for k,v in ends.items() if k[2]=="level"})
