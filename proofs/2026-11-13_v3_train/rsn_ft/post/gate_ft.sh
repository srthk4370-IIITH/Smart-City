#!/usr/bin/env bash
# gate_ft.sh <candidate gguf>: STRICT host-GPU gate of the rsn_ft candidate vs r3-2800 (rsn_v3_4b_r3_q4_0.gguf).
# Machinery = 2026-11-06_4b_local/post/gate_4b.sh / 2026-11-12_topup_r4/train/post/gate_r4.sh (unchanged): host llama-server
# ~/llama-cuda-b11815 (-ngl 99 -cram 256 -np 1 --jinja, = board numerics), ONE server at a time, waits for an idle GPU and a free
# GPU_LOCK and holds it as "rsn_ft_gate ...", watchdog SIGSTOPs the server at >= HEAT_HI C (92) or Windows available < 500 MB and
# resumes at <= HEAT_LO (88) and >= 700 MB, need_ram before start, STOP file (post/STOP), marker per step (<out>/.m/<step>.done),
# resumable result files (a re-run continues where it stopped). Never touches the board. Nothing is written into the round-1
# eval/results or p0/results trees: every result goes to <out>/res, <out>/p0, <out>/chat.
# Candidate think mode GATE_THINK=1 (= app reasoner_think=adaptive); r3-2800 incidents think 0, chat adaptive (its gate_r3 modes).
# Steps (cheapest decisive first; scoreN = gate_score_ft.py --partial, FAIL stops the gate when EARLY_STOP=1):
#   rep rwh2 dev3                 the 19 checks + P0 (+ RW6 info) for the candidate     (r3-2800: cached gate_r3 results)
#   v4inc_<suite> v4site v4fog    v4 held-out tests for the candidate                  -> score1
#   bsite                         test_campus_chat for r3-2800 (H6 needs it)
#   t4new t4base c4new c4base     r4 tests (test_inc_r4 / test_chat_r4) for both       -> score2
#   r3new t2new                   chat_test_r3 (983) + incidents_test_r2 (1,368), candidate (r3-2800 cached) -> score3 (verdict)
#   bv4inc_<suite> bfog           reference: r3-2800 on the v4 prompts (BASE_V4=0 skips) -> final score (verdict unchanged)
# exit: 0 PASS, 1 FAIL, 2 incomplete, 3 STOP, other = error.
# Dry run (CPU, test/run_dryrun.sh): DRYRUN=1 SERVER_CMD=<stub> LIMIT=n: no GPU checks, no GPU_LOCK, no nvidia-smi.
SCRIPT=${SCRIPT:-rsn_ft_gate}; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
P=$QIDK/proofs/2026-11-13_v3_train/rsn_ft/post
STATUS=${POST_STATUS:-$P/STATUS.md}
G=${1:?candidate gguf}
OUT=${GATE_OUT:-$P/gate_ft}; MK=$OUT/.m; RES=$OUT/res; CH=$OUT/chat; mkdir -p "$MK" "$RES" "$CH"
TAG=${GATE_TAG:-rsn_ft_cand}; BT=r3s2800_ft; GATE_THINK=${GATE_THINK:-1}; EARLY_STOP=${EARLY_STOP:-1}; BASE_V4=${BASE_V4:-1}
LIMIT=${LIMIT:-0}; DRYRUN=${DRYRUN:-0}
G3=$QIDK/Code/models_stage/rsn_v3_4b_r3_q4_0.gguf
H=$QIDK/proofs/2026-11-06_4b_local; D4=$QIDK/proofs/2026-11-12_topup_r4/data/final
V4D=$QIDK/proofs/2026-11-13_v3_data/rsn/data/final; V4T=$V4D/tests; TOOLS4=$V4D/tools_v4.json
RWH2=$KG/build/r1/heldout/incidents_rwh2.jsonl; T2=$H/data/final/incidents_test_r2.jsonl
CB=$H/post/gate_r3/chatdev3_r3.jsonl; R3B=$H/post/gate_r3/chat_test_r3_4b.jsonl
T4I=$D4/test_inc_r4.jsonl; T4C=$D4/test_chat_r4.jsonl; TOOLS_R4=$D4/tools_r3.json
PY=${PY:-~/venvs/rsn/bin/python}; LC=~/llama-cuda-b11815; PORT=${PORT:-18097}
LOCK=$V3/GPU_LOCK; PAUSE=$R1/PAUSE_GPU; STOPF=${STOPF:-$P/STOP}
export HEAT_HI=${HEAT_HI:-92} HEAT_LO=${HEAT_LO:-88} HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RAM_LO=500; RAM_OK=700
[ "$G" != "$G3" ] || die "gate: the candidate is the r3 GGUF itself" 2
for f in "$G" "$G3" "$RWH2" "$T2" "$CB" "$R3B" "$T4I" "$T4C" "$TOOLS_R4" "$TOOLS4" "$V4T/test_fog.jsonl" "$V4T/test_campus_chat.jsonl"; do
  [ -s "$f" ] || die "gate: missing $f" 2; done
