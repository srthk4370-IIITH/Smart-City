#!/bin/bash
# v2 stage 1 (CPU only): windows -> agt_v3 real outputs. Log ~/detached/rsn_v2_s1.log
export CUDA_VISIBLE_DEVICES=
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn
W=data/final_v2/work
mkdir -p $W
[ -s $W/windows.jsonl ] || nice -n 15 python3 v2_windows.py --out $W/windows.jsonl --n-syn 1500 --n-real 500 || exit 1
nice -n 15 python3 v2_agent_run.py $W/windows.jsonl $W/agent_out.jsonl
echo "stage1 exit $? $(date)"
