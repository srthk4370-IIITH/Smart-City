#!/usr/bin/env bash
# One command: preflight -> pilot+plan -> QLoRA training -> eval -> merge -> copy results to repo.
#   bash run_all.sh                      # deadline defaults to Wed 2026-10-07 13:00
#   DEADLINE="2026-10-07 12:00" bash run_all.sh
#   Re-running the same command CONTINUES the latest run (resumes training from its last checkpoint,
#   skips finished stages). Start over on purpose with:  FRESH=1 bash run_all.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEADLINE="${DEADLINE:-2026-10-07 13:00}"
LATEST=$(ls -d "$HOME"/smartcity_runs/agents_* 2>/dev/null | tail -1 || true)
if [ -z "${RUN_DIR:-}" ]; then
  if [ -n "$LATEST" ] && [ -z "${FRESH:-}" ] && [ -z "${SMOKE:-}" ]; then
    RUN_DIR="$LATEST"; echo "Continuing existing run $RUN_DIR (set FRESH=1 to start a new one)"
  else
    RUN_DIR="$HOME/smartcity_runs/agents_$(date +%Y%m%d_%H%M)"
  fi
fi
if [ -f "$RUN_DIR/plan.json" ] && [ ! -f "$RUN_DIR/adapter/adapter_model.safetensors" ]; then RESUME=1; fi
mkdir -p "$RUN_DIR"
source "$HOME/venvs/train/bin/activate"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false TZ=Asia/Kolkata
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
cd "$HERE"
exec > >(tee -a "$RUN_DIR/run_all.log") 2>&1
echo "=== $(date)  RUN_DIR=$RUN_DIR  DEADLINE=$DEADLINE"
echo "--- preflight"; python preflight.py
if [ ! -f "$RUN_DIR/adapter/adapter_model.safetensors" ]; then
  echo "--- train"
  python train_agents.py --out "$RUN_DIR" --deadline "$DEADLINE" ${RESUME:+--resume} ${SMOKE:+--smoke} ${TRAIN_ARGS:-}
fi
if [ ! -f "$RUN_DIR/eval.json" ]; then
  echo "--- eval"
  # eval is a report only: if it fails, continue to merge/export (the model itself is fine)
  if [ -n "${SMOKE:-}" ]; then python eval_agents.py --run "$RUN_DIR" --per-role 2 --bs 2 --max-new 64 --skip-base || echo "WARNING: eval failed (continuing)"
  else python eval_agents.py --run "$RUN_DIR" || echo "WARNING: eval failed (continuing; rerun later: python eval_agents.py --run $RUN_DIR)"; fi
fi
echo "--- merge"; python merge_adapter.py --run "$RUN_DIR"
DEST="$HERE/results/$(basename "$RUN_DIR")"; mkdir -p "$DEST"
cp -r "$RUN_DIR/adapter" "$RUN_DIR/plan.json" "$RUN_DIR/train.log" "$RUN_DIR/run_all.log" "$DEST/" 2>/dev/null || true
cp "$RUN_DIR"/eval.* "$DEST/" 2>/dev/null || true
echo "=== DONE $(date). Adapter+report copied to $DEST ; merged model at $RUN_DIR/merged"
