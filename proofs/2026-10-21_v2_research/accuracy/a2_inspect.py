import json,sys
rows=json.load(open("a1_rows.json"))
T=sys.argv[1]; D=int(sys.argv[2]); N=int(sys.argv[3])
for r in rows:
    if r["truth"]==T and r["d"]==D and r["n"]==N:
        print("OK " if r["truth"]==r["pred"] else "BAD", r["id"], r["role"][:5], r["metric"], "->", r["pred"], r["status"], "conf",r["conf"],
              "slope",r["slope"],"r2",r["r2"],"curv",r.get("curv"),"h",r.get("h1"),r.get("h2"),"cross",r.get("cross"),"noise",r.get("noise"),"flat",r.get("flat"),"jump",r.get("maxjump"),"max",r["max"],"min",r["min"],"last",r["last"],"|",r["e9"][:60],"|",r["e10"][:70])
