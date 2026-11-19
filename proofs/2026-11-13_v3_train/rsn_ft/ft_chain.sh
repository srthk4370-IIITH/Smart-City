#!/usr/bin/env bash
# ft_chain.sh (from chain_r4.sh 2026-11-13): unattended rsn v3 fine-tune (edited r3-2800 + approved v4 data) on the RTX 4050.
# usage (detached): BASE=<edited base dir> set in run_ft.env or env. Clean stop: touch rsn_ft/chain/STOP
SCRIPT=ft_chain; RUN_ID=v3ft
source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
T4=$QIDK/proofs/2026-11-13_v3_train/rsn_ft; C=$T4/chain; mkdir -p "$C"
set -a; source "$T4/run_ft.env"; [ -s "$C/BASE" ] && BASE=$(cat "$C/BASE"); set +a
export RUN=rsn3_4b_v3ft
O=$HOME/smartcity_runs/$RUN; mkdir -p "$O"
if [ -s "$C/chain.pid" ] && kill -0 "$(cat "$C/chain.pid")" 2>/dev/null; then die "ft_chain already running" 8; fi
echo $$ > "$C/chain.pid"; trap 'rm -f "$C/chain.pid"' EXIT
[ -s "$BASE/config.json" ] || die "BASE not set / no config.json ($BASE)" 2
for f in "$NEW" "$REPLAY" "$TOOLS4" "$DEV4_INC" "$DEV4_CHAT" "$GEN_INC3" "$GEN_CHAT3"; do [ -s "$f" ] || die "missing $f" 2; done
if [ -n "${START_ADAPTER:-}" ]; then   # empty = fresh LoRA on a merged base (r3_edit_C1 already contains the r3 LoRA)
M=$(cat "$START_ADAPTER/adapter_model.safetensors" "$START_ADAPTER/adapter_config.json" | md5sum | cut -d' ' -f1)
[ -s "$O/start_adapter.md5" ] || echo "$M  $START_ADAPTER" > "$O/start_adapter.md5"
[ "$(cut -d' ' -f1 "$O/start_adapter.md5")" = "$M" ] || die "start adapter changed since the run began" 10
fi
[ -s "$O/base.txt" ] || echo "$BASE" > "$O/base.txt"
[ "$(cat "$O/base.txt")" = "$BASE" ] || die "BASE changed since the run began ($(cat "$O/base.txt") -> $BASE)" 10
status "start (run $RUN, base $BASE, new $(wc -l < "$NEW") replay $(wc -l < "$REPLAY"))"
fails=0
while true; do
  [ -e "$C/STOP" ] && { status "STOP file: chain stops"; exit 0; }
  bash "$T4/ft_chunk.sh"; rc=$?
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
