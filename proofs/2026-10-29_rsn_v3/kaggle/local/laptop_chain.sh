#!/usr/bin/env bash
# laptop_chain.sh: the unattended laptop side of rsn_v3 (launch via proofs/detach.sh; survives Claude limits). Steps, in order,
# each idempotent (marker kaggle/chain/<step>.done) and logged to kaggle/STATUS.md:
#   data_a      bundle A exists (make_data + make_bundle for $RUN_ID; waits if that build is already running)
#   distill     wait for the laptop distillation job (distill_llama.py / run_distill.sh / GPU_LOCK "distill_laptop"; never
#               touched) -> its chat3_distilled.jsonl (runs its finalize.sh only if the job ended without it)
#   replay      ~1,000 general prompts answered by the base 4B (llama-server under GPU_LOCK)
#   bundle_b    rsn_v3_chat_bundle.zip (+ md5) for Kaggle
#   mix         laptop mixes (dev slice; chat + replay rows at the planned share)
#   base_2b     Qwen/Qwen3.5-2B downloaded to ~/models/qwen3.5-2b (+ SHA256SUMS)
#   train_2b    2B candidate, same data and recipe, guarded chunks of laptop_train.sh until epoch-1 end / early stop
#   export_2b   best 2B checkpoint -> Q4_0 GGUF (models_stage/rsn_v3_2b_q4_0.gguf) -> gate (gate/g2b_$RUN_ID)
#   4B watch    (between every chunk and afterwards) a new C:\Users\hp\Downloads\rsn_v3_adapter_{best,final,epoch1}.zip ->
#               import -> Q4_0 (rsn_v3_4b_<n>) -> gate (gate/g4b_<n>) -> compare with the 2B -> READY_FOR_BOARD
# Guards: kaggle/chain/STOP (clean stop between steps / at the trainer's next step), one chain instance (chain.pid), RAM / disk /
# GPU temperature (in the sub-scripts), GPU_LOCK for every GPU step. Never touches the board.
SCRIPT=laptop_chain; source "$(dirname "$0")/guard.sh"
RUN_ID=${RUN_ID:-r1}; export RUN_ID
L=$KG/local; C=$KG/chain; B=$KG/build/$RUN_ID; DLD=$V3/distill_laptop; DL=/mnt/c/Users/hp/Downloads; LOCK=$V3/GPU_LOCK
mkdir -p "$C"
# r2 and later (2026-11-02, proofs/2026-11-02_2b_r2): prebuilt data in that proofs dir (data/final), own step markers
# kaggle/chain/<RUN_ID>/<step>.done, own GGUF rsn_v3_2b_<RUN_ID>_q4_0.gguf, tools_r2.json, GEN eval on the r2 test slices.
# r1 keeps its old markers (kaggle/chain/<step>.done) and file names.
CM=$C; GGUF_NAME=rsn_v3_2b
if [ "$RUN_ID" != r1 ]; then
  CM=$C/$RUN_ID; GGUF_NAME=rsn_v3_2b_$RUN_ID; R2D=$QIDK/proofs/2026-11-02_2b_r2/data/final
  mkdir -p "$CM"
  for f in incidents_train.jsonl chat_train.jsonl dev_mix3.jsonl gen_inc_r2.jsonl gen_chat_r2.jsonl tools_r2.json; do
    [ -s "$R2D/$f" ] || die "missing r2 data file $R2D/$f" 2
  done
  for s in data_a distill replay bundle_b mix base_2b; do [ -e "$CM/$s.done" ] || echo "prebuilt ($R2D)" > "$CM/$s.done"; done
  [ -s "$HOME/models/qwen3.5-2b/config.json" ] || rm -f "$CM/base_2b.done"
fi
if [ -s "$C/chain.pid" ] && kill -0 "$(cat "$C/chain.pid")" 2>/dev/null; then die "laptop_chain already running (pid $(cat "$C/chain.pid"))" 8; fi
echo $$ > "$C/chain.pid"; trap 'rm -f "$C/chain.pid"' EXIT
stopchk() { [ -e "$C/STOP" ] && { status "STOP file: chain stops here (rm kaggle/chain/STOP and relaunch to continue)"; exit 0; }; }
done_() { touch "$CM/$1.done"; status "step $1 done"; }
isdone() { [ -e "$CM/$1.done" ]; }
take_lock() { until [ ! -e "$LOCK" ] || grep -q "^laptop_chain $1 " "$LOCK"; do stopchk; sleep 300; done; echo "laptop_chain $1 $(date -Is) pid=$$" > "$LOCK"; }
drop_lock() { grep -q "^laptop_chain $1 " "$LOCK" 2>/dev/null && rm -f "$LOCK"; }
status "chain start (run $RUN_ID, pid $$)"

