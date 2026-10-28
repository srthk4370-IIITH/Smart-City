#!/usr/bin/env bash
# merged_v2 (HF bf16) -> GGUF f16 -> imatrix on OUR calibration prompts -> Q4_0 (device candidate) + Q4_K_M
# (host-side alternative; the Hexagon backend runs Q4_0 / Q8_0, so Q4_K_M is for comparison only).
# Device layout as today (pack_exact_gguf.py): every block Q4_0, output.weight Q8_0, token_embd F16.
# Resumable: finished files are kept. Usage: bash to_gguf.sh  (env: RUN, POST, LLAMA_CPP, IMATRIX_CHUNKS)
set -euo pipefail
RUN="${RUN:-$HOME/smartcity_runs/agents_v2}"
POST="${POST:-$RUN/post}"
MERGED="${MERGED:-$RUN/merged_v2}"
L="${LLAMA_CPP:-$HOME/gpu_work/llama.cpp}"
B="$L/build-host/bin"
GG="$POST/gguf"
CHUNKS="${IMATRIX_CHUNKS:-256}"     # x 1024 tokens; calib.txt holds ~450k tokens, the first 256 chunks cover all strata (shuffled)
THREADS="${THREADS:-8}"
PY="$HOME/venvs/train/bin/python"
mkdir -p "$GG"
cd "$GG"
ts() { date '+%F %T'; }

if [ ! -s ft_v2_f16.gguf ]; then
  echo "[$(ts)] convert HF -> f16 GGUF"
  # the converter imports sentencepiece before falling back to Llama 3's BPE vocab; the train venv lacks it, so
  # borrow the (py3.11) package from the qaihm venv through a one-package shim dir - nothing is installed
  SHIM="$POST/pyshim"; mkdir -p "$SHIM"
  SP=$(ls -d "$HOME"/venvs/*/lib/python3.11/site-packages/sentencepiece 2>/dev/null | head -1)
  [ -n "$SP" ] && ln -sfn "$SP" "$SHIM/sentencepiece"
  PYTHONPATH="$L/gguf-py:$SHIM" "$PY" "$L/convert_hf_to_gguf.py" "$MERGED" --outtype f16 --outfile ft_v2_f16.gguf.tmp
  mv ft_v2_f16.gguf.tmp ft_v2_f16.gguf
fi
if [ ! -s ft_v2_q8_0.gguf ]; then
  echo "[$(ts)] Q8_0 (imatrix pass model; faster than f16 on CPU, near-lossless)"
  "$B/llama-quantize" ft_v2_f16.gguf ft_v2_q8_0.gguf.tmp Q8_0 "$THREADS"
  mv ft_v2_q8_0.gguf.tmp ft_v2_q8_0.gguf
fi
if [ ! -s imatrix_v2.gguf ]; then
  echo "[$(ts)] imatrix on $(wc -c < "$POST/calib/calib.txt") chars of calibration prompts, $CHUNKS chunks x 1024"
  "$B/llama-imatrix" -m ft_v2_q8_0.gguf -f "$POST/calib/calib.txt" --parse-special -c 1024 --chunks "$CHUNKS" \
      -t "$THREADS" -o imatrix_v2.gguf.tmp --output-format gguf --save-frequency 64 2>&1 | grep -vE "^\s*$" | tail -n 40
  [ -s imatrix_v2.gguf.tmp ] && mv imatrix_v2.gguf.tmp imatrix_v2.gguf
fi
# ffn_down: llama-quantize bumps the first layers to Q4_1 for the Q4_0 ftype; the Hexagon backend runs Q4_0/Q8_0 only
TYPES="--output-tensor-type q8_0 --token-embedding-type f16 --tensor-type ffn_down=q4_0"
if [ ! -s ft_v2_q4_0.gguf ]; then
  echo "[$(ts)] Q4_0 + imatrix (device candidate)"
  "$B/llama-quantize" --imatrix imatrix_v2.gguf $TYPES ft_v2_f16.gguf ft_v2_q4_0.gguf.tmp Q4_0 "$THREADS"
  mv ft_v2_q4_0.gguf.tmp ft_v2_q4_0.gguf
fi
if [ ! -s ft_v2_q4_0_noimx.gguf ]; then
  echo "[$(ts)] Q4_0 without imatrix (to measure what the imatrix buys)"
  "$B/llama-quantize" $TYPES ft_v2_f16.gguf ft_v2_q4_0_noimx.gguf.tmp Q4_0 "$THREADS"
  mv ft_v2_q4_0_noimx.gguf.tmp ft_v2_q4_0_noimx.gguf
fi
if [ ! -s ft_v2_q4_k_m.gguf ]; then
  echo "[$(ts)] Q4_K_M + imatrix (host alternative)"
  "$B/llama-quantize" --imatrix imatrix_v2.gguf ft_v2_f16.gguf ft_v2_q4_k_m.gguf.tmp Q4_K_M "$THREADS"
  mv ft_v2_q4_k_m.gguf.tmp ft_v2_q4_k_m.gguf
fi
echo "[$(ts)] tensor types + hashes"
PYTHONPATH="$L/gguf-py" "$PY" - <<'PY'
import collections, glob, hashlib, json, os
import gguf
res = {}
for f in sorted(glob.glob("ft_v2_*.gguf")):
    r = gguf.GGUFReader(f)
    c = collections.Counter(t.tensor_type.name for t in r.tensors)
    special = {t.name: t.tensor_type.name for t in r.tensors if not t.name.startswith("blk.")}
    h = hashlib.sha256()
    with open(f, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 24), b""):
            h.update(b)
    res[f] = {"bytes": os.path.getsize(f), "sha256": h.hexdigest(), "types": dict(c), "non_block": special}
json.dump(res, open("gguf_manifest.json", "w"), indent=1)
print(json.dumps(res, indent=1))
PY
echo "[$(ts)] to_gguf done"
