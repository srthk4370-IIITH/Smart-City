#!/usr/bin/env bash
# ctl_4b.sh start|stop|status: owner control of the 4B r3 laptop run (called by start.ps1 / stop.ps1 in the repo root).
# stop = clean: the trainer saves ckpt_latest at its next step and exits; start resumes from it.
H=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local; C=$H/chain; R=~/smartcity_runs/rsn3_4b_r3
KS=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/STATUS.md
running() { p=$(cat $C/chain.pid 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
trainer() { pgrep -f "train_rsn3.py.*rsn3_4b_r3" > /dev/null; }
show() { echo "last step: $(grep -E 'step [0-9]+/' $R/train.log 2>/dev/null | tail -1)"; grep 'rsn3_4b_r3\|chain_4b' $KS | tail -2
  nvidia-smi --query-gpu=utilization.gpu,temperature.gpu,memory.used --format=csv,noheader 2>/dev/null | sed 's/^/GPU util, temp, mem: /'; }
case $1 in
start)
  if running; then echo "ALREADY RUNNING (chain pid $(cat $C/chain.pid))"; show; exit 0; fi
  if [ -e $R/BATON_AT_KAGGLE ]; then echo "Kaggle holds the baton (baton/BATON): not starting the laptop; baton_auto brings it back"; exit 3; fi
  if trainer; then echo "a trainer is still exiting; wait a minute, then start"; exit 1; fi
  rm -f $C/STOP $R/STOP
  set -a; . $H/run.env; set +a
  bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh rsn3_4b_r3 $H/chain_4b.sh
  sleep 8
  if running; then echo "STARTED 4B r3 (chain pid $(cat $C/chain.pid)); resumes from the last checkpoint"
  else echo "FAILED to start; last log lines:"; tail -5 ~/detached/rsn3_4b_r3.log; exit 1; fi ;;
stop)
  if ! running && ! trainer; then echo "NOT RUNNING"; show; exit 0; fi
  touch $C/STOP $R/STOP; echo "STOP requested: checkpoint at the next step, then exit..."
  for i in $(seq 1 90); do { running || trainer; } || break; sleep 10; done
  if running || trainer; then echo "still stopping after 15 min (paused for heat/RAM?); it exits at its next step"; else echo "STOPPED"; fi; show ;;
status) if running; then echo "RUNNING (chain pid $(cat $C/chain.pid))"; else echo "NOT RUNNING"; fi; show ;;
*) echo "usage: ctl_4b.sh start|stop|status"; exit 2 ;;
esac
