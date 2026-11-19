#!/usr/bin/env bash
# gate_4b.sh <gguf>: host-GPU gate of the 4B r3 Q4_0 (host llama-server CUDA b11815 = board numerics) vs rsn_v1 (ft612).
# Called by post_chain.sh after the export. One GPU job: waits until the GPU is idle (< 800 MiB used, no trainer /
# llama-server, no PAUSE_GPU, GPU_LOCK free) and holds GPU_LOCK ("post_4b ...") for the whole gate. One llama-server at a
# time; watchdog SIGSTOPs it at >= HEAT_HI C (92) or Windows available < 1200 MB and resumes at <= HEAT_LO (88) and
# >= 1800 MB; run_v3.py's own gpu_cool gets the same 92/88. Every step has a marker (post/gate_r3/.m/<step>.done) and its
# result file is resumable, so a re-run continues where it stopped. Steps (gate inputs first, informational last):
#   rep      RWH 150 + round-1 dev 120 + P0 (eval/run_v3.py, round-1 incident prompt, ctx 8192 as eval_gguf.sh)
#   rwh2     RWH-2 150 (run_suite.py); rsn_v1's RWH-2 is cached under eval/results/ft612 (run if incomplete)
#   dev3     chat dev v3 (300) with the r3 app prompt, adaptive think (chat_r3_eval.py --mode dev3), ctx 12288
#   score1   gate_score_4b.py -> GATE.md / gate.json (the verdict; informational sections "not run yet")
#   r3new    chat_test_r3 (983) for the 4B, adaptive think;  r3v1: the same for rsn_v1 with the r3 prompt, empty think (OOD)
#   t2new    incidents_test_r2 (1,368) for the 4B;           t2v1: rsn_v1 (cached under eval/results/ft612/test_r2.jsonl)
#   score2   rescore with everything -> GATE.md / gate.json; MD5SUMS
# exit: 0 PASS, 1 FAIL, 2 incomplete, other = error. Never touches the board.
SCRIPT=${SCRIPT:-post_4b}; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
STATUS=${POST_STATUS:-$STATUS}   # tests write their status lines elsewhere
G=${1:?gguf}; H=$QIDK/proofs/2026-11-06_4b_local; P=$H/post
OUT=${GATE_OUT:-$P/gate_r3}; MK=$OUT/.m; mkdir -p "$MK"
TAG=${GATE_TAG:-rsn_v3_4b_r3}; BASE_TAG=ft612
V1=$QIDK/Code/models_stage/rsn_v1_q4_0.gguf
RWH2=$KG/build/r1/heldout/incidents_rwh2.jsonl
DEV3=$V3/data/chat3_dev.jsonl
CB=$KG/gate/rsn_v1_chatdev3_$(md5sum < "$DEV3" | cut -c1-12).jsonl
T3=$H/data/final/chat_test_r3.jsonl; T2=$H/data/final/incidents_test_r2.jsonl
PY=~/venvs/rsn/bin/python; LC=~/llama-cuda-b11815; PORT=18098
LOCK=$V3/GPU_LOCK; PAUSE=$R1/PAUSE_GPU; STOPF=${STOPF:-$P/STOP}
export HEAT_HI=${HEAT_HI:-92} HEAT_LO=${HEAT_LO:-88} HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RAM_LO=500; RAM_OK=700   # 2026-11-09: WSL capped at 6 GB, owner keeps Chrome + VS Code open
for f in "$G" "$V1" "$RWH2" "$DEV3" "$CB" "$T3" "$T2"; do [ -s "$f" ] || die "gate: missing $f" 2; done
for g in "$G" "$V1"; do [ -s "$g.md5" ] && { (cd "$(dirname "$g")" && md5sum -c --quiet "$(basename "$g").md5") || die "gate: md5 mismatch $g" 2; }; done

gtemp() { nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9; }
gmem() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9; }
mine() { [ -e "$LOCK" ] && grep -q "^post_4b " "$LOCK"; }
gpu_idle() { [ ! -e "$PAUSE" ] && { [ ! -e "$LOCK" ] || mine; } && [ "$(gmem)" -lt 800 ] 2>/dev/null \
  && ! pgrep -f "[t]rain_3e.py|[t]rain_rsn|[l]lama-server" > /dev/null; }
stopchk() { [ -e "$STOPF" ] && { status "gate: STOP file (resumes at the next launch)"; exit 3; }; }
wait_gpu() { local t=0; until gpu_idle; do stopchk
    [ $((t % 60)) = 0 ] && status "gate: waiting for an idle GPU (lock: $(head -c 80 "$LOCK" 2>/dev/null || echo none), $(gmem) MiB used)"
    sleep 60; t=$((t + 1)); done; }
