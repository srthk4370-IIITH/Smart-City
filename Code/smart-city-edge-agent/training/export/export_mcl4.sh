#!/usr/bin/env bash
# Re-export the EXISTING fine-tuned GPTQ checkpoint with multiple context lengths.
# Same weights, same encodings -> identical model, different graph shapes only.
# CKPT must be the w4a16 checkpoint: w4 compiles but does NOT load on 8 Gen 3 (err 1002).
# Graphs per part = len(sequence_lengths) x len(context_lengths) = 2 x 2 = 4  (must stay <= 8).
# Any bundle with >2 graphs per part also needs "enable-graph-switching": true in the Genie config,
# or it fails to load with err 1002 (HANDBOOK 2.12). Extra graphs cost ~200 ms prefill + ~150 ms
# init per call, so only add one if it buys more than that.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source ~/venvs/qaihm/bin/activate
export TZ=Asia/Kolkata
export PYTHONPATH="$HERE/pyhooks${PYTHONPATH:+:$PYTHONPATH}"   # parallel S3 upload hook
CKPT=~/qaihm_work/ftgptq16_ckpt
OUT=~/qaihm_work/ftgptq16_genie_mcl4
[ -f "$CKPT/.ready" ] || { echo "checkpoint not ready"; exit 1; }
mkdir -p "$OUT"
echo "=== $(date) multi-context-length export"
echo "    ckpt=$CKPT  out=$OUT  ctx=[2048,4096]  seq=[128,1] (default)"
qai-hub-models export llama_v3_2_3b_instruct \
  --checkpoint "$CKPT" \
  --context-lengths 2048,4096 \
  --device "Samsung Galaxy S24 (Family)" \
  --target-runtime genie --skip-profiling \
  --output-dir "$OUT"
echo "=== $(date) DONE"; find "$OUT" -name "*.bin" -o -name "*.json" | head -30; du -sh "$OUT"
