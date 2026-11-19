"""ke_pack.py PACKDIR NONCE BUDGET_MIN TAG=ADAPTERDIR [TAG=ADAPTERDIR ...]   (laptop, CPU)
Builds the eval upload for the PRIVATE run dataset: sets/{t1,t2,hard,val}.jsonl (fixed seeded subsamples, identical for every model and round),
adapters/<tag>/ (adapter_model.safetensors + adapter_config.json), eval_worker.py, rows.py, eval_cfg.json. REAL val rows go only into the existing
private dataset (owner exception, logged by ke_run.sh). Tags order = priority (first = started first)."""
import json
import os
import random
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
pack, nonce, budget = sys.argv[1], sys.argv[2], int(sys.argv[3])
adapters = [x.split("=", 1) for x in sys.argv[4:]]
K2 = os.path.expanduser(os.environ.get("EVAL_LOCAL", "~/smartcity_runs/agt_topup_k2/local"))
AGT = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt/kaggle"
N = {"val": int(os.environ.get("N_VAL", 200)), "hard": int(os.environ.get("N_HARD", 160))}
KEEP = ("id", "prompt", "completion", "gold", "family", "role", "turn", "tool_kind", "synthetic", "source")


def rd(n):
    return [json.loads(l) for l in open("%s/%s.jsonl" % (K2, n)) if l.strip()]


shutil.rmtree(pack, ignore_errors=True)
os.makedirs(pack + "/sets")
sizes = {}
for out, src, k in (("t1", "tool_t1", 0), ("t2", "tool_t2", 0), ("hard", "hard_val", N["hard"]), ("val", "val_sel", N["val"])):
    rows = sorted(rd(src), key=lambda r: r["id"])
    if k:
        rows = random.Random(20261117).sample(rows, k)
    sizes[out] = len(rows)
    with open("%s/sets/%s.jsonl" % (pack, out), "w", newline="\n") as f:
        for r in rows:
            f.write(json.dumps({x: r[x] for x in KEEP if x in r}, ensure_ascii=False) + "\n")
for tag, d in adapters:
    os.makedirs("%s/adapters/%s" % (pack, tag))
    for f in ("adapter_model.safetensors", "adapter_config.json"):
        shutil.copy(os.path.join(os.path.expanduser(d), f), "%s/adapters/%s/%s" % (pack, tag, f))
shutil.copy(HERE + "/eval_worker.py", pack)
shutil.copy(AGT + "/rows.py", pack)
json.dump({"nonce": nonce, "tags": [t for t, _ in adapters], "eval_budget_min": budget, "sizes": sizes,
           "base_hf": "unsloth/Llama-3.2-3B-Instruct"}, open(pack + "/eval_cfg.json", "w"), indent=1)
print(json.dumps(sizes))
