#!/system/bin/sh
# chat_gpu.sh (board): eval-only 2B chat server on the Adreno GPU (owner 2026-11-04: 2B scored higher on chat, 0.737 vs
# 0.477 chat dev v3; the 4B stays the reports model on the NPU and the general model). The app talks to it through
# htpd_profile chat_url=http://127.0.0.1:8090 and falls back to htpd if it's down. Remove chat_url = back to 4B chat.
#   sh chat_gpu.sh start | stop | status
# Guards (HANDBOOK 2.37: a second model next to the NPU model once made the OOM killer take system processes):
#   llama-server oom_score_adj 1000 (it dies first, never the system); MemAvailable < 700 MB -> kill it;
#   supervisor restarts it only when MemAvailable >= 1500 MB and max temp < 80 C; never reboots.
D=/data/local/tmp/llama.cpp-new; S=/data/local/tmp/chatgpu; M=/data/local/tmp/gpu/rsn_v3_2b_r2_q4_0.gguf
# flags: gpu/tune/TUNE.md (2026-11-04): -t 6 = 10 t/s vs 8 (recurrent ops run on the CPU); -cms 0 -ub 128 = a warm
# question re-prefills ~130 tokens, not ~520 (checkpoint 1 micro-batch before a prompt end). Outputs identical to -t 2.
PORT=8090; LOG=$S/chat_gpu.log; mkdir -p $S/clcache
log() { echo "$(date +%T) $*" >> $LOG; }
tmax() { cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1 | awk '{print int($1/1000)}'; }
mavail() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
run_server() {
  # own libs (native_build.sh, OpenCL only) when pushed, else the bench libs of the same commit
  LIB=$S/lib; [ -f $LIB/libllama.so ] || LIB=$D/lib
  export LD_LIBRARY_PATH=$LIB:/vendor/lib64 GGML_OPENCL_KERNEL_CACHE_DIR=$S/clcache
  # $S/device = cpu: the same server on the CPU only (round 3/4 of TUNE.md: ~25 t/s vs ~9 on the GPU, same text; -t 5 =
  # -t 6 speed, 3 cores left for htpd/edge-agent; -t 8 slower: little cores); the
  # app badge follows the profile key chat_device (split_on.sh writes it from this file). Default/absent = gpu.
  DEV="--device GPUOpenCL -ngl 99"; [ "$(cat $S/device 2>/dev/null)" = cpu ] && DEV="--device none -ngl 0"
  sh -c "echo 1000 > /proc/self/oom_score_adj; exec $S/llama-server -m $M $DEV -c 8192 -np 1 -t ${CHAT_T:-5} -tb ${CHAT_T:-5} -cms 0 -ub 128 \
    --host 127.0.0.1 --port $PORT --no-webui -cram 256" >> $S/server.log 2>&1 &
  echo $! > $S/server.pid; log "server start pid $(cat $S/server.pid) (avail $(mavail) MB, t $(tmax) C)"
}
case "$1" in
start)
  [ -f $S/super.pid ] && kill -0 "$(cat $S/super.pid)" 2>/dev/null && { echo "already running"; exit 0; }
  rm -f $S/STOP
  ( while [ ! -e $S/STOP ]; do
      p=$(cat $S/server.pid 2>/dev/null); a=$(mavail); t=$(tmax)
      if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
        [ "$a" -lt 700 ] && { kill -9 "$p"; log "GUARD KILL avail=$a MB t=$t C"; }
      elif [ "$a" -ge 1500 ] && [ "$t" -lt 80 ]; then run_server; sleep 20
        # pre-warm: the 15-tool header alone (warm.json, n_predict 1) leaves a cache checkpoint before the hourly time
        # line, so the first chat after a (re)start does not pay the full ~3,100-token prefill (~18 s on the CPU)
        [ -f $S/warm.json ] && { curl -s -m 120 -H 'Content-Type: application/json' -d @$S/warm.json \
          http://127.0.0.1:$PORT/completion > /dev/null; log "pre-warm done (t $(tmax) C)"; }
      fi
      [ $(( $(date +%s) % 60 )) -lt 2 ] && echo "$(date +%T) t=$t avail=$a pid=$p" >> $S/telemetry.log
      sleep 2
    done; log "supervisor stop" ) > /dev/null 2>&1 &
  echo $! > $S/super.pid; echo started;;
stop)
  touch $S/STOP; p=$(cat $S/server.pid 2>/dev/null); [ -n "$p" ] && kill -TERM "$p" 2>/dev/null; sleep 3
  for q in $(pidof llama-server); do [ "$q" = "$p" ] && kill -9 "$q"; done; log "stopped"; echo stopped;;
status)
  p=$(cat $S/server.pid 2>/dev/null); kill -0 "$p" 2>/dev/null && echo "server up pid $p" || echo "server down"
  echo "avail $(mavail) MB, t $(tmax) C"; tail -3 $LOG;;
esac
