#!/usr/bin/env bash
# Reasoner QLoRA run (agent-owned background shell; no nohup/setsid). Watchdog: kill the job if HEARTBEAT > 15 min old.
# Starts only when the GPU is idle (< 800 MiB used, no other trainer) and Windows has >= 3 GB free RAM.
R=~/smartcity_runs/reasoner_v1; O=$R/${RUN:-run1}; H=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/train
HB=$R/HEARTBEAT; mkdir -p $O; touch $HB; exec >> $R/master.log 2>&1; MAIN=$$
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
free_mb() { $PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -dc 0-9; }
PAUSEF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/PAUSE_GPU
lim() { h=$(TZ=Asia/Kolkata date +%-H); if [ $h -ge 22 ] || [ $h -lt 8 ]; then echo 14400; else echo 900; fi; }   # owner rule
( paused=0; while sleep 60; do kill -0 $MAIN 2>/dev/null || exit 0; age=$(( $(date +%s) - $(stat -c %Y $HB) ))
  [ -e $PAUSEF ] && [ $paused -eq 1 ] && { pkill -CONT -f "[t]rain_rsn.py"; paused=0; }
  [ -e $PAUSEF ] && continue
  if [ $age -gt $(lim) ]; then echo "$(date +%T) WATCHDOG: heartbeat ${age}s old -> stopping"; pkill -CONT -f "[t]rain_rsn.py"; pkill -TERM -f "[t]rain_rsn.py"; sleep 120; pkill -KILL -f "[t]rain_rsn.py"; kill $MAIN; exit 0; fi
  f=$(free_mb); [ -z "$f" ] && continue
  if [ $paused -eq 0 ] && [ "$f" -lt 1536 ]; then pkill -STOP -f "[t]rain_rsn.py" && { paused=1; echo "$(date +%T) RAM PAUSE: Windows free ${f} MB"; }; fi
  if [ $paused -eq 1 ] && [ "$f" -ge 3072 ]; then pkill -CONT -f "[t]rain_rsn.py"; paused=0; echo "$(date +%T) RAM RESUME: ${f} MB"; fi
done ) &
WD=$!; trap "kill $WD 2>/dev/null; pkill -TERM -f '[t]rain_rsn.py'" EXIT
waitgpu() { while true; do u=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9)
  if [ "$u" -lt 800 ] && ! pgrep -f "[t]rain_3e.py|[l]lama-server" >/dev/null; then f=$(free_mb); [ -n "$f" ] && [ "$f" -ge 3072 ] && return; echo "$(date +%T) RAM gate: ${f} MB free"; fi; sleep 30; done; }
source ~/venvs/rsn/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold:0.8
cd $H; echo "=== $(date) run.sh start $O args: $*"
[ -e /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/PAUSE_GPU ] && { echo "PAUSE_GPU present -> not starting"; exit 0; }
until grep -q '"done": true' $O/status.json 2>/dev/null; do
  waitgpu; echo "$(date +%T) GPU free, RAM ok -> train"
  nice -n 10 python train_rsn.py --out $O "$@"; rc=$?; echo "$(date +%T) train rc=$rc"
  [ -e $O/STOP ] && { echo "STOP file -> exit"; exit 0; }
  [ -e /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/PAUSE_GPU ] && { echo "$(date +%T) owner PAUSE_GPU -> exit"; exit 0; }
  [ $rc -eq 3 ] && grep -q "heartbeat" $O/train.log && exit 0
  [ "$PROBE" = 1 ] && exit 0
  sleep 60
done
echo "=== $(date) RUN DONE"
