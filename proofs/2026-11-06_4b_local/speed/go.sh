#!/usr/bin/env bash
# go.sh <script.py> <args...>: start one CPU test detached (TRAINER = the scratch full trainer unless set)
export TRAINER=${TRAINER:-/mnt/c/Users/hp/AppData/Local/Temp/claude/5cb597a87cde10fb/125df7ac-c9eb-46de-b63b-ce87f4c7e8ce/scratchpad/sp/train_full.py}
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/speed
n=$(basename "$1" .py)
setsid nohup bash run_eq.sh "$@" > "$n.log" 2>&1 < /dev/null &
sleep 2; cat eq.pid
