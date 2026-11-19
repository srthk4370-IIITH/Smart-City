"""rank_balance_eval.py RUN_DIR [N_STEPS] [START]: CPU check of train_rsn3.sp_rank_split on the real r3 schedule + token caches
(memory-mapped): every row of a step goes to exactly one rank, the split is deterministic, and the layer-token cost of the
slower rank (the step's wall-time proxy on 2 GPUs) vs the strided split and vs 1 GPU. Prints one json line."""
import glob
import json
import os
import sys

os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle")
import torch  # noqa: E402
import train_rsn3 as T  # noqa: E402

run = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 300
s0 = int(sys.argv[3]) if len(sys.argv) > 3 else 511
rows = {}
for f in glob.glob(os.path.join(run, "inc_*_tok.pt")) + glob.glob(os.path.join(run, "chat_*_tok.pt")):
    for d in torch.load(f, mmap=True, weights_only=False):
        rows[d["id"]] = d
G = json.load(open(os.path.join(run, "schedule.json")))["groups"]
mp = 256
tot = {"one_gpu": 0, "strided_max": 0, "balanced_max": 0, "row_tokens": 0}
changed = 0
for s in range(s0, min(s0 + n, len(G))):
    exs = [rows[k] for k in G[s]]
    st = [exs[r::2] for r in range(2)]
    bal = T.sp_rank_split(exs, 2, mp)
    assert sorted(e["id"] for p in bal for e in p) == sorted(G[s]), "rows lost or duplicated at step %d" % s
    assert [[e["id"] for e in p] for p in bal] == [[e["id"] for e in p] for p in T.sp_rank_split(list(exs), 2, mp)], "not deterministic"
    tot["one_gpu"] += T.sp_cost(exs, mp)
    tot["strided_max"] += max(T.sp_cost(p, mp) for p in st)
    bm = max(T.sp_cost(p, mp) for p in bal)
    tot["balanced_max"] += bm
    tot["row_tokens"] += sum(len(e["ids"]) for e in exs)
    changed += [[e["id"] for e in p] for p in bal] != [[e["id"] for e in p] for p in st]
k = s0 + n - s0
print(json.dumps({"steps": k, "split_changed_steps": changed,
                  "mean_layer_tokens_per_step": {x: round(v / k) for x, v in tot.items()},
                  "speedup_vs_strided": round(tot["strided_max"] / tot["balanced_max"], 3),
                  "two_gpu_scaling_strided": round(tot["one_gpu"] / tot["strided_max"], 3),
                  "two_gpu_scaling_balanced": round(tot["one_gpu"] / tot["balanced_max"], 3)}))
