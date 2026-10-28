import sys, random, json
sys.argv=["x"]
sys.path.insert(0,"/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts")
import e1_stories as E
from collections import Counter, defaultdict
from e1_stories import GV, V, TE, HA, SRC, T, F
man0=json.loads((SRC/"manifest.json").read_text()); heldout=dict(man0["heldout_nodes"])
kj=json.loads((SRC/"kthr.json").read_text()); kthr=defaultdict(lambda:99,{tuple(k.split("/")):v["thr"] for k,v in kj.items()})
V.NODE_LIMITS.update(json.loads((SRC/"node_limits.json").read_text())); HA.register(); TE.build_calibration()
S,roles,ends=T.load_role("water")
for when in ("day","night"):
    ctx=E.SCtx(S,ends,roles,heldout,"test","water",kthr,random.Random(1)).setup("seen",when,E.lvl)
    c=Counter()
    for i in range(400):
        b=GV.calm_base(ctx,48,ok=lambda k:k[1] in V.NODE_LIMITS)
        if not b: c["cb_none"]+=1; continue
        key,tag,end,y,s0,bst=b; tl=V.NODE_LIMITS[key[1]]; n=48
        if max(y[-n:])>=tl["high"]: c["high"]+=1; continue
        d=40; o=len(y)-d; m=V.METRICS[key[0],key[2]]
        A=min(6*s0*d/12, 0.45*(y[o-1]-m["lo"]))
        if A<4*s0: c[("small",key[1],round(s0,1),round(y[o-1]))]+=1; continue
        GV.inj_gradual(y,o,A,-1); y=GV.clamp(y,m)
        prompt, st, ev, info = V.agent_prompt(key[0], key[1], GV.G.describe(key[1]), key[2], y[-V.HIST:], n, end)
        ex=dict(role=key[0],metric=key[2],node=key[1],n=n,end_epoch=end,st=st,info=info,pattern="gradual_decrease",family="e1",rng=ctx.rng,d=d,onset_idx=n-d,size=A/s0,base_mean=bst["mean"])
        tgt,meta=TE.label(ex); c[(key[1],tgt["pattern"],tgt["status"],tgt["likely_cause"],meta["fault_kind"],meta["small"])]+=1
    print(when, c.most_common(8))
