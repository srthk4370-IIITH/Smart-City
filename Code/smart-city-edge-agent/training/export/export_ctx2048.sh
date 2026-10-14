#!/usr/bin/env bash
# Re-export the SAME fine-tuned checkpoint with a 2048-token context instead of 4096.
#
# Why: the KV cache is a fixed buffer sized by the compiled context length, and on this model it is
#   28 layers x 8 KV heads x 128 head-dim x 2 (K,V) x ctx x 2 bytes
#   = 469 MB at ctx 4096, 235 MB at ctx 2048
# That buffer is part of the bytes the NPU moves per decode token, and decode is bandwidth-bound
# (HANDBOOK 2.15), so halving it should take roughly 10% off decode. We use ~610 of the 4096 slots
# on an agent call, so the upper half of that buffer is pure waste.
#
# ctx 1024 was considered and rejected: generation has been measured reaching ~1120 tokens total,
# and the Mode 2 / synthesizer prompts are far longer than an agent prompt, so 1024 would overflow.
#
# IMPORTANT: this changes NOTHING about the model. Same checkpoint, same encodings, same weights,
# same 4-bit params and 8-bit lm_head. No fine-tuning, no retraining, no recalibration. The only
# difference is the compiled context window. Output must still be proven identical with
# compare_bundles.py before anything ships.
#
# Never run two exports at once: that is what exhausted WSL memory and filled C: on 2026-10-14.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source ~/venvs/qaihm/bin/activate
export TZ=Asia/Kolkata
export PYTHONPATH="$HERE/pyhooks${PYTHONPATH:+:$PYTHONPATH}"
CKPT=${CKPT:-~/qaihm_work/ftgptq16_ckpt}
OUT=${OUT:-~/qaihm_work/ftgptq16_genie_ctx2048}

[ -f "$CKPT/.ready" ] || { echo "checkpoint not ready: $CKPT"; exit 1; }

# refuse to start if another export is already running
if pgrep -f "qai-hub-models export" >/dev/null; then
  echo "ERROR: an export is already running; refusing to start a second one"
  exit 1
fi

# Memory guard. NOTE: this export is EXPECTED to exhaust RAM and run into swap - that is normal for
# this pipeline and is why the swap VHD grew on 2026-10-14. An earlier version of this guard watched
# MemAvailable alone and killed two perfectly healthy exports at 141 MB and 233 MB free, while
# gigabytes of swap sat unused. So the guard watches RAM + swap together, which is the real
# out-of-memory condition. The historical failure mode was the DISK filling, not RAM; disk_guard.sh
# below is the one that actually matters.
mem_free_mb() { awk '/MemAvailable/ {m=$2} /SwapFree/ {s=$2} END {print int((m+s)/1024)}' /proc/meminfo; }
avail_mb=$(mem_free_mb)
echo "RAM+swap available at start: ${avail_mb} MB"
if [ "$avail_mb" -lt 6000 ]; then
  echo "ERROR: only ${avail_mb} MB of RAM+swap available, need ~6600 MB. Close things or restart WSL."
  exit 1
fi
( while true; do
    a=$(mem_free_mb)
    if [ "$a" -lt 600 ]; then
      echo "$(date) MEM GUARD: only ${a} MB of RAM+swap left, aborting export" >> ~/qaihm_work/ctx2048_export.log
      pkill -f "qai-hub-models export"
      exit 1
    fi
    sleep 20
  done ) & MEMGUARD=$!
trap 'kill $MEMGUARD 2>/dev/null || true' EXIT

setsid nohup bash "$HERE/disk_guard.sh" 5 >/dev/null 2>&1 &

mkdir -p "$OUT"
echo "=== $(date) ctx-2048 export"
echo "    ckpt=$CKPT  out=$OUT  context-lengths=2048  (sequence lengths left at the default)"
qai-hub-models export llama_v3_2_3b_instruct \
  --checkpoint "$CKPT" \
  --context-lengths 2048 \
  --device "Samsung Galaxy S24 (Family)" \
  --target-runtime genie --skip-profiling \
  --output-dir "$OUT"
echo "=== $(date) DONE"
find "$OUT" -name '*.bin' -printf '%s\t%p\n' | sort -rn
du -sh "$OUT"
