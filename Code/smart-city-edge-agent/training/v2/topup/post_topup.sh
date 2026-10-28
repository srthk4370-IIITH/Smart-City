#!/usr/bin/env bash
# v2 top-up post pipeline (WSL, offline): chosen adapter (choice.json from train_topup.py) -> merge (CPU bf16,
# untied lm_head, merge_v2.py) -> GGUF f16 -> Q8_0 -> imatrix on the SAME calibration prompts as ft_v2
# (agents_v2/post/calib/calib.txt, 64 chunks x 1024) -> Q4_0 with every ffn_down Q4_0, output Q8_0, token_embd F16
# (as ft_v2_q4_0.gguf) -> per-tensor type comparison with the deployed GGUF -> md5/sha256 -> proofs.
# Resumable: finished files are kept. Never touches ~/smartcity_runs/agents_v2 (read-only: calib.txt, deployed GGUF).
#   bash post_topup.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../../.." && pwd)"
RUN="$HOME/smartcity_runs/${1:-agents_v2_topup}"; export RUN; TAG="${2:-v2t}"; export TAG
POST="$RUN/post"
GG="$POST/gguf"
MERGED="$RUN/merged_v2t"
REF_GGUF="$HOME/smartcity_runs/agents_v2/post/gguf/ft_v2_q4_0.gguf"
CALIB="$HOME/smartcity_runs/agents_v2/post/calib/calib.txt"
L="${LLAMA_CPP:-$HOME/gpu_work/llama.cpp}"
B="$L/build-host/bin"
THREADS="${THREADS:-$(nproc)}"
PROOF="$REPO/proofs/2026-10-21_v2_topup"; [ "$(basename "$RUN")" != agents_v2_topup ] && PROOF="$PROOF/$(basename "$RUN")"
PY="$HOME/venvs/train/bin/python"
mkdir -p "$POST" "$GG" "$PROOF"
exec > >(tee -a "$POST/post_topup.log") 2>&1
source "$HOME/venvs/train/bin/activate"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false TZ=Asia/Kolkata
ts() { date '+%F %T'; }
step() { echo; echo "=== [$(ts)] $*"; echo "$(ts) $*" > "$POST/STATUS"; }
fail() { echo "!!! [$(ts)] FAILED: $*"; echo "$(ts) FAILED: $*" > "$POST/STATUS"; bash "$HERE/proofs_topup.sh" || true; exit 1; }
dropcache() { /mnt/c/Windows/System32/wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null \
  && echo "[$(ts)] page cache dropped" || echo "[$(ts)] (drop_caches unavailable)"; }

