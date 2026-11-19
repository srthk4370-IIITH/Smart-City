#!/usr/bin/env bash
# dpo.sh: PLAN_V2 stage 4, the optional preference step. Run it BY HAND only when a gate failed (normally gate B after
# repair_pool.sh) and its GATE.md shows a remaining confusion (e.g. sensor_fault vs normal, unknown vs normal); laptop_chain.sh
# never starts it. Laptop only, resumable (rerun the same command), never touches the board.
# usage (WSL, via detach.sh):
#   RUN_ID=dp1 GATE=gB_rp1 REPAIR=rp1 bash proofs/detach.sh dpo_dp1 .../kaggle/local/dpo.sh
#   CKPT defaults to the repair round's exported checkpoint (kaggle/repair/$REPAIR/best_ckpt.txt); without REPAIR give CKPT=<adapter
#   dir of the gated candidate>. Optional env: GGUF, BASE, MODEL_DIR, MAX_LEN, N_INC=3000 N_CHAT=800 SEED_INC=821 SEED_CHAT=822,
#   MAX_PAIRS=2000, BETA=0.1, LR=5e-6, SFT_ALPHA=0, TEACHER_H=4, CHUNK_H=3, UNTIL=<step>, FORCE=1 (run although the gate shows
#   no label confusion), FORCE_FINAL=1. Stop cleanly: touch kaggle/dpo/$RUN_ID/STOP (or kaggle/chain/STOP).
# Steps (marker kaggle/dpo/$RUN_ID/<step>.done, status lines in kaggle/STATUS.md):
#   weights   failure profile + label confusions of the candidate on the gate's held-out suites (counts only)
#   pool_inc / pool_chat   fresh synthetic pools (new seeds; no real_agent rows; held-out, epoch-1 and repair-pool prompts dropped)
#   run_inc / run_chat     the gated candidate GGUF on both pools (on-policy rejected answers)
#   score     strict per-row scoring (as repair_pool.sh)
#   teacher   failed chat questions -> base-model self-distillation + select_distill (verified chosen answers)
#   pairs     ~2k pairs (MAX_PAIRS): chosen = verified gold report (compact, re-verified) / verified chat answer; rejected = the
#             model's own wrong output on the same prompt. Incident pairs whose gold->predicted label matches a gate confusion
#             first, then other label/severity errors, then other strict failures (check recall/precision-only misses stay SFT
#             material); chat pairs <= 30 %; on-policy pairs before the repair pool's (older model) ones
#   check     Kaggle-safety check (synthetic only, no held-out prompt or id)
#   train     cont_train.py --mode dpo from CKPT: beta 0.1 (small), LR 5e-6, LoRA dropout off, reference log-probs = the
#             starting adapter (computed once), logits at loss positions only, 1 epoch, dev score every 25 steps, best-3
#             checkpoints that beat the start, patience 3, 5 % of the pairs held out for reward accuracy
#   export / gate   best checkpoint -> Code/models_stage/rsn_v3_dpo_$RUN_ID_q4_0.gguf -> gate_eval.sh -> kaggle/gate/gD_$RUN_ID
SCRIPT=dpo; source "$(dirname "$0")/guard.sh"
check_run_id
OUT=$KG/dpo/$RUN_ID
if [ -z "${CKPT:-}" ] && [ -n "${REPAIR:-}" ]; then CKPT=$(cat "$KG/repair/$REPAIR/best_ckpt.txt" 2>/dev/null); fi
source "$(dirname "$0")/repair_common.sh"
setup_candidate
TAG=dpo_$RUN_ID
RP=${REPAIR:+$KG/repair/$REPAIR}
if [ ! -d "$OUT" ]; then
  [ -e "$R1/eval/results/$TAG" ] && die "eval/results/$TAG exists: use a new run id" 6
  new_dir "$OUT"
fi
if [ -s "$OUT/run.pid" ] && kill -0 "$(cat "$OUT/run.pid")" 2>/dev/null; then die "dpo $RUN_ID already running (pid $(cat "$OUT/run.pid"))" 8; fi
echo $$ > "$OUT/run.pid"; trap 'drop_lock; rm -f "$OUT/run.pid"' EXIT
stopchk
status "start: gate $GATE, candidate $GGUF, adapter $CKPT, base $BASE, max_len $MAX_LEN${RP:+, repair pool $RP}"
PYL="$PY $L/repair_lib.py"

if ! isdone weights; then
  $PYL gate-weights --tag "$GTAG" --gate-dir "$KG/gate/$GATE" --rwh2 "$RWH2" --out "$OUT/weights.json" > "$OUT/weights.log" 2>&1 \
    || die "gate weights failed ($OUT/weights.log)"
  status "$(tail -n 1 "$OUT/weights.log")"
  if [ "${FORCE:-0}" != 1 ] && python3 -c "import json,sys;w=json.load(open('$OUT/weights.json'));sys.exit(1 if w['label_confusions'] or w['severity_confusions'] else 0)"; then
    die "gate $GATE shows no label / severity confusion: the preference step is not needed (FORCE=1 to run anyway)" 1
  fi
  done_ weights
