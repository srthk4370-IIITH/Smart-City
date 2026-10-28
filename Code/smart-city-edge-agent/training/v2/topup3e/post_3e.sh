#!/usr/bin/env bash
# 3e candidate -> Q4_0 GGUF built exactly like ft_v2_q4_0.gguf: merge_lowmem (bit-exact with merge_v2) -> f16 GGUF ->
# imatrix -> Q4_0 with ffn_down q4_0, output q8_0, token_embd f16 -> per-tensor type check vs the deployed v2 GGUF.
#   bash post_3e.sh ADAPTER_DIR TAG [IMATRIX]
# IMATRIX = v2 (default for screening: reuse imatrix_v2.gguf, same calib; the weight change is ~0.1 %), or "own"
# (compute this model's own imatrix on the same calib.txt, 64 x 1024, on its Q8_0, as post_topup.sh did for v2t/3d).
set -uo pipefail
ADIR=$1; TAG=$2; IMX=${3:-v2}
R=~/smartcity_runs/agents_v2_topup3e; P=$R/post/$TAG; G=$R/post/gguf; mkdir -p $P $G
L=~/gpu_work/llama.cpp; B=$L/build-host/bin; PY=~/venvs/train/bin/python
V2=~/smartcity_runs/agents_v2/post/gguf; CALIB=~/smartcity_runs/agents_v2/post/calib/calib.txt
TOP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup
exec >> $P/post.log 2>&1
echo "=== $(date) post $TAG from $ADIR imatrix=$IMX"
dc() { /mnt/c/Windows/System32/wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || true; }
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
echo "{\"adapter_dir\": \"$ADIR\", \"chosen\": \"$TAG\"}" > $P/choice.json
OUT=$G/ft_${TAG}_q4_0.gguf
if [ ! -s $OUT ]; then
  [ -s $P/f16.gguf ] || { nice $PY $TOP/merge_lowmem.py --post $P --out $P/merged || exit 1; dc
    SHIM=$P/pyshim; mkdir -p $SHIM; SP=$(ls -d ~/venvs/*/lib/python3.11/site-packages/sentencepiece 2>/dev/null | head -1); [ -n "$SP" ] && ln -sfn $SP $SHIM/sentencepiece
    PYTHONPATH=$L/gguf-py:$SHIM nice $PY $L/convert_hf_to_gguf.py $P/merged --outtype f16 --outfile $P/f16.gguf.tmp && mv $P/f16.gguf.tmp $P/f16.gguf || exit 2
    rm -rf $P/merged; dc; }
  if [ "$IMX" = own ]; then
    [ -s $P/imatrix.gguf ] || { nice $B/llama-quantize $P/f16.gguf $P/q8.gguf Q8_0 8 > $P/q8.log 2>&1 && \
      nice $B/llama-imatrix -m $P/q8.gguf -f $CALIB --parse-special -c 1024 --chunks 64 -t 8 -o $P/imatrix.gguf.tmp --output-format gguf > $P/imatrix.log 2>&1 && \
      mv $P/imatrix.gguf.tmp $P/imatrix.gguf; rm -f $P/q8.gguf; }
    IM=$P/imatrix.gguf
  else
    IM=$V2/imatrix_v2.gguf
  fi
  nice $B/llama-quantize --imatrix $IM --output-tensor-type q8_0 --token-embedding-type f16 --tensor-type ffn_down=q4_0 \
     $P/f16.gguf $OUT.tmp Q4_0 8 > $P/q4_0.log 2>&1 && mv $OUT.tmp $OUT || exit 3
  rm -f $P/f16.gguf; dc
fi
PYTHONPATH=$L/gguf-py $PY - $V2/ft_v2_q4_0.gguf $OUT $IM > $P/gguf_check.json <<'PY'
import collections, hashlib, json, sys
import gguf
def types(f):
    return {t.name: (t.tensor_type.name, [int(x) for x in t.shape]) for t in gguf.GGUFReader(f).tensors}
a, b = types(sys.argv[1]), types(sys.argv[2])
diff = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}
m = hashlib.md5()
with open(sys.argv[2], "rb") as fh:
    for blk in iter(lambda: fh.read(1 << 24), b""):
        m.update(blk)
print(json.dumps({"gguf": sys.argv[2], "md5": m.hexdigest(), "imatrix": sys.argv[3], "n_tensors": len(b),
                  "types": dict(collections.Counter(v[0] for v in b.values())), "tensor_type_match_vs_v2": not diff,
                  "diff": {k: str(v) for k, v in list(diff.items())[:10]}}, indent=1))
PY
md5sum $OUT | cut -d' ' -f1 > $OUT.md5
echo "=== $(date) DONE $TAG $(cat $OUT.md5) match=$(grep -o '"tensor_type_match_vs_v2": [a-z]*' $P/gguf_check.json)"
