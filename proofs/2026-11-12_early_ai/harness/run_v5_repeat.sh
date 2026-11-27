#!/usr/bin/env bash
# Repeat copy of run_v5.sh (EAS_RAW / EAS_DATA_IN overrides) for the k=8 self-repeat noise floor. Early-AI gate study, v5 rerun (2026-11-27). Same harness as run.sh, with today's board models and profile:
#   reasoner rsn_v3_4b_v5_q4_0 (md5 afdae452..., = board /data/local/tmp/gpu), agents agt3_s0450_q4_0 (md5 996777a4..., = board)
#   profile: post_rules=all solo_rerun=runaway reasoner=v3 reasoner_prompt=v4 reasoner_think=adaptive agents=agt_v3
#            agent_tools=1 agent_ctx=1280 (board lines), shim HTPD_AGENT_MAX_NEW=240 with the Llama 3.2 prefill marker.
# Output: raw_v5/ (old raw/ untouched). Resumable (rows already in raw_v5/rows_s*.jsonl are skipped).
# Owner rules 2026-11-27: no pause/SIGSTOP throttling. Guards every 20 s only log; GPU >= 92 C, Windows free RAM < 500 MB or
# C: < 20 GB free -> STOP file (shards finish their current row and exit), servers released; rerun this script to resume.
# GPU_LOCK: the same file the other jobs use. The known stale 2026-10-31 laptop_train line (pid long gone) is saved and
# restored on exit, as proofs/2026-11-26_paper/metrics_gen/r4_models.sh does.
Q=/mnt/c/Users/hp/Desktop/qidk; P=$Q/proofs/2026-11-12_early_ai; R=${EAS_RAW:-$P/raw_v5}; W=~/early_ai; LOCK=$Q/proofs/2026-10-29_rsn_v3/GPU_LOCK
RSN=$Q/Code/models_stage/rsn_v3_4b_v5_q4_0.gguf; AGT=~/smartcity_runs/agt_topup_k2b/post/s0450/agt3_s0450_q4_0.gguf
L=~/llama-cuda-b11815/bin; PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
STALE="laptop_train rsn3_2b_r1 2026-10-31T21:45:50+00:00 pid=17932"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a $R/run.log; }
free_mb() { $PS -NoProfile -Command "[int](Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue" < /dev/null 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9; }
gtemp() { nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | head -1 | cut -d. -f1 | tr -dc 0-9; }
cfree_gb() { df -BG /mnt/c | tail -1 | awk '{print $4}' | tr -dc 0-9; }
lock_free() { [ ! -e "$LOCK" ] || [ "$(cat $LOCK 2>/dev/null)" = "$STALE" ]; }
gpu_free() { lock_free && [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | cut -d. -f1 | tr -dc 0-9)" -lt 800 ] \
  && ! pgrep -f "[l]lama-server|[t]rain_" >/dev/null; }
mkdir -p $R $W/work; rm -f $W/PAUSE $W/STOP
w=0; until gpu_free; do [ $((w % 15)) = 0 ] && log "waiting for GPU ($(head -c 80 $LOCK 2>/dev/null))"; w=$((w+1)); sleep 120; done
OLD=$(cat $LOCK 2>/dev/null)
echo "early_ai_v5 $(date -Is) pid $$ (proofs/2026-11-12_early_ai)" > "$LOCK"
SRV=""; T=""
cleanup() {
  touch $W/STOP; [ -n "$T" ] && kill $T 2>/dev/null; [ -n "$SRV" ] && kill $SRV 2>/dev/null; sleep 3
  if grep -q "^early_ai_v5" "$LOCK" 2>/dev/null; then if [ -n "$OLD" ]; then echo "$OLD" > $LOCK; else rm -f $LOCK; fi; fi
  log "servers stopped, GPU_LOCK released"
}
trap cleanup EXIT
trap 'log "signal: stopping"; exit 1' INT TERM HUP
log "lock taken (saved: ${OLD:-none})"
export LD_LIBRARY_PATH=$L:$LD_LIBRARY_PATH
$L/llama-server -m $RSN -c ${RSN_CTX:-16384} -np 2 -ngl 99 -fa auto -cram 256 --port 8192 --host 127.0.0.1 -t 4 --no-webui > $W/rsn_server.log 2>&1 & SRV="$!"
$L/llama-server -m $AGT -c ${AGT_CTX:-4096} -np 2 -ngl ${AGT_NGL:-99} -fa auto -cram 256 --port 8193 --host 127.0.0.1 -t 4 --no-webui > $W/agent_server.log 2>&1 & SRV="$SRV $!"
HTPD_AGENT_MAX_NEW=240 python3 $P/harness/htpd_shim_v5.py 8191 http://127.0.0.1:8193 > $W/shim.log 2>&1 & SRV="$SRV $!"
for i in $(seq 120); do curl -sf localhost:8192/health >/dev/null && curl -sf localhost:8193/health >/dev/null && break; sleep 5; done
{ curl -sf localhost:8192/health >/dev/null && curl -sf localhost:8193/health >/dev/null; } || { log "servers failed"; tail -5 $W/rsn_server.log $W/agent_server.log | tee -a $R/run.log; exit 1; }
log "servers up; vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader | head -1)"
printf 'post_rules=all\nsolo_rerun=runaway\nreasoner=v3\nreasoner_prompt=v4\nreasoner_think=adaptive\nagents=agt_v3\nagent_tools=1\nagent_ctx=1280\n' > $W/work/htpd_profile
cp $W/work/htpd_profile $R/htpd_profile_used; echo cool > $W/thermal
export EAS_DATA=${EAS_DATA_IN:-$Q/proofs/2026-10-28_master/gate_study/eval3e.jsonl} EAS_WORK=$W/work \
  EAS_PAUSE=$W/PAUSE EAS_STOP=$W/STOP EAS_GROUPS=${EAS_GROUPS:-0} SCE_AGENT_VERSION=v2 SCE_NPU_ENGINE=htpd SCE_HTPD=127.0.0.1:8191 \
  SCE_REASONER=v3 SCE_REASONER_ENGINE=llama SCE_REASONER_URL=http://127.0.0.1:8192 SCE_THERMAL_FAKE=$W/thermal
NS=${EAS_NSHARD:-2}
for s in $(seq 0 $((NS-1))); do
  (cd $W/app/backend && EAS_SHARD=$s EAS_NSHARD=$NS EAS_OUT=$R/rows_s$s.jsonl exec $W/eas.test -test.run TestEarlyAIStudy -test.timeout 0 -test.v > $W/shard$s.log 2>&1) & T="$T $!"
done
end=$(( $(date +%s) + $(awk "BEGIN{print int(${EAS_HOURS:-7}*3600)}") )); i=0
while true; do
  alive=0; for p in $T; do kill -0 $p 2>/dev/null && alive=1; done; [ $alive = 0 ] && break
  [ $(date +%s) -ge $end ] && [ ! -e $W/STOP ] && { touch $W/STOP; log "deadline: stop after current rows"; }
  t=$(gtemp); f=$(free_mb); c=$(cfree_gb)
  [ $((i % 15)) = 0 ] && log "gpu=${t}C free_ram=${f}MB c_free=${c}GB rows=$(cat $R/rows_s*.jsonl 2>/dev/null | wc -l)"
  if [ ! -e $W/STOP ]; then
    why=""
    { [ -n "$t" ] && [ "$t" -ge 92 ]; } && why="gpu ${t}C >= 92"
    { [ -n "$f" ] && [ "$f" -lt 500 ]; } && why="windows free RAM ${f} MB < 500"
    { [ -n "$c" ] && [ "$c" -lt 20 ]; } && why="C: free ${c} GB < 20"
    [ -n "$why" ] && { touch $W/STOP; log "STOP ($why): shards finish their current row; rerun run_v5.sh later to resume"; }
  fi
  i=$((i+1)); sleep 20
done
log "shards finished: $(cat $R/rows_s*.jsonl 2>/dev/null | wc -l) rows"; tail -3 $W/shard*.log | tee -a $R/run.log
[ -e $W/STOP ] && log "EARLY_AI_V5_STOPPED (resumable)" || log "EARLY_AI_V5_DONE"