fi
stopchk
if ! isdone pool_inc; then
  need_ram 1536
  $PYL inc-pool --out "$OUT/pool_inc.jsonl" --seed "${SEED_INC:-821}" --n "${N_INC:-3000}" --weights "$OUT/weights.json" \
    --exclude "$INC_E1" "$RWH2" ${RP:+"$RP/pool_inc.jsonl"} > "$OUT/pool_inc.log" 2>&1 || die "incident pool failed ($OUT/pool_inc.log)"
  status "$(tail -n 1 "$OUT/pool_inc.log")"
  done_ pool_inc
fi
stopchk
if ! isdone pool_chat; then
  need_ram 1536
  $PYL chat-pool --out "$OUT/pool_chat.jsonl" --seed "${SEED_CHAT:-822}" --n "${N_CHAT:-800}" --weights "$OUT/weights.json" \
    > "$OUT/pool_chat.log" 2>&1 || die "chat pool failed ($OUT/pool_chat.log)"
  status "$(tail -n 1 "$OUT/pool_chat.log")"
  done_ pool_chat
fi
stopchk
run_pools "$TAG"
RES=$R1/eval/results/$TAG/pool.jsonl
if ! isdone score; then
  $PYL inc-score --pool "$OUT/pool_inc.jsonl" --results "$RES" --out "$OUT/inc_scored.jsonl" > "$OUT/score.log" 2>&1 || die "scoring failed"
  $PYL chat-failed --pool "$OUT/pool_chat.jsonl" --results "$OUT/pool_chat_res.jsonl" --out "$OUT/chat_failed.jsonl" >> "$OUT/score.log" 2>&1 \
    || die "chat failures failed"
  status "$(tr '\n' ' ' < "$OUT/score.log" | cut -c1-300)"
  done_ score
fi
stopchk
if ! isdone teacher; then
  TEACHER_H=${TEACHER_H:-4} teacher "$OUT/chat_failed.jsonl" "$OUT/chat_chosen.jsonl"
  done_ teacher
fi
stopchk
if ! isdone pairs; then
  S=("$OUT/inc_scored.jsonl"); P=("$OUT/pool_inc.jsonl"); R=("$RES")
  CP=("$OUT/pool_chat.jsonl"); CR=("$OUT/pool_chat_res.jsonl"); CC=("$OUT/chat_chosen.jsonl")
  if [ -n "$RP" ] && [ -s "$RP/inc_scored.jsonl" ]; then      # the repair round's failures (older model): after the on-policy ones
    S+=("$RP/inc_scored.jsonl"); P+=("$RP/pool_inc.jsonl"); R+=("$R1/eval/results/repair_$REPAIR/pool.jsonl")
    CP+=("$RP/pool_chat.jsonl"); CR+=("$RP/pool_chat_res.jsonl"); CC+=("$RP/chat_repair.jsonl")
  fi
  $PYL pairs --scored "${S[@]}" --pool "${P[@]}" --results "${R[@]}" --chat-pool "${CP[@]}" --chat-results "${CR[@]}" --chat-chosen "${CC[@]}" \
    --weights "$OUT/weights.json" --max "${MAX_PAIRS:-2000}" --out "$OUT/pairs.jsonl" > "$OUT/pairs.log" 2>&1 || die "pairs failed ($OUT/pairs.log)"
  status "$(tail -n 1 "$OUT/pairs.log")"
  [ -s "$OUT/pairs.jsonl" ] || die "no preference pairs (the candidate made no strict error on the pools)" 1
  done_ pairs
fi
if ! isdone check; then
  $PYL check --files "$OUT/pairs.jsonl" --rwh2 "$RWH2" > "$OUT/check.log" 2>&1 || die "Kaggle-safety check failed: $(tail -n 1 "$OUT/check.log")"
  status "$(tail -n 1 "$OUT/check.log")"
  md5_manifest "$OUT"
  done_ check
fi
stopchk
TR=rsn3_dpo_$RUN_ID
if ! isdone train; then
  train_loop dpo "$TR" "$OUT/pairs.jsonl" "--lr ${LR:-5e-6} --beta ${BETA:-0.1} --sft-alpha ${SFT_ALPHA:-0} --accum 16 --epochs 1 --gen-every 25 --patience 3 --keep-best 3 --val-frac 0.05"
  done_ train
fi
if ! isdone export; then
  B=$(best_ckpt "$TR")
  if [ -z "$B" ]; then
    [ "${FORCE_FINAL:-0}" = 1 ] || die "no DPO checkpoint beat the starting adapter's dev score (see ~/smartcity_runs/$TR/gen_eval.jsonl); FORCE_FINAL=1 exports ckpt_final" 1
    B=$HOME/smartcity_runs/$TR/ckpt_final
  fi
  echo "$B" > "$OUT/best_ckpt.txt"
  status "export $B"
  done_ export
fi
if ! isdone gate; then
  export_gate "$(cat "$OUT/best_ckpt.txt")" "rsn_v3_dpo_$RUN_ID" "gD_$RUN_ID"; rc=$?
  case $rc in
    0) status "GATE PASS after DPO $RUN_ID ($KG/gate/gD_$RUN_ID/GATE.md): next = chain.sh compare / board A/B (owner approval)";;
    1) status "GATE FAIL after DPO $RUN_ID ($KG/gate/gD_$RUN_ID/GATE.md): keep the previous candidate";;
    *) die "gate incomplete rc=$rc ($KG/gate/gD_$RUN_ID)";;
  esac
  done_ gate
fi
status "dpo $RUN_ID done"