# ---- data_a: bundle A
if ! isdone data_a; then
  while pgrep -f "[m]ake_data.sh|[m]ake_bundle.sh" >/dev/null; do stopchk; sleep 120; done
  if [ ! -s "$B/rsn_v3_bundle.zip" ]; then
    [ -s "$B/data/manifest.json" ] || SKIP_CHAT=1 bash "$L/make_data.sh" || die "make_data failed"
    bash "$L/make_bundle.sh" || die "make_bundle failed"
  fi
  done_ data_a
fi
stopchk

# ---- distill: wait for the laptop distillation job, then its distilled chat file
if ! isdone distill; then
  while pgrep -f "[d]istill_llama.py|[r]un_distill.sh" >/dev/null || grep -qs "^distill_laptop" "$LOCK"; do stopchk; sleep 300; done
  if [ ! -s "$DLD/chat3_distilled.jsonl" ] && [ -s "$DLD/raw_train.jsonl" ]; then
    bash "$DLD/finalize.sh" "$DLD" > "$C/finalize.log" 2>&1 || die "distill finalize failed ($C/finalize.log)"
  fi
  [ -s "$DLD/chat3_distilled.jsonl" ] || die "no $DLD/chat3_distilled.jsonl after the distill job ended"
  done_ distill
fi
stopchk

# ---- replay: base-model answers (GPU)
if ! isdone replay; then
  mkdir -p "$B/replay"; need_ram 2048 60
  take_lock replay
  LC=~/llama-cuda-b11815
  LD_LIBRARY_PATH=$LC/bin $LC/bin/llama-server -m ~/models/qwen3.5-4b-gguf/qwen3.5-4b-q8_0.gguf -ngl 99 -c 8192 -np 4 -lm none -cram 256 --jinja -t 2 -tb 2 \
    --host 127.0.0.1 --port 18112 --no-webui > "$B/replay/server.log" 2>&1 &
  SP=$!
  for i in $(seq 1 90); do sleep 2; curl -s localhost:18112/health | grep -q ok && break; done
  python3 "$L/make_replay.py" --port 18112 --out "$B/replay/replay_train.jsonl" > "$B/replay/replay.log" 2>&1; rc=$?
  kill $SP 2>/dev/null; wait $SP 2>/dev/null; drop_lock replay
  [ $rc = 0 ] || die "replay failed ($B/replay/replay.log)"
  status "replay: $(tail -n 1 "$B/replay/replay.log")"
  done_ replay
fi
stopchk

# ---- bundle_b
if ! isdone bundle_b; then
  [ -s "$B/rsn_v3_chat_bundle.zip" ] || bash "$L/make_bundle_b.sh" "$DLD/chat3_distilled.jsonl" "$B/replay/replay_train.jsonl" || die "bundle B failed"
  done_ bundle_b
fi

# ---- mix (laptop copies of the Kaggle mixes)
MX=$B/mix_laptop; INC=$B/data/incidents3_train.jsonl
if ! isdone mix; then
  python3 "$KG/build_mix3.py" --inc "$INC" --inc-dev "$B/data/incidents_dev60.jsonl" --chat-dev "$V3/data/chat3_dev.jsonl" --out-dir "$MX" || die "dev mix failed"
  python3 "$KG/build_mix3.py" --inc "$INC" --chat "$DLD/chat3_distilled.jsonl" --replay "$B/replay/replay_train.jsonl" --out-dir "$MX" || die "chat mix failed"
  status "$(tail -n 1 "$MX/mix3.txt")"
  done_ mix
fi

# ---- base_2b
M2=$HOME/models/qwen3.5-2b
if ! isdone base_2b; then
  need_disk ~ 12000
  [ -s "$M2/config.json" ] || { ~/venvs/rsn/bin/python -c "from huggingface_hub import snapshot_download as s; s('Qwen/Qwen3.5-2B', local_dir='$M2.part')" \
    > "$C/base_2b.log" 2>&1 && mv "$M2.part" "$M2"; } || die "2B download failed ($C/base_2b.log)"
  (cd "$M2" && sha256sum *.safetensors *.json *.jinja > SHA256SUMS)
  done_ base_2b
fi