for gg in "$G" "$G3"; do [ -s "$gg.md5" ] && { (cd "$(dirname "$gg")" && md5sum -c --quiet "$(basename "$gg").md5") || die "gate: md5 mismatch $gg" 2; }; done

gtemp() { nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9; }
gmem() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9; }
mine() { [ -e "$LOCK" ] && grep -q "^rsn_ft_gate " "$LOCK"; }
busy_gpu() { pgrep -f "[t]rain_3e.py|[t]rain_rsn|[t]opup_train.py|[r]sn_ft_train.py|[c]ont_train.py|[l]lama-server" > /dev/null; }
gpu_idle() { [ ! -e "$PAUSE" ] && { [ ! -e "$LOCK" ] || mine; } && [ "$(gmem)" -lt 800 ] 2>/dev/null && ! busy_gpu; }
stopchk() { [ -e "$STOPF" ] && { status "gate: STOP file (resumes at the next launch)"; exit 3; }; }
if [ "$DRYRUN" = 1 ]; then
  status "gate: DRY RUN (stub server, LIMIT=$LIMIT): no GPU, no GPU_LOCK"
  export FT_NO_COOL=1
else
  t=0; until gpu_idle; do stopchk
    [ $((t % 60)) = 0 ] && status "gate: waiting for an idle GPU (lock: $(head -c 80 "$LOCK" 2>/dev/null || echo none), $(gmem) MiB used)"
    sleep 60; t=$((t + 1)); done
  echo "rsn_ft_gate $(date -Is) pid=$$" > "$LOCK"
  trap 'mine && rm -f "$LOCK"' EXIT
  need_ram 1536 600
fi
status "gate: start $G vs r3-2800 ($G3) -> $OUT"

