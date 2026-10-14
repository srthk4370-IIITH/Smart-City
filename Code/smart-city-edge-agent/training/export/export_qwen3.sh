#!/usr/bin/env bash
# Export Qwen3-1.7B as the SEPARATE cross-domain reasoner (owner's decision, 2026-10-14):
# a distinct model so cross-domain reasoning does not degrade the five fine-tuned domain agents,
# and so it can be fine-tuned and improved from operator feedback on its own schedule.
#
# Stock weights for now. Default sequence/context lengths (ar128 + ar1 at the model's defaults
# would mean several context lengths); pinned to ctx 2048, 2 graphs per part, the shape this
# device's DSP SMMU accepts without graph switching (HANDBOOK 2.12).
#
#   setsid nohup bash export_qwen3.sh > ~/qaihm_work/qwen3_run.log 2>&1 &
#   cat ~/qaihm_work/qwen3.status
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source ~/venvs/qaihm/bin/activate
export TZ=Asia/Kolkata
OUT=~/qaihm_work/qwen3_1_7b_genie
ST=~/qaihm_work/qwen3.status
note() { echo "$(date +%H:%M:%S) $*" | tee -a "$ST"; }
: > "$ST"

mem_free_mb() { awk '/MemAvailable/ {m=$2} /SwapFree/ {s=$2} END {print int((m+s)/1024)}' /proc/meminfo; }
( while sleep 20; do
    a=$(mem_free_mb)
    [ "$a" -lt 600 ] && { note "MEM GUARD: ${a} MB RAM+swap left - stopping export"; pkill -f "qai-hub-models export qwen3"; }
  done ) & GUARD=$!
trap 'kill $GUARD 2>/dev/null || true' EXIT
setsid nohup bash "$HERE/disk_guard.sh" 5 >/dev/null 2>&1 &

rm -rf "$OUT"; mkdir -p "$OUT"
note "START qwen3_1_7b (RAM+swap free $(mem_free_mb) MB)"
t0=$(date +%s)
# PYTHONUNBUFFERED so progress reaches the log as it happens - the failed ar4 run left an EMPTY
# log after 10 minutes, which made it impossible to tell what it was doing.
if PYTHONUNBUFFERED=1 qai-hub-models export qwen3_1_7b \
     --sequence-lengths 128,1 --context-lengths 2048 \
     --target-runtime genie --skip-profiling \
     --device "Samsung Galaxy S24 (Family)" --output-dir "$OUT"; then
  note "DONE in $(( ($(date +%s) - t0) / 60 )) min: $(find "$OUT" -name '*.bin' | wc -l) bins, $(du -sh "$OUT" | cut -f1)"
else
  note "FAILED after $(( ($(date +%s) - t0) / 60 )) min - see ~/qaihm_work/qwen3_run.log"
fi
