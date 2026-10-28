#!/system/bin/sh
# Self-contained htpd A/B on the board: each config = one standalone htpd (app stopped), the same command line as the
# app's supervisor, env from the profile + the config's extra env. Per config: agents request (v7 regression), the
# reason requests (warm-up first), agents request again, release, stop (SIGTERM while idle, wait exit + 30 s).
# usage: setsid nohup sh ab_board.sh "name,binary,model|-,extra env" ... (mksh: "|" is a pattern operator) ; REQS="0 0 1 2" (first = warm-up)
W=/data/local/tmp/rfast
B=/data/local/tmp/llama.cpp/bin
OUT=$W/ab; mkdir -p $OUT
LOG=$OUT/ab.log
log() { echo "$(date +%T) $*" >> $LOG; }
tmax() { cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1 | awk '{print int($1/1000)}'; }
cool() { while [ "$(tmax)" -ge ${1:-70} ]; do sleep 15; done; }
mavail() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
npu_others() { ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)"; }
( while true; do echo "$(date +%T) up=$(cut -d' ' -f1 /proc/uptime) t=$(tmax) avail=$(mavail) $(ps -A -o NAME= | grep -E '^(llama|htpd)' | tr '\n' ' ')" >> $OUT/telemetry.log; sleep 2; done ) & TP=$!
trap 'kill $TP 2>/dev/null' EXIT
REQS=${REQS:-"0 0 1 2 3 4 5"}
log "=== ab start: $*"
while [ "$(getprop sys.boot_completed)" != 1 ] || [ "$(cut -d. -f1 /proc/uptime)" -lt 240 ]; do sleep 15; done
am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -f "[b]in/htpd"
for i in $(seq 1 90); do npu_others >/dev/null || break; sleep 1; done
sleep 30
if npu_others; then log "ABORT: NPU client still running"; exit 3; fi
head -1 /data/local/tmp/smart_city_edge/htpd_warmup.jsonl > $W/agents_req.json
[ $# -eq 0 ] && set -- $AB_CFGS
for cfg in "$@"; do
  name=${cfg%%,*}; rest=${cfg#*,}; bin=${rest%%,*}; rest=${rest#*,}; rm=${rest%%,*}; extra=${rest#*,}
  [ "$rm" = "-" ] && rm=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf
  LIBD=/data/local/tmp/llama.cpp/lib; case $bin in htpd_new*) LIBD=/data/local/tmp/llama.cpp-new/lib;; htpd_k4*) LIBD=/data/local/tmp/llama.cpp-k4/lib;; esac
  RS=1; RQ=rreq; RCX=""; case $name in sp2*) RS=2; RQ=rreq_split2;; sp4*) RS=4; RQ=rreq_split4;; sp6*) RS=6; RQ=rreq_split6;; sp*) RS=3; RQ=rreq_split;; esac  # split configs: 3 reason streams + split requests
  cool 60
  log "config $name: $bin model $rm env [$extra] (MemAvailable $(mavail) MB)"
  env LD_LIBRARY_PATH=$LIBD ADSP_LIBRARY_PATH=$LIBD GGML_HEXAGON_FA_STREAMS=1 HTPD_SPEC=0 \
    GGML_HEXAGON_HMX_PIPE_ALL=1 HTPD_LEGACY_PREFILL=1 HTPD_DRAFT=1 HTPD_DRAFT_K=8 HTPD_PREFIX_CACHE=1 HTPD_AGENT_MAX_NEW=160 \
    HTPD_JSON_ABORT=2 HTPD_SYNTH_PREFIX_CACHE=1 HTPD_REASON_IDLE_MS=600000 $extra \
    $B/$bin -m ${AGM:-/data/local/tmp/gpu/ft_B50_q4_0.gguf} --agents 10 --agent-ctx 1280 --synth-ctx 4096 --ubatch 512 --ubatch-synth 512 \
    --port 8091 --reasoner-model $rm --reason-streams $RS $RCX > $OUT/htpd_$name.log 2>&1 &
  hp=$!
  for i in $(seq 1 120); do grep -q "htpd: ready in" $OUT/htpd_$name.log && break; kill -0 $hp 2>/dev/null || break; sleep 1; done
  if ! kill -0 $hp 2>/dev/null; then log "  htpd $name died at start"; continue; fi
  nc -q 300 -W 300 127.0.0.1 8091 < $W/agents_req.json > $OUT/${name}_agents0.json
  k=0
  for r in $REQS; do
    cool 60
    nc -q 900 -W 900 127.0.0.1 8091 < $W/$RQ/q$r.json > $OUT/${name}_q${r}_$k.json
    log "  $name q$r#$k: $(grep -o '"total_ms":[0-9.]*' $OUT/${name}_q${r}_$k.json) $(grep -o '"stop":"[a-z]*"' $OUT/${name}_q${r}_$k.json) temp $(tmax) avail $(mavail)"
    k=$((k+1))
    kill -0 $hp 2>/dev/null || { log "  htpd $name died on q$r"; break; }
  done
  kill -0 $hp 2>/dev/null && nc -q 300 -W 300 127.0.0.1 8091 < $W/agents_req.json > $OUT/${name}_agents1.json
  kill $hp 2>/dev/null; for i in $(seq 1 90); do kill -0 $hp 2>/dev/null || break; sleep 1; done
  log "  $name stopped; $(grep -E 'reason spec|reason stream|reasoner loaded' $OUT/htpd_$name.log | tail -3 | tr '\n' ' ')"
  sleep 30
done
log "restart app"
am start -n com.iiith.smartcityedge/.MainActivity >> $LOG 2>&1
log "=== ab done"
