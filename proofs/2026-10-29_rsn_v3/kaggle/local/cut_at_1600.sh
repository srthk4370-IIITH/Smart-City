#!/usr/bin/env bash
# cut_at_1600.sh: owner wants the 2B on the board tonight (2026-11-01). Wait for the step-1600 GEN eval, then stop the
# trainer cleanly (STOP -> checkpoint), mark train_2b done and restart the chain, which exports the best checkpoint
# (best.json top: 1200/1400/1600) to Q4_0 and runs the gate vs rsn_v1. Launch via proofs/detach.sh.
KG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle; C=$KG/chain; R=~/smartcity_runs/rsn3_2b_r1
st() { echo "- $(date '+%F %T') [cut_at_1600] $*" >> $KG/STATUS.md; echo "$(date '+%T') $*"; }
st "waiting for GEN step 1600, then stop + export best + gate (owner: 2B on board tonight)"
until grep -q 'GEN step 1600' $R/train.log; do sleep 60; done
st "GEN 1600: $(grep 'GEN step 1600' $R/train.log | tail -1 | grep -o '"score": [0-9.]*' | head -1); stopping trainer"
touch $C/STOP
while pgrep -f train_rsn3.py >/dev/null || { p=$(cat $C/chain.pid 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }; do sleep 20; done
touch $C/train_2b.done
st "trainer stopped; train_2b marked done; best.json: $(tr -d ' \n' < $R/best.json | cut -c1-80)"
bash $KG/local/train_ctl.sh start
st "chain restarted -> export_2b + gate"
