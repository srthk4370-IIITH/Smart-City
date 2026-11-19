#!/usr/bin/env bash
# cut_now_r2.sh: eval 2026-11-04 12:00 IST; export + gate (~6 h) + deploy/board tests (~2 h) need to start now.
# Stop r2 cleanly, mark train_2b done, restart the chain -> export best checkpoint (step 1000, 0.9625) + gate g2b_r2.
KG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle; C=$KG/chain; CM=$C/r2; R=~/smartcity_runs/rsn3_2b_r2
st() { echo "- $(date '+%F %T') [cut_now_r2] $*" >> $KG/STATUS.md; echo "$(date '+%T') $*"; }
pkill -f early_stop_r2.sh
st "eval tomorrow noon: stopping r2 at step $(grep -o 'step [0-9]*/3508' $R/train.log | tail -1) -> export best + gate"
touch $C/STOP
while pgrep -f train_rsn3.py >/dev/null || { p=$(cat $C/chain.pid 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }; do
  pkill -CONT -f train_rsn3.py; sleep 15; done
touch $CM/train_2b.done; rm -f $C/STOP
st "trainer stopped; best.json: $(tr -d ' \n' < $R/best.json | cut -c1-60)"
bash $KG/local/train_ctl.sh start
st "chain restarted -> export_2b + gate g2b_r2"