wait_gpu
echo "post_4b gate $(date -Is) pid=$$" > "$LOCK"
trap 'mine && rm -f "$LOCK"' EXIT
need_ram 1536 600
status "gate: start $G vs rsn_v1 ($BASE_TAG, $V1) -> $OUT"

serve_run() {   # serve_run <gguf> <ctx> <log> <cmd...>: one llama-server + watchdog, the command, then stop the server
  local m=$1 ctx=$2 lg=$3; shift 3
  stopchk
  until [ ! -e "$PAUSE" ] && [ "$(gmem)" -lt 800 ] 2>/dev/null && ! pgrep -f "[l]lama-server|[t]rain_rsn" > /dev/null; do stopchk; sleep 60; done
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
step() {   # step <name> <gguf> <ctx> <cmd...>: marker-guarded, up to 4 tries (a paused server can time a client out)
  local n=$1 m=$2 ctx=$3 k; shift 3
  [ -e "$MK/$n.done" ] && return 0
  for k in 1 2 3 4; do
    serve_run "$m" "$ctx" "$OUT/server_$n.log" "$@" >> "$OUT/$n.log" 2>&1 && { touch "$MK/$n.done"; status "gate: $n done ($(tail -n 1 "$OUT/$n.log" | cut -c1-120))"; return 0; }
    stopchk; status "gate: $n try $k failed: $(tail -n 1 "$OUT/$n.log" | cut -c1-160)"; sleep 120
  done
  die "gate: step $n failed 4 times ($OUT/$n.log)" 9
}
score() {   # score <tag>: gate_score_4b.py with whatever exists
  (cd "$R1/eval" && python3 p0_score.py "$TAG" "$BASE_TAG" 2>&1 | tail -2) > "$OUT/p0.txt"
  python3 "$P/gate_score_4b.py" --new "$TAG" --base "$BASE_TAG" --chat-new "$OUT/chatdev3_r3.jsonl" --chat-base "$CB" --out "$OUT" \
    --rwh2 "$RWH2" --r3-new "$OUT/chat_test_r3_4b.jsonl" --r3-base "$OUT/chat_test_r3_v1.jsonl" --test-r2 "$T2" --p0 "$OUT/p0.txt" \
    > "$OUT/gate_score_$1.log" 2>&1
}
cd "$R1/eval"
step rep "$G" 8192 python3 run_v3.py --tag "$TAG" --port $PORT --suites rwh,dev,p0
step rwh2 "$G" 8192 python3 "$KG/local/run_suite.py" --tag "$TAG" --port $PORT --suite rwh2 --file "$RWH2"
if [ "$(wc -l < "$R1/eval/results/$BASE_TAG/rwh2.jsonl" 2>/dev/null || echo 0)" -lt "$(wc -l < "$RWH2")" ]; then
  step rwh2_v1 "$V1" 8192 python3 "$KG/local/run_suite.py" --tag "$BASE_TAG" --port $PORT --suite rwh2 --file "$RWH2"
fi
step dev3 "$G" 12288 $PY "$P/chat_r3_eval.py" --port $PORT --mode dev3 --think 1 --out "$OUT/chatdev3_r3.jsonl"
score 1; rc=$?
case $rc in 0) status "gate: GATE PASS on the gate inputs ($OUT/GATE.md); informational tests follow";;
            1) status "gate: GATE FAIL on the gate inputs ($OUT/GATE.md); informational tests follow";;
            *) die "gate: scoring incomplete rc=$rc ($OUT/gate_score_1.log)" 2;; esac
step r3new "$G" 12288 $PY "$P/chat_r3_eval.py" --port $PORT --mode r3test --think 1 --out "$OUT/chat_test_r3_4b.jsonl"
step r3v1 "$V1" 12288 $PY "$P/chat_r3_eval.py" --port $PORT --mode r3test --think 0 --out "$OUT/chat_test_r3_v1.jsonl"
step t2new "$G" 8192 python3 "$KG/local/run_suite.py" --tag "$TAG" --port $PORT --suite test_r2 --file "$T2"
step t2v1 "$V1" 8192 python3 "$KG/local/run_suite.py" --tag "$BASE_TAG" --port $PORT --suite test_r2 --file "$T2"
score 2; rc=$?
echo "$G" > "$OUT/gguf.txt"
md5_manifest "$OUT"
case $rc in 0) status "gate: final GATE PASS ($OUT/GATE.md)";; 1) status "gate: final GATE FAIL ($OUT/GATE.md)";;
            *) status "gate: final scoring incomplete rc=$rc ($OUT/gate_score_2.log)";; esac
exit $rc
