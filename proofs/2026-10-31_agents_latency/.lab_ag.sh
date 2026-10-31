#!/system/bin/sh
# Agents lab window on the board (pattern of proofs/2026-10-29_latency/lab_ab.sh): app + htpd stopped (one NPU client),
# each config = one standalone htpd, the 24 real agent requests agl/a00..a23 in app order, then one reasoner request
# (q10: a swap sample with /proc CPU split of the load) and a00 again (agents' model back). App restarted at the end.
# Guards: start <= 55 C, kill htpd at >= 105 C for 3 samples, $W/lab/ABORT stops the window.
# usage: setsid nohup sh lab_ag.sh <outdir> "name,binary,extra env" ...   (@CORPUS in env = a fresh copy of the lab corpus)
W=/data/local/tmp/rfast; B=/data/local/tmp/llama.cpp/bin; L=/data/local/tmp/llama.cpp/lib_rp29; G=/data/local/tmp/gpu
OUT=$W/lab/$1; shift; mkdir -p $OUT; LOG=$OUT/ab.log; ABORT=$W/lab/ABORT
STOPL="htpd_v8x5 htpd_v8x5p htpd_v8x3 htpd_v8x4 htpd_v9 htpd_v9b htpd_v9c htpd_v9d htpd_v9e htpd"
log() { echo "$(date +%T) $*" >> $LOG; }
tmax() { cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1 | awk '{print int($1/1000)}'; }
mavail() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
npu_others() { ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)"; }
ms() { n=$(date +%s%N); echo ${n%??????}; }
d() { awk "BEGIN{print $2-$1}"; }
hp=""
( hot=0; while true; do t=$(tmax); echo "$(date +%T) t=$t avail=$(mavail) $(ps -A -o NAME= | grep -E '^htpd' | tr '\n' ' ')" >> $OUT/telemetry.log
    if [ "$t" -ge 105 ]; then hot=$((hot+1)); else hot=0; fi
    if [ $hot -ge 3 ]; then echo "$(date +%T) HEAT $t C for 3 samples: kill htpd" >> $LOG; for p in $(pidof $STOPL); do kill -TERM $p; done; fi
    sleep 2; done ) & TP=$!
