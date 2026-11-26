#!/system/bin/sh
# lab_serve.sh: standalone htpd for a LAPTOP driver (board_drive.py over adb forward tcp:18091 -> 8091). Same stop / htpd / guards as setc_board.sh;
# instead of a request list it serves until $OUT/STOP (driver done), $W/lab/ABORT, htpd death or 10 h, then restarts the app. Owner 2026-11-26: app stopped for the window.
# App + htpd stopped (one NPU client), ONE standalone htpd with the live command line and profile env (v9h, agt3 agents, v5 reasoner,
# reason ctx 8192 x 3 streams), the Set C requests in order (per case: agents batches, then the reasoner request), then the app restarted.
# Live corpora are COPIED into the run dir, so harness outputs never reach the app's spec corpora.
# Guards: every case starts at <= 55 C; a watcher kills htpd at >= 105 C for 3 samples; $W/lab/ABORT stops the window and restarts the app.
# usage: setsid nohup sh lab_serve.sh <outdir> > /dev/null 2>&1 &
W=/data/local/tmp/rfast; B=/data/local/tmp/llama.cpp/bin; G=/data/local/tmp/gpu; S=/data/local/tmp/smart_city_edge
L=/data/local/tmp/llama.cpp/lib_rp29
OUT=$W/lab/$1; mkdir -p $OUT; LOG=$OUT/run.log; ABORT=$W/lab/ABORT
log() { echo "$(date +%T) $*" >> $LOG; }
tmax() { cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1 | awk '{print int($1/1000)}'; }
mavail() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
npu_others() { ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)"; }
ms() { n=$(date +%s%N); echo ${n%??????}; }
hp=""
( hot=0; while true; do t=$(tmax); echo "$(date +%T) t=$t avail=$(mavail)" >> $OUT/telemetry.log
    if [ "$t" -ge 105 ]; then hot=$((hot+1)); else hot=0; fi
    if [ $hot -ge 3 ]; then echo "$(date +%T) HEAT $t C for 3 samples: kill htpd" >> $LOG; for p in $(pidof htpd_v9h); do kill -TERM $p; done; fi
    sleep 2; done ) & TP=$!
finish() {
  log "finish ($1)"; trap '' HUP TERM
  [ -n "$hp" ] && kill -TERM $hp 2>/dev/null; for i in $(seq 1 90); do [ -n "$hp" ] && kill -0 $hp 2>/dev/null || break; sleep 1; done
  kill $TP 2>/dev/null
  i=0; while [ $i -lt 60 ] && ps -A -o NAME= | grep -qE "^htpd"; do sleep 1; i=$((i+1)); done
  sleep 5; log "restart app ($1)"; am start -n com.iiith.smartcityedge/.MainActivity >> $LOG 2>&1
  for i in $(seq 1 60); do sleep 5; tail -3 $S/state/htpd.log | grep -q "ready in" && break; done
  log "app htpd: $(pidof htpd_v9h) agent: $(pidof edge-agent)"; log "=== setc done ($1)"; echo done > $OUT/DONE; exit 0
}
cool() { while [ "$(tmax)" -gt 55 ]; do [ -e $ABORT ] && finish abort; sleep 10; done; }
log "=== setc start"
rm -f $ABORT
am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -TERM -f "[b]in/htpd"
for i in $(seq 1 120); do npu_others >/dev/null || break; sleep 1; done
sleep 30
npu_others && { log "ABORT: NPU client still running"; finish npu; }
cp $S/reason_corpus_live.jsonl $OUT/reason_corpus_live.jsonl; cp $S/agent_corpus.txt $OUT/agent_corpus.txt
cool
log "start htpd (avail $(mavail), t $(tmax))"
env HTPD_AGENT_MAX_NEW=240 HTPD_JSON_ABORT=1 HTPD_SYNTH_PREFIX_CACHE=1 GGML_HEXAGON_OPPOLL=1 HTPD_REASON_IDLE_MS=3000 \
  LD_LIBRARY_PATH=$L ADSP_LIBRARY_PATH=$L GGML_HEXAGON_REPACK_THREADS=8 GGML_HEXAGON_REPACK_STATS=1 HTPD_REASON_SPLIT_SPEC=8 \
  HTPD_REASON_SPEC_MIN=2 HTPD_REASON_SPEC_ALIGN=1 HTPD_REASON_CORPUS=$S/reason_corpus_v2.jsonl HTPD_REASON_CORPUS_LIVE=$OUT/reason_corpus_live.jsonl \
  HTPD_REASON_SPEC_KLONG=16 HTPD_REASON_SPEC_ROWS=48 HTPD_AGENT_NGMAX=8 HTPD_AGENT_RECENT_MAX=500 HTPD_AGENT_CORPUS=$OUT/agent_corpus.txt \
  HTPD_CHAT_SPEC=8 HTPD_CHAT_SPEC_MIN=4 HTPD_CHAT_CORPUS=$S/chat_corpus.jsonl HTPD_REASON_POOL=12544 HTPD_REASON_CHAIN=1 HTPD_REASON_DISK_KEEP=6 \
  $B/htpd_v9h -m $G/agt3_s0450_q4_0.gguf --agents 10 --agent-ctx 1280 --synth-ctx 4096 --ubatch 512 --ubatch-synth 512 --port 8091 \
  --reasoner-model $G/rsn_v3_4b_v5_q4_0.gguf --reason-streams 3 --reason-ctx 8192 > $OUT/htpd.log 2>&1 &
hp=$!
for i in $(seq 1 120); do grep -q "htpd: ready in" $OUT/htpd.log && break; kill -0 $hp 2>/dev/null || break; sleep 1; done
kill -0 $hp 2>/dev/null || { log "ABORT: htpd died at start"; hp=""; finish dead; }
echo ready > $OUT/READY; log "serving"
n=0
while [ ! -e $OUT/STOP ] && [ ! -e $ABORT ] && [ $n -lt 7200 ]; do
  kill -0 $hp 2>/dev/null || { log "ABORT: htpd died while serving"; hp=""; finish dead; }
  sleep 5; n=$((n+1))
done
[ -e $ABORT ] && finish abort
kill -TERM $hp; for i in $(seq 1 90); do kill -0 $hp 2>/dev/null || break; sleep 1; done; hp=""
log "htpd stopped: $(grep -E 'load phases|repack stats|swap' $OUT/htpd.log | tail -4 | tr '
' ' ')"
finish ok
