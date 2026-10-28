#!/usr/bin/env bash
# Entry point used by run_topup.ps1. $1 = run name under ~/smartcity_runs (default agents_v2_topup), $2 = trainer script.
# Extra trainer arguments come from <run>/train_args.txt (one line), so Windows quoting cannot split them.
# Continues the run from its newest checkpoint on every call.
set -euo pipefail
HERE=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup
RUN_DIR="$HOME/smartcity_runs/${1:-agents_v2_topup}"
mkdir -p "$RUN_DIR"
EXTRA="$(cat "$RUN_DIR/train_args.txt" 2>/dev/null || true)"
source "$HOME/venvs/train/bin/activate"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false TZ=Asia/Kolkata
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
cd "$HERE"
exec > >(tee -a "$RUN_DIR/session.log") 2>&1
echo "=== $(date)  RUN_DIR=$RUN_DIR  EXTRA=$EXTRA"
# shellcheck disable=SC2086
python "${2:-train_topup.py}" --out "$RUN_DIR" --thermal-pause-at 76 --thermal-resume-at 68 $EXTRA
echo "=== session done $(date)"; cat "$RUN_DIR/session_status.json" 2>/dev/null || true
