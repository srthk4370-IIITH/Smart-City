#!/usr/bin/env bash
# eval_gguf.sh <gguf> <tag> [suites]  -- one llama-server (CUDA b11815) on the GPU, run the suites, stop the server.
# Run only when no training holds the GPU (one model on the GPU). Agent-owned shell; the caller touches HEARTBEAT.
G=$1; TAG=$2; SUITES=${3:-rw6,rwh,dev,chatdev,p0}; PORT=18096; LC=~/llama-cuda-b11815
HB=~/smartcity_runs/reasoner_v1/HEARTBEAT; E=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/eval
u=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9); [ "$u" -gt 800 ] && { echo "GPU busy ($u MiB)"; exit 2; }
LD_LIBRARY_PATH=$LC/bin nice -n 10 $LC/bin/llama-server -m $G -ngl 99 ${LORA:+--lora $LORA} -c 8192 -np 1 --jinja -t 2 -tb 2 --host 127.0.0.1 --port $PORT --no-webui > $E/results/server_$TAG.log 2>&1 &
SP=$!; MAIN=$$
# watchdog (2026-10-28): stale HEARTBEAT or PAUSE_GPU -> stop; GPU >= 80 C or Windows Available < 1.5 GB -> SIGSTOP the
# server (re-applied every pass), resume at <= 72 C and >= 2.5 GB
PAUSE=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/PAUSE_GPU; PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
( hot=0; while sleep 20; do kill -0 $MAIN 2>/dev/null || exit 0
    if [ $(( $(date +%s) - $(stat -c %Y $HB) )) -gt 900 ] || [ -e $PAUSE ]; then echo "WATCHDOG stop"; kill -CONT $SP; kill $SP; pkill -f "run_v3.py --tag $TAG"; exit 0; fi
    t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | tr -dc 0-9)
    f=$($PS -NoProfile -Command "[int](Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue" < /dev/null 2>/dev/null | tr -dc 0-9)
    { { [ -n "$t" ] && [ "$t" -ge 80 ]; } || { [ -n "$f" ] && [ "$f" -lt 1536 ]; }; } && { [ $hot = 0 ] && echo "pause gpu=${t}C avail=${f}MB"; hot=1; }
    [ $hot = 1 ] && kill -STOP $SP
    if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 72 ] && { [ -z "$f" ] || [ "$f" -ge 2560 ]; }; then kill -CONT $SP; hot=0; echo "resume gpu=${t}C avail=${f}MB"; fi
  done ) &
WD=$!; trap "kill $SP $WD 2>/dev/null" EXIT
for i in $(seq 1 90); do sleep 2; curl -s localhost:$PORT/health | grep -q ok && break; done
cd $E && python3 run_v3.py --tag $TAG --port $PORT --suites $SUITES
