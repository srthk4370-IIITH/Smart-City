"""reweight_fix.py (2026-11-23): reweight.py picked beh_v2 ids that the trainer drops (> max_len 6656 tokens) -> KeyError crash
loop. Replace every scheduled id from step S on that is not loadable with an unused loadable beh_v2 id (else the backup's id)."""
import json, os, torch
R = os.path.expanduser("~/smartcity_runs/rsn_full")
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full/data/train_new.jsonl"
rows = torch.load(R + "/new_3e013a2c90cd_seg_tok.pt", weights_only=False)
ok = {"N:" + r["id"] for r in rows if len(r["ids"]) <= 6656}
blk = {"N:" + json.loads(l)["id"]: json.loads(l).get("block") for l in open(P)}
S = json.load(open(R + "/status.json"))["step"]
sch = json.load(open(R + "/schedule.json")); bak = json.load(open(R + "/schedule.json.bak_reweight"))
G = sch["groups"]
inuse = {i for g in G for i in g}
pool = [i for i, b in blk.items() if b == "beh_v2" and i in ok and i not in inuse]
bad = fixed = 0
for s in range(S, len(G)):
    for j, i in enumerate(G[s]):
        if i.startswith("N:") and i not in ok:
            bad += 1
            G[s][j] = pool.pop(0) if pool else bak["groups"][s][j]
            fixed += 1
left = [i for g in G[S:] for i in g if i.startswith("N:") and i not in ok]
json.dump(sch, open(R + "/schedule.json.part", "w")); os.replace(R + "/schedule.json.part", R + "/schedule.json")
beh = sum(1 for g in G[S:] for i in g if blk.get(i) == "beh_v2")
print("loadable new rows %d; step %d: bad ids %d fixed %d, still bad %d; beh rows in remaining steps %d" % (len(ok), S, bad, fixed, len(left), beh))
