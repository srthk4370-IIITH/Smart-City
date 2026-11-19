#!/usr/bin/env bash
# Early-AI gate study GPU run (2026-11-12). Start: bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh early_ai <this>
# Waits for a free GPU (no GPU_LOCK, < 800 MiB used, no llama-server/train_), takes GPU_LOCK, serves the gated reasoner
# (rsn_v3_4b_r3_q4_0, port 8192) and the agents (ft_B50_q4_0 via the htpd shim, 8193/8191) on llama-cuda-b11815,
# runs 2 shards of the Go harness (resumable: rows already in raw/rows.jsonl are skipped). Guards every 20 s:
# GPU >= 92 C or Windows free RAM < 500 MB -> pause (no new rows), resume at <= 88 C and >= 800 MB; deadline
# EAS_HOURS (default 5.5 h of run time) -> stop file; always releases its own GPU_LOCK and servers.
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_early_ai; W=~/early_ai; LOCK=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK
M=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage; L=~/llama-cuda-b11815/bin; PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
log() { echo "$(date -u +%FT%TZ) $*" | tee -a $P/raw/run.log; }
free_mb() { $PS -NoProfile -Command "[int](Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue" < /dev/null 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9; }
gtemp() { nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | head -1 | cut -d. -f1 | tr -dc 0-9; }
gpu_free() { [ ! -e "$LOCK" ] && [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | cut -d. -f1 | tr -dc 0-9)" -lt 800 ] \
  && ! pgrep -f "[l]lama-server|[t]rain_" >/dev/null; }
mkdir -p $P/raw $W/work; rm -f $W/PAUSE $W/STOP
w=0; until gpu_free; do [ $((w % 30)) = 0 ] && log "waiting for GPU ($(head -c 80 $LOCK 2>/dev/null))"; w=$((w+1)); sleep 120; done
echo "early_ai_study $(date -Is) pid $$ (proofs/2026-11-12_early_ai)" > "$LOCK"
SRV=""
cleanup() { [ -n "$SRV" ] && kill $SRV 2>/dev/null; sleep 3; grep -q "^early_ai_study" "$LOCK" 2>/dev/null && rm -f "$LOCK"; log "servers stopped, GPU_LOCK released"; }
trap cleanup EXIT
log "lock taken"
export LD_LIBRARY_PATH=$L:$LD_LIBRARY_PATH
$L/llama-server -m $M/rsn_v3_4b_r3_q4_0.gguf -c 16384 -np 2 -ngl 99 -fa auto --port 8192 --host 127.0.0.1 -t 4 > $W/rsn_server.log 2>&1 & SRV="$!"
$L/llama-server -m $M/ft_B50_q4_0.gguf -c 8192 -np 4 -ngl 99 -fa auto --port 8193 --host 127.0.0.1 -t 4 > $W/agent_server.log 2>&1 & SRV="$SRV $!"
python3 $P/harness/htpd_shim.py 8191 http://127.0.0.1:8193 > $W/shim.log 2>&1 & SRV="$SRV $!"
for i in $(seq 120); do curl -sf localhost:8192/health >/dev/null && curl -sf localhost:8193/health >/dev/null && break; sleep 5; done
curl -sf localhost:8192/health >/dev/null || { log "servers failed"; tail -5 $W/rsn_server.log $W/agent_server.log | tee -a $P/raw/run.log; exit 1; }
log "servers up; vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader | head -1)"
printf 'post_rules=all\nsolo_rerun=runaway\nreasoner=v3\n' > $W/work/htpd_profile; echo cool > $W/thermal
export EAS_DATA=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/gate_study/eval3e.jsonl EAS_OUT=$P/raw/rows.jsonl EAS_WORK=$W/work \
  EAS_PAUSE=$W/PAUSE EAS_STOP=$W/STOP EAS_GROUPS=${EAS_GROUPS:-0} SCE_AGENT_VERSION=v2 SCE_NPU_ENGINE=htpd SCE_HTPD=127.0.0.1:8191 \
  SCE_REASONER=v3 SCE_REASONER_ENGINE=llama SCE_REASONER_URL=http://127.0.0.1:8192 SCE_THERMAL_FAKE=$W/thermal
NS=${EAS_NSHARD:-2}; T=""
for s in $(seq 0 $((NS-1))); do
  (cd $W/app/backend && EAS_SHARD=$s EAS_NSHARD=$NS EAS_OUT=$P/raw/rows_s$s.jsonl $W/eas.test -test.run TestEarlyAIStudy -test.timeout 0 -test.v > $W/shard$s.log 2>&1) & T="$T $!"
done
end=$(( $(date +%s) + $(awk "BEGIN{print int(${EAS_HOURS:-5.5}*3600)}") )); hot=0
while true; do
  alive=0; for p in $T; do kill -0 $p 2>/dev/null && alive=1; done; [ $alive = 0 ] && break
  [ $(date +%s) -ge $end ] && [ ! -e $W/STOP ] && { touch $W/STOP; log "deadline: stop after current rows"; }
  t=$(gtemp); f=$(free_mb); want=0
  { [ -n "$t" ] && [ "$t" -ge 92 ]; } && want=1; { [ -n "$f" ] && [ "$f" -lt 500 ]; } && want=1
  if [ $hot = 0 ] && [ $want = 1 ]; then touch $W/PAUSE; hot=1; log "pause gpu=${t}C free=${f}MB"; fi
  if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 88 ] && { [ -z "$f" ] || [ "$f" -ge 800 ]; }; then rm -f $W/PAUSE; hot=0; log "resume gpu=${t}C free=${f}MB"; fi
  sleep 20
done
log "shards finished: $(cat $P/raw/rows_s*.jsonl 2>/dev/null | wc -l) rows"; tail -3 $W/shard*.log | tee -a $P/raw/run.log
log "EARLY_AI_DONE"
