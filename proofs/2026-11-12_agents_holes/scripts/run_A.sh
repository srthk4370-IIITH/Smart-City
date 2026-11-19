#!/usr/bin/env bash
# GPU_LOCK wrapper for run_A.py: wait while the lock is held / GPU busy / Windows RAM low; take lock; release on exit.
LOCK=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK; D=$(dirname "$0")
gpu_free() { [ ! -e "$LOCK" ] && [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -dc 0-9)" -lt 800 ] \
  && ! pgrep -f "[l]lama-server|[t]rain_" >/dev/null; }
until gpu_free; do echo "$(date -Is) waiting for GPU"; sleep 120; done
echo "agents_holes studyA $(date -Is) pid $$" > "$LOCK"
trap 'grep -q "^agents_holes studyA" "$LOCK" 2>/dev/null && rm -f "$LOCK"' EXIT
echo "$(date -Is) lock taken"
timeout 7000 python3 "$D/run_A.py"
echo "$(date -Is) exit $?"
