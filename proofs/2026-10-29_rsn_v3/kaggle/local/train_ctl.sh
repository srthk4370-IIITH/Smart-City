#!/usr/bin/env bash
# train_ctl.sh start|stop|status: owner controls for the laptop GPU training (rsn_v3 chain: 2B training + 4B adapter watch).
# Called by start.ps1 / stop.ps1 in the repo root. stop = clean stop: the trainer saves a checkpoint at its next step and
# exits; start resumes from that checkpoint (finished chain steps are skipped).
RUN_ID=${RUN_ID:-r2}; export RUN_ID   # r2 since 2026-11-02 (RUN_ID=r1 for the old run)
KG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle; C=$KG/chain; R=~/smartcity_runs/rsn3_2b_$RUN_ID
running() { p=$(cat $C/chain.pid 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
trainer() { pgrep -f train_rsn3.py > /dev/null; }
show() { echo "last step: $(grep -E 'step [0-9]+/' $R/train.log 2>/dev/null | tail -1)"; tail -2 $KG/STATUS.md
  nvidia-smi --query-gpu=utilization.gpu,temperature.gpu --format=csv,noheader 2>/dev/null | sed 's/^/GPU util, temp: /'; }
case $1 in
start)
  if running; then echo "ALREADY RUNNING (chain pid $(cat $C/chain.pid))"; show; exit 0; fi
  if trainer; then echo "a trainer is still exiting; run stop.ps1 again or wait a minute, then start"; exit 1; fi
  rm -f $C/STOP $R/STOP
  RUN_ID=$RUN_ID bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh rsn3_laptop_chain $KG/local/laptop_chain.sh
  sleep 8
  if running; then echo "STARTED run $RUN_ID (chain pid $(cat $C/chain.pid)); training resumes from the last checkpoint"
  else echo "FAILED to start; last log lines:"; tail -5 ~/detached/rsn3_laptop_chain.log; exit 1; fi ;;
stop)
  if ! running && ! trainer; then echo "NOT RUNNING"; show; exit 0; fi
  touch $C/STOP; echo "STOP requested: trainer saves a checkpoint at its next step, then exits (a few minutes)..."
  for i in $(seq 1 90); do { running || trainer; } || break; sleep 10; done
  if running || trainer; then echo "still stopping after 15 min (paused for heat/RAM?); STOP stays set, it exits at its next step"
  else echo "STOPPED"; fi; show ;;
status) if running; then echo "RUNNING (chain pid $(cat $C/chain.pid))"; else echo "NOT RUNNING"; fi; show ;;
*) echo "usage: train_ctl.sh start|stop|status"; exit 2 ;;
esac
