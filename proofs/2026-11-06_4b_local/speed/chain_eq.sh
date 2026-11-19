#!/usr/bin/env bash
# chain_eq.sh: final-code CPU checks in sequence (started by go.sh-style setsid; one process group for kill_eq.sh)
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/speed
echo $$ > eq.pid; export NOPID=1 TRAINER=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/train_rsn3.py
bash run_eq.sh eq_shared.py eq_shared.json > eq_shared.log 2>&1
bash run_eq.sh eq_tail.py eq_tail.json > eq_tail.log 2>&1
bash run_eq.sh resume_test.py $TRAINER resume_test.json > resume_test.log 2>&1
echo chain done > chain_eq.done
