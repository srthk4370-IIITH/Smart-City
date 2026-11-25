"""reweight.py (owner 2026-11-23): after a clean STOP at step S, rewrite schedule.json groups[S:] so each remaining step has 2 unseen
beh_v2 rows in place of 2 non-beh new rows (real_agt3 replaced first, then other blocks); reset best.json since_best to 0 (the
step-400 dip does not count, so step 500 cannot early-stop). Backups: schedule.json.bak_reweight, best.json.bak_reweight."""
import json, os, shutil
R = os.path.expanduser("~/smartcity_runs/rsn_full")
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full/data/train_new.jsonl"
S = json.load(open(R + "/status.json"))["step"]
sch = json.load(open(R + "/schedule.json")); best = json.load(open(R + "/best.json"))
shutil.copy(R + "/schedule.json", R + "/schedule.json.bak_reweight"); shutil.copy(R + "/best.json", R + "/best.json.bak_reweight")
blk = {"N:" + json.loads(l)["id"]: json.loads(l).get("block") for l in open(P)}
G = sch["groups"]; kn = sch["k_new"]
seen = {i for g in G[:S] for i in g}
pool = [i for i, b in blk.items() if b == "beh_v2" and i not in seen]
later = {i for g in G[S:] for i in g}
pool = [i for i in pool if i not in later] + [i for i in pool if i in later]   # rows not already scheduled first
used, rep = set(), 0
for g in G[S:]:
    new = g[:kn]
    have = sum(1 for i in new if blk.get(i) == "beh_v2")
    order = sorted([j for j, i in enumerate(new) if blk.get(i) != "beh_v2"], key=lambda j: blk.get(new[j]) != "real_agt3")
    for j in order[:max(0, 2 - have)]:
        while pool and (pool[0] in used or pool[0] in g):
            pool.pop(0)
        if not pool:
            break
        new[j] = pool.pop(0); used.add(new[j]); rep += 1
    g[:kn] = new
json.dump(sch, open(R + "/schedule.json.part", "w")); os.replace(R + "/schedule.json.part", R + "/schedule.json")
best["since_best"] = 0
json.dump(best, open(R + "/best.json", "w"), indent=1)
c = sum(1 for g in G[S:] for i in g[:kn] if blk.get(i) == "beh_v2")
print("step %d: replaced %d rows; beh rows in remaining %d steps = %d (%.1f%% of rows); since_best reset 0" % (S, rep, len(G) - S, c, 100.0 * c / (16 * (len(G) - S))))
