#!/usr/bin/env bash
# chain_4b.sh: unattended Qwen3.5-4B QLoRA run on the laptop RTX 4050, dataset r3 (launch via ctl_4b.sh start -> proofs/detach.sh).
# Loops guarded chunks of kaggle/local/laptop_train.sh (heat 87/82 C pause, Windows RAM < 1.0 GB pause, GPU_LOCK, checkpoint
# every chunk, resume from ckpt_latest) until epoch 1 ends or early stop on the generation dev score. Status lines ->
# proofs/2026-10-29_rsn_v3/kaggle/STATUS.md (tag [chain_4b r3]). Clean stop: touch the STOP file (ctl_4b.sh stop).
# Never touches the board. Export + gate of the best checkpoint are a separate step (not automatic: owner decides).
SCRIPT=chain_4b; RUN_ID=r3
source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
H=$QIDK/proofs/2026-11-06_4b_local; D=$H/data/final; C=$H/chain; mkdir -p "$C"
export RUN=rsn3_4b_r3 BASE=$HOME/models/qwen3.5-4b TOOLS=$D/tools_r3.json \
  INC=$D/incidents_train.jsonl CHAT=$D/chat_train_r3.jsonl DEV=$D/dev_r3.jsonl \
  GEN_INC=$QIDK/proofs/2026-11-02_2b_r2/data/final/gen_inc_r2.jsonl GEN_CHAT=$D/gen_chat_r3.jsonl GEN_TRAIN_CHAT=$D/gen_train_chat_r3.jsonl \
  CHUNK_H=${CHUNK_H:-6} TORCHINDUCTOR_COMPILE_THREADS=1 MALLOC_ARENA_MAX=2 RSN3_SEG_TOKENIZE=1
export EXTRA="--model-dir $HOME/models/qwen3.5-4b-nf4 ${FIT_FLAGS:?FIT_FLAGS missing (see FIT.md)} ${GEN_FLAGS:-}"
O=$HOME/smartcity_runs/$RUN; mkdir -p "$O"
[ -n "${MAX_LEN:-}" ] && [ ! -s "$O/maxlen.json" ] && echo "{\"max_len\": $MAX_LEN, \"probe\": \"FIT.md\"}" > "$O/maxlen.json"
for f in "$INC" "$CHAT" "$DEV" "$TOOLS" "$GEN_INC" "$GEN_CHAT"; do [ -s "$f" ] || die "missing $f" 2; done
if [ -s "$C/chain.pid" ] && kill -0 "$(cat "$C/chain.pid")" 2>/dev/null; then die "chain_4b already running" 8; fi
echo $$ > "$C/chain.pid"; trap 'rm -f "$C/chain.pid"' EXIT
status "start (run $RUN, max_len $(cat "$O/maxlen.json" 2>/dev/null | cut -c1-40))"
fails=0
while true; do
  [ -e "$C/STOP" ] && { status "STOP file: chain stops (ctl_4b.sh start resumes)"; exit 0; }
  bash "$KG/local/laptop_train.sh"; rc=$?
  case $rc in
    3) fails=0 ;;                                   # chunk hours used or STOP: loop (STOP checked above)
    0|5) status "epoch 1 done (rc $rc): best checkpoint in $O/best.json"; touch "$C/train.done"; exit 0 ;;
    6) status "early stop (rc 6): best checkpoint in $O/best.json"; touch "$C/train.done"; exit 0 ;;
    4) status "waited 60 min for Windows RAM (close apps); retrying in 15 min"; sleep 900 ;;   # need_ram gave up: not a failure
    7|8) status "lock/another trainer (rc $rc): chain exits"; exit $rc ;;
    *) fails=$((fails + 1)); status "chunk failed rc=$rc (#$fails): $(tail -n 2 "$O/stdout.log" | tr '\n' ' ' | cut -c1-200)"
       [ $fails -ge 3 ] && die "3 failed chunks in a row" 9
       sleep 600 ;;
  esac
done
