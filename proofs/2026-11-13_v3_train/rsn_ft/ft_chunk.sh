#!/usr/bin/env bash
# ft_chunk.sh (from topup_chunk.sh 2026-11-13): one guarded chunk of rsn_ft_train.py on the RTX 4050 (as kaggle/local/laptop_train.sh, which stays unchanged).
#   env (chain_r4.sh): RUN, START_ADAPTER, NEW REPLAY TOOLS4 DEV4_INC DEV4_CHAT GEN_INC3 GEN_CHAT3, MAX_LEN, CHUNK_H,
#        FIT_FLAGS TOPUP_FLAGS GEN_FLAGS
# - waits for an idle GPU: GPU_LOCK free (or ours), no other trainer / llama-server, < 800 MiB used; then holds GPU_LOCK
# - one trainer per run dir (run.pid); STOP file (run dir or chain dir) -> clean stop at the next step
# - watchdog (10 s): GPU >= 92 C or Windows available RAM < 400 MB -> SIGSTOP; resume at <= 88 C and >= 500 MB; heartbeat
# exit: trainer rc (0 done, 3 chunk time / STOP, 6 early stop, 7 OOM STOP, 9 data check, 10 init check), 11 = GPU wait aborted (STOP)
SCRIPT=ft_chunk; RUN_ID=v3ft; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
T4=$QIDK/proofs/2026-11-13_v3_train/rsn_ft; C=$T4/chain; mkdir -p "$C"
RUN=${RUN:-rsn3_4b_v3ft}; BASE=${BASE:?BASE (edited base dir) missing}; CHUNK_H=${CHUNK_H:-6}
O=$HOME/smartcity_runs/$RUN; mkdir -p "$O"
LOCK=$V3/GPU_LOCK; PY=~/venvs/rsn/bin/python
[ -s "$BASE/config.json" ] || die "no base model at $BASE" 2
for f in "$NEW" "$REPLAY" "$TOOLS4" ${START_ADAPTER:+"$START_ADAPTER/adapter_model.safetensors"}; do [ -s "$f" ] || die "missing $f" 2; done
if [ -s "$O/run.pid" ] && kill -0 "$(cat "$O/run.pid")" 2>/dev/null; then die "another trainer is running on $O (pid $(cat "$O/run.pid"))" 8; fi
echo $$ > "$O/run.pid"
trap 'grep -q "^rsn_ft $RUN " "$LOCK" 2>/dev/null && rm -f "$LOCK"; rm -f "$O/run.pid"' EXIT
{ [ -e "$O/STOP" ] || [ -e "$C/STOP" ]; } && { status "STOP file present: not starting"; exit 3; }
need_ram 800 60
need_disk ~ 8000
gmem() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9; }
gpu_free() { { [ ! -e "$LOCK" ] || grep -q "^rsn_ft $RUN " "$LOCK"; } && [ "$(gmem)" -lt 800 ] 2>/dev/null \
  && ! pgrep -f "[l]lama-server|[t]rain_rsn3.py|[t]rain_3e.py|[c]ont_train.py|[r]sn_ft_train.py|[t]opup_train.py" > /dev/null; }
t=0; until gpu_free; do
  { [ -e "$O/STOP" ] || [ -e "$C/STOP" ]; } && exit 11
  [ $((t % 12)) = 0 ] && status "waiting for an idle GPU (lock: $(head -c 80 "$LOCK" 2>/dev/null || echo none), $(gmem) MiB used)"
  sleep 300; t=$((t + 1))
done
echo "rsn_ft $RUN $(date -Is) pid=$$" > "$LOCK"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export TORCHINDUCTOR_COMPILE_THREADS=1 MALLOC_ARENA_MAX=2 RSN3_SEG_TOKENIZE=1 RSN3_GEN_TOK_BUDGET=${RSN3_GEN_TOK_BUDGET:-8400}
ARGS="--base $BASE ${START_ADAPTER:+--init-adapter $START_ADAPTER} --tools $TOOLS4 --new $NEW --replay $REPLAY
 --out $O --max-len ${MAX_LEN:-7424} --quant nf4 --dtype bf16 --gen-v4-inc $DEV4_INC --gen-v4-chat $DEV4_CHAT ${R3REF:+--r3-ref $R3REF}
 --gen-inc $GEN_INC3 --gen-chat $GEN_CHAT3 ${FIT_FLAGS:?FIT_FLAGS missing} ${TOPUP_FLAGS:-} ${GEN_FLAGS:-} ${MAX_STEPS:+--max-steps $MAX_STEPS}"
status "$RUN chunk start (${CHUNK_H} h, max_len ${MAX_LEN:-7424})"
nice -n 10 $PY "$T4/rsn_ft_train.py" $ARGS --hours "$CHUNK_H" >> "$O/stdout.log" 2>&1 &
TP=$!
( hot=0; n=0; np=0; while sleep 10; do kill -0 $TP 2>/dev/null || exit 0
    { [ -e "$O/STOP" ] || [ -e "$C/STOP" ]; } && touch "$O/STOP"
    t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | head -1 | cut -d. -f1 | tr -dc 0-9); f=$(free_mb)
    if [ $hot = 0 ] && { { [ -n "$t" ] && [ "$t" -ge 92 ]; } || { [ -n "$f" ] && [ "$f" -lt 400 ]; }; }; then kill -STOP $TP; hot=1; np=$((np + 1)); { [ $((np % 30)) = 1 ] || [ "${f:-9999}" -lt 1024 ]; } && status "$RUN paused #$np (gpu ${t}C, ram ${f} MB)"; fi
    if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 88 ] && { [ -z "$f" ] || [ "$f" -ge 500 ]; }; then kill -CONT $TP; hot=0; fi
    n=$((n + 1)); [ $((n % 180)) = 0 ] && status "$RUN heartbeat: $(tail -n 1 "$O/train.log" 2>/dev/null | cut -c1-140)"
  done ) &
WD=$!
wait $TP; rc=$?
kill $WD 2>/dev/null
rm -f "$O/STOP"
status "$RUN chunk end rc=$rc: $(tail -n 1 "$O/train.log" 2>/dev/null | cut -c1-160)"
exit $rc