finish() {
  log "finish ($1)"; trap '' HUP TERM
  [ -n "$hp" ] && kill -TERM $hp 2>/dev/null; for i in $(seq 1 90); do [ -n "$hp" ] && kill -0 $hp 2>/dev/null || break; sleep 1; done
  kill $TP 2>/dev/null
  i=0; while [ $i -lt 60 ] && ps -A -o NAME= | grep -qE "^htpd"; do sleep 1; i=$((i+1)); done
  sleep 5; log "restart app ($1)"; am start -n com.iiith.smartcityedge/.MainActivity >> $LOG 2>&1; log "=== lab ab done ($1)"; exit 0
}
cool() { while [ "$(tmax)" -gt 55 ]; do [ -e $ABORT ] && finish abort; sleep 10; done; }
cpu() { awk '{print $14, $15}' /proc/$1/stat 2>/dev/null; }
log "=== lab ag start: $*"
rm -f $ABORT
am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof $STOPL); do kill -TERM $p; done
for i in $(seq 1 120); do npu_others >/dev/null || break; sleep 1; done
sleep 30
npu_others && { log "ABORT: NPU client still running"; finish npu; }
for cfg in "$@"; do
  name=${cfg%%,*}; rest=${cfg#*,}; bin=${rest%%,*}; extra=${rest#*,}
  [ "$extra" = "$rest" ] && extra=""
  [ -e $ABORT ] && finish abort
  cool
  cp $W/lab/agent_corpus_lab.txt $OUT/corpus_$name.txt
  extra=$(echo "$extra" | sed "s#@CORPUS#$OUT/corpus_$name.txt#")
  log "config $name: $bin env [$extra] (avail $(mavail), t $(tmax))"
  env LD_LIBRARY_PATH=$L ADSP_LIBRARY_PATH=$L GGML_HEXAGON_FA_STREAMS=1 HTPD_SPEC=0 GGML_HEXAGON_REPACK_THREADS=8 GGML_HEXAGON_REPACK_STATS=1 \
    GGML_HEXAGON_HMX_PIPE_ALL=1 HTPD_LEGACY_PREFILL=1 HTPD_DRAFT=1 HTPD_DRAFT_K=8 HTPD_PREFIX_CACHE=1 HTPD_AGENT_MAX_NEW=160 \
    HTPD_JSON_ABORT=2 HTPD_SYNTH_PREFIX_CACHE=1 HTPD_REASON_IDLE_MS=600000 GGML_HEXAGON_OPPOLL=1 HTPD_REASON_DISK_CACHE=0 \
    HTPD_REASON_SPLIT_SPEC=8 HTPD_REASON_SPEC_MIN=2 HTPD_REASON_SPEC_ALIGN=1 HTPD_REASON_CORPUS=/data/local/tmp/smart_city_edge/reason_corpus_v2.jsonl \
    HTPD_REASON_SPEC_KLONG=16 HTPD_REASON_SPEC_ROWS=48 $extra \
    $B/$bin -m $G/ft_B50_q4_0.gguf --agents 10 --agent-ctx 1280 --synth-ctx 4096 --ubatch 512 --ubatch-synth 512 \
    --port 8091 --reasoner-model $G/qwen35_reasoner_q4_0.gguf --reason-streams 3 > $OUT/htpd_$name.log 2>&1 &
  hp=$!
  for i in $(seq 1 120); do grep -q "htpd: ready in" $OUT/htpd_$name.log && break; kill -0 $hp 2>/dev/null || break; sleep 1; done
  kill -0 $hp 2>/dev/null || { log "ABORT: htpd $name died at start"; hp=""; finish dead; }
  k=0
  for f in $(ls $W/lab/agl | grep -E '^a[0-9]+\.json$' | sort); do
    [ -e $ABORT ] && finish abort
    [ $((k % 8)) = 0 ] && cool
    r=${f%.json}
    s0=$(ms); nc -q 300 -W 300 127.0.0.1 8091 < $W/lab/agl/$f > $OUT/${name}_$r.json; s1=$(ms)
    log "  $name $r: wall $(d $s0 $s1) ms $(grep -o '"prefill_ms":[0-9.]*' $OUT/${name}_$r.json | tail -1) $(grep '^htpd: draft steps' $OUT/htpd_$name.log | tail -1) t $(tmax)"
    kill -0 $hp 2>/dev/null || { log "ABORT: htpd $name died on $r"; hp=""; finish dead; }
    k=$((k+1))
  done
  cool; [ -e $ABORT ] && finish abort
  c0=$(cpu $hp)
  ( while kill -0 $hp 2>/dev/null && [ ! -e $OUT/.qdone ]; do echo "$(ms) $(cpu $hp) $(mavail)" >> $OUT/cpu_$name.log; sleep 0.1; done ) & CP=$!
  s0=$(ms); nc -q 600 -W 600 127.0.0.1 8091 < $W/rreq_split/q10.json > $OUT/${name}_q10.json; s1=$(ms); touch $OUT/.qdone; wait $CP; rm -f $OUT/.qdone
  log "  $name q10: wall $(d $s0 $s1) ms start $s0 cpu $c0 -> $(cpu $hp) $(grep -E 'reasoner load phases|reasoner loaded in' $OUT/htpd_$name.log | tail -2 | tr '\n' ' ') t $(tmax)"
  kill -0 $hp 2>/dev/null || { log "ABORT: htpd $name died on q10"; hp=""; finish dead; }
  s0=$(ms); nc -q 300 -W 300 127.0.0.1 8091 < $W/lab/agl/a00.json > $OUT/${name}_a00b.json; s1=$(ms)
  log "  $name a00b: wall $(d $s0 $s1) ms $(grep -o '"swap_ms":[0-9.]*' $OUT/${name}_a00b.json | tail -1) $(grep '^htpd: draft steps' $OUT/htpd_$name.log | tail -1)"
  kill -TERM $hp; for i in $(seq 1 90); do kill -0 $hp 2>/dev/null || break; sleep 1; done; hp=""
  log "  $name stopped"
  sleep 20
done
finish ok
