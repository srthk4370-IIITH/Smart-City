#!/usr/bin/env bash
# Export the GPTQ checkpoint (built by gptq_quant.py + gptq_to_ckpt.py) to a Genie bundle.
# Scales are already exact for the GPTQ integers, so NO scale refresh is run here.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source ~/venvs/qaihm/bin/activate
export TZ=Asia/Kolkata
export PYTHONPATH="$HERE/pyhooks${PYTHONPATH:+:$PYTHONPATH}"
CKPT=${CKPT:-~/qaihm_work/ftgptq_ckpt}
OUT=${OUT:-~/qaihm_work/ftgptq_genie}
exec > >(tee -a ~/qaihm_work/ftgptq_export.log) 2>&1
echo "=== $(date) GPTQ export: $CKPT ($(cat "$CKPT/args.json"))"
[ -f "$CKPT/.ready" ] || { echo "checkpoint not ready"; exit 1; }
find_bin() { ls "$OUT"/*/part"$1"_of_3.bin "$OUT"/*/*part_"$1"_of_3.bin 2>/dev/null | head -1; }
if [ -z "$(find_bin 3)" ]; then
  qai-hub-models export llama_v3_2_3b_instruct --checkpoint "$CKPT" --device "Samsung Galaxy S24 (Family)" \
    --target-runtime genie --skip-profiling --output-dir "$OUT"
fi
FIRST="$(find_bin 1)"; [ -n "$FIRST" ] || { echo "ERROR: no context binaries in $OUT"; exit 1; }
echo "=== GPTQ bundle ready: $(dirname "$FIRST")"; ls -la "$(dirname "$FIRST")"
