#!/usr/bin/env bash
# Fine-tuned merged model -> Genie bundle for SM8650 (HTP V75) via Qualcomm AI Hub (free).
#   bash export_to_npu.sh                     # uses the newest ~/smartcity_runs/agents_*/merged
#   MERGED=~/smartcity_runs/<run>/merged bash export_to_npu.sh
#   SPIKE=1 bash export_to_npu.sh             # round-trip test with the UNMODIFIED base model
# Stages are resumable (skipped if their output exists). Do not run while training is using the GPU/RAM.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source ~/venvs/qaihm/bin/activate
export TZ=Asia/Kolkata
export PYTHONPATH="$HERE/pyhooks${PYTHONPATH:+:$PYTHONPATH}"   # parallel S3 transfers (slow per-connection network)
if [ -n "${SPIKE:-}" ]; then
  MERGED=$(ls -d ~/.cache/huggingface/hub/models--meta-llama--Llama-3.2-3B-Instruct/snapshots/* | head -1); TAG=base_spike
else
  MERGED=${MERGED:-$(ls -d ~/smartcity_runs/agents_*/merged | tail -1)}; TAG=ft
fi
CKPT=~/qaihm_work/${TAG}_ckpt_w4a16; OUT=~/qaihm_work/${TAG}_genie
mkdir -p ~/qaihm_work; exec > >(tee -a ~/qaihm_work/${TAG}_export.log) 2>&1
echo "=== $(date) MERGED=$MERGED"; free -g | head -2; df -h ~ | tail -1
FREE_GB=$(df --output=avail -BG ~ | tail -1 | tr -dc 0-9)
echo "WSL free: ${FREE_GB} GB (Windows C: is the real limit; ~45 GB needed)"
if [ ! -f "$CKPT/model_dynamic.onnx" ]; then echo "--- build checkpoint (60-90 min, CPU + swap)"; python "$HERE/build_ft_ckpt.py" "$MERGED" "$CKPT"; fi
# intermediates of the library's export (14 GB each); the checkpoint only needs model_dynamic.onnx + model.data
rm -f "$CKPT/model.onnx" "$CKPT/model.onnx.data" ; rm -rf ~/.qaihm/tmp/*
if [ ! -f "$CKPT/.scales_refreshed" ] && [ -z "${SPIKE:-}" ]; then
  echo "--- MSE-optimal weight scales for the merged weights"
  PUB=$(ls ~/.qaihm/qai-hub-models/models/llama_v3_2_3b_instruct/v*/w4a16/model.encodings 2>/dev/null | tail -1)
  python "$HERE/refresh_param_scales.py" "$CKPT" "$PUB"
  touch "$CKPT/.scales_refreshed"
fi
# AI Hub writes part1_of_3.bin; older local exports wrote llama_..._part_1_of_3.bin
find_bin() { ls "$OUT"/*/part"$1"_of_3.bin "$OUT"/*/*part_"$1"_of_3.bin 2>/dev/null | head -1; }
if [ -z "$(find_bin 3)" ]; then
  echo "--- AI Hub compile (upload ~14 GB + 6 compile + 3 link jobs; 2-3 h)"
  qai-hub-models export llama_v3_2_3b_instruct --checkpoint "$CKPT" --device "Samsung Galaxy S24 (Family)" \
    --target-runtime genie --skip-profiling --output-dir "$OUT"
fi
FIRST="$(find_bin 1)"
if [ -z "$FIRST" ]; then echo "ERROR: no context binaries in $OUT"; exit 1; fi
B=$(dirname "$FIRST")
echo "=== bundle ready: $B"; ls -la "$B"; grep -i qairt "$B"/tool-versions.yaml 2>/dev/null || true
echo "Next (Windows):  powershell -ExecutionPolicy Bypass -File Code\\smart-city-edge-agent\\training\\deploy_tuned.ps1"
