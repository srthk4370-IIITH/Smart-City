#!/bin/bash
# run_build.sh [stages...]: CPU-only data build (nice), logs in logs/
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big
export CUDA_VISIBLE_DEVICES=
for s in "$@"; do nice -n 15 python3 build/build_big.py --stage $s > logs/build_$s.log 2>&1; echo "stage $s rc $? $(date)" >> logs/build_chain.log; done
