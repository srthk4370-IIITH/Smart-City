import json
from collections import Counter
rows=json.load(open("a1_rows.json")); F={(f["id"],f["d"],f["n"]):f for f in json.load(open("a3_series_feats.json"))}
for d in (8,18,24,36):
  print("== d",d,"pred gradual_increase: truth x rule48 x conf")
  c=Counter()
  for r in rows:
    if r["d"]==d and r["pred"]=="gradual_increase":
      f=F[(r["id"],r["d"],r["n"])]; c[(r["truth"],f["rule48"],r["conf"]<=0.5 if isinstance(r["conf"],(int,float)) else None)]+=1
  for k,v in sorted(c.items(), key=lambda x:-x[1]): print(" ",k,v)
print("== clean rows: rule48 on clean when model says gradual_increase:", Counter(F[(r["id"],0,r["n"])]["rule48"] for r in rows if r["clean"] and r["pred"]=="gradual_increase"))
print("== pred stable at d>=18 with truth spike: early pred", Counter((r["n"],[x for x in rows if x["id"]==r["id"] and x["d"]==8 and x["n"]==48][0]["pred"]) for r in rows if r["d"]==36 and r["truth"]=="spike" and r["pred"]=="stable"))
print("== erratic d=36: rule48 & model", Counter((F[(r["id"],36,r["n"])]["rule48"], r["pred"]) for r in rows if r["d"]==36 and r["truth"]=="erratic"))
print("== model erratic precision all d:", sum(r["truth"]=="erratic" for r in rows if r["pred"]=="erratic"), sum(1 for r in rows if r["pred"]=="erratic"))
print("== INVALID texts sample")
import itertools
