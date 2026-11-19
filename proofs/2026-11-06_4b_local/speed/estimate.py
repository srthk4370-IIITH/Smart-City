"""item 4: token-count estimate of --shared-prefix on the REAL r3 schedule (schedule.json of the live run, its token caches,
mmap). Per step: rows clustered exactly as the trainer does (prefix_clusters, min 256); layer tokens = tokens that go through the
32 decoder layers (each costs forward + recompute + backward), real and padded (micro-batches of 7424 / continuation batches of
7424 - p). Usage: estimate.py <trainer.py> <run dir> <out.json> [step stride]"""
import importlib.util
import json
import os
import sys

import torch

spec = importlib.util.spec_from_file_location("tr", sys.argv[1])
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
R, OUT = sys.argv[2], sys.argv[3]
stride = int(sys.argv[4]) if len(sys.argv) > 4 else 1
caches = json.load(open(os.path.join(R, "caches.json")))
rows = {}
for k in ("inc", "chat"):
    for d in torch.load(os.path.join(R, os.path.basename(caches[k])), mmap=True):
        rows[d["id"]] = {"id": d["id"], "kind": d["kind"], "ids": d["ids"], "labels": d["labels"]}
S = json.load(open(os.path.join(R, "schedule.json")))
G = S["groups"]
MT = 7424
tot = dict(base_real=0, base_pad=0, new_real=0, new_pad=0, steps=0, prefix_tokens_saved=0, fwd_base=0, fwd_new=0,
           prefix_labels_rows=0)
plen = {"chat": [], "incident": []}
for s in range(0, len(G), stride):
    exs = [rows[k] for k in G[s]]
    tot["steps"] += 1
    tot["base_real"] += sum(len(e["ids"]) for e in exs)
    mbs = T.micro_batches(exs, MT)
    tot["base_pad"] += sum(len(mb) * len(mb[0]["ids"]) for mb in mbs)
    tot["fwd_base"] += len(mbs)
    alone = []
    for p, cl in T.prefix_clusters(exs, 256):
        if not p:
            alone += cl
            continue
        plen[cl[0]["kind"]].append(p)
        tot["prefix_tokens_saved"] += (len(cl) - 1) * p
        tot["new_real"] += p + sum(len(e["ids"]) - p for e in cl)
        tot["new_pad"] += p
        tot["fwd_new"] += 1
        tot["prefix_labels_rows"] += sum(bool((e["labels"][1:p + 1] != -100).any()) for e in cl)
        cs = sorted((len(e["ids"]) - p for e in cl), reverse=True)
        cur = []
        for c in cs:
            if cur and (len(cur) + 1) * cur[0] > max(1, MT - p):
                tot["new_pad"] += len(cur) * cur[0]
                tot["fwd_new"] += 1
                cur = []
            cur.append(c)
        tot["new_pad"] += len(cur) * cur[0]
        tot["fwd_new"] += 1
    tot["new_real"] += sum(len(e["ids"]) for e in alone)
    mbs = T.micro_batches(alone, MT)
    tot["new_pad"] += sum(len(mb) * len(mb[0]["ids"]) for mb in mbs)
    tot["fwd_new"] += len(mbs)
for k, v in plen.items():
    v.sort()
    tot["prefix_%s" % k] = {"clusters": len(v), "min": v[0] if v else 0, "p50": v[len(v) // 2] if v else 0, "max": v[-1] if v else 0}
tot["ratio_real"] = tot["base_real"] / tot["new_real"]
tot["ratio_padded"] = tot["base_pad"] / tot["new_pad"]
tot["stride"] = stride
json.dump(tot, open(OUT, "w"), indent=1)
print(json.dumps(tot, indent=1))
