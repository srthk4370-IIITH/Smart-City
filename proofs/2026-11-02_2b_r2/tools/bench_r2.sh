#!/usr/bin/env bash
# bench_r2.sh: 20-step benchmark of the r2 trainer, baseline (one row per forward, as r1) vs micro-batched rows, same data,
# same step groups, same LR schedule, through laptop_train.sh (same guards: GPU_LOCK, 87/82 C and 1024/1100 MB pauses).
# Writes proofs/2026-11-02_2b_r2/bench/{bench.md, <variant>_losses.jsonl, <variant>_train.log}. Launch via proofs/detach.sh.
set -u
Q=/mnt/c/Users/hp/Desktop/qidk; KG=$Q/proofs/2026-10-29_rsn_v3/kaggle; R2D=$Q/proofs/2026-11-02_2b_r2/data/final
OUT=$Q/proofs/2026-11-02_2b_r2/bench; mkdir -p "$OUT"
VARIANTS=${VARIANTS:-"base:0 mt6144:6144 mt8192:8192"}
STEPS=${STEPS:-20}
first=""
for v in $VARIANTS; do
  name=${v%%:*}; mt=${v##*:}
  RUN=rsn3_2b_r2bench_$name; O=$HOME/smartcity_runs/$RUN
  if [ -n "$first" ] && [ ! -e "$O" ]; then      # share the tokenized caches and the max_len probe of the first variant
    mkdir -p "$O"; cp "$first"/*_tok.pt "$first"/maxlen.json "$first"/caches.json "$O"/ 2>/dev/null
    sed -i "s#$first#$O#g" "$O/caches.json" 2>/dev/null
  fi
  RSN3_SEG_TOKENIZE=1 RUN=$RUN TOOLS=$R2D/tools_r2.json INC=$R2D/incidents_train.jsonl CHAT=$R2D/chat_train.jsonl DEV=$R2D/dev_mix3.jsonl \
    GEN_INC=$R2D/gen_inc_r2.jsonl GEN_CHAT=$R2D/gen_chat_r2.jsonl CHUNK_H=3 \
    EXTRA="--max-steps $STEPS --eval-every 400 --gen-every 400 --micro-tokens $mt" bash "$KG/local/laptop_train.sh"
  echo "$name rc=$?" >> "$OUT/bench_rc.txt"
  cp "$O/losses.jsonl" "$OUT/${name}_losses.jsonl" 2>/dev/null; cp "$O/train.log" "$OUT/${name}_train.log" 2>/dev/null
  [ -z "$first" ] && first=$O
done
python3 - "$OUT" $VARIANTS <<'EOF'
import json, os, sys
out = sys.argv[1]
rows = []
for v in sys.argv[2:]:
    name = v.split(":")[0]
    p = os.path.join(out, name + "_losses.jsonl")
    if not os.path.exists(p):
        rows.append((name, None, None, None)); continue
    L = [json.loads(l) for l in open(p)]
    later = [x for x in L if x["step"] > 5]           # step 1-5 window includes model load / dev loss
    tps = sum(x["tok_s"] for x in later) / max(1, len(later))
    rows.append((name, round(tps), [round(x["loss"], 4) for x in L], len(L)))
with open(os.path.join(out, "bench.md"), "w") as f:
    f.write("# r2 trainer benchmark (20 steps, same rows per step)\n\n| variant | tok/s (steps 6-20, incl. heat pauses) | loss per 5 steps |\n|---|---|---|\n")
    for n, t, l, k in rows:
        f.write("| %s | %s | %s |\n" % (n, t, l))
print(open(os.path.join(out, "bench.md")).read())
EOF
