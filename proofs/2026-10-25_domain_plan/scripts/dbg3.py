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
for nm,keyok in (("lvl",E.lvl),("ph",lambda k:k[2]=="ph")):
  ctx=E.SCtx(S,ends,roles,heldout,"test","water",kthr,random.Random(1)).setup("seen","day",keyok)
  print(nm, {k[1]:len(ctx._ends(k)) for k in ctx.seen if keyok(k)})
  c=Counter(); of=GV.finish
  def fin(ctx_,key,tag,end,y,n,fam,sub,pattern,extra):
      try:
        r=of(ctx_,key,tag,end,y,n,fam,sub,pattern,extra); c["ok" if r else "none"]+=1; return r
      except AssertionError as e: c["assert:"+str(e)[:60]]+=1; raise
  GV.finish=fin
  for i in range(300):
      key,tag=ctx.pick_key(lambda k: k[1] in V.NODE_LIMITS or nm=="ph")
      if key is None: c["nokey"]+=1; continue
      end,y=ctx.base(key,48)
      if y is None: c["nobase"]+=1; continue
      if nm=="lvl" and max(y[-48:])>=V.NODE_LIMITS[key[1]]["high"]: c["high"]+=1; continue
      try: (E.leak(36,46) if nm=="lvl" else E.ph_drift)(ctx,48) if False else None
      except Exception: pass
      try: r=(E.leak(36,46) if nm=="lvl" else E.ph_drift)(ctx,48)
      except AssertionError: pass
  GV.finish=of; print(nm, c.most_common(6))
