#!/usr/bin/env bash
# gate_full.sh (2026-11-22): copy of rsn_big gate_big.sh for the rsn_full retrain: own dir/GGUF name (no stale skip), tools_v5 schema, p2 results reused
# gate_big.sh <new_adapter_dir>: frozen gate of the big top-up (~45 min GPU): p2 vs the new model on gate/gate_set.jsonl
#   slices: report_all (40 report rows over all existing families) | new_family (30) | chat_en (40 English chat rows) | tool_chain (20 tool-chain probes)
#   both models: Q4_0 GGUF on the host llama-server (as rsn_p2_gate.sh), think = adaptive, greedy; p2 = Code/models_stage/rsn_v3_4b_p2_q4_0.gguf
#   (made from ckpt_best_0220); the new GGUF is made from <new_adapter_dir> on the edited base r3_edit_C1 (export_ft.sh, CPU only).
#   GPU only under GPU_LOCK: it WAITS for a free GPU, never kills anything. Output gate/GATE.md with per-slice scores (+ per sub-slice).
#   NO PASS / auto-deploy: the scores go to the owner; "FLAG" lines only say where a slice dropped > 0.03 or JSON validity fell below p2.
SCRIPT=rsn_full_gate; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
NEWA=${1:?new adapter dir (ckpt_best_NNNN from the Kaggle run)}
BIG=$QIDK/proofs/2026-11-20_rsn_big; OUT=$QIDK/proofs/2026-11-21_rsn_full/gate_full; mkdir -p $OUT/res; STATUS=$QIDK/proofs/2026-11-21_rsn_full/STATUS.md
RSN=$QIDK/proofs/2026-11-13_v3_data/rsn; FT=$QIDK/proofs/2026-11-13_v3_train/rsn_ft; BASE=$(cat $FT/chain/BASE)
STAGE=$QIDK/Code/models_stage; LC=~/llama-cuda-b11815; LOCK=$V3/GPU_LOCK; PORT=18299; PY=~/venvs/rsn/bin/python
TOOLS=$QIDK/proofs/2026-11-21_rsn_full/data/tools_v5.json; GS=$OUT/gate_set.jsonl; [ -s "$GS" ] || GS=$BIG/data/final_big/gate/gate_set.jsonl
[ -s "$GS" ] && [ -s "$TOOLS" ] || die "no gate set / tools" 2
GP=$STAGE/rsn_v3_4b_p2_q4_0.gguf; [ -s "$GP" ] || die "no p2 GGUF at $GP" 2
GN=$STAGE/rsn_v3_4b_full_q4_0.gguf
python3 - "$GS" "$OUT/gate_inc.jsonl" <<'PY'
import json,sys
rs=[json.loads(l) for l in open(sys.argv[1],encoding="utf-8") if l.strip()]
open(sys.argv[2],"w",newline="\n",encoding="utf-8").writelines(json.dumps(r,ensure_ascii=False)+"\n" for r in rs if r["slice"] in ("report_all","new_family"))
PY
status "gate: export new GGUF from $NEWA (CPU)"
bash $FT/post/export_ft.sh $BASE $NEWA rsn_v3_4b_full || die "export new adapter" 3
run_model() {   # run_model <gguf> <tag>
  local t0=$(date +%s)
  until { [ ! -e "$LOCK" ] || grep -q "^rsn_big_gate " "$LOCK"; } && [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -dc 0-9)" -lt 800 ]; do sleep 120; done
  echo "rsn_big_gate $(date -Is) pid=$$" > "$LOCK"
  LD_LIBRARY_PATH=$LC/bin nice -n 10 $LC/bin/llama-server -m "$1" -ngl 99 -cram 256 -c 12288 -np 1 --jinja -t 2 -tb 2 --host 127.0.0.1 --port $PORT --no-webui > $OUT/res/server_$2.log 2>&1 &
  local sp=$!; for i in $(seq 90); do curl -sf http://127.0.0.1:$PORT/health >/dev/null && break; sleep 5; done
  [ -s $OUT/res/$2/inc.jsonl ] && [ "$(wc -l < $OUT/res/$2/inc.jsonl)" -ge "$(wc -l < $OUT/gate_inc.jsonl)" ] || \
    timeout 2700 python3 $FT/post/run_ft.py --think 1 --tag $2 --port $PORT --resdir $OUT/res v4 --name inc --file $OUT/gate_inc.jsonl --tools $TOOLS >> $OUT/res/run_$2.log 2>&1
  timeout 2400 $PY $BIG/build/gate_run_chat.py --port $PORT --tag $2 --resdir $OUT/res --file $GS --tools $TOOLS >> $OUT/res/run_$2.log 2>&1
  kill $sp 2>/dev/null; wait $sp 2>/dev/null; grep -q "^rsn_big_gate " "$LOCK" 2>/dev/null && rm -f "$LOCK"
  status "gate: $2 done in $(( $(date +%s) - t0 )) s"
}
run_model $GP p2
run_model $GN new
python3 $OUT/gate_score_big.py $GS $OUT/res/p2 $OUT/res/new > $OUT/scores.json || die "score" 3
python3 $OUT/gate_report_big.py $OUT/scores.json "$NEWA" "$GN" > $OUT/GATE.md || die "report" 3
status "gate: GATE.md written (scores only, no auto-deploy)"; tail -3 $OUT/GATE.md
