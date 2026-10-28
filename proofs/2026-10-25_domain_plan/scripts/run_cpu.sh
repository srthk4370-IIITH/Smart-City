#!/usr/bin/env bash
# run_cpu.sh OUTDIR TAG MODEL.gguf [TAG MODEL ...] : host Q4_0 eval on the CPU llama.cpp build (620d222, = htpd),
# 4 threads, nice/ionice idle, one llama-server at a time. Agent-owned background shell only.
#  - HEARTBEAT ($D/HEARTBEAT) older than 15 min -> kill own jobs, exit.
#  - Windows free RAM: start only >= 3 GB; SIGSTOP own llama-server below 2 GB, SIGCONT at >= 3 GB.
#  - resumable: host_eval3e skips ids already in samples.jsonl.
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; OUT=$1; shift
H3E=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
free_mb() { $PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" < /dev/null 2>/dev/null | tr -dc 0-9; }
touch $D/HEARTBEAT; LOG=$D/run_cpu.log; exec >> $LOG 2>&1
SRV="gpu_work/llama.cpp/build-host/bin/llama-server"
mypids() { pgrep -f "$SRV" -P "$(pgrep -f "host_eval3e.py run --out $OUT" | tr '\n' ',' | sed 's/,$//')" 2>/dev/null; }
( paused=0; low=0; while sleep 30; do
    age=$(( $(date +%s) - $(stat -c %Y $D/HEARTBEAT) ))
    if [ $age -gt 900 ]; then echo "$(date +%T) WATCHDOG heartbeat ${age}s -> stop"; P=$(mypids); pkill -f "host_eval3e.py run --out $OUT"; for p in $P; do kill -CONT $p; kill $p; done; kill $$; exit 0; fi
    f=$(free_mb); [ -z "$f" ] && continue
    if [ "$f" -lt 2560 ]; then low=$((low+1)); else low=0; fi
    if [ $paused = 0 ] && [ $low -ge 2 ]; then for p in $(mypids); do kill -STOP $p; done; paused=1; echo "$(date +%T) pause (free ${f} MB)"; fi
    if [ $paused = 1 ] && [ "$f" -ge 3072 ]; then for p in $(mypids); do kill -CONT $p; done; paused=0; echo "$(date +%T) resume (free ${f} MB)"; fi
    if [ $paused = 0 ]; then for q in $(pgrep -f "host_eval3e.py run --out $OUT") $(mypids); do [ "$(ps -o stat= -p $q | cut -c1)" = T ] && { kill -CONT $q; echo "$(date +%T) cont $q (job-control stop)"; }; done; fi
  done ) & WD=$!
trap "kill $WD 2>/dev/null" EXIT
source ~/venvs/train/bin/activate; cd $H3E
while [ $# -ge 2 ]; do
  TAG=$1; M=$2; shift 2
  while f=$(free_mb); [ -z "$f" ] || [ "$f" -lt 4608 ]; do sleep 30; done
  echo "$(date +%T) start $TAG ($M) free ${f} MB"
  nice -n 19 ionice -c3 python host_eval3e.py run --out $OUT --model $M --tag $TAG --threads 4 --np 2 < /dev/null > $OUT/eval_$TAG.log 2>&1
  echo "$(date +%T) done $TAG rows $(wc -l < $OUT/eval/$TAG/samples.jsonl)"
done
echo "$(date +%T) RUN_CPU_DONE"
