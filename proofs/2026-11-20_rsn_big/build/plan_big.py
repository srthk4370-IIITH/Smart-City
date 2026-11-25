"""plan_big.py DATA_DIR [TRAIN_H=9.0] [TOK_S=450]: training plan from tokens_v4.json (tok_v4.py): rows seen, steps, epochs fraction, ETA, flags -> DATA_DIR/PLAN.json + PLAN.md.
10 new + 6 replay rows per step (mix 0.625, accum 16); the trainer shuffles --new with a fixed seed and takes epochs x len(new) rows: the pool composition IS the sampling weight; the files are already the prioritised selection (build_big assemble: B 30 %, tool-critical chat 27 %, other chat 8 %, agent rows 35 %; replay balanced over every block), full pools in pool_*.jsonl."""
import json, math, sys
D = sys.argv[1]; TRAIN_H = float(sys.argv[2]) if len(sys.argv) > 2 else 9.0; TOK_S = float(sys.argv[3]) if len(sys.argv) > 3 else 450.0
T = json.load(open(D + "/tokens_v4.json")); M = json.load(open(D + "/MANIFEST.json"))
def mean(pref):
    rs = [(v["rows"], v["mean_tokens"]) for k, v in T.items() if k.startswith(pref) and isinstance(v, dict)]
    n = sum(r for r, _ in rs); return n, sum(r * m for r, m in rs) / max(n, 1)
nn, mn = mean("train_new.jsonl:"); nr, mr = mean("replay.jsonl:")
k_new, k_rep = 10, 6
tps = k_new * mn + k_rep * mr
steps = min(int(TRAIN_H * 3600 * TOK_S / tps), math.ceil(nn / k_new))
epochs = round(min(1.0, steps * k_new / nn), 4)
flags = ("--lr 1.5e-5 --warmup 0.05 --floor 0.1 --accum 16 --mix 0.625 --epochs %s --save-every 20 --eval-every %d --gen-every %d --patience 3 --keep-best 3 --w-r4 0.6 --r3-tol 0.01 "
         "--gen-r4-n 40 --gen-n 24 --gen-r3 auto --micro-tokens 7424 --head-cpu --ckpt-offload --mlp-chunk 512 --lean-host --shared-prefix --oom-stop "
         "--mlp-chunk-min 4096 --offload-min 4096") % (epochs, steps // 2, steps // 2)
seen_new, seen_rep = steps * k_new, steps * k_rep
plan = {"pool_new_rows": nn, "pool_replay_rows": nr, "mean_tokens_new": round(mn), "mean_tokens_replay": round(mr), "tokens_per_step": round(tps), "assumed_tok_s": TOK_S,
        "train_h": TRAIN_H, "steps": steps, "epochs_fraction": epochs, "new_rows_seen": seen_new, "replay_rows_seen": seen_rep,
        "seen_share_new_pool": round(seen_new / nn, 3), "seen_share_replay_pool": round(seen_rep / nr, 3), "flags": flags,
        "eta_h": {"train": TRAIN_H, "gen_evals_3x_assumed_1h": 3.0, "setup_2_sessions": 2.0, "total": round(TRAIN_H + 5.0, 1)}}
json.dump(plan, open(D + "/PLAN.json", "w"), indent=1)
open(D + "/PLAN.md", "w").write("# training plan\n\n" + "\n".join("- %s: %s" % (k, v) for k, v in plan.items()) + "\n")
print(json.dumps({k: v for k, v in plan.items() if k != "flags"}))
