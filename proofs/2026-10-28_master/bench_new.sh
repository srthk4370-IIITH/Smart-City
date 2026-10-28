#!/system/bin/sh
# Board-side A/B: old llama.cpp (deployed libs) vs new upstream build (338fce65, Hexagon preset) with llama-bench.
# Run: setsid nohup sh bench_new.sh >/dev/null 2>&1 &   Result: /data/local/tmp/rfast/new/bench.md + DONE
# Safety: app + htpd + edge-agent stopped, wait for exit + 30 s (one NPU client); start each run < 65 C;
# MemAvailable < 500 MB kills llama-bench; app restarted at the end. Never reboots.
O=/data/local/tmp/llama.cpp; N=/data/local/tmp/llama.cpp-new; W=/data/local/tmp/rfast/new; mkdir -p $W; rm -f $W/DONE
LOG=$W/bench.log; log() { echo "$(date +%T) $*" >> $LOG; }
tmax() { cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1 | awk '{print int($1/1000)}'; }
cool() { while [ "$(tmax)" -ge 65 ]; do sleep 20; done; }
mavail() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
guard() { while true; do [ "$(mavail)" -lt 500 ] && { pkill -9 -f "bin/llama-bench"; log "GUARD KILL"; sleep 5; }; sleep 0.5; done; }
log "=== bench_new start"
am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -f "[b]in/htpd"
for i in $(seq 1 90); do ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie)" || break; sleep 1; done
if ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)"; then log "ABORT: NPU client still running"; echo abort > $W/DONE; exit 3; fi
sleep 30
guard & GP=$!
: > $W/bench.md
for m in /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf /data/local/tmp/gpu/ft_B50_q4_0.gguf; do
  for side in old new; do
    D=$O; [ $side = new ] && D=$N
    cool; ps -A -o NAME= | grep -qE "^(htpd|edge-agent)" && { log "ABORT: app came back"; break 2; }
    log "$side $(basename $m) (temp $(tmax), avail $(mavail))"
    echo "## $side $(basename $m)" >> $W/bench.md
    LD_LIBRARY_PATH=$D/lib ADSP_LIBRARY_PATH=$D/lib GGML_HEXAGON_HMX_PIPE_ALL=1 $D/bin/llama-bench -m $m --device HTP0 -ngl 99 -fa 1 -ub 512 \
      -p 256 -n 64 -r 3 -o md >> $W/bench.md 2>> $W/bench_$side.err
    log "  rc=$?"; sleep 20
  done
done
kill $GP
log "restart app"; am start -n com.iiith.smartcityedge/.MainActivity >> $LOG 2>&1
log "=== bench_new done"; echo ok > $W/DONE
