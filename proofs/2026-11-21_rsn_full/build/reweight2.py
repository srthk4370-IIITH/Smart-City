"""reweight2.py (owner 2026-11-24): chat plateaued, reports up -> from step S on, keep at most KEEP report rows among the 10 new rows
of each step; the rest become unseen loadable chat rows (beh_v2 first, then gen5 tool/agentic chat, then other chat). Replay (6/step)
untouched, so reports keep ~4 new + ~5 replay rows per step. DRY=1 prints the plan only. Backup schedule.json.bak_reweight2."""
import json, os, shutil, sys, collections, torch
KEEP = int(os.environ.get("KEEP", "4")); DRY = os.environ.get("DRY") == "1"
R = os.path.expanduser("~/smartcity_runs/rsn_full")
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full/data/"
rows = torch.load(R + "/new_3e013a2c90cd_seg_tok.pt", weights_only=False)
ok = {"N:" + r["id"] for r in rows if len(r["ids"]) <= 6656}
meta, fam = {}, {}
for l in open(P + "train_new.jsonl"):
    d = json.loads(l); meta["N:" + d["id"]] = (d.get("block"), str(d.get("tools", "")).startswith("incident"))
    f = str(d.get("family") or d.get("id")).split(":"); fam["N:" + d["id"]] = "%s|%s" % (d.get("block"), ":".join(f[:2]) if f[0] in ("site", "r5tool", "r5replay") else f[0].rsplit("-", 1)[0])
rep_rep = {}
for l in open(P + "replay.jsonl"):
    d = json.loads(l); rep_rep["R:" + d["id"]] = str(d.get("tools", "")).startswith("incident")
S = json.load(open(R + "/status.json"))["step"]
sch = json.load(open(R + "/schedule.json")); G = sch["groups"]; kn = sch["k_new"]
used = {i for g in G for i in g}
# owner: all chat kinds, not only behaviour -> round-robin over chat families (site, fog, tools, agentic, multi-domain chat...)
by = collections.defaultdict(list)
for i in meta:
    if i in ok and i not in used and not meta[i][1]:
        by[fam[i]].append(i)
import random
rr = random.Random(20261124)
for v in by.values():
    rr.shuffle(v)
pool, ks = [], sorted(by)
while any(by[k] for k in ks):
    for k in ks:
        if by[k]:
            pool.append(by[k].pop())
def share(gs):
    n = sum(len(g) for g in gs) or 1
    r = sum(1 for g in gs for i in g if (meta.get(i, (0, rep_rep.get(i, False)))[1]))
    return round(100.0 * r / n, 1)
before = share(G[S:]); swapped = 0; cnt = collections.Counter(); cf = collections.Counter()
for g in G[S:]:
    new = g[:kn]
    reps = [j for j, i in enumerate(new) if meta.get(i, (0, False))[1]]
    for j in reps[KEEP:]:
        if not pool:
            break
        c = pool.pop(0); cnt[fam[c].split("|")[0]] += 1; cf[fam[c]] += 1; new[j] = c; swapped += 1
    g[:kn] = new
print("step %d, %d steps left: report share of rows %.1f%% -> %.1f%%; swapped %d report rows for chat %s; unseen chat left %d"
      % (S, len(G) - S, before, share(G[S:]), swapped, dict(cnt), len(pool)))
if not DRY:
    shutil.copy(R + "/schedule.json", R + "/schedule.json.bak_reweight2")
    json.dump(sch, open(R + "/schedule.json.part", "w")); os.replace(R + "/schedule.json.part", R + "/schedule.json")
print("families used:", len(cf), cf.most_common(12))
