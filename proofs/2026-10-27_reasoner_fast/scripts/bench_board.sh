#!/system/bin/sh
# Self-contained board micro-benchmark (reasoner speed levers). Run with: setsid nohup sh bench_board.sh CONFIGS >/dev/null 2>&1 &
# Safety: stops the app + htpd + edge-agent and waits for exit + 10 s (one NPU client); temperature pacing (<70 C to start
# each step); Normal-zone watchdog kills llama-* below 800 MB; restarts the app at the end. Never reboots.
W=/data/local/tmp/rfast
D=/data/local/tmp/llama.cpp
M=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf
OUT=$W/out; mkdir -p $OUT
LOG=$OUT/bench.log
export LD_LIBRARY_PATH=$D/lib ADSP_LIBRARY_PATH=$D/lib GGML_HEXAGON_HMX_PIPE_ALL=1 GGML_HEXAGON_FA_STREAMS=1
log() { echo "$(date +%T) $*" >> $LOG; }
tmax() { cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1 | awk '{print int($1/1000)}'; }
cool() { while [ "$(tmax)" -ge ${1:-70} ]; do log "temp $(tmax) C, waiting 20 s"; sleep 20; done; }
nfree() { awk '/zone   Normal/ {z=1} z && /pages free/ {print int($3*4/1024); exit}' /proc/zoneinfo; }
mavail() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
# emergency only (SIGKILL of an NPU client mid-call is itself a panic risk, ROOT_CAUSE 2026-10-22): MemAvailable < 500 MB.
# Normal-zone FREE pages are not a usable signal: the mmapped GGUF page cache sits there and is reclaimable.
guard() { while true; do n=$(mavail); if [ "$n" -lt 500 ]; then pkill -9 -f "bin/llama-"; log "GUARD KILL MemAvailable=$n MB"; sleep 5; fi; sleep 0.5; done; }
npu_others() { ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie)"; }
stop_all() {
  # after a reboot BootReceiver starts EdgeService late: wait for boot_completed + 240 s uptime first, else the app
  # comes back after the stop and two NPU clients overlap (seen 2026-10-27 21:11)
  while [ "$(getprop sys.boot_completed)" != 1 ] || [ "$(cut -d. -f1 /proc/uptime)" -lt 240 ]; do log "waiting for boot to settle"; sleep 15; done
  am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -f "[b]in/htpd"
  for i in $(seq 1 90); do ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie)" || break; sleep 1; done
  if ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)"; then log "ABORT: NPU client still running"; exit 3; fi
  # 30 s settle; no drop_caches / compact_memory (2nd reboot 2026-10-27 came ~15 s after a stop, during them)
  sleep 30
  if npu_others; then log "ABORT: the app restarted after the stop"; exit 3; fi
}
server_run() { # name args...
  name=$1; shift
  cool 68
  npu_others && { log "ABORT: NPU client present"; exit 4; }
  log "server $name: $*  (MemAvailable $(mavail) MB, Normal free $(nfree) MB)"
  $D/bin/llama-server -m $M --device HTP0 -ngl 99 -fa on -c 4096 -b 512 -ub 512 -np 1 --port 8093 --host 127.0.0.1 --no-webui "$@" > $OUT/server_$name.log 2>&1 &
  sp=$!
  for i in $(seq 1 120); do curl -s -m 2 http://127.0.0.1:8093/health | grep -q ok && break; kill -0 $sp 2>/dev/null || break; sleep 1; done
  if ! kill -0 $sp 2>/dev/null; then log "server $name died at start"; return; fi
  for r in $REQS; do
    cool 70
    if npu_others; then log "ABORT: another NPU client appeared; stopping llama-server (SIGTERM) and exiting"; kill $sp; exit 4; fi
    t0=$(date +%s%N)
    curl -s -m 400 -H 'Content-Type: application/json' -d @$W/req/r$r.json http://127.0.0.1:8093/completion > $OUT/${name}_r$r.json
    t1=$(date +%s%N); log "  $name r$r $(( (t1-t0)/1000000 )) ms, $(wc -c < $OUT/${name}_r$r.json) B, temp $(tmax)"
    kill -0 $sp 2>/dev/null || { log "server $name died on r$r"; break; }
  done
  kill $sp; for i in $(seq 1 60); do kill -0 $sp 2>/dev/null || break; sleep 1; done; sleep 30
}
REQS=${REQS:-"0 1 2 3 4 5"}
guard & GP=$!
( while true; do echo "$(date +%T) up=$(cut -d' ' -f1 /proc/uptime) t=$(tmax) avail=$(mavail) normal=$(nfree) $(ps -A -o NAME= | grep -E '^(llama|htpd)' | tr '
' ' ')" >> $OUT/telemetry.log; sleep 2; done ) & TP=$!
trap 'kill $GP $TP 2>/dev/null' EXIT
log "=== bench start: $* (REQS $REQS)"
stop_all
for c in "$@"; do
  case $c in
    lbench) cool 68; npu_others && { log "ABORT: NPU client present"; exit 4; }; log "llama-bench"; $D/bin/llama-bench -m $M --device HTP0 -ngl 99 -fa 1 -ub 512 -p 1,2,3,4,6,8,16,64 -n 64 -r 2 -o md > $OUT/llama_bench.md 2> $OUT/llama_bench.err; log "llama-bench rc=$?";;
    base)  server_run base;;
    mtp1)  server_run mtp1 --spec-type draft-mtp --spec-draft-n-max 1;;
    mtp2)  server_run mtp2 --spec-type draft-mtp --spec-draft-n-max 2;;
    mtp3)  server_run mtp3 --spec-type draft-mtp --spec-draft-n-max 3;;
    mtp4)  server_run mtp4 --spec-type draft-mtp --spec-draft-n-max 4;;
    ngram) server_run ngram --spec-type ngram-simple --spec-draft-n-max 8;;
    mtpng) server_run mtpng --spec-type draft-mtp,ngram-mod --spec-draft-n-max 4;;
  esac
done
kill $GP $TP
log "restart app"
am start -n com.iiith.smartcityedge/.MainActivity >> $LOG 2>&1
log "=== bench done"
