#!/usr/bin/env bash
# gate_r4.sh <r4 gguf>: STRICT host-GPU gate of the r4 top-up vs r3 step 2800 (rsn_v3_4b_r3_q4_0.gguf, its cached gate_r3 results).
# Same machinery as 2026-11-06_4b_local/post/gate_4b.sh (which stays unchanged): waits for an idle GPU, holds GPU_LOCK
# ("post_r4 ..."), one llama-server at a time, watchdog SIGSTOP at >= 92 C or Windows available < 500 MB (resume <= 88 C,
# >= 700 MB), marker per step (gate_r4/.m), resumable result files. Order = cheapest decisive first:
#   t4new / t4base  r4 held-out test incidents: r4 (think GATE_THINK=1, = app reasoner_think=adaptive) and r3-2800 (think off,
#                   its trained mode); c4new / c4base: r4 test chat records (adaptive think, both) when TEST4_CHAT exists
#   scoreA          gate_score_r4.py --stage a: (a) fails -> FAIL now (nothing else runs; r3-2800 stays)
#   rep rwh2 dev3   the 19 gate inputs for r4 (r3-2800: cached under eval/results/rsn_v3_4b_r3 + post/gate_r3/chatdev3_r3.jsonl)
#   r3new           chat_test_r3 (983) for r4 (r3-2800: post/gate_r3/chat_test_r3_4b.jsonl)
#   score           final verdict -> GATE_r4.md, gate.json, MD5SUMS
# exit: 0 PASS, 1 FAIL, 2 incomplete, 3 STOP, other = error. Never touches the board.
SCRIPT=${SCRIPT:-post_r4}; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
STATUS=${POST_STATUS:-$STATUS}
G=${1:?gguf}; T4=$QIDK/proofs/2026-11-12_topup_r4/train; P=$T4/post; H=$QIDK/proofs/2026-11-06_4b_local
source "$T4/paths_r4.sh"
OUT=${GATE_OUT:-$P/gate_r4}; MK=$OUT/.m; mkdir -p "$MK"
TAG=${GATE_TAG:-rsn_v3_4b_r4}; BASE_TAG=rsn_v3_4b_r3; T4BASE_TAG=r3s2800_r4test; GATE_THINK=${GATE_THINK:-1}
G3=$QIDK/Code/models_stage/rsn_v3_4b_r3_q4_0.gguf
RWH2=$KG/build/r1/heldout/incidents_rwh2.jsonl
CB=$H/post/gate_r3/chatdev3_r3.jsonl; R3B=$H/post/gate_r3/chat_test_r3_4b.jsonl
PY=~/venvs/rsn/bin/python; LC=~/llama-cuda-b11815; PORT=18099
LOCK=$V3/GPU_LOCK; PAUSE=$R1/PAUSE_GPU; STOPF=${STOPF:-$P/STOP}
export HEAT_HI=${HEAT_HI:-92} HEAT_LO=${HEAT_LO:-88} HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RAM_LO=500; RAM_OK=700
[ "$G" != "$G3" ] || die "gate: the candidate is the r3 GGUF itself" 2
for f in "$G" "$G3" "$RWH2" "$CB" "$R3B" "$TEST4_INC"; do [ -s "$f" ] || die "gate: missing ${f:-TEST4_INC (paths_r4.sh)}" 2; done
for g in "$G" "$G3"; do [ -s "$g.md5" ] && { (cd "$(dirname "$g")" && md5sum -c --quiet "$(basename "$g").md5") || die "gate: md5 mismatch $g" 2; }; done

gtemp() { nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9; }
gmem() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9; }
mine() { [ -e "$LOCK" ] && grep -q "^post_r4 " "$LOCK"; }
busy_gpu() { pgrep -f "[t]rain_3e.py|[t]rain_rsn|[t]opup_train.py|[c]ont_train.py|[l]lama-server" > /dev/null; }
gpu_idle() { [ ! -e "$PAUSE" ] && { [ ! -e "$LOCK" ] || mine; } && [ "$(gmem)" -lt 800 ] 2>/dev/null && ! busy_gpu; }
stopchk() { [ -e "$STOPF" ] && { status "gate: STOP file (resumes at the next launch)"; exit 3; }; }
t=0; until gpu_idle; do stopchk
  [ $((t % 60)) = 0 ] && status "gate: waiting for an idle GPU (lock: $(head -c 80 "$LOCK" 2>/dev/null || echo none), $(gmem) MiB used)"
  sleep 60; t=$((t + 1)); done
echo "post_r4 gate $(date -Is) pid=$$" > "$LOCK"
trap 'mine && rm -f "$LOCK"' EXIT
need_ram 1536 600
status "gate: start $G vs r3-2800 ($G3) -> $OUT"

