#!/usr/bin/env bash
# export.sh ADAPTER_DIR TAG [shared|own]: agt_v3 adapter -> Q4_0 GGUF exactly like B50 (b50_build.sh -> topup3f/post_3f.sh):
# merge_mix.py (bf16, fp32 sum, layer-wise low RAM) -> f16 GGUF (convert_hf_to_gguf.py) -> imatrix -> llama-quantize Q4_0 with
# --output-tensor-type q8_0 --token-embedding-type f16 --tensor-type ffn_down=q4_0 -> per-tensor type check vs the B50 GGUF -> md5.
# imatrix: "shared" (selection screening; computed once on the first exported snapshot, as B50 screening reused imatrix_v2) or
# "own" (final candidate: its own imatrix on its Q8_0). Calibration = 512 synthetic agt_v3 TRAIN rows (prompt + gold),
# 64 x 1024 tokens (the v2 recipe). CPU only. Resumable. -> $POST/<TAG>/agt3_<TAG>_q4_0.gguf (+ .md5, gguf_check.json)
source "$(dirname "$(readlink -f "$0")")/lib.sh"
ADIR=$1; TAG=$2; IMX=${3:-shared}
P=$POST/$TAG; mkdir -p "$P"; OUTG=$P/agt3_${TAG}_q4_0.gguf; B=$LLAMA/build-host/bin
exec >> "$P/export.log" 2>&1
echo "=== $(date -Is) export $TAG from $ADIR imatrix=$IMX"
[ -s "$OUTG" ] && [ -s "$OUTG.md5" ] && { echo "already done"; exit 0; }
need_c; need_ram 3000
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 CUDA_VISIBLE_DEVICES=
dc() { /mnt/c/Windows/System32/wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || true; }
CAL=$POST/calib_agt3.txt
if [ ! -s "$CAL" ]; then
  "$PY" -I - "$AGT_TRAIN" "$CAL" "$A/kaggle" <<'P' || exit 4
import json, random, sys
sys.path.insert(0, sys.argv[3]); import rows as RW
rs = RW.read_jsonl(sys.argv[1]); random.Random(2026).shuffle(rs)
by = {}
for r in rs:
    n = RW.norm(r); by.setdefault((n["role"], n["family"]), []).append(n)
pick, keys = [], sorted(by)
while len(pick) < 512 and any(by.values()):
    for k in keys:
        if by[k] and len(pick) < 512: pick.append(by[k].pop())
open(sys.argv[2], "w").write("\n".join(n["prompt"] + n["completion"] for n in pick))
P
fi
if [ ! -s "$P/f16.gguf" ]; then
  echo "{\"mix\": [[\"$ADIR\", 1.0]], \"chosen\": \"$TAG\"}" > "$P/choice.json"
  rm -rf "$P/merged"
  nice "$TPY" "$QIDK/Code/smart-city-edge-agent/training/v2/topup3f/merge_mix.py" --post "$P" --out "$P/merged" --base "$BASE_LOCAL" || exit 1
  dc
  SHIM=$P/pyshim; mkdir -p "$SHIM"; SP=$(ls -d ~/venvs/*/lib/python3.11/site-packages/sentencepiece 2>/dev/null | head -1); [ -n "$SP" ] && ln -sfn "$SP" "$SHIM/sentencepiece"
  PYTHONPATH=$LLAMA/gguf-py:$SHIM nice "$TPY" "$LLAMA/convert_hf_to_gguf.py" "$P/merged" --outtype f16 --outfile "$P/f16.gguf.tmp" \
    && mv "$P/f16.gguf.tmp" "$P/f16.gguf" || exit 2
  rm -rf "$P/merged"; dc
fi
mkimx() {   # mkimx F16 OUT
  nice "$B/llama-quantize" "$1" "$P/q8.gguf" Q8_0 2 > "$P/q8.log" 2>&1 && \
  nice "$B/llama-imatrix" -m "$P/q8.gguf" -f "$CAL" --parse-special -c 1024 --chunks 64 -t 6 -o "$2.tmp" --output-format gguf > "$P/imatrix.log" 2>&1 && \
  mv "$2.tmp" "$2"; rm -f "$P/q8.gguf"; [ -s "$2" ]
}
if [ "$IMX" = own ]; then IM=$P/imatrix.gguf; [ -s "$IM" ] || mkimx "$P/f16.gguf" "$IM" || exit 3
else IM=$POST/imatrix_agt3_shared.gguf; [ -s "$IM" ] || { mkimx "$P/f16.gguf" "$IM" && echo "{\"from\": \"$TAG\"}" > "$IM.json"; } || exit 3; fi
nice "$B/llama-quantize" --imatrix "$IM" --output-tensor-type q8_0 --token-embedding-type f16 --tensor-type ffn_down=q4_0 \
  "$P/f16.gguf" "$OUTG.tmp" Q4_0 2 > "$P/q4_0.log" 2>&1 && mv "$OUTG.tmp" "$OUTG" || exit 3
rm -f "$P/f16.gguf"; dc
PYTHONPATH=$LLAMA/gguf-py "$TPY" - "$B50_GGUF" "$OUTG" "$IM" > "$P/gguf_check.json" <<'PY'
import collections, json, sys
import gguf
def types(f):
    return {t.name: (t.tensor_type.name, [int(x) for x in t.shape]) for t in gguf.GGUFReader(f).tensors}
a, b = types(sys.argv[1]), types(sys.argv[2])
diff = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}
print(json.dumps({"gguf": sys.argv[2], "imatrix": sys.argv[3], "n_tensors": len(b), "types": dict(collections.Counter(v[0] for v in b.values())),
                  "tensor_type_match_vs_B50": not diff, "diff": {k: str(v) for k, v in list(diff.items())[:10]}}, indent=1))
PY
md5sum "$OUTG" | cut -d' ' -f1 > "$OUTG.md5"
echo "=== $(date -Is) DONE $TAG $(cat "$OUTG.md5") $(grep -o '"tensor_type_match_vs_B50": [a-z]*' "$P/gguf_check.json")"