serve_run() {   # serve_run <gguf> <ctx> <log> <cmd...>: one llama-server + watchdog, the command, then stop the server
  local m=$1 ctx=$2 lg=$3; shift 3
  stopchk
  local sp
  if [ "$DRYRUN" = 1 ]; then
    $SERVER_CMD --port $PORT --model "$m" > "$lg" 2>&1 &
    sp=$!
  else
    until [ ! -e "$PAUSE" ] && [ "$(gmem)" -lt 800 ] 2>/dev/null && ! busy_gpu; do stopchk; sleep 60; done
    LD_LIBRARY_PATH=$LC/bin nice -n 10 $LC/bin/llama-server -m "$m" -ngl 99 -cram 256 -c "$ctx" -np 1 --jinja -t 2 -tb 2 \
      --host 127.0.0.1 --port $PORT --no-webui > "$lg" 2>&1 &
    sp=$!
  fi
  local wd=0
  if [ "$DRYRUN" != 1 ]; then
    ( hot=0; while sleep 20; do kill -0 $sp 2>/dev/null || exit 0
        if [ -e "$PAUSE" ] || [ -e "$STOPF" ]; then kill -CONT $sp; kill $sp; exit 0; fi
        t=$(gtemp); f=$(free_mb)
        if { [ -n "$t" ] && [ "$t" -ge "$HEAT_HI" ]; } || { [ -n "$f" ] && [ "$f" -lt $RAM_LO ]; }; then
          [ $hot = 0 ] && echo "$(date +%T) pause gpu=${t}C avail=${f}MB" >> "$OUT/watchdog.log"; hot=1; fi
        [ $hot = 1 ] && kill -STOP $sp
        if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le "$HEAT_LO" ] && { [ -z "$f" ] || [ "$f" -ge $RAM_OK ]; }; then
          kill -CONT $sp; hot=0; echo "$(date +%T) resume gpu=${t}C avail=${f}MB" >> "$OUT/watchdog.log"; fi
      done ) &
    wd=$!
  fi
  local ok=0
  for i in $(seq 1 120); do sleep 2; curl -s localhost:$PORT/health | grep -q ok && { ok=1; break; }; done
  local rc=1
  if [ $ok = 1 ]; then nice -n 5 "$@"; rc=$?; else echo "server did not come up: $(tail -n 3 "$lg")"; fi
  [ "$wd" != 0 ] && kill $wd 2>/dev/null
  kill -CONT $sp 2>/dev/null; kill $sp 2>/dev/null; wait $sp 2>/dev/null
  return $rc
}
step() {   # step <name> <gguf> <ctx> <cmd...>: marker-guarded, up to 4 tries (a paused server can time a client out)
  local n=$1 m=$2 ctx=$3 k; shift 3
  [ -e "$MK/$n.done" ] && return 0
  for k in 1 2 3 4; do
    serve_run "$m" "$ctx" "$OUT/server_$n.log" "$@" >> "$OUT/$n.log" 2>&1 && { touch "$MK/$n.done"; status "gate: $n done ($(tail -n 1 "$OUT/$n.log" | cut -c1-120))"; return 0; }
    stopchk; status "gate: $n try $k failed: $(tail -n 1 "$OUT/$n.log" | cut -c1-160)"; [ "$DRYRUN" = 1 ] || sleep 120
  done
  die "gate: step $n failed 4 times ($OUT/$n.log)" 9
}
L=(); [ "$LIMIT" != 0 ] && L=(--limit "$LIMIT")
RF="python3 $P/run_ft.py"; CE=$H/post/chat_r3_eval.py; CV=$P/chat_v4_eval.py
SCORE_ARGS=(--out "$OUT" --res "$RES" --tag "$TAG" --base-run-tag "$BT" --p0-root "$OUT/p0" --gguf "$G"
  --chatdev-new "$CH/chatdev3_new.jsonl" --r3-new "$CH/chat_test_r3_new.jsonl"
  --t4-new "$RES/$TAG/test_r4.jsonl" --t4-base "$RES/$BT/test_r4.jsonl" --c4-new "$CH/chat_test_r4_new.jsonl" --c4-base "$CH/chat_test_r4_base.jsonl"
  --site-new "$CH/site_new.jsonl" --site-base "$CH/site_base.jsonl" --fog-new "$CH/fog_new.jsonl" --fog-base "$CH/fog_base.jsonl")
[ "$DRYRUN" = 1 ] && SCORE_ARGS+=(--min-cover 0)
score() {   # score <label> [--partial]: rc 0 pass/partial-ok, 1 FAIL, 2 incomplete
  python3 "$P/gate_score_ft.py" "${SCORE_ARGS[@]}" "${@:2}" > "$OUT/score_$1.log" 2>&1; local rc=$?
  status "gate: score $1 -> $(head -1 "$OUT/GATE_FT.md" 2>/dev/null | cut -c1-140) (rc $rc)"
  if [ $rc = 1 ] && [ "$EARLY_STOP" = 1 ] && [ "${2:-}" = "--partial" ]; then
    echo "$G" > "$OUT/gguf.txt"; md5_manifest "$OUT"
    status "gate: STRICT GATE FAIL at $1 ($OUT/GATE_FT.md); r3-2800 stays (EARLY_STOP=1)"; exit 1
  fi
  [ $rc -le 2 ] || die "gate: scorer error rc=$rc ($OUT/score_$1.log)" 2
  return $rc
}
TH="--think $GATE_THINK --tag $TAG --port $PORT --resdir $RES"
cd "$R1/eval"
# ---- 1. the 19 checks + P0 (+ RW6 info) for the candidate
step rep "$G" 8192 $RF $TH "${L[@]}" v3 --suites rwh,dev,rw6,p0 --p0-root "$OUT/p0"
step rwh2 "$G" 8192 $RF $TH "${L[@]}" suite --name rwh2 --file "$RWH2"
step dev3 "$G" 12288 $PY "$CE" --port $PORT --mode dev3 --think 1 --out "$CH/chatdev3_new.jsonl" "${L[@]}"
# ---- 2. v4 held-out tests, candidate
for s in test_campus_inc test_unseen_metric test_unseen_layout test_taxonomy test_real_agent; do
  step "v4inc_$s" "$G" 12288 $RF $TH "${L[@]}" v4 --name "$s" --file "$V4T/$s.jsonl" --tools "$TOOLS4"
