#!/usr/bin/env bash
# Seed library generation (standalone: bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh rag_seed <this>). GENERATION only.
# Waits for final/.f3 (reasoner decided) and an idle GPU, serves that exact reasoner GGUF (CUDA b11815, -ngl 99, 2 CPU threads),
# runs seed_run.py over balanced train-split incidents until done or 08:45 IST, builds rag_seed.json, touches .done.
# Guards (20 s): GPU >= 80 C or Windows Available < 1.5 GB -> SIGSTOP the server, resume <= 72 C and >= 2.5 GB; PAUSE_GPU -> stop.
S=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/rag_seed; F=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/final
STAGE=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage; LC=~/llama-cuda-b11815; PORT=18097
PAUSE=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/PAUSE_GPU; PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
exec >> $S/seed_gen.log 2>&1 < /dev/null; MAIN=$$
log(){ echo "$(date -u +%FT%TZ) $*"; }
ist(){ TZ=Asia/Kolkata date +%H%M; }
log "waiting for final/.f3 and an idle GPU"
until [ -e $F/.f3 ] && [ -s $F/reasoner ]; do [ -e $PAUSE ] && exit 0; [ "$(ist)" -ge 0845 ] && [ "$(ist)" -lt 1200 ] && { log "deadline before start"; exit 0; }; sleep 60; done
R=$(cat $F/reasoner | tr -d ' \n')
case $R in qwen35_reasoner_q4_0.gguf|rsn_v1*) G=$STAGE/rsn_v1_q4_0.gguf; TAG=rsn_v1;; rsn_v2*) G=$STAGE/rsn_v2_q4_0.gguf; TAG=rsn_v2;; *) G=$STAGE/$R; TAG=${R%.gguf};; esac
[ -s $G ] || { log "reasoner GGUF $G missing"; exit 2; }
log "reasoner $R -> $G ($TAG)"
until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9)" -lt 800 ]; do [ -e $PAUSE ] && exit 0; sleep 60; done
LD_LIBRARY_PATH=$LC/bin nice -n 10 $LC/bin/llama-server -m $G -ngl 99 -c 8192 -np 1 --jinja -t 2 -tb 2 --host 127.0.0.1 --port $PORT --no-webui > $S/server.log 2>&1 &
SP=$!
( hot=0; while sleep 20; do kill -0 $MAIN 2>/dev/null || exit 0
    if [ -e $PAUSE ]; then log "PAUSE_GPU -> stop"; kill -CONT $SP; kill $SP; pkill -f "seed_run.py run"; exit 0; fi
    t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | tr -dc 0-9)
    f=$($PS -NoProfile -Command "[int](Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue" < /dev/null 2>/dev/null | tr -dc 0-9)
    { { [ -n "$t" ] && [ "$t" -ge 80 ]; } || { [ -n "$f" ] && [ "$f" -lt 1536 ]; }; } && { [ $hot = 0 ] && log "pause gpu=${t}C avail=${f}MB"; hot=1; }
    [ $hot = 1 ] && kill -STOP $SP
    if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 72 ] && { [ -z "$f" ] || [ "$f" -ge 2560 ]; }; then kill -CONT $SP; hot=0; log "resume gpu=${t}C"; fi
  done ) &
WD=$!; trap "kill -CONT $SP 2>/dev/null; kill $SP $WD 2>/dev/null" EXIT
for i in $(seq 1 120); do sleep 2; curl -s localhost:$PORT/health | grep -q ok && break; done
log "server up; generating"
cd $S && python3 seed_run.py run --port $PORT --tag $TAG --n 1000 --until 0845
kill -CONT $SP; kill $SP 2>/dev/null
python3 seed_run.py build --tag $TAG && touch $S/.done
log "=== seed done: $(cat $S/manifest.json | tr -d '\n ' | cut -c1-200)"
