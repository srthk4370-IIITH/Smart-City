#!/usr/bin/env bash
# go_r2.sh: owner said skip the benchmark and start r2 training now (2026-11-02 ~11:05 IST).
# Kill the bench driver, stop its trainer cleanly, then start the r2 chain (micro-tokens 6144 default in laptop_chain.sh).
KG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle; C=$KG/chain
grep -n 'R2_EXTRA' $KG/local/laptop_chain.sh
bp=$(cat ~/detached/r2_bench.pid 2>/dev/null); [ -n "$bp" ] && kill "$bp" 2>/dev/null
pkill -f 'bench_r2.sh'; pkill -f 'keepalive.sh r2_bench'
touch $C/STOP
for i in $(seq 1 90); do pgrep -f train_rsn3.py >/dev/null || break; pkill -CONT -f train_rsn3.py; sleep 10; done
pgrep -f train_rsn3.py && { echo "trainer still running"; exit 1; }
pkill -f 'laptop_train.sh' 2>/dev/null
rm -f $C/STOP
bash $KG/local/train_ctl.sh start
