#!/usr/bin/env bash
# Entry point used by run_v2.ps1 (no arguments, so Windows argument quoting cannot split it).
export SESSION_HOURS=1000
export TRAIN_ARGS="--base /home/hp_srthk4370/models/llama-3.2-3b-instruct --dev-n 200 --eval-every 300 --save-every 14 --thermal-pause-at 76 --thermal-resume-at 68"  # ~10 min between checkpoints (43.6 s/step)
exec bash /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/session_v2.sh
