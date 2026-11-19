#!/system/bin/sh
# Lab A/B on the board (owner 2026-10-29 afternoon: short windows, real app back after each, abort for a demo).
# One window = the configs given, each one standalone htpd (app stopped; one NPU client), then the app is restarted.
# usage: setsid nohup sh lab_ab.sh <outdir> "name,binary,model,extra env" ... ; REQS="10 10 11 12 13 14 15" (first = warm-up)
# extra env may override LD_LIBRARY_PATH/ADSP_LIBRARY_PATH (later env assignments win) to test a lib dir; "a" in REQS = agents request (swap sample)
# Guards: every request starts at <= 55 C; a watcher kills htpd at >= 105 C sustained (owner 2026-10-29; normal runs reach 94-97 C, NSP throttle 100, shutdown trip 115) 3 samples (~6 s); $W/lab/ABORT (written by the laptop driver
# when proofs/2026-10-29_latency/DEMO_NOW exists) stops the window and restarts the app at once.
W=/data/local/tmp/rfast; B=/data/local/tmp/llama.cpp/bin; L=/data/local/tmp/llama.cpp/lib; G=/data/local/tmp/gpu
OUT=$W/lab/$1; shift; mkdir -p $OUT; LOG=$OUT/ab.log; ABORT=$W/lab/ABORT
log() { echo "$(date +%T) $*" >> $LOG; }
tmax() { cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1 | awk '{print int($1/1000)}'; }
mavail() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
npu_others() { ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)"; }
hp=""
( hot=0; while true; do t=$(tmax); echo "$(date +%T) t=$t avail=$(mavail) $(ps -A -o NAME= | grep -E '^htpd' | tr '\n' ' ')" >> $OUT/telemetry.log
    if [ "$t" -ge 105 ]; then hot=$((hot+1)); else hot=0; fi  # sustained only: model load gives a 1-sample CPU spike
    if [ $hot -ge 3 ]; then echo "$(date +%T) HEAT $t C for 3 samples: kill htpd" >> $LOG; for p in $(pidof htpd_v8x5 htpd_v8x5p htpd_v8x3 htpd_v9 htpd_v9b htpd_v9c htpd_v9d htpd_v9e htpd_v9f); do kill -TERM $p; done; fi
    sleep 2; done ) & TP=$!
finish() {
  log "finish ($1)"; trap '' HUP TERM
  [ -n "$hp" ] && kill -TERM $hp 2>/dev/null; for i in $(seq 1 90); do [ -n "$hp" ] && kill -0 $hp 2>/dev/null || break; sleep 1; done
  kill $TP 2>/dev/null
  i=0; while [ $i -lt 60 ] && ps -A -o NAME= | grep -qE "^htpd"; do sleep 1; i=$((i+1)); done
  sleep 5; log "restart app ($1)"; am start -n com.iiith.smartcityedge/.MainActivity >> $LOG 2>&1; log "=== lab ab done ($1)"; exit 0
}
cool() { while [ "$(tmax)" -gt 55 ]; do [ -e $ABORT ] && finish abort; sleep 10; done; }
log "=== lab ab start: $*"
rm -f $ABORT
am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x5 htpd_v8x5p htpd_v8x3 htpd_v8x4 htpd_v9 htpd_v9b htpd_v9c htpd_v9d htpd_v9e htpd_v9f htpd); do kill -TERM $p; done
for i in $(seq 1 120); do npu_others >/dev/null || break; sleep 1; done
sleep 30
npu_others && { log "ABORT: NPU client still running"; finish npu; }
REQS=${REQS:-"10 10 11 12 13 14 15"}
for cfg in "$@"; do
  name=${cfg%%,*}; rest=${cfg#*,}; bin=${rest%%,*}; rest=${rest#*,}; rm=${rest%%,*}; extra=${rest#*,}
  cool
  log "config $name: $bin $rm env [$extra] (avail $(mavail), t $(tmax))"
  env LD_LIBRARY_PATH=$L ADSP_LIBRARY_PATH=$L GGML_HEXAGON_FA_STREAMS=1 HTPD_SPEC=0 \
    GGML_HEXAGON_HMX_PIPE_ALL=1 HTPD_LEGACY_PREFILL=1 HTPD_DRAFT=1 HTPD_DRAFT_K=8 HTPD_PREFIX_CACHE=1 HTPD_AGENT_MAX_NEW=160 \
    HTPD_JSON_ABORT=2 HTPD_SYNTH_PREFIX_CACHE=1 HTPD_REASON_IDLE_MS=600000 GGML_HEXAGON_OPPOLL=1 HTPD_REASON_DISK_CACHE=0 $extra \
    $B/$bin -m $G/ft_B50_q4_0.gguf --agents 10 --agent-ctx 1280 --synth-ctx 4096 --ubatch 512 --ubatch-synth 512 \
    --port 8091 --reasoner-model $G/$rm --reason-streams 3 > $OUT/htpd_$name.log 2>&1 &
  hp=$!
  for i in $(seq 1 120); do grep -q "htpd: ready in" $OUT/htpd_$name.log && break; kill -0 $hp 2>/dev/null || break; sleep 1; done
  kill -0 $hp 2>/dev/null || { log "ABORT: htpd $name died at start"; hp=""; finish dead; }
  k=0
  for r in $REQS; do
    if [ "$r" = a ]; then  # "a" in REQS (repack study): an agents request = reasoner down + agents' model back (a swap sample)
      [ -e $ABORT ] && finish abort
      nc -q 300 -W 300 127.0.0.1 8091 < $W/lab/agents10.json > $OUT/${name}_agentsR_$k.json
      log "  $name agents#$k: $(grep -o '"swap_ms":[0-9.]*' $OUT/${name}_agentsR_$k.json | tail -1) $(grep -o '"total_ms":[0-9.]*' $OUT/${name}_agentsR_$k.json | tail -1) t $(tmax)"
      kill -0 $hp 2>/dev/null || { log "ABORT: htpd $name died on agents"; hp=""; finish dead; }
      k=$((k+1)); continue
    fi
    cool; [ -e $ABORT ] && finish abort
    nc -q 600 -W 600 127.0.0.1 8091 < $W/chatlab/c$r.json > $OUT/${name}_c${r}_$k.json
    log "  $name c$r#$k: $(grep -o '"total_ms":[0-9.]*' $OUT/${name}_c${r}_$k.json | tail -1) $(grep -o '"stop":"[a-z]*"' $OUT/${name}_c${r}_$k.json | tail -1) t $(tmax) avail $(mavail)"
    kill -0 $hp 2>/dev/null || { log "ABORT: htpd $name died on q$r"; hp=""; finish dead; }
    k=$((k+1))
  done
  kill -TERM $hp; for i in $(seq 1 90); do kill -0 $hp 2>/dev/null || break; sleep 1; done; hp=""
  log "  $name stopped: $(grep -E 'pruned lm_head|load phases|step profile|repack stats' $OUT/htpd_$name.log | tail -4 | tr '\n' ' ')"
  sleep 20
done
finish ok
