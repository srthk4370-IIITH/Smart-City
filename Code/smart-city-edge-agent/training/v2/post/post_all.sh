#!/usr/bin/env bash
# v2 post-training pipeline (WSL): wait for training -> choose adapter -> merge -> calibration prompts ->
# GGUF (f16, imatrix, Q4_0, Q4_K_M) -> host eval (HF bf16 on the GPU, GGUF on the CPU) -> quantisation-loss
# table -> proofs. Every step is resumable: re-running skips what is finished.
# Log: ~/smartcity_runs/agents_v2/post/post_all.log. Proofs: <repo>/proofs/2026-10-20_v2_post/.
#   bash post_all.sh            (env: SKIP_HF=1, SKIP_KM=1, EVAL_NOIMX=1, EVAL_F16=1)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../../.." && pwd)"
RUN="${RUN:-$HOME/smartcity_runs/agents_v2}"
POST="$RUN/post"
MERGED="$RUN/merged_v2"
PROOF="$REPO/proofs/2026-10-20_v2_post"
mkdir -p "$POST" "$PROOF"
exec > >(tee -a "$POST/post_all.log") 2>&1
source "$HOME/venvs/train/bin/activate"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false TZ=Asia/Kolkata
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
cd "$HERE"
ts() { date '+%F %T'; }
step() { echo; echo "=== [$(ts)] $*"; echo "$(ts) $*" > "$POST/STATUS"; }
fail() { echo "!!! [$(ts)] FAILED: $*"; echo "$(ts) FAILED: $*" > "$POST/STATUS"; snapshot; exit 1; }

snapshot() {  # copy everything small enough to be evidence into proofs/
  mkdir -p "$PROOF/eval" "$PROOF/gguf" "$PROOF/calib"
  cp -f "$POST/post_all.log" "$POST/choice.json" "$POST/eval_set.json" "$PROOF/" 2>/dev/null
  cp -f "$MERGED/merge_check.json" "$PROOF/" 2>/dev/null
  cp -f "$POST/calib/calib_manifest.json" "$PROOF/calib/" 2>/dev/null
  cp -f "$POST/gguf/gguf_manifest.json" "$POST/gguf/imatrix_info.json" "$PROOF/gguf/" 2>/dev/null
  cp -rf "$POST/eval/." "$PROOF/eval/" 2>/dev/null
  cp -f "$RUN/best.json" "$RUN/session_status.json" "$RUN/plan.json" "$PROOF/" 2>/dev/null
  "$HOME/venvs/train/bin/python" - "$PROOF" <<'PY'
import hashlib, json, sys, os, datetime
root = sys.argv[1]
files = {}
for d, _, fs in os.walk(root):
    for f in fs:
        if f == "manifest.json":
            continue
        p = os.path.join(d, f)
        files[os.path.relpath(p, root).replace(os.sep, "/")] = {"bytes": os.path.getsize(p),
            "sha256_16": hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]}
json.dump({"what": "v2 domain agents: adapter choice, merge, GGUF (imatrix Q4_0 / Q4_K_M), host eval, quantisation loss",
           "updated": datetime.datetime.now().isoformat(timespec="seconds"), "files": files},
          open(os.path.join(root, "manifest.json"), "w"), indent=1)
PY
}

# user rule: give the page cache back to Windows after every heavy step (root via WSL interop)
dropcache() { /mnt/c/Windows/System32/wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null \
  && echo "[$(ts)] page cache dropped" || echo "[$(ts)] (drop_caches unavailable)"; }

step "post_all start (RUN=$RUN)"
# 1. wait for training (normally already done when the Windows launcher starts us)
while true; do
  if [ -f "$RUN/session_status.json" ] && grep -q '"done": true' "$RUN/session_status.json" && [ -d "$RUN/adapter" ]; then break; fi
  echo "[$(ts)] training not complete yet; waiting"; sleep 300
done
step "1/7 choose adapter"
python choose_adapter.py --run "$RUN" --post "$POST" || fail "choose_adapter"
dropcache
step "2/7 merge (CPU, bf16)"
python merge_v2.py --post "$POST" --out "$MERGED" || fail "merge_v2"
dropcache
step "3/7 calibration prompts + eval set"
[ -s "$POST/calib/calib.txt" ] || python calib_prompts.py --out "$POST/calib" || fail "calib_prompts"
python host_eval_v2.py select --post "$POST" || fail "select"
snapshot
dropcache
step "4/7 GGUF: f16 -> imatrix -> Q4_0 / Q4_K_M (first, so the QIDK eval can start)"
bash to_gguf.sh || fail "to_gguf"
echo "$(ts) GGUF ready" > "$POST/GGUF_READY"
snapshot; dropcache
step "5/7 host eval: HF merged bf16 on the GPU (CPU offload for what does not fit)"
if [ -z "${SKIP_HF:-}" ]; then
  python host_eval_v2.py run --subset "${HOST_SUBSET:-160}" --post "$POST" --backend hf --model "$MERGED" --tag hf_bf16 --load bf16 || echo "!!! hf_bf16 eval failed (continuing)"
fi
snapshot; dropcache
step "6/7 host eval: GGUF on the CPU (llama-server, same ggml graph as htpd)"
python host_eval_v2.py run --subset "${HOST_SUBSET:-160}" --post "$POST" --backend gguf --model "$POST/gguf/ft_v2_q4_0.gguf" --tag gguf_q4_0 || echo "!!! gguf_q4_0 eval failed"
dropcache
snapshot
[ -z "${SKIP_KM:-}" ] && { python host_eval_v2.py run --subset "${HOST_SUBSET:-160}" --post "$POST" --backend gguf --model "$POST/gguf/ft_v2_q4_k_m.gguf" --tag gguf_q4_k_m || echo "!!! gguf_q4_k_m eval failed"; }
[ -n "${EVAL_NOIMX:-}" ] && { python host_eval_v2.py run --subset "${HOST_SUBSET:-160}" --post "$POST" --backend gguf --model "$POST/gguf/ft_v2_q4_0_noimx.gguf" --tag gguf_q4_0_noimx || true; }
[ -n "${EVAL_F16:-}" ] && { python host_eval_v2.py run --subset "${HOST_SUBSET:-160}" --post "$POST" --backend gguf --model "$POST/gguf/ft_v2_f16.gguf" --tag gguf_f16 || true; }
step "7/7 quantisation loss table"
REF=hf_bf16; [ -f "$POST/eval/hf_bf16/summary.json" ] || REF=gguf_f16
python host_eval_v2.py compare --post "$POST" --ref "$REF" --cand gguf_q4_0 gguf_q4_k_m gguf_q4_0_noimx gguf_f16 || echo "!!! compare failed"
snapshot
step "DONE: results in $POST/eval and $PROOF; device candidate $POST/gguf/ft_v2_q4_0.gguf"
echo "$(ts) DONE" > "$POST/DONE"
