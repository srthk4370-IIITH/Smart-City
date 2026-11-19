#!/usr/bin/env bash
# ctl_r4.sh start|stop|status: owner control of the r4 top-up run (start_r4.ps1 / stop_r4.ps1 call it).
# stop = clean: the trainer saves ckpt_latest at its next step and exits; start resumes from it.
T4=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/train; C=$T4/chain; R=~/smartcity_runs/rsn3_4b_r4topup
KS=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/STATUS.md
running() { p=$(cat $C/chain.pid 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
trainer() { pgrep -f "topup_train.py.*rsn3_4b_r4topup" > /dev/null; }
show() { echo "last step: $(grep -E 'step [0-9]+/' $R/train.log 2>/dev/null | tail -1)"; grep 'chain_r4\|topup_chunk' $KS | tail -2
  nvidia-smi --query-gpu=utilization.gpu,temperature.gpu,memory.used --format=csv,noheader 2>/dev/null | sed 's/^/GPU util, temp, mem: /'; }
case $1 in
start)
  if running; then echo "ALREADY RUNNING (chain pid $(cat $C/chain.pid))"; show; exit 0; fi
  if trainer; then echo "a trainer is still exiting; wait a minute, then start"; exit 1; fi
  if [ -e $C/train.done ]; then echo "training already finished (chain/train.done); post phase: post_r4.sh"; exit 0; fi
  mkdir -p $C; rm -f $C/STOP $R/STOP
  set -a; . $T4/run_r4.env; set +a
  bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh rsn3_4b_r4topup $T4/chain_r4.sh
  sleep 8
  if running; then echo "STARTED r4 top-up (chain pid $(cat $C/chain.pid)); resumes from the last checkpoint"
  else echo "FAILED to start; last log lines:"; tail -5 ~/detached/rsn3_4b_r4topup.log; exit 1; fi ;;
stop)
  if ! running && ! trainer; then echo "NOT RUNNING"; show; exit 0; fi
  mkdir -p $C; touch $C/STOP $R/STOP; echo "STOP requested: checkpoint at the next step, then exit..."
  for i in $(seq 1 90); do { running || trainer; } || break; sleep 10; done
  if running || trainer; then echo "still stopping after 15 min (paused for heat/RAM?); it exits at its next step"; else echo "STOPPED"; fi; show ;;
status) if running; then echo "RUNNING (chain pid $(cat $C/chain.pid))"; else echo "NOT RUNNING"; fi; show ;;
*) echo "usage: ctl_r4.sh start|stop|status"; exit 2 ;;
esac
