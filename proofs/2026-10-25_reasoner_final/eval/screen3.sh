#!/usr/bin/env bash
# replaces screen.sh/screen2.sh after the base model proved too slow (one RWH item took 8,283 s):
# base RWH capped at 60 items (resumes), then ft600 (rw6,rwh,dev) and ft300 (rw6,rwh,dev,p0). Base P0 = earlier 0.79.
R=~/smartcity_runs/reasoner_v1; E=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/eval
B=~/models/qwen3.5-4b-gguf/qwen3.5-4b-q4_0.gguf
exec >> $E/results/screen.log 2>&1; echo "=== $(date) screen3 start"
n=$(wc -l < $E/results/base_v3s/rwh.jsonl); left=$(( 60 - n )); [ $left -gt 0 ] && timeout 3600 bash $E/eval_gguf.sh $B base_v3s rwh_lim
LORA=$R/lora/s0600.gguf bash $E/eval_gguf.sh $B ft600 rw6,rwh,dev
LORA=$R/lora/s0300.gguf bash $E/eval_gguf.sh $B ft300 rw6,rwh,dev,p0
echo "=== $(date) SCREEN3 DONE"
