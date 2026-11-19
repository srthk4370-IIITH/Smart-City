#!/usr/bin/env bash
# repair_common.sh: shared steps of repair_pool.sh (PLAN_V2 stage 3) and dpo.sh (stage 4). Source it after guard.sh with
# SCRIPT, RUN_ID and OUT set. Every step is idempotent (marker $OUT/<step>.done) and logged to kaggle/STATUS.md.
#   stopchk            $OUT/STOP or kaggle/chain/STOP -> clean exit 0 (rm the file and rerun the same command to continue)
#   step NAME / done_  run a step only once; UNTIL=<step> ends the run after that step
#   take_lock / drop_lock   GPU_LOCK "<script> <run id>" (waits while another job holds it; never touches that job)
#   serve_run GGUF LOG CMD..  one llama-server (-cram 256, same flags as gate_eval.sh) + thermal / RAM / STOP watchdog
#   run_pools TAG      candidate GGUF on the incident pool (round-1 runner) and the chat pool (chat3_eval.py, adaptive think)
#   teacher FAILED OUT_ROWS   base-model self-distillation of failed chat questions (distill_laptop/distill_llama.py: base
#                      Qwen3.5-4B Q8_0, K samples, inline verify) -> select_distill.py (re-verify; verified reference /
#                      template row when no sample passes) -> verified chat rows
#   train_loop MODE RUNDIR DATA EXTRA   guarded cont_chunk.sh chunks until done / early stop
#   best_ckpt RUNDIR   best checkpoint by dev score (only ones that beat the starting adapter), else empty
#   export_gate CKPT NAME GATE_ID      export_gguf.sh -> gate_eval.sh (same rule as gate A / B) -> kaggle/gate/<GATE_ID>
L=$KG/local; DLD=$V3/distill_laptop; LOCK=$V3/GPU_LOCK; PY=~/venvs/rsn/bin/python; LC=~/llama-cuda-b11815
PAUSE=$R1/PAUSE_GPU; PORT=${PORT:-18098}
BUILD=${BUILD:-r1}
INC_E1=${INC_E1:-$KG/build/$BUILD/data/incidents3_train.jsonl}
CHAT_E1=${CHAT_E1:-$KG/build/$BUILD/mix_laptop/chat_mix3.jsonl}
RWH2=${RWH2:-$(ls -t $KG/build/*/heldout/incidents_rwh2.jsonl 2>/dev/null | head -1)}
GEN_INC=${GEN_INC:-$KG/build/$BUILD/data/incidents_dev60.jsonl}
GEN_CHAT=${GEN_CHAT:-$V3/data/chat3_dev.jsonl}

stopped() { [ -e "$OUT/STOP" ] || [ -e "$KG/chain/STOP" ]; }
stopchk() { stopped && { status "STOP file: stopping here (rm $OUT/STOP or kaggle/chain/STOP and rerun to continue)"; exit 0; }; }
isdone() {      # a step done on an earlier run still honours UNTIL
  [ -e "$OUT/$1.done" ] || return 1
  [ "${UNTIL:-}" = "$1" ] && { status "UNTIL=$1 (already done): stopping"; exit 0; }
  return 0
}
done_() { touch "$OUT/$1.done"; status "step $1 done"; [ "${UNTIL:-}" = "$1" ] && { status "UNTIL=$1 reached: stopping"; exit 0; }; return 0; }
take_lock() { until [ ! -e "$LOCK" ] || grep -q "^$SCRIPT $RUN_ID " "$LOCK"; do stopchk; sleep 300; done; echo "$SCRIPT $RUN_ID $(date -Is) pid=$$" > "$LOCK"; }
drop_lock() { grep -q "^$SCRIPT $RUN_ID " "$LOCK" 2>/dev/null && rm -f "$LOCK"; return 0; }
gpu_idle() { [ ! -e "$PAUSE" ] && [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9)" -lt 800 ] \
  && ! pgrep -f "[t]rain_3e.py|[t]rain_rsn|[c]ont_train.py|[l]lama-server" >/dev/null; }

serve_run() {   # serve_run <gguf> <log> <cmd...>; returns the client's rc (130 = stopped)
  local m=$1 lg=$2; shift 2
  until gpu_idle; do stopchk; sleep 60; done
  LD_LIBRARY_PATH=$LC/bin nice -n 10 $LC/bin/llama-server -m "$m" -ngl 99 -cram 256 -c 8192 -np 1 --jinja -t 2 -tb 2 --host 127.0.0.1 \
    --port $PORT --no-webui > "$lg" 2>&1 &
  local sp=$!
  for i in $(seq 1 90); do sleep 2; curl -s localhost:$PORT/health | grep -q ok && break; done
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 "$@" &
  local cp=$!
  ( hot=0; while sleep 20; do kill -0 $cp 2>/dev/null || exit 0
      if [ -e "$PAUSE" ] || stopped; then kill $cp; kill -CONT $sp; exit 0; fi       # client first: no error rows recorded
      t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | head -1 | cut -d. -f1 | tr -dc 0-9); f=$(free_mb)
      { { [ -n "$t" ] && [ "$t" -ge 80 ]; } || { [ -n "$f" ] && [ "$f" -lt 1536 ]; }; } && hot=1
      [ $hot = 1 ] && kill -STOP $sp
      if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 72 ] && { [ -z "$f" ] || [ "$f" -ge 2560 ]; }; then kill -CONT $sp; hot=0; fi
    done ) &
  local wd=$!
  wait $cp; local rc=$?
  kill $wd 2>/dev/null; kill -CONT $sp 2>/dev/null; kill $sp 2>/dev/null; wait $sp 2>/dev/null
  stopped && rc=130
  return $rc
}

run_pools() {   # run_pools <results tag>: needs $GGUF, $OUT/pool_inc.jsonl, $OUT/pool_chat.jsonl
  local tag=$1
  if ! isdone run_inc; then
    take_lock
    serve_run "$GGUF" "$OUT/server_inc.log" python3 "$L/run_suite.py" --tag "$tag" --port $PORT --suite pool --file "$OUT/pool_inc.jsonl" \
      > "$OUT/run_inc.log" 2>&1; rc=$?
    drop_lock; stopchk
    [ $rc = 0 ] || die "incident pool run failed: $(tail -n 2 "$OUT/run_inc.log")"
    status "incident pool: $(tail -n 1 "$OUT/run_inc.log")"
    done_ run_inc
  fi
  if ! isdone run_chat; then
    take_lock
    serve_run "$GGUF" "$OUT/server_chat.log" $PY "$L/chat3_eval.py" --port $PORT --think 1 --records "$OUT/pool_chat.jsonl" \
      --out "$OUT/pool_chat_res.jsonl" > "$OUT/run_chat.log" 2>&1; rc=$?
    drop_lock; stopchk
    [ $rc = 0 ] || die "chat pool run failed: $(tail -n 2 "$OUT/run_chat.log")"
    status "chat pool: $(tail -n 1 "$OUT/run_chat.log")"
    done_ run_chat
  fi
}

teacher() {     # teacher <failed records> <out rows>
  local recs=$1 rows=$2 T=$OUT/teacher n
  mkdir -p "$T"
  n=$(wc -l < "$recs")
  if [ "$n" -gt 0 ]; then
    need_ram 2048 60
    until gpu_idle; do stopchk; sleep 120; done
    (cd "$DLD" && HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PATH=$PATH:/usr/lib/wsl/lib nice -n 10 $PY distill_llama.py \
      --dir "$T" --name "${SCRIPT}_teacher_$RUN_ID" --hours "${TEACHER_H:-8}" --set teacher="$recs") > "$T/run.log" 2>&1 &
    local dp=$!
    ( while kill -0 $dp 2>/dev/null; do stopped && touch "$T/STOP"; sleep 30; done ) &
    wait $dp; rm -f "$T/STOP"
    stopchk
    grep -qE "GPU busy|render check failed|restart failed" "$T/distill.log" 2>/dev/null && die "teacher distillation did not run: $(tail -n 1 "$T/distill.log")"
    status "teacher: $(grep -c . "$T/raw_teacher.jsonl" 2>/dev/null || echo 0)/$n questions sampled ($(tail -n 1 "$T/distill.log" | cut -c1-120))"
  fi
  $PY "$DLD/select_distill.py" --records "$recs" --raw "$T/raw_teacher.jsonl" --out "$rows" --report "$T/select_report.json" \
    --fallback-unsampled > "$T/select.log" 2>&1 || die "select_distill failed ($T/select.log)"
  status "teacher rows: $(tail -n 1 "$T/select.log" | cut -c1-200)"
}

train_loop() {  # train_loop <mode> <run dir name> <data> <extra cont_train flags>
  local mode=$1 run=$2 data=$3 extra=$4 fails=0 rc
  while true; do
    stopchk
    RUN=$run STOP_FILE=$OUT/STOP CHUNK_H=${CHUNK_H:-3} ARGS="--mode $mode --base $BASE ${MODEL_DIR:+--model-dir $MODEL_DIR} --adapter $CKPT \
      --tools $V3/pipeline/tools_v4.json --data $data --max-len $MAX_LEN --gen-inc $GEN_INC --gen-chat $GEN_CHAT $extra" \
      bash "$L/cont_chunk.sh"; rc=$?
    case $rc in
      0|6) status "$mode training finished (rc $rc)"; return 0;;
      3) fails=0;;
      7) stopchk; exit 0;;
      *) fails=$((fails + 1)); status "$mode chunk rc $rc (failure $fails/3)"; [ $fails -ge 3 ] && die "$mode training keeps failing"; sleep 600;;
    esac
  done
}

best_ckpt() {
  local O=$HOME/smartcity_runs/$1
  python3 -c "import json,sys;t=json.load(open('$O/best.json'))['top'];print('$O/ckpt_best_%04d' % t[0][1] if t else '')" 2>/dev/null
}

export_gate() { # export_gate <ckpt> <gguf name> <gate run id>
  local ck=$1 name=$2 gid=$3 G=$QIDK/Code/models_stage/${2}_q4_0.gguf rc
  [ -s "$G" ] || bash "$L/export_gguf.sh" "$BASE" "$ck" "$name" || die "export failed"
  if [ ! -s "$KG/gate/$gid/gate.json" ]; then
    RUN_ID=$gid bash "$L/gate_eval.sh" "$G"; rc=$?
  else
    python3 -c "import json,sys;sys.exit(0 if json.load(open('$KG/gate/$gid/gate.json'))['pass'] else 1)"; rc=$?
  fi
  echo "$G" > "$KG/gate/$gid/gguf.txt"
  return $rc
}

setup_candidate() {   # GATE -> TAG, GGUF; CKPT/BASE/MAX_LEN checks (training steps only)
  [ -n "${GATE:-}" ] || die "GATE missing (the gate run id whose failures drive this run, e.g. GATE=g2b_r1)" 2
  [ -s "$KG/gate/$GATE/gate.json" ] || die "no $KG/gate/$GATE/gate.json" 2
  GTAG=rsn_v3_$GATE
  GGUF=${GGUF:-$(cat "$KG/gate/$GATE/gguf.txt" 2>/dev/null)}
  [ -s "$GGUF" ] || die "no candidate GGUF (GGUF=... or $KG/gate/$GATE/gguf.txt)" 2
  [ -n "${CKPT:-}" ] && [ -s "$CKPT/adapter_model.safetensors" ] || die "CKPT must be the candidate's adapter dir (adapter_model.safetensors)" 2
  case "$GGUF" in *_2b*) BASE=${BASE:-$HOME/models/qwen3.5-2b};; *) BASE=${BASE:-$HOME/models/qwen3.5-4b};; esac
  [ -s "$BASE/config.json" ] || die "no base model at $BASE (BASE=...)" 2
  MAX_LEN=${MAX_LEN:-$(python3 -c "import json;print(json.load(open('$(dirname "$CKPT")/maxlen.json'))['max_len'])" 2>/dev/null || echo 4096)}
  for f in "$INC_E1" "$GEN_INC" "$GEN_CHAT"; do [ -s "$f" ] || die "missing $f" 2; done
}
