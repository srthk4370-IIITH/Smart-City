import json, collections
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/"
gold = {}
for l in open(P + "2026-11-06_4b_local/data/final/incidents_test_r2.jsonl", encoding="utf-8"):
    r = json.loads(l); gold[r["id"]] = r
conf = collections.Counter(); fam = collections.Counter(); famn = collections.Counter(); ex = []
for l in open(P + "2026-10-25_reasoner_final/eval/results/rsn_v3_4b_r3/test_r2.jsonl", encoding="utf-8"):
    r = json.loads(l); g = gold.get(r["id"])
    if not g: continue
    gr = json.loads(g["messages"][-1]["content"])
    try: pr = json.loads(r["final"]["content"])
    except Exception: pr = {}
    sl = g.get("slice")
    f = g["family"].split("+")[0]
    famn[(sl, f)] += 1
    if pr.get("severity") != gr["severity"]:
        conf[(sl, gr["severity"], pr.get("severity"))] += 1; fam[(sl, f)] += 1
        if sl == "heat" and len(ex) < 4: ex.append((g["id"], g["family"], gr["severity"], gr["label"], pr.get("severity"), pr.get("label"), pr.get("title"), gr["title"]))
print(sorted(conf.items(), key=lambda z: -z[1])[:20])
print([(k, v, famn[k]) for k, v in sorted(fam.items(), key=lambda z: -z[1])[:25]])
for e in ex: print(e)
