#!/system/bin/sh
# Guarded board retry of the pruned lm_head (owner-approved 2026-10-28). Board side, self-contained.
# Phase 1 (probe): pruned head (htpd_v8p2 + libllama_p + rsn_v1_q4_0_keep.gguf), split-3 + OPPOLL, prompts q0-q2.
#   Any anomaly (htpd death, MemAvailable < 1 GB, bad/missing response) aborts the whole run. The 02:11 reboot is
#   detected on the host side (uptime reset).
# Phase 2: 10 prompts, full head (htpd_v8x2, rsn_v1_q4_0.gguf) vs pruned head, both split-3 + OPPOLL.
# Every request starts at <= 60 C. One NPU client: app stopped, wait for exit + 30 s. App restarted at the end.
W=/data/local/tmp/rfast; B=/data/local/tmp/llama.cpp/bin; G=/data/local/tmp/gpu; OUT=$W/prab; mkdir -p $OUT; LOG=$OUT/ab.log
log() { echo "$(date +%T) $*" >> $LOG; }
tmax() { cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1 | awk '{print int($1/1000)}'; }
cool() { while [ "$(tmax)" -ge 60 ]; do sleep 15; done; }
mavail() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
npu_others() { ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)"; }
( while true; do echo "$(date +%T) up=$(cut -d' ' -f1 /proc/uptime) t=$(tmax) avail=$(mavail) $(ps -A -o NAME= | grep -E '^htpd' | tr '\n' ' ')" >> $OUT/telemetry.log; sync; sleep 2; done ) & TP=$!
finish() { kill $TP 2>/dev/null; log "restart app"; am start -n com.iiith.smartcityedge/.MainActivity >> $LOG 2>&1; log "=== pruned ab done ($1)"; exit 0; }
log "=== pruned ab start (uptime $(cut -d' ' -f1 /proc/uptime))"
for f in $B/htpd_v8p2 $B/htpd_v8x2 /data/local/tmp/llama.cpp/lib/libllama_p.so $G/rsn_v1_q4_0_keep.gguf $G/qwen35_reasoner_q4_0.gguf; do
  [ -s $f ] || { log "ABORT: missing $f"; finish missing; }; done
[ "$(stat -c %s $G/rsn_v1_q4_0_keep.gguf)" = 2680929472 ] || { log "ABORT: keep gguf size"; finish size; }
am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -f "[b]in/htpd"
for i in $(seq 1 90); do npu_others >/dev/null || break; sleep 1; done; sleep 30
npu_others && { log "ABORT: NPU client still running"; finish npu; }
run_cfg() {  # name bin model reqs...
  name=$1; bin=$2; m=$3; shift 3
  cool; log "config $name: $bin $m (avail $(mavail))"
  env LD_LIBRARY_PATH=/data/local/tmp/llama.cpp/lib ADSP_LIBRARY_PATH=/data/local/tmp/llama.cpp/lib GGML_HEXAGON_FA_STREAMS=1 HTPD_SPEC=0 \
    GGML_HEXAGON_HMX_PIPE_ALL=1 HTPD_LEGACY_PREFILL=1 HTPD_DRAFT=1 HTPD_DRAFT_K=8 HTPD_PREFIX_CACHE=1 HTPD_AGENT_MAX_NEW=160 \
    HTPD_JSON_ABORT=2 HTPD_SYNTH_PREFIX_CACHE=1 HTPD_REASON_IDLE_MS=600000 GGML_HEXAGON_OPPOLL=1 \
    $B/$bin -m $G/ft_B50_q4_0.gguf --agents 10 --agent-ctx 1280 --synth-ctx 4096 --ubatch 512 --ubatch-synth 512 \
    --port 8091 --reasoner-model $m --reason-streams 3 > $OUT/htpd_$name.log 2>&1 &
  hp=$!
  for i in $(seq 1 120); do grep -q "htpd: ready in" $OUT/htpd_$name.log && break; kill -0 $hp 2>/dev/null || break; sleep 1; done
  kill -0 $hp 2>/dev/null || { log "ABORT: htpd $name died at start"; return 1; }
  k=0
  for r in "$@"; do
    cool
    [ "$(mavail)" -lt 1024 ] && { log "ABORT: MemAvailable $(mavail) MB before q$r"; kill $hp; return 1; }
    nc -q 900 -W 900 127.0.0.1 8091 < $W/rreq_split/q$r.json > $OUT/${name}_q${r}_$k.json
    t=$(grep -o '"total_ms":[0-9.]*' $OUT/${name}_q${r}_$k.json | tail -1); s=$(grep -o '"stop":"[a-z]*"' $OUT/${name}_q${r}_$k.json | tail -1)
    log "  $name q$r#$k: $t $s temp $(tmax) avail $(mavail)"
    kill -0 $hp 2>/dev/null || { log "ABORT: htpd $name died on q$r"; return 1; }
    [ -n "$t" ] && [ "$s" = '"stop":"json"' ] || { log "ABORT: bad response $name q$r"; kill $hp; return 1; }
    [ "$(mavail)" -lt 1024 ] && { log "ABORT: MemAvailable $(mavail) MB after q$r"; kill $hp; return 1; }
    k=$((k+1))
  done
  kill $hp; for i in $(seq 1 90); do kill -0 $hp 2>/dev/null || break; sleep 1; done
  log "  $name stopped: $(grep -E 'pruned lm_head|split answer' $OUT/htpd_$name.log | tail -2 | tr '\n' ' ')"; sleep 30
  return 0
}
run_cfg probe htpd_v8p2 $G/rsn_v1_q4_0_keep.gguf 0 0 1 2 || finish abort-probe
log "probe passed"
run_cfg full htpd_v8x2 $G/qwen35_reasoner_q4_0.gguf 0 0 1 2 3 4 5 6 7 8 9 || finish abort-full
run_cfg pruned htpd_v8p2 $G/rsn_v1_q4_0_keep.gguf 0 0 1 2 3 4 5 6 7 8 9 || finish abort-pruned
finish ok
