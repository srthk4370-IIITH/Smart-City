#!/usr/bin/env bash
# One training session of the v2 domain agents (RETRAIN_V2_SPEC.md). Run in WSL; the same command continues
# the run from its newest checkpoint each time.
#   bash session_v2.sh                 # 7 h session (SESSION_HOURS=6..8)
#   PILOT=1 bash session_v2.sh         # speed/VRAM check only
#   SMOKE=1 bash session_v2.sh         # tiny end-to-end check in a separate dir
# Stop early and cleanly (checkpoint first):  touch $RUN_DIR/STOP
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${RUN_DIR:-$HOME/smartcity_runs/agents_v2}"
[ -n "${SMOKE:-}" ] && RUN_DIR="$HOME/smartcity_runs/agents_v2_smoke"
mkdir -p "$RUN_DIR"
source "$HOME/venvs/train/bin/activate"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false TZ=Asia/Kolkata
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
cd "$HERE"
exec > >(tee -a "$RUN_DIR/session.log") 2>&1
echo "=== $(date)  RUN_DIR=$RUN_DIR"
python train_v2.py --out "$RUN_DIR" --session-hours "${SESSION_HOURS:-7}" ${PILOT:+--pilot} ${SMOKE:+--smoke} ${TRAIN_ARGS:-}
echo "=== session done $(date)"; cat "$RUN_DIR/session_status.json" 2>/dev/null || true
