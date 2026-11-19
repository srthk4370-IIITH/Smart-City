#!/usr/bin/env bash
# fake_ctl.sh start|stop|status: stands in for ctl_4b.sh in the offline tests. "Training" = a sleep process in chain.pid;
# stop bumps the laptop checkpoint by $LAPTOP_STEPS (default 10) to model laptop progress between handovers.
C=${BATON_CHAIN_DIR:?}; R=${BATON_RUN_DIR:?}; mkdir -p "$C"
running() { p=$(cat $C/chain.pid 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
case $1 in
start) running && { echo ALREADY RUNNING; exit 0; }; setsid sleep 3600 < /dev/null > /dev/null 2>&1 & echo $! > $C/chain.pid; echo STARTED ;;
stop) running || { echo NOT RUNNING; exit 0; }; kill "$(cat $C/chain.pid)"; rm -f $C/chain.pid
  CUDA_VISIBLE_DEVICES= ${BATON_PY:-$HOME/venvs/rsn/bin/python} - "$R/ckpt_latest/state.pt" "${LAPTOP_STEPS:-10}" <<'PY'
import sys, torch
p, n = sys.argv[1], int(sys.argv[2]); st = torch.load(p, weights_only=False, map_location="cpu")
st["step"] += n; st["sched"]["last_epoch"] += n; st.update(dtype="torch.bfloat16", world=1, host="laptop-fake", scaler={}); torch.save(st, p)   # a bf16 save has no scaler
PY
  echo STOPPED ;;
status) running && echo RUNNING || echo "NOT RUNNING" ;;
esac
