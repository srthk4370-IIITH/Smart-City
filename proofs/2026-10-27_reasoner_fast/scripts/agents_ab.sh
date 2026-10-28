#!/system/bin/sh
# Agents (B50, Llama) batch A/B: deployed htpd_v8x2 + libs vs upstream (htpd_new) vs upstream + 32x4 kernel (htpd_k4,
# HVX rows 4 and 8). Per config: standalone htpd (app stopped, one NPU client), warm-up, then agents10 x3 and agents4 x3.
W=/data/local/tmp/rfast; B=/data/local/tmp/llama.cpp/bin; OUT=$W/agab; mkdir -p $OUT; LOG=$OUT/ab.log
log() { echo "$(date +%T) $*" >> $LOG; }
tmax() { cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1 | awk '{print int($1/1000)}'; }
cool() { while [ "$(tmax)" -ge 60 ]; do sleep 15; done; }
npu_others() { ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)"; }
log "=== agents ab start"
am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -f "[b]in/htpd"
for i in $(seq 1 90); do npu_others >/dev/null || break; sleep 1; done; sleep 30
if npu_others; then log "ABORT: NPU client still running"; exit 3; fi
for cfg in "old,htpd_v8x2,/data/local/tmp/llama.cpp/lib,X=0" "new,htpd_new,/data/local/tmp/llama.cpp-new/lib,X=0" \
           "k4,htpd_k4,/data/local/tmp/llama.cpp-k4/lib,X=0" "k4r8,htpd_k4,/data/local/tmp/llama.cpp-k4/lib,GGML_HEXAGON_MM_HVX_ROWS=8"; do
  name=${cfg%%,*}; r=${cfg#*,}; bin=${r%%,*}; r=${r#*,}; lib=${r%%,*}; extra=${r#*,}
  cool; log "config $name"
  env LD_LIBRARY_PATH=$lib ADSP_LIBRARY_PATH=$lib GGML_HEXAGON_FA_STREAMS=1 HTPD_SPEC=0 GGML_HEXAGON_HMX_PIPE_ALL=1 HTPD_LEGACY_PREFILL=1 \
    HTPD_DRAFT=1 HTPD_DRAFT_K=8 HTPD_PREFIX_CACHE=1 HTPD_AGENT_MAX_NEW=160 HTPD_JSON_ABORT=2 HTPD_SYNTH_PREFIX_CACHE=1 GGML_HEXAGON_OPPOLL=1 $extra \
    $B/$bin -m /data/local/tmp/gpu/ft_B50_q4_0.gguf --agents 10 --agent-ctx 1280 --synth-ctx 4096 --ubatch 512 --ubatch-synth 512 --port 8091 \
    > $OUT/htpd_$name.log 2>&1 &
  hp=$!
  for i in $(seq 1 120); do grep -q "htpd: ready in" $OUT/htpd_$name.log && break; kill -0 $hp 2>/dev/null || break; sleep 1; done
  kill -0 $hp 2>/dev/null || { log "  $name died at start"; continue; }
  k=0
  for q in agents4 agents10 agents10 agents10 agents4 agents4; do
    cool; nc -q 300 -W 300 127.0.0.1 8091 < $W/$q.json > $OUT/${name}_${q}_$k.json
    log "  $name $q#$k $(grep -o '"total_ms":[0-9.]*' $OUT/${name}_${q}_$k.json | tail -1) temp $(tmax)"; k=$((k+1))
  done
  kill $hp; for i in $(seq 1 90); do kill -0 $hp 2>/dev/null || break; sleep 1; done; sleep 30
done
log "restart app"; am start -n com.iiith.smartcityedge/.MainActivity >> $LOG 2>&1; log "=== agents ab done"
