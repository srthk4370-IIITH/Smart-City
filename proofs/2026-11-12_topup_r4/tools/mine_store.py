import sys, json, collections, re
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/tools")
import tools_r3_impl as TR
ex = TR.ToolsR3(fog="offline")
d = ex.D
full = [x for x in d.incs if x["full"] and not x["injected"]]
print(len(full), collections.Counter(len(x["domains"]) for x in full))
tot = collections.Counter(); labs = collections.Counter()
for x in full[:1000]:
    r = ex.run("co_occurring_incidents", {"id": x["id"], "window_min": 120})
    tot[min(r["total"], 6)] += 1
    for it in r["items"]:
        labs[(x["label"], it["label"])] += 1
print(tot); print(labs.most_common(40))
print([x["title"] for x in full[:8]])
