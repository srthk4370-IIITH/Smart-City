#!/usr/bin/env bash
# chain_r4.sh: unattended r4 top-up of the gated 4B r3 adapter (step 2800) on the laptop RTX 4050 (launch: ctl_r4.sh start).
# Loops guarded 6 h chunks of topup_chunk.sh -> topup_train.py (resume from ckpt_latest) until the plan ends or early stop.
# Status lines: proofs/2026-10-29_rsn_v3/kaggle/STATUS.md tag [chain_r4 r4topup]. Clean stop: ctl_r4.sh stop (STOP file).
# Before the first chunk: data present (paths_r4.sh), start adapter md5 recorded (start_adapter.md5) and checked on every start.
SCRIPT=chain_r4; RUN_ID=r4topup
source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
T4=$QIDK/proofs/2026-11-12_topup_r4/train; C=$T4/chain; mkdir -p "$C"
export RUN=rsn3_4b_r4topup
source "$T4/paths_r4.sh"
O=$HOME/smartcity_runs/$RUN; mkdir -p "$O"
if [ -s "$C/chain.pid" ] && kill -0 "$(cat "$C/chain.pid")" 2>/dev/null; then die "chain_r4 already running" 8; fi
echo $$ > "$C/chain.pid"; trap 'rm -f "$C/chain.pid"' EXIT
for v in NEW REPLAY; do [ -s "${!v:-}" ] || die "data: $v not resolved ($(paths_show)); waiting for data/final or set it in run_r4.env" 2; done
[ -n "${DEV4_INC:-}${DEV4_CHAT:-}" ] || die "data: no r4 dev slice ($(paths_show))" 2
for f in "$GEN_INC3" "$GEN_CHAT3" "$TOOLS4"; do [ -s "$f" ] || die "missing $f" 2; done
M=$(cat "$START_ADAPTER/adapter_model.safetensors" "$START_ADAPTER/adapter_config.json" | md5sum | cut -d' ' -f1)
[ -s "$O/start_adapter.md5" ] || echo "$M  $START_ADAPTER" > "$O/start_adapter.md5"
[ "$(cut -d' ' -f1 "$O/start_adapter.md5")" = "$M" ] || die "start adapter changed since the run began ($START_ADAPTER)" 10
status "start (run $RUN, $(paths_show | cut -c1-300))"
fails=0
while true; do
  [ -e "$C/STOP" ] && { status "STOP file: chain stops (ctl_r4.sh start resumes)"; exit 0; }
  bash "$T4/topup_chunk.sh"; rc=$?
  case $rc in
    3) fails=0 ;;
    0) status "plan done (rc 0): best checkpoints in $O/best.json"; touch "$C/train.done"; exit 0 ;;
    6) status "early stop (rc 6): best checkpoints in $O/best.json"; touch "$C/train.done"; exit 0 ;;
    4) status "waited 60 min for Windows RAM (close apps); retrying in 15 min"; sleep 900 ;;
    8|11) status "another trainer / STOP during the GPU wait (rc $rc): chain exits"; exit $rc ;;
    9|10) die "data or init check failed (rc $rc): $(grep -E 'DATA CHECK|INIT_CHECK' "$O/train.log" | tail -1 | cut -c1-200)" $rc ;;
    *) fails=$((fails + 1)); status "chunk failed rc=$rc (#$fails): $(tail -n 2 "$O/stdout.log" | tr '\n' ' ' | cut -c1-200)"
       [ $fails -ge 3 ] && die "3 failed chunks in a row" 9
       sleep 600 ;;
  esac
done
