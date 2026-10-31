#!/usr/bin/env bash
# laptop_train.sh: one guarded chunk of train_rsn3.py on the RTX 4050 (the 2B candidate by default), resumable.
#   env: RUN (run dir name under ~/smartcity_runs, default rsn3_2b), BASE (model dir, default ~/models/qwen3.5-2b),
#        INC CHAT DEV GEN_INC GEN_CHAT GEN_TRAIN_CHAT (data files), CHUNK_H (hours this call, default 3), EXTRA (more trainer flags)
# - first call: fit probe at 6144 / 5120 / 4096 tokens (2 synthetic rows + real rows, r32, NF4, bf16) -> maxlen.json
# - GPU_LOCK held while the GPU is used (waits while another job holds it; never touches that job);
#   one trainer per run dir (run.pid); STOP file (run dir or kaggle/chain/STOP) -> clean stop at the next step;
#   watchdog (10 s): GPU >= 84 C or Windows available RAM < 1.0 GB -> SIGSTOP, resume at <= 79 C and >= 1.1 GB (narrow band: the
#   4050 heats 51 -> 86 C in 90 s and a 75 C resume point left it idle most of the time); heartbeat -> STATUS.md
# exit: trainer rc (0 done, 3 chunk time used, 4 waiting for chat, 5 epoch 1 done, 6 early stop), 7 = lock/guard wait aborted
SCRIPT=laptop_train; source "$(dirname "$0")/guard.sh"
RUN=${RUN:-rsn3_2b}; BASE=${BASE:-$HOME/models/qwen3.5-2b}; CHUNK_H=${CHUNK_H:-3}
O=$HOME/smartcity_runs/$RUN; mkdir -p "$O"
LOCK=$V3/GPU_LOCK; PY=~/venvs/rsn/bin/python
[ -s "$BASE/config.json" ] || die "no base model at $BASE" 2
for f in "$INC" "$DEV"; do [ -s "$f" ] || die "missing data file $f" 2; done
if [ -s "$O/run.pid" ] && kill -0 "$(cat "$O/run.pid")" 2>/dev/null; then die "another trainer is running on $O (pid $(cat "$O/run.pid"))" 8; fi
echo $$ > "$O/run.pid"
[ -e "$O/STOP" ] || [ -e "$KG/chain/STOP" ] && { status "STOP file present: not starting"; exit 3; }
need_ram 1536 60
need_disk ~ 8000
until [ ! -e "$LOCK" ] || grep -q "^laptop_train $RUN " "$LOCK"; do
  [ -e "$KG/chain/STOP" ] && exit 7
  sleep 300
done
echo "laptop_train $RUN $(date -Is) pid=$$" > "$LOCK"
trap 'grep -q "^laptop_train $RUN " "$LOCK" 2>/dev/null && rm -f "$LOCK"; rm -f "$O/run.pid"' EXIT
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
COMMON="--base $BASE --tools $V3/pipeline/tools_v4.json --inc $INC --dev $DEV --quant nf4 --dtype bf16"
if [ ! -s "$O/maxlen.json" ]; then
  for L in 6144 5120 4096; do
    mkdir -p "$O/probe"
    nice -n 10 $PY "$KG/train_rsn3.py" $COMMON --out "$O/probe" --accum 8 --probe-steps 1 --probe-len $L --max-len 8192 > "$O/probe/probe_$L.log" 2>&1
    r=$(grep -h PROBE_RESULT "$O/probe/train.log" 2>/dev/null | tail -1 | sed 's/.*PROBE_RESULT //'); : > "$O/probe/train.log"
    status "$RUN probe len $L: ${r:-failed ($(tail -n 1 "$O/probe/probe_$L.log" | cut -c1-120))}"
    if echo "$r" | grep -q '"oom_steps": 0'; then echo "{\"max_len\": $L, \"probe\": $r}" > "$O/maxlen.json"; break; fi
  done
  [ -s "$O/maxlen.json" ] || die "$RUN: nothing fits even at 4096 tokens" 9
fi
ML=$(python3 -c "import json;print(json.load(open('$O/maxlen.json'))['max_len'])")
ARGS="$COMMON --out $O --max-len $ML --accum 16 ${CHAT:+--chat $CHAT} ${GEN_INC:+--gen-inc $GEN_INC} ${GEN_CHAT:+--gen-chat $GEN_CHAT} \
 --gen-train-inc $INC ${GEN_TRAIN_CHAT:+--gen-train-chat $GEN_TRAIN_CHAT} ${EXTRA:-}"
status "$RUN chunk start (max_len $ML, ${CHUNK_H} h${CHAT:+, chat on})"
nice -n 10 $PY "$KG/train_rsn3.py" $ARGS --hours "$CHUNK_H" >> "$O/stdout.log" 2>&1 &
TP=$!
( hot=0; n=0; np=0; while sleep 10; do kill -0 $TP 2>/dev/null || exit 0
    { [ -e "$O/STOP" ] || [ -e "$KG/chain/STOP" ]; } && touch "$O/STOP"
    t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | tr -dc 0-9); f=$(free_mb)
    if [ $hot = 0 ] && { { [ -n "$t" ] && [ "$t" -ge 84 ]; } || { [ -n "$f" ] && [ "$f" -lt 1024 ]; }; }; then kill -STOP $TP; hot=1; np=$((np + 1)); { [ $((np % 30)) = 1 ] || [ "${f:-9999}" -lt 1024 ]; } && status "$RUN paused #$np (gpu ${t}C, ram ${f} MB)"; fi
    if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 79 ] && { [ -z "$f" ] || [ "$f" -ge 1100 ]; }; then kill -CONT $TP; hot=0; fi
    n=$((n + 1)); [ $((n % 180)) = 0 ] && status "$RUN heartbeat: $(tail -n 1 "$O/train.log" 2>/dev/null | cut -c1-140)"
  done ) &
WD=$!
wait $TP; rc=$?
kill $WD 2>/dev/null
rm -f "$O/STOP"
status "$RUN chunk end rc=$rc: $(tail -n 1 "$O/train.log" 2>/dev/null | cut -c1-160)"
exit $rc
