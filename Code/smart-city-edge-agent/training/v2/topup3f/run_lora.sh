#!/usr/bin/env bash
# run_lora.sh SET TAG... : pipe_lora with an in-shell heartbeat (agent-owned bg shell).
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
( while sleep 120; do touch $R/HEARTBEAT; done ) & HBP=$!; trap "kill $HBP" EXIT
bash $H/pipe_lora.sh "$@"
