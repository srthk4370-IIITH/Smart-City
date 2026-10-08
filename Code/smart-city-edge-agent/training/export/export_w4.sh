#!/usr/bin/env bash
# Step A: export the fine-tuned model at precision w4 (4-bit weights, fp16 activations).
# w4 has NO activation encodings, so the base-model activation ranges we were forced to reuse for
# w4a16 cannot be stale. Reuses the already-built ONNX graph + fine-tuned weights (identical for both
# precisions) via hard links, so nothing is rebuilt.
#   bash export_w4.sh                 # SCALE_MODE=widen (default; best measured on device)
#   SCALE_MODE=published bash export_w4.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source ~/venvs/qaihm/bin/activate
export TZ=Asia/Kolkata
export PYTHONPATH="$HERE/pyhooks${PYTHONPATH:+:$PYTHONPATH}"
SRC=~/qaihm_work/ft_ckpt_w4a16
CKPT=~/qaihm_work/ftw4_ckpt
OUT=~/qaihm_work/ftw4_genie
mkdir -p ~/qaihm_work; exec > >(tee -a ~/qaihm_work/ftw4_export.log) 2>&1
echo "=== $(date) w4 export, SCALE_MODE=${SCALE_MODE:-widen}"
[ -f "$SRC/model_dynamic.onnx" ] || { echo "missing $SRC (run export_to_npu.sh once first)"; exit 1; }

if [ ! -f "$CKPT/.ready" ]; then
  mkdir -p "$CKPT"
  for f in model.data model_dynamic.onnx; do ln -f "$SRC/$f" "$CKPT/$f"; done
  for f in config.json special_tokens_map.json tokenizer.json tokenizer_config.json; do cp "$SRC/$f" "$CKPT/"; done
  PUB=$(python - <<'PY'
from qai_hub_models.models.llama_v3_2_3b_instruct.model import Llama3_2_3B_QuantizablePreSplit as Q
from qai_hub_models.utils.asset_loaders import CachedWebModelAsset
print(CachedWebModelAsset.from_asset_store(Q.model_id, Q.model_asset_version, "w4/model.encodings").fetch())
PY
)
  echo "published w4 encodings: $PUB"
  python "$HERE/refresh_param_scales.py" "$CKPT" "$PUB"
  echo '{"precision": "w4"}' > "$CKPT/args.json"
  touch "$CKPT/.ready"
fi

find_bin() { ls "$OUT"/*/part"$1"_of_3.bin "$OUT"/*/*part_"$1"_of_3.bin 2>/dev/null | head -1; }
if [ -z "$(find_bin 3)" ]; then
  echo "--- AI Hub compile (w4)"
  qai-hub-models export llama_v3_2_3b_instruct --checkpoint "$CKPT" --device "Samsung Galaxy S24 (Family)" \
    --target-runtime genie --skip-profiling --output-dir "$OUT"
fi
FIRST="$(find_bin 1)"
[ -n "$FIRST" ] || { echo "ERROR: no context binaries in $OUT"; exit 1; }
echo "=== w4 bundle ready: $(dirname "$FIRST")"; ls -la "$(dirname "$FIRST")"