step "post_topup start (RUN=$RUN)"
[ -f "$RUN/choice.json" ] || fail "no $RUN/choice.json (training not finished?)"
cp -f "$RUN/choice.json" "$POST/choice.json"
step "1/5 merge (CPU, bf16) of $(grep -o '"adapter_dir": "[^"]*"' "$POST/choice.json")"
if [ "${LOWMEM:-1}" = 1 ]; then
  "$PY" "$HERE/merge_lowmem.py" --post "$POST" --out "$MERGED" || fail "merge_lowmem"   # bit-exact with merge_v2.py, ~1 layer of RAM (8 GB WSL)
else
  ( cd "$HERE/../post" && "$PY" merge_v2.py --post "$POST" --out "$MERGED" ) || fail "merge_v2"
fi
dropcache
cd "$GG"
step "2/5 GGUF f16 + Q8_0"
if [ ! -s ft_${TAG}_f16.gguf ]; then
  SHIM="$POST/pyshim"; mkdir -p "$SHIM"
  SP=$(ls -d "$HOME"/venvs/*/lib/python3.11/site-packages/sentencepiece 2>/dev/null | head -1)
  [ -n "$SP" ] && ln -sfn "$SP" "$SHIM/sentencepiece"
  PYTHONPATH="$L/gguf-py:$SHIM" "$PY" "$L/convert_hf_to_gguf.py" "$MERGED" --outtype f16 --outfile ft_${TAG}_f16.gguf.tmp || fail "convert"
  mv ft_${TAG}_f16.gguf.tmp ft_${TAG}_f16.gguf
fi
if [ ! -s ft_${TAG}_q8_0.gguf ]; then
  "$B/llama-quantize" ft_${TAG}_f16.gguf ft_${TAG}_q8_0.gguf.tmp Q8_0 "$THREADS" > q8.log 2>&1 || fail "q8_0"
  mv ft_${TAG}_q8_0.gguf.tmp ft_${TAG}_q8_0.gguf
fi
dropcache
step "3/5 imatrix: same calib.txt as ft_v2, 64 chunks x 1024"
if [ ! -s imatrix_${TAG}.gguf ]; then
  "$B/llama-imatrix" -m ft_${TAG}_q8_0.gguf -f "$CALIB" --parse-special -c 1024 --chunks 64 \
      -t "$THREADS" -o imatrix_${TAG}.gguf.tmp --output-format gguf 2>&1 | grep -vE "^\s*$" | tail -n 30
  [ -s imatrix_${TAG}.gguf.tmp ] && mv imatrix_${TAG}.gguf.tmp imatrix_${TAG}.gguf || fail "imatrix"
fi
echo "{\"imatrix\": \"imatrix_${TAG}.gguf\", \"chunks\": 64, \"ctx\": 1024, \"imatrix_model\": \"ft_${TAG}_q8_0.gguf\", \"calib\": \"$CALIB\", \"calib_md5\": \"$(md5sum < "$CALIB" | cut -d' ' -f1)\"}" > imatrix_info.json
step "4/5 Q4_0 (+imatrix; ffn_down q4_0, output q8_0, token_embd f16)"
TYPES="--output-tensor-type q8_0 --token-embedding-type f16 --tensor-type ffn_down=q4_0"
if [ ! -s ft_${TAG}_q4_0.gguf ]; then
  "$B/llama-quantize" --imatrix imatrix_${TAG}.gguf $TYPES ft_${TAG}_f16.gguf ft_${TAG}_q4_0.gguf.tmp Q4_0 "$THREADS" > q4_0.log 2>&1 || fail "q4_0"
  mv ft_${TAG}_q4_0.gguf.tmp ft_${TAG}_q4_0.gguf
fi
step "5/5 per-tensor types vs deployed ft_v2_q4_0.gguf + hashes"
PYTHONPATH="$L/gguf-py" "$PY" - "$REF_GGUF" ft_${TAG}_q4_0.gguf <<'PY' || fail "tensor type check"
import collections, hashlib, json, os, sys
import gguf
ref, new = sys.argv[1], sys.argv[2]
def types(f):
    r = gguf.GGUFReader(f)
    return {t.name: (t.tensor_type.name, [int(x) for x in t.shape]) for t in r.tensors}
a, b = types(ref), types(new)
diff = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}
def hashes(f):
    m, s = hashlib.md5(), hashlib.sha256()
    with open(f, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 24), b""):
            m.update(blk); s.update(blk)
    return m.hexdigest(), s.hexdigest()
res = {}
for f in sorted(x for x in os.listdir(".") if x.startswith("ft_" + os.environ.get("TAG", "v2t") + "_") and x.endswith(".gguf")) + [ref]:
    t = types(f)
    md5, sha = hashes(f)
    res[os.path.basename(f) if f != ref else "REFERENCE_deployed_ft_v2_q4_0.gguf"] = {
        "path": os.path.abspath(f), "bytes": os.path.getsize(f), "md5": md5, "sha256": sha,
        "types": dict(collections.Counter(v[0] for v in t.values())),
        "ffn_down": dict(collections.Counter(v[0] for k, v in t.items() if "ffn_down" in k)),
        "non_block": {k: v[0] for k, v in t.items() if not k.startswith("blk.")}}
res["tensor_type_match_vs_deployed"] = {"match": not diff, "n_tensors": len(b), "differences": {k: str(v) for k, v in list(diff.items())[:20]}}
json.dump(res, open("gguf_manifest.json", "w"), indent=1)
print(json.dumps(res, indent=1))
sys.exit(0 if not diff else 3)
PY
md5sum ft_${TAG}_q4_0.gguf > ft_${TAG}_q4_0.gguf.md5
if [ -z "${KEEP_INTERMEDIATE:-}" ]; then  # C: is tight: drop the regenerable 17 GB (merged bf16, f16, q8)
  rm -rf "$MERGED" ft_${TAG}_f16.gguf ft_${TAG}_q8_0.gguf; echo "intermediates deleted $(date) (regenerable)" > INTERMEDIATES_DELETED.txt
  /mnt/c/Windows/System32/wsl.exe -d Ubuntu -u root -- fstrim / 2>/dev/null || true
fi
dropcache
bash "$HERE/proofs_topup.sh"
step "DONE: $GG/ft_${TAG}_q4_0.gguf md5 $(cut -d' ' -f1 ft_${TAG}_q4_0.gguf.md5)"
echo "$(ts) DONE" > "$POST/DONE"
