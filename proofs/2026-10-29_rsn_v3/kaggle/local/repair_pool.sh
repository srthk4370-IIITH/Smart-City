#!/usr/bin/env bash
# repair_pool.sh: PLAN_V2 stage 3, the error-driven repair round (STaR-style). Run it BY HAND only when gate A failed for a
# candidate; laptop_chain.sh never starts it. Laptop only, resumable (rerun the same command), never touches the board.
# usage (WSL, via detach.sh):
#   RUN_ID=rp1 GATE=g2b_r1 CKPT=~/smartcity_runs/rsn3_2b_r1/ckpt_best_XXXX \
#     bash proofs/detach.sh repair_rp1 .../kaggle/local/repair_pool.sh
#   optional env: GGUF (default kaggle/gate/$GATE/gguf.txt), BASE (2b/4b from the GGUF name), MODEL_DIR (pre-quantized NF4),
#   N_INC=3000 N_CHAT=2000 SEED_INC=811 SEED_CHAT=812, HARD_FRAC=0.25, BUDGET_TOK=15e6, TEACHER_H=8, CHUNK_H=3, MAX_LEN,
#   UNTIL=<step> (stop after it, e.g. UNTIL=check to only build the data), FORCE_FINAL=1 (export ckpt_final when no checkpoint
#   beat the starting adapter's dev score). Stop cleanly: touch kaggle/repair/$RUN_ID/STOP (or kaggle/chain/STOP).
# Steps (marker kaggle/repair/$RUN_ID/<step>.done, status lines in kaggle/STATUS.md):
#   weights   gate A failure profile of the candidate: failure rate per incident family / chat kind + label confusions
#             (counts only; no RWH / RWH-2 / dev / chat dev row is ever copied)
#   pool_inc  fresh synthetic incident pool (round-1 generator, new seed, NO real_agent rows, verify.py pass, prompts of the
#             held-out sets and of epoch 1 dropped), families weighted by the gate failure rate and rsn_v1's weak list
#   pool_chat fresh chat questions (gen_chat_v3 train phrasings, new seed, dev questions dropped), kinds weighted likewise
#   run_inc / run_chat   the candidate GGUF on both pools (llama-server -cram 256, GPU_LOCK, thermal / RAM watchdog)
#   score     score_v3 per incident row (strict: parse, schema, label, severity, req, check recall/precision, inject,
#             forbidden actions, needs_more_data); failed chat answers (verify_chat)
#   teacher   failed chat questions -> base-model self-distillation (distill_llama.py, base Qwen3.5-4B Q8_0 teacher, same
#             verification as the chat distillation) -> select_distill.py -> verified chat rows
#   rows      failed incidents -> gold report rows (compact, re-verified, epoch-1 form) + hardest passing rows of the weak
#             families (HARD_FRAC x failures: +tool / +inject first, then lowest stated confidence)
#   mix       repair rows + an equal number of tokens of replayed epoch-1 rows (synthetic only), capped at BUDGET_TOK (~15 M)
#   check     Kaggle-safety check of the mix (no real_agent row, no held-out prompt or id): the mix may go into a Kaggle bundle
#   train     cont_train.py --mode sft from CKPT: LR 5e-5, LoRA dropout 0.05 (from the adapter), wd 0.01, dev score every 50
#             steps, best-3 checkpoints that beat the start, patience 3 (guarded chunks: cont_chunk.sh)
#   export    best checkpoint -> Q4_0 GGUF Code/models_stage/rsn_v3_repair_$RUN_ID_q4_0.gguf
#   gate      gate B = gate_eval.sh (same rule) -> kaggle/gate/gB_$RUN_ID; PASS -> compare / board steps (owner), FAIL with a
#             remaining confusion -> dpo.sh (stage 4)
SCRIPT=repair_pool; source "$(dirname "$0")/guard.sh"
check_run_id
OUT=$KG/repair/$RUN_ID
source "$(dirname "$0")/repair_common.sh"
setup_candidate
TAG=repair_$RUN_ID
if [ ! -d "$OUT" ]; then
  [ -e "$R1/eval/results/$TAG" ] && die "eval/results/$TAG exists: use a new run id" 6
  new_dir "$OUT"
fi
if [ -s "$OUT/run.pid" ] && kill -0 "$(cat "$OUT/run.pid")" 2>/dev/null; then die "repair_pool $RUN_ID already running (pid $(cat "$OUT/run.pid"))" 8; fi
echo $$ > "$OUT/run.pid"; trap 'drop_lock; rm -f "$OUT/run.pid"' EXIT
stopchk
status "start: gate $GATE, candidate $GGUF, adapter $CKPT, base $BASE, max_len $MAX_LEN"
PYL="$PY $L/repair_lib.py"