done
step v4site "$G" 12288 $PY "$CV" --port $PORT --mode site --records "$V4T/test_campus_chat.jsonl" --tools "$TOOLS4" --think 1 --out "$CH/site_new.jsonl" "${L[@]}"
step v4fog "$G" 12288 $PY "$CV" --port $PORT --mode fog --records "$V4T/test_fog.jsonl" --tools "$TOOLS4" --think 1 --out "$CH/fog_new.jsonl" "${L[@]}"
score 1 --partial
step bsite "$G3" 12288 $PY "$CV" --port $PORT --mode site --records "$V4T/test_campus_chat.jsonl" --tools "$TOOLS4" --think 1 --out "$CH/site_base.jsonl" "${L[@]}"
# ---- 3. r4 tests, both models (r3-2800: incidents think 0 = its trained mode, chat adaptive, as gate_r4)
step t4new "$G" 12288 $RF $TH "${L[@]}" suite --name test_r4 --file "$T4I"
step t4base "$G3" 12288 $RF --think 0 --tag $BT --port $PORT --resdir "$RES" "${L[@]}" suite --name test_r4 --file "$T4I"
step c4new "$G" 12288 $PY "$CE" --port $PORT --mode r3test --think 1 --records "$T4C" --tools "$TOOLS_R4" --out "$CH/chat_test_r4_new.jsonl" "${L[@]}"
step c4base "$G3" 12288 $PY "$CE" --port $PORT --mode r3test --think 1 --records "$T4C" --tools "$TOOLS_R4" --out "$CH/chat_test_r4_base.jsonl" "${L[@]}"
score 2 --partial
# ---- 4. r3 test sets, candidate (r3-2800 cached in gate_r3 / eval/results/rsn_v3_4b_r3)
step r3new "$G" 12288 $PY "$CE" --port $PORT --mode r3test --think 1 --out "$CH/chat_test_r3_new.jsonl" "${L[@]}"
step t2new "$G" 8192 $RF $TH "${L[@]}" suite --name test_r2 --file "$T2"
score 3; rc=$?
echo "$G" > "$OUT/gguf.txt"; md5_manifest "$OUT"
case $rc in 0) status "gate: STRICT GATE PASS ($OUT/GATE_FT.md); r3-2800 reference runs on the v4 prompts follow";;
            1) status "gate: STRICT GATE FAIL ($OUT/GATE_FT.md); r3-2800 stays";;
            *) status "gate: scoring incomplete rc=$rc ($OUT/score_3.log)";; esac
# ---- 5. reference only: r3-2800 on the v4 prompts (never trained on them); the verdict above does not change
if [ "$BASE_V4" = 1 ]; then
  for s in test_campus_inc test_unseen_metric test_unseen_layout test_taxonomy test_real_agent; do
    step "bv4inc_$s" "$G3" 12288 $RF --think 0 --tag $BT --port $PORT --resdir "$RES" "${L[@]}" v4 --name "$s" --file "$V4T/$s.jsonl" --tools "$TOOLS4"
  done
  step bfog "$G3" 12288 $PY "$CV" --port $PORT --mode fog --records "$V4T/test_fog.jsonl" --tools "$TOOLS4" --think 1 --out "$CH/fog_base.jsonl" "${L[@]}"
  score final; rc=$?
  md5_manifest "$OUT"
  status "gate: final report with the r3-2800 v4 reference ($OUT/GATE_FT.md, rc $rc)"
fi
exit $rc
