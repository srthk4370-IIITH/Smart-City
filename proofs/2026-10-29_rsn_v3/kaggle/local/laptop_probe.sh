#!/usr/bin/env bash
# laptop_probe.sh: how train_rsn3.py fits on the RTX 4050 (6 GB): r32, NF4 pre-quantized base, bf16, fla, micro-batch 1.
# For each length (default 6144 5120 4096 3072) one optimizer step of 8 rows: 2 synthetic rows of that length (fit test)
# + 6 real incident rows (speed). Stops at the first length that fits. Takes GPU_LOCK for the duration (waits if another job
# holds it; never touches that job). Result lines -> kaggle/local/laptop_probe.json + STATUS.md.
# usage: bash laptop_probe.sh <incident rows .jsonl> [lengths...]
SCRIPT=laptop_probe; source "$(dirname "$0")/guard.sh"
INC=${1:?incident rows file}; shift
LENS=${*:-6144 5120 4096 3072}
LOCK=$V3/GPU_LOCK
OUT=${PROBE_OUT:-$HOME/smartcity_runs/rsn3_probe}; mkdir -p "$OUT"
need_ram 1536
while [ -e "$LOCK" ] && ! grep -q "^rsn3_laptop_probe" "$LOCK"; do status "waiting for GPU_LOCK ($(head -c 80 "$LOCK"))"; sleep 120; done
echo "rsn3_laptop_probe $(date -Is)" > "$LOCK"; trap 'grep -q "^rsn3_laptop_probe" "$LOCK" 2>/dev/null && rm -f "$LOCK"' EXIT
[ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9)" -lt 800 ] || die "GPU busy"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
R=$KG/local/laptop_probe.json; : > "$R"
for L in $LENS; do
  need_ram 1536
  nice -n 10 ~/venvs/rsn/bin/python "$KG/train_rsn3.py" --base ~/models/qwen3.5-4b --model-dir ~/models/qwen3.5-4b-nf4 \
    --tools "$V3/pipeline/tools_v4.json" --inc "$INC" --out "$OUT" --accum 8 --probe-steps 1 --probe-len "$L" --max-len 8192 \
    > "$OUT/probe_$L.log" 2>&1
  l=$(grep -h "PROBE_RESULT" "$OUT/train.log" | tail -1 | sed 's/.*PROBE_RESULT //')
  grep -h "PROBE_RESULT" "$OUT/train.log" | tail -1 >/dev/null
  echo "{\"len\": $L, \"result\": ${l:-null}, \"log_tail\": $(tail -n 2 "$OUT/probe_$L.log" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()[-300:]))')}" >> "$R"
  : > "$OUT/train.log"
  status "len $L: ${l:-no result (see $OUT/probe_$L.log)}"
  echo "$l" | grep -q '"oom_steps": 0' && break
done