if ! isdone weights; then
  $PYL gate-weights --tag "$GTAG" --gate-dir "$KG/gate/$GATE" --rwh2 "$RWH2" --out "$OUT/weights.json" > "$OUT/weights.log" 2>&1 \
    || die "gate weights failed ($OUT/weights.log)"
  status "$(tail -n 1 "$OUT/weights.log")"
  done_ weights
fi
stopchk
if ! isdone pool_inc; then
  need_ram 1536
  $PYL inc-pool --out "$OUT/pool_inc.jsonl" --seed "${SEED_INC:-811}" --n "${N_INC:-3000}" --weights "$OUT/weights.json" \
    --exclude "$INC_E1" "$RWH2" > "$OUT/pool_inc.log" 2>&1 || die "incident pool failed ($OUT/pool_inc.log)"
  status "$(tail -n 1 "$OUT/pool_inc.log")"
  done_ pool_inc
fi
stopchk
if ! isdone pool_chat; then
  need_ram 1536
  $PYL chat-pool --out "$OUT/pool_chat.jsonl" --seed "${SEED_CHAT:-812}" --n "${N_CHAT:-2000}" --weights "$OUT/weights.json" \
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
  teacher "$OUT/chat_failed.jsonl" "$OUT/chat_repair.jsonl"
  done_ teacher
fi
stopchk
if ! isdone rows; then
  $PYL inc-rows --scored "$OUT/inc_scored.jsonl" --pool "$OUT/pool_inc.jsonl" --weights "$OUT/weights.json" --hard-frac "${HARD_FRAC:-0.25}" \
    --out "$OUT/inc_repair.jsonl" > "$OUT/rows.log" 2>&1 || die "repair rows failed ($OUT/rows.log)"
  status "$(tail -n 1 "$OUT/rows.log")"
  done_ rows
fi
if ! isdone mix; then
  need_ram 1536
  $PYL mix --repair "$OUT/inc_repair.jsonl" "$OUT/chat_repair.jsonl" --replay-inc "$INC_E1" --replay-chat "$CHAT_E1" --ratio 1 \
    --budget-tokens "${BUDGET_TOK:-15e6}" --out "$OUT/repair_mix.jsonl" > "$OUT/mix.log" 2>&1 || die "mix failed ($OUT/mix.log)"
  status "$(tail -n 1 "$OUT/mix.log")"
  done_ mix
fi
if ! isdone check; then
  $PYL check --files "$OUT/repair_mix.jsonl" --rwh2 "$RWH2" > "$OUT/check.log" 2>&1 || die "Kaggle-safety check failed: $(tail -n 1 "$OUT/check.log")"
  status "$(tail -n 1 "$OUT/check.log")"
  md5_manifest "$OUT"
  done_ check
fi
stopchk
TR=rsn3_repair_$RUN_ID
if ! isdone train; then
  train_loop sft "$TR" "$OUT/repair_mix.jsonl" "--lr 5e-5 --accum 16 --gen-every 50 --patience 3 --keep-best 3 --gen-train-inc $INC_E1"
  done_ train
fi
if ! isdone export; then
  B=$(best_ckpt "$TR")
  if [ -z "$B" ]; then
    [ "${FORCE_FINAL:-0}" = 1 ] || die "no repair checkpoint beat the starting adapter's dev score (see ~/smartcity_runs/$TR/gen_eval.jsonl); FORCE_FINAL=1 exports ckpt_final" 1
    B=$HOME/smartcity_runs/$TR/ckpt_final
  fi
  echo "$B" > "$OUT/best_ckpt.txt"
  status "export $B"
  done_ export
fi
if ! isdone gate; then
  export_gate "$(cat "$OUT/best_ckpt.txt")" "rsn_v3_repair_$RUN_ID" "gB_$RUN_ID"; rc=$?
  case $rc in
    0) status "GATE B PASS for repair $RUN_ID ($KG/gate/gB_$RUN_ID/GATE.md): next = chain.sh compare / board A/B (owner approval)";;
    1) status "GATE B FAIL for repair $RUN_ID ($KG/gate/gB_$RUN_ID/GATE.md): if a confusion remains, run dpo.sh with GATE=gB_$RUN_ID";;
    *) die "gate B incomplete rc=$rc ($KG/gate/gB_$RUN_ID)";;
  esac
  done_ gate
fi
status "repair round $RUN_ID done"
