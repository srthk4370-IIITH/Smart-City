#!/usr/bin/env bash
# cont_chunk.sh: one guarded chunk of cont_train.py (repair SFT or DPO continuation of an adapter) on the laptop GPU, resumable.
# Same guards as laptop_train.sh: GPU_LOCK (waits while another job holds it; never touches that job), one trainer per run dir
# (run.pid), STOP file (run dir, kaggle/chain/STOP or the caller's STOP_FILE) -> clean stop at the next step, watchdog (10 s):
# GPU >= 84 C or Windows available RAM < 1.5 GB -> SIGSTOP, resume at <= 79 C and >= 2 GB; heartbeat -> STATUS.md.
#   env: RUN (run dir name under ~/smartcity_runs), ARGS (cont_train.py flags without --out/--hours), CHUNK_H (default 3),
#        STOP_FILE (extra stop file, e.g. the repair run's STOP)
# exit: cont_train rc (0 done, 3 chunk time used / STOP, 6 early stop), 7 = lock wait aborted by STOP
SCRIPT=${SCRIPT:-cont_chunk}; source "$(dirname "$0")/guard.sh"
RUN=${RUN:?RUN}; ARGS=${ARGS:?ARGS}; CHUNK_H=${CHUNK_H:-3}; STOP_FILE=${STOP_FILE:-$KG/chain/STOP}
O=$HOME/smartcity_runs/$RUN; mkdir -p "$O"
LOCK=$V3/GPU_LOCK; PY=~/venvs/rsn/bin/python
stopped() { [ -e "$O/STOP" ] || [ -e "$KG/chain/STOP" ] || [ -e "$STOP_FILE" ]; }
if [ -s "$O/run.pid" ] && kill -0 "$(cat "$O/run.pid")" 2>/dev/null; then die "another trainer is running on $O (pid $(cat "$O/run.pid"))" 8; fi
echo $$ > "$O/run.pid"
stopped && { status "STOP file present: not starting $RUN"; rm -f "$O/run.pid"; exit 3; }
need_ram 1536 60
need_disk ~ 8000
until [ ! -e "$LOCK" ] || grep -q "^cont_train $RUN " "$LOCK"; do
  stopped && { rm -f "$O/run.pid"; exit 7; }
  sleep 300
done
echo "cont_train $RUN $(date -Is) pid=$$" > "$LOCK"
trap 'grep -q "^cont_train $RUN " "$LOCK" 2>/dev/null && rm -f "$LOCK"; rm -f "$O/run.pid"' EXIT
until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9)" -lt 800 ]; do
  stopped && exit 7
  status "$RUN waiting: GPU memory in use by a process outside GPU_LOCK"; sleep 300
done
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
status "$RUN chunk start (${CHUNK_H} h)"
nice -n 10 $PY "$KG/local/cont_train.py" $ARGS --out "$O" --hours "$CHUNK_H" >> "$O/stdout.log" 2>&1 &
TP=$!
( hot=0; n=0; np=0; while sleep 10; do kill -0 $TP 2>/dev/null || exit 0
    stopped && touch "$O/STOP"
    t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | tr -dc 0-9); f=$(free_mb)
    if [ $hot = 0 ] && { { [ -n "$t" ] && [ "$t" -ge 84 ]; } || { [ -n "$f" ] && [ "$f" -lt 1536 ]; }; }; then kill -STOP $TP; hot=1; np=$((np + 1)); { [ $((np % 30)) = 1 ] || [ "${f:-9999}" -lt 1536 ]; } && status "$RUN paused #$np (gpu ${t}C, ram ${f} MB)"; fi
    if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 79 ] && { [ -z "$f" ] || [ "$f" -ge 2048 ]; }; then kill -CONT $TP; hot=0; fi
    n=$((n + 1)); [ $((n % 180)) = 0 ] && status "$RUN heartbeat: $(tail -n 1 "$O/train.log" 2>/dev/null | cut -c1-140)"
  done ) &
WD=$!
wait $TP; rc=$?
kill $WD 2>/dev/null
rm -f "$O/STOP"
status "$RUN chunk end rc=$rc: $(tail -n 1 "$O/train.log" 2>/dev/null | cut -c1-160)"
exit $rc
