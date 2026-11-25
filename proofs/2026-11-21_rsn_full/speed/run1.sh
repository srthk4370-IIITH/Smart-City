#!/usr/bin/env bash
# usage: run1.sh NAME "FIT_FLAGS"   (GPU lock held by caller)
N=$1; F=$2; V=/mnt/c/Users/hp/Desktop/qidk/proofs; S=$HOME/speedtest; O=$S/$N; rm -rf $O; mkdir -p $O
FT=$V/2026-11-13_v3_train/rsn_ft
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export TORCHINDUCTOR_COMPILE_THREADS=1 MALLOC_ARENA_MAX=2 RSN3_SEG_TOKENIZE=1
( while sleep 2; do nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 >> $O/vram.txt; done ) & W=$!
timeout 330 ~/venvs/rsn/bin/python $FT/rsn_ft_train.py --base /mnt/c/Users/hp/qidk_models/r3_edit_C1 \
 --init-adapter $V/2026-11-20_rsn_big/best/ckpt_best_0242 --tools $V/2026-11-20_rsn_big/data/final_big/tools_v4.json \
 --new $S/s48.jsonl --replay $S/s48.jsonl --out $O --max-len 7424 --quant nf4 --dtype bf16 \
 --lr 2e-5 --accum 4 --mix 1.0 --epochs 1 --save-every 1000 --eval-every 1000 --gen-every 1000 --max-steps 2 --step-log \
 $F > $O/stdout.log 2>&1
echo rc=$? >> $O/stdout.log; kill $W
echo "$N peak_vram=$(sort -n $O/vram.txt | tail -1)"; cat $O/step_log.jsonl 2>/dev/null | cut -c1-200; tail -3 $O/stdout.log | cut -c1-200
grep -ci "fast path is not available\|fallback" $O/stdout.log
