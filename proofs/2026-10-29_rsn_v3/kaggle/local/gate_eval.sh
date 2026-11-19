#!/usr/bin/env bash
# gate_eval.sh [gguf]: host-GPU gate of rsn_v3 (Q4_0, host = board numerics) vs rsn_v1.
#   1. RWH 150 + dev 120 + P0 with the round-1 runner (eval/eval_gguf.sh: llama-server CUDA b11815, one model on the GPU)
#      -> proofs/2026-10-25_reasoner_final/eval/results/rsn_v3_$RUN_ID (+ p0/results/...)
#   2. chat dev v3 (300) for rsn_v3 with adaptive thinking, and once for rsn_v1 (empty think, its trained mode; cached per
#      chat3_dev md5) -> kaggle/gate/...
#   3. gate_score.py: PASS only if RWH + RWH-2 report metrics >= rsn_v1 (schema_err <=), dev within 1 item, chat pass rate up
#      -> kaggle/gate/$RUN_ID/{gate.json,GATE.md}; exit 0 PASS, 1 FAIL, 2 incomplete.
# Starts only when the GPU is idle (< 800 MiB, no trainer / llama-server, no PAUSE_GPU) and Windows RAM >= 1.5 GB.
# Does not touch the board. usage: RUN_ID=t1 bash detach.sh gate_t1 .../local/gate_eval.sh [Code/models_stage/rsn_v3_q4_0.gguf]
SCRIPT=gate_eval; source "$(dirname "$0")/guard.sh"
check_run_id
G=${1:-$QIDK/Code/models_stage/rsn_v3_q4_0.gguf}
V1=${V1_GGUF:-$QIDK/Code/models_stage/rsn_v1_q4_0.gguf}
BASE_TAG=${BASE_TAG:-ft612}
TAG=rsn_v3_$RUN_ID
OUT=$KG/gate/$RUN_ID
PY=~/venvs/rsn/bin/python
LC=~/llama-cuda-b11815; PORT=18097
PAUSE=$R1/PAUSE_GPU
RWH2=${RWH2:-$(ls -t $KG/build/*/heldout/incidents_rwh2.jsonl 2>/dev/null | head -1)}
LOCK=$V3/GPU_LOCK
[ -s "$RWH2" ] || die "no RWH-2 file (RWH2=...)" 2
[ -s "$G" ] || die "no GGUF $G" 2
[ -s "$G.md5" ] && { (cd "$(dirname "$G")" && md5sum -c --quiet "$(basename "$G").md5") || die "GGUF md5 mismatch"; }
[ -e "$R1/eval/results/$TAG" ] && die "eval/results/$TAG exists: refusing to overwrite, use a new run id" 6
new_dir "$OUT"
need_ram 1536
status "start: $G vs rsn_v1 ($BASE_TAG results, $V1)"
gpu_free() { [ ! -e "$PAUSE" ] && { [ ! -e "$LOCK" ] || grep -q "^gate_eval $RUN_ID" "$LOCK"; } && [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9)" -lt 800 ] \
  && ! pgrep -f "[t]rain_3e.py|[t]rain_rsn|[l]lama-server" >/dev/null; }
until gpu_free; do sleep 120; done
echo "gate_eval $RUN_ID $(date -Is)" > "$LOCK"; trap 'grep -q "^gate_eval $RUN_ID" "$LOCK" 2>/dev/null && rm -f "$LOCK"' EXIT
need_ram 1536

# ---- 1. report suites + P0 (round-1 runner, unchanged)
bash "$R1/eval/eval_gguf.sh" "$G" "$TAG" rwh,dev,p0 > "$OUT/eval_gguf.log" 2>&1
status "report suites: $(grep -E 'items in' "$OUT/eval_gguf.log" | tr '\n' ';')"

# ---- 2. chat dev v3 on one llama-server (same flags as eval_gguf.sh) with the thermal / RAM pause watchdog
serve_run() {   # serve_run <gguf> <log> <cmd...>
  local m=$1 lg=$2; shift 2
  until gpu_free; do sleep 60; done
  LD_LIBRARY_PATH=$LC/bin nice -n 10 $LC/bin/llama-server -m "$m" -ngl 99 -cram 256 -c 8192 -np 1 --jinja -t 2 -tb 2 --host 127.0.0.1 \
    --port $PORT --no-webui > "$lg" 2>&1 &
  local sp=$! main=$$
  ( hot=0; while sleep 20; do kill -0 $sp 2>/dev/null || exit 0
      [ -e "$PAUSE" ] && { kill -CONT $sp; kill $sp; exit 0; }
      t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | head -1 | cut -d. -f1 | tr -dc 0-9); f=$(free_mb)
      { { [ -n "$t" ] && [ "$t" -ge 80 ]; } || { [ -n "$f" ] && [ "$f" -lt 1536 ]; }; } && hot=1
      [ $hot = 1 ] && kill -STOP $sp
      if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 72 ] && { [ -z "$f" ] || [ "$f" -ge 2560 ]; }; then kill -CONT $sp; hot=0; fi
    done ) &
  local wd=$!
  for i in $(seq 1 90); do sleep 2; curl -s localhost:$PORT/health | grep -q ok && break; done
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 "$@"; local rc=$?
  kill $wd 2>/dev/null; kill -CONT $sp 2>/dev/null; kill $sp 2>/dev/null; wait $sp 2>/dev/null
  return $rc
}
serve_run "$G" "$OUT/server_v3.log" $PY "$KG/local/chat3_eval.py" --port $PORT --think 1 --out "$OUT/chatdev3_v3.jsonl" \
  > "$OUT/chatdev3_v3.log" 2>&1 || die "chat dev v3 (rsn_v3) failed: $(tail -n 2 "$OUT/chatdev3_v3.log")"
# ---- RWH-2 (held out) for rsn_v3, and once for rsn_v1 (stored with its other results under the base tag)
serve_run "$G" "$OUT/server_v3_rwh2.log" python3 "$KG/local/run_suite.py" --tag "$TAG" --port $PORT --suite rwh2 --file "$RWH2" \
  > "$OUT/rwh2_v3.log" 2>&1 || die "RWH-2 (rsn_v3) failed: $(tail -n 2 "$OUT/rwh2_v3.log")"
if [ "$(wc -l < "$R1/eval/results/$BASE_TAG/rwh2.jsonl" 2>/dev/null || echo 0)" -lt "$(wc -l < "$RWH2")" ]; then
  serve_run "$V1" "$OUT/server_v1_rwh2.log" python3 "$KG/local/run_suite.py" --tag "$BASE_TAG" --port $PORT --suite rwh2 --file "$RWH2" \
    > "$OUT/rwh2_v1.log" 2>&1 || die "RWH-2 (rsn_v1) failed: $(tail -n 2 "$OUT/rwh2_v1.log")"
fi
DEVMD5=$(md5sum < "$V3/data/chat3_dev.jsonl" | cut -c1-12)
CB=$KG/gate/rsn_v1_chatdev3_$DEVMD5.jsonl
if [ "$(wc -l < "$CB" 2>/dev/null || echo 0)" -lt "$(wc -l < "$V3/data/chat3_dev.jsonl")" ]; then
  serve_run "$V1" "$OUT/server_v1.log" $PY "$KG/local/chat3_eval.py" --port $PORT --think 0 --out "$CB" \
    > "$OUT/chatdev3_v1.log" 2>&1 || die "chat dev v3 (rsn_v1) failed: $(tail -n 2 "$OUT/chatdev3_v1.log")"
fi
status "chat dev v3 done (v3 $(wc -l < "$OUT/chatdev3_v3.jsonl"), v1 $(wc -l < "$CB") items)"

# ---- 2b. (r2+, informational) the full r2 TEST set at the end: incidents_test_r2 (1,368, per slice) + chat_test_r2 (581),
#          15-tool chat header; set TEST_R2=<proofs/2026-11-02_2b_r2/data/final>
if [ -n "${TEST_R2:-}" ] && [ -s "$TEST_R2/incidents_test_r2.jsonl" ]; then
  serve_run "$G" "$OUT/server_v3_test_r2.log" python3 "$KG/local/run_suite.py" --tag "$TAG" --port $PORT --suite test_r2 \
    --file "$TEST_R2/incidents_test_r2.jsonl" > "$OUT/test_r2_inc.log" 2>&1 || status "WARN: test_r2 incidents failed: $(tail -n 2 "$OUT/test_r2_inc.log")"
  serve_run "$G" "$OUT/server_v3_test_r2_chat.log" $PY "$KG/local/chat3_eval.py" --port $PORT --think 1 --records "$TEST_R2/chat_test_r2.jsonl" \
    --out "$OUT/chat_test_r2_v3.jsonl" > "$OUT/test_r2_chat.log" 2>&1 || status "WARN: test_r2 chat failed: $(tail -n 2 "$OUT/test_r2_chat.log")"
  status "test_r2 done: incidents $(wc -l < "$R1/eval/results/$TAG/test_r2.jsonl" 2>/dev/null), chat $(wc -l < "$OUT/chat_test_r2_v3.jsonl" 2>/dev/null)"
fi

# ---- 3. P0 (informational) + gate
(cd "$R1/eval" && python3 p0_score.py "$TAG" "$BASE_TAG" 2>&1 | tail -2) > "$OUT/p0.txt"
python3 "$KG/local/gate_score.py" --new "$TAG" --base "$BASE_TAG" --chat-new "$OUT/chatdev3_v3.jsonl" --chat-base "$CB" --out "$OUT" \
  --p0 "$OUT/p0.txt" --rwh2 "$RWH2" > "$OUT/gate_score.log" 2>&1
rc=$?
md5_manifest "$OUT"
case $rc in 0) status "GATE PASS ($OUT/GATE.md)";; 1) status "GATE FAIL ($OUT/GATE.md)";; *) status "GATE INCOMPLETE rc=$rc ($OUT/gate_score.log)";; esac
exit $rc
