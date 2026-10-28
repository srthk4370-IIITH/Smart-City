#!/usr/bin/env bash
# v2.1 checkpoint screen (LoRA-scaling) on rw5dev + dev3f for the given steps; heartbeat touched inside (agent shell).
#   bash screen_v21.sh 621 500 400
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f; O=~/smartcity_runs/agents_v21/run1
exec >> $R/master.log 2>&1; echo "=== $(date) screen_v21 $*"
( while sleep 120; do touch $R/HEARTBEAT; done ) & HBP=$!; trap "kill $HBP" EXIT
T=""; for s in "$@"; do bash $H/conv_lora_3f.sh v21_$s $O/checkpoints/checkpoint-$s; echo "v21_$s:1.0" > $R/screen/V21_$s.lora; T="$T V21_$s"; done
bash $H/pipe_lora.sh rw5dev $T; bash $H/pipe_lora.sh dev $T
echo "=== $(date) SCREEN_V21_DONE"