# ---- 4B watch: import + gate every new Kaggle adapter zip, then compare with the gated 2B
check_4b() {
  local z m n
  for z in $(ls -t "$DL"/rsn_v3_adapter_best*.zip "$DL"/rsn_v3_adapter_final*.zip "$DL"/rsn_v3_adapter_epoch1*.zip 2>/dev/null); do
    m=$(md5sum < "$z" | cut -c1-12)
    grep -qs "^$m " "$C/4b_seen.txt" && continue
    n=$(( $(wc -l < "$C/4b_seen.txt" 2>/dev/null || echo 0) + 1 ))
    echo "$m $z g4b_$n" >> "$C/4b_seen.txt"
    status "new 4B adapter $z (md5 $m) -> g4b_$n"
    RUN_ID=g4b_$n NAME=rsn_v3_4b_$n bash "$L/import_adapter.sh" "$z" || { status "4B import g4b_$n failed"; continue; }
    RUN_ID=g4b_$n bash "$L/gate_eval.sh" "$QIDK/Code/models_stage/rsn_v3_4b_${n}_q4_0.gguf"
    echo "$QIDK/Code/models_stage/rsn_v3_4b_${n}_q4_0.gguf" > "$KG/gate/g4b_$n/gguf.txt"
    compare
    break                                   # newest first; older zips are picked up on the next call
  done
}
compare() {
  local a b
  a=$(ls -td "$KG"/gate/g4b_* 2>/dev/null | head -1); b=$KG/gate/g2b_$RUN_ID
  if [ -s "$a/gate.json" ] && [ -s "$b/gate.json" ]; then
    RUN_ID=c_$(basename "$a")_$RUN_ID bash "$L/chain.sh" compare "$(basename "$a")" "g2b_$RUN_ID"
  elif [ -s "$a/gate.json" ] && isdone export_2b; then
    status "compare: 2B gate missing; 4B $(basename "$a") gated alone (see its GATE.md)"
  fi
}

# ---- train_2b (guarded chunks; the 4B watch runs between chunks)
if ! isdone train_2b; then
  fails=0
  while true; do
    stopchk; check_4b
    if [ "$RUN_ID" = r1 ]; then
      RUN=rsn3_2b_$RUN_ID BASE=$M2 INC=$INC CHAT=$MX/chat_mix3.jsonl DEV=$MX/dev_mix3.jsonl GEN_INC=$B/data/incidents_dev60.jsonl \
        GEN_CHAT=$V3/data/chat3_dev.jsonl GEN_TRAIN_CHAT=$V3/data/chat3_train.jsonl CHUNK_H=${CHUNK_H:-6} bash "$L/laptop_train.sh"; rc=$?
    else
      RSN3_SEG_TOKENIZE=1 RUN=rsn3_2b_$RUN_ID BASE=$M2 TOOLS=$R2D/tools_r2.json INC=$R2D/incidents_train.jsonl CHAT=$R2D/chat_train.jsonl \
        DEV=$R2D/dev_mix3.jsonl GEN_INC=$R2D/gen_inc_r2.jsonl GEN_CHAT=$R2D/gen_chat_r2.jsonl \
        GEN_TRAIN_CHAT=$QIDK/proofs/2026-11-02_2b_r2/data/chat_gen/chat3_train.jsonl EXTRA="${R2_EXTRA:---micro-tokens 6144}" \
        CHUNK_H=${CHUNK_H:-6} bash "$L/laptop_train.sh"; rc=$?
    fi
    case $rc in
      0|5|6) status "2B training finished (rc $rc)"; break;;
      3) fails=0;;
      7) exit 0;;
      *) fails=$((fails + 1)); status "2B chunk rc $rc (failure $fails/3)"; [ $fails -ge 3 ] && die "2B training keeps failing"; sleep 600;;
    esac
  done
  done_ train_2b
fi

# ---- export_2b + gate
if ! isdone export_2b; then
  O2=$HOME/smartcity_runs/rsn3_2b_$RUN_ID
  BEST=$(python3 -c "import json;t=json.load(open('$O2/best.json'))['top'];print('$O2/ckpt_best_%04d' % t[0][1])" 2>/dev/null)
  [ -d "$BEST" ] || BEST=$O2/ckpt_epoch1
  [ -d "$BEST" ] || BEST=$O2/ckpt_latest
  status "2B export from $BEST"
  GG=$QIDK/Code/models_stage/${GGUF_NAME}_q4_0.gguf
  [ -s "$GG" ] || EXPORT_RAM_MB=${EXPORT_RAM_MB:-1500} bash "$L/export_gguf.sh" "$M2" "$BEST" "$GGUF_NAME" || die "2B export failed"
  # gate chat suite = chat3_eval.py with the tools_v4 15-tool chat header (what the app sends to rsn_v3 from r2 on)
  [ -s "$KG/gate/g2b_$RUN_ID/gate.json" ] || TEST_R2=${R2D:-} RUN_ID=g2b_$RUN_ID bash "$L/gate_eval.sh" "$GG"
  echo "$GG" > "$KG/gate/g2b_$RUN_ID/gguf.txt"
  done_ export_2b
  compare
fi

# ---- keep watching for 4B adapters (7 days or STOP)
status "watching $DL for rsn_v3_adapter_{best,final,epoch1}*.zip (STOP: kaggle/chain/STOP)"
for i in $(seq 1 1008); do stopchk; check_4b; sleep 600; done
status "chain watch ended (7 days)"
