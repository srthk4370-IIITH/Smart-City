#!/usr/bin/env bash
# after screen.sh: P0 for ft600 and ft300 (checkpoint pick is on the weighted P0 total). Stops before 07:30 IST (owner day rule).
R=~/smartcity_runs/reasoner_v1; E=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/eval
B=~/models/qwen3.5-4b-gguf/qwen3.5-4b-q4_0.gguf
exec >> $E/results/screen.log 2>&1
while pgrep -f "eval/[s]creen.sh" >/dev/null; do sleep 60; done
for s in 0300; do h=$(TZ=Asia/Kolkata date +%-H%M); [ $h -ge 730 ] && [ $h -lt 2200 ] && { echo "07:30 IST cutoff -> skip ft${s#0} p0"; continue; }
  LORA=$R/lora/s$s.gguf timeout 4500 bash $E/eval_gguf.sh $B ft${s#0} p0; done
echo "=== $(date) SCREEN2 DONE"
