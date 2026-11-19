#!/usr/bin/env bash
# ONE command to resume the early-AI gate study (waits for GPU_LOCK to be free, then resumes; rows already in
# raw/rows_s*.jsonl are skipped). From Windows:
#   wsl.exe -e bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_early_ai/harness/start.sh
# Rebuilds the harness copy in ~/early_ai if it is missing, starts run.sh detached (proofs/detach.sh) and a hidden
# keepalive. Optional env: EAS_HOURS (run-time cap after the lock is taken, default 5.5), KEEP_H (keepalive, default 80).
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_early_ai; W=~/early_ai; A=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app
pgrep -f "2026-11-12_early_ai/harness/run.sh" >/dev/null && { echo "already running"; exit 0; }
if [ ! -x $W/eas.test ] || ! cmp -s $P/harness/eas_test.go $W/app/backend/eas_test.go; then
  rm -rf $W/app; mkdir -p $W/app/device; cp -r $A/backend $W/app/; cp -r $A/device/data $W/app/device/
  cp $P/harness/eas_test.go $W/app/backend/
  (cd $W/app/backend && PATH=$HOME/go-sdk/go/bin:$PATH GOPROXY=off nice go test -c -o $W/eas.test .) || { echo "build failed"; exit 1; }
fi
EAS_HOURS=${EAS_HOURS:-5.5} bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh early_ai $P/harness/run.sh
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command "Start-Process -WindowStyle Hidden wsl.exe -ArgumentList '-e','bash','/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/distill_laptop/keepalive.sh','early_ai','${KEEP_H:-80}'"
echo "started; progress: tail $P/raw/run.log; analysis: python3 $P/harness/analyze.py"
