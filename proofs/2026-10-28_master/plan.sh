#!/usr/bin/env bash
# Master plan (owner 2026-10-28): one detached chain so nothing depends on a Claude session.
# Already-detached jobs: b50 (CPU build), p3b (GPU queue, RAM-gated), newhex_build (waits >=5 GB).
# This chain: wait for P3b's verdict -> build/stage the winner (winner_build.sh handles the missing-c49 path).
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; L=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/plan.log
log(){ echo "$(date -u +%FT%TZ) $*" >> $L; }
log "plan start"
until [ -s $D/B50_STAGED.json ]; do sleep 120; done; log "B50 staged: $(cat $D/B50_STAGED.json | head -c 200)"
until [ -s $D/QUEUE_DONE_P3B.json ]; do sleep 300; done; log "P3b done: $(head -c 300 $D/QUEUE_DONE_P3B.json)"
bash $D/scripts/winner_build.sh < /dev/null >> $L 2>&1; log "winner_build rc=$?"
log "plan done (board deploys + Kaggle import are run by agents/owner)"