serve_run() {   # serve_run <gguf> <ctx> <log> <cmd...>
  local m=$1 ctx=$2 lg=$3; shift 3
  stopchk
  until [ ! -e "$PAUSE" ] && [ "$(gmem)" -lt 800 ] 2>/dev/null && ! busy_gpu; do stopchk; sleep 60; done
  LD_LIBRARY_PATH=$LC/bin nice -n 10 $LC/bin/llama-server -m "$m" -ngl 99 -cram 256 -c "$ctx" -np 1 --jinja -t 2 -tb 2 \
    --host 127.0.0.1 --port $PORT --no-webui > "$lg" 2>&1 &
  local sp=$!
  ( hot=0; while sleep 20; do kill -0 $sp 2>/dev/null || exit 0
      if [ -e "$PAUSE" ] || [ -e "$STOPF" ]; then kill -CONT $sp; kill $sp; exit 0; fi
      t=$(gtemp); f=$(free_mb)
      if { [ -n "$t" ] && [ "$t" -ge "$HEAT_HI" ]; } || { [ -n "$f" ] && [ "$f" -lt $RAM_LO ]; }; then
        [ $hot = 0 ] && echo "$(date +%T) pause gpu=${t}C avail=${f}MB" >> "$OUT/watchdog.log"; hot=1; fi
      [ $hot = 1 ] && kill -STOP $sp
      if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le "$HEAT_LO" ] && { [ -z "$f" ] || [ "$f" -ge $RAM_OK ]; }; then
        kill -CONT $sp; hot=0; echo "$(date +%T) resume gpu=${t}C avail=${f}MB" >> "$OUT/watchdog.log"; fi
    done ) &
  local wd=$! ok=0
  for i in $(seq 1 120); do sleep 2; curl -s localhost:$PORT/health | grep -q ok && { ok=1; break; }; done
  local rc=1
  if [ $ok = 1 ]; then nice -n 5 "$@"; rc=$?; else echo "llama-server did not come up: $(tail -n 3 "$lg")"; fi
  kill $wd 2>/dev/null; kill -CONT $sp 2>/dev/null; kill $sp 2>/dev/null; wait $sp 2>/dev/null
  return $rc
}
step() {   # step <name> <gguf> <ctx> <cmd...>
  local n=$1 m=$2 ctx=$3 k; shift 3
  [ -e "$MK/$n.done" ] && return 0
  for k in 1 2 3 4; do
    serve_run "$m" "$ctx" "$OUT/server_$n.log" "$@" >> "$OUT/$n.log" 2>&1 && { touch "$MK/$n.done"; status "gate: $n done ($(tail -n 1 "$OUT/$n.log" | cut -c1-120))"; return 0; }
    stopchk; status "gate: $n try $k failed: $(tail -n 1 "$OUT/$n.log" | cut -c1-160)"; sleep 120
  done
  die "gate: step $n failed 4 times ($OUT/$n.log)" 9
}
RES=$R1/eval/results
SCORE_ARGS="--out $OUT --new $TAG --base $BASE_TAG --test4-inc $TEST4_INC --t4-new $RES/$TAG/test_r4.jsonl --t4-base $RES/$T4BASE_TAG/test_r4.jsonl"
cd "$R1/eval"
RT=$P/run_think.py; CE=$H/post/chat_r3_eval.py
step t4new "$G" 12288 python3 "$RT" --think "$GATE_THINK" suite --tag "$TAG" --port $PORT --suite test_r4 --file "$TEST4_INC"
step t4base "$G3" 12288 python3 "$RT" --think 0 suite --tag "$T4BASE_TAG" --port $PORT --suite test_r4 --file "$TEST4_INC"
if [ -s "${TEST4_CHAT:-}" ]; then
  step c4new "$G" 12288 $PY "$CE" --port $PORT --mode r3test --think 1 --records "$TEST4_CHAT" --tools "$TOOLS4" --out "$OUT/chat_test_r4_new.jsonl"
  step c4base "$G3" 12288 $PY "$CE" --port $PORT --mode r3test --think 1 --records "$TEST4_CHAT" --tools "$TOOLS4" --out "$OUT/chat_test_r4_base.jsonl"
  SCORE_ARGS="$SCORE_ARGS --c4-new $OUT/chat_test_r4_new.jsonl --c4-base $OUT/chat_test_r4_base.jsonl"
fi
python3 "$P/gate_score_r4.py" --stage a $SCORE_ARGS > "$OUT/score_a.log" 2>&1; rc=$?
case $rc in
  0) status "gate: (a) r4 test PASS ($(head -1 "$OUT/GATE_r4.md" | cut -c1-120)); 19 checks + fog slices follow";;
  1) md5_manifest "$OUT"; status "gate: FAIL at (a): r4 does not beat r3-2800 on the r4 test ($OUT/GATE_r4.md); r3-2800 stays"; exit 1;;
  *) die "gate: (a) scoring incomplete rc=$rc ($OUT/score_a.log)" 2;;
esac
step rep "$G" 8192 python3 "$RT" --think "$GATE_THINK" v3 --tag "$TAG" --port $PORT --suites rwh,dev
step rwh2 "$G" 8192 python3 "$RT" --think "$GATE_THINK" suite --tag "$TAG" --port $PORT --suite rwh2 --file "$RWH2"
step dev3 "$G" 12288 $PY "$CE" --port $PORT --mode dev3 --think 1 --out "$OUT/chatdev3_r4.jsonl"
step r3new "$G" 12288 $PY "$CE" --port $PORT --mode r3test --think 1 --out "$OUT/chat_test_r3_r4.jsonl"
python3 "$P/gate_score_r4.py" --stage final $SCORE_ARGS --rwh2 "$RWH2" --chatdev-new "$OUT/chatdev3_r4.jsonl" --chatdev-base "$CB" \
  --r3-new "$OUT/chat_test_r3_r4.jsonl" --r3-base "$R3B" > "$OUT/score_final.log" 2>&1; rc=$?
echo "$G" > "$OUT/gguf.txt"
md5_manifest "$OUT"
case $rc in 0) status "gate: final STRICT GATE PASS ($OUT/GATE_r4.md)";; 1) status "gate: final STRICT GATE FAIL ($OUT/GATE_r4.md); r3-2800 stays";;
            *) status "gate: final scoring incomplete rc=$rc ($OUT/score_final.log)";; esac
exit $rc
