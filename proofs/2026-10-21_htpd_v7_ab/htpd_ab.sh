#!/usr/bin/env bash
# Start htpd for the v7 A/B: htpd_ab.sh BIN "ARGS" "ENV"   (app stopped first; v2 model; port 8091 forwarded)
#   htpd_ab.sh stop   -> kill htpd, relaunch the app
set -uo pipefail
export MSYS_NO_PATHCONV=1
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
if [ "$1" = stop ]; then
  "$ADB" shell 'pkill -x edge-agent; pkill -x genied; pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; for i in $(seq 1 80); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; sleep 10; true'; "$ADB" forward --remove tcp:8091 2>/dev/null
  "$ADB" shell 'monkey -p com.iiith.smartcityedge -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; true'; echo stopped; exit 0
fi
BIN=$1; ARGS=$2; ENVS=$3
BASEENV="GGML_HEXAGON_FA_STREAMS=1 HTPD_SPEC=0 HTPD_LEGACY_PREFILL=1 GGML_HEXAGON_HMX_PIPE_ALL=1 HTPD_DRAFT=1 HTPD_DRAFT_K=8 HTPD_PREFIX_CACHE=1"
"$ADB" shell am force-stop com.iiith.smartcityedge
"$ADB" shell 'pkill -x edge-agent; pkill -x genied; pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; for i in $(seq 1 80); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; sleep 10; true'
"$ADB" shell "cd /data/local/tmp/llama.cpp; (LD_LIBRARY_PATH=./lib ADSP_LIBRARY_PATH=./lib $BASEENV $ENVS setsid nohup ./bin/$BIN -m /data/local/tmp/gpu/ft_v2_q4_0.gguf --synth-ctx 4096 --ubatch 512 --ubatch-synth 512 --port 8091 $ARGS > /data/local/tmp/htpd_ab.log 2>&1 < /dev/null &); for i in \$(seq 1 90); do grep -q 'htpd: ready' /data/local/tmp/htpd_ab.log && break; sleep 2; done; tail -2 /data/local/tmp/htpd_ab.log; cat /sys/class/thermal/thermal_zone30/temp"
"$ADB" forward tcp:8091 tcp:8091 >/dev/null
