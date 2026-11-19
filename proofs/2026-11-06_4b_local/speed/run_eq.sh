#!/usr/bin/env bash
# run_eq.sh <script.py> <out.json> [args]: CPU only, nice 15, CUDA hidden, 1 inductor compile thread; pid -> eq.pid (for kill_eq.sh)
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/speed
export CUDA_VISIBLE_DEVICES="" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=3 MKL_NUM_THREADS=3 \
  TORCHINDUCTOR_COMPILE_THREADS=1 MALLOC_ARENA_MAX=2 TORCHDYNAMO_DISABLE=1
free -m | head -2
[ -n "${NOPID:-}" ] || echo $$ > eq.pid
exec nice -n 15 $HOME/venvs/rsn/bin/python -u "$@"
