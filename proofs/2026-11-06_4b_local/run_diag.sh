#!/usr/bin/env bash
# run_diag.sh <len> [labels] [tag]: one fit_diag.py run (GPU_LOCK must already hold a fit_4b line)
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local
grep -q "^fit_4b" /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK || { echo "no fit_4b lock"; exit 1; }
export TORCHINDUCTOR_COMPILE_THREADS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=${ALLOC:-expandable_segments:True}
free -m | awk 'NR==2{print "wsl free", $7, "MB"}'
nvidia-smi --query-gpu=memory.used,temperature.gpu --format=csv,noheader
LEVERS=${LEVERS:-} ~/venvs/rsn/bin/python $D/fit_diag.py "$1" "${2:-500}" 2>&1 | grep -v -e "Loading weights" -e Triton -e "causal_conv1d" > $D/logs/diag_${3:-$1}.log
cat $D/logs/diag_${3:-$1}.log | tail -20
