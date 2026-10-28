#!/usr/bin/env bash
# LoRA screening without merge: base Q4_0 GGUF + runtime --lora (CUDA llama-server), short prompt. Log: eval/results/screen.log
R=~/smartcity_runs/reasoner_v1; E=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/eval
B=~/models/qwen3.5-4b-gguf/qwen3.5-4b-q4_0.gguf
exec >> $E/results/screen.log 2>&1; echo "=== $(date) screen start"
LORA=$R/lora/s0612.gguf bash $E/eval_gguf.sh $B ft612 rw6,rwh,dev,chatdev,p0
bash $E/eval_gguf.sh $B base_v3s rw6,rwh,dev,chatdev,p0
LORA=$R/lora/s0600.gguf bash $E/eval_gguf.sh $B ft600 rw6,rwh,dev
LORA=$R/lora/s0300.gguf bash $E/eval_gguf.sh $B ft300 rw6,rwh,dev
echo "=== $(date) SCREEN DONE"
