#!/system/bin/sh
# Self-contained: per-op HTP profile of the reasoner decode + env knob sweep (llama-bench tg32). App stopped by the
# caller's earlier job? No: this script stops it itself (same rules as bench_board.sh) and restarts it at the end.
W=/data/local/tmp/rfast; D=/data/local/tmp/llama.cpp; M=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf
OUT=$W/prof; mkdir -p $OUT; LOG=$OUT/prof.log
export LD_LIBRARY_PATH=$D/lib ADSP_LIBRARY_PATH=$D/lib GGML_HEXAGON_HMX_PIPE_ALL=1 GGML_HEXAGON_FA_STREAMS=1
log() { echo "$(date +%T) $*" >> $LOG; }
tmax() { cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1 | awk '{print int($1/1000)}'; }
cool() { while [ "$(tmax)" -ge ${1:-66} ]; do sleep 15; done; }
npu_others() { ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)"; }
log "=== prof start"
while [ "$(getprop sys.boot_completed)" != 1 ] || [ "$(cut -d. -f1 /proc/uptime)" -lt 240 ]; do sleep 15; done
am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -f "[b]in/htpd"
for i in $(seq 1 90); do npu_others >/dev/null || break; sleep 1; done
sleep 30
if npu_others; then log "ABORT: NPU client still running"; exit 3; fi
cool; log "profile decode (llama-completion -v, PROFILE=1)"
GGML_HEXAGON_PROFILE=1 $D/bin/llama-completion -m $M --device HTP0 -ngl 99 -fa on -c 1024 -ub 512 -p "The quick brown fox jumps over the lazy dog. Then" -n 24 -no-cnv --temp 0 -v > $OUT/prof_out.txt 2> $OUT/prof_err.txt < /dev/null
log "profile rc=$? ($(grep -c profile-op $OUT/prof_err.txt) op lines)"
sleep 20
for cfg in "base,X=0" "poll,GGML_HEXAGON_OPPOLL=1" "nhvx2,GGML_HEXAGON_NHVX=2" "sushp,GGML_HEXAGON_POWER_MODE=sustained_high_performance" "nofuse,GGML_HEXAGON_OPFUSION=0"; do
  n=${cfg%%,*}; e=${cfg#*,}
  cool; log "tg32 $n [$e]"
  env $e $D/bin/llama-bench -m $M --device HTP0 -ngl 99 -fa 1 -ub 512 -p 0 -n 32 -r 3 -o md > $OUT/tg_$n.md 2> $OUT/tg_$n.err
  log "  $(grep tg32 $OUT/tg_$n.md)"
  sleep 20
done
log "restart app"; am start -n com.iiith.smartcityedge/.MainActivity >> $LOG 2>&1; log "=== prof done"
