#!/usr/bin/env bash
# Laptop driver for the chat-spec lab window (from lab_run.sh). usage: run_chat.sh <window> "cfg" ...
export MSYS_NO_PATHCONV=1
P=/c/Users/hp/Desktop/qidk/proofs/2026-10-31_night; Q=/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency; A=C:/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
W=/data/local/tmp/rfast; BIN=/data/local/tmp/llama.cpp/bin; N=$1; shift
sh_() { "$A" -s 3ce9a4e2 shell "$@" | tr -d '\r'; }
log() { echo "$(date +%T) $*" | tee -a $P/chatlab/run.log; }
N=$1
sleep 20; t0=$(date +%s)
while true; do
  [ -e $Q/DEMO_NOW ] && { sh_ "touch $W/lab/ABORT"; log "DEMO_NOW: abort sent"; }
  sh_ "tail -1 $W/lab/$N/ab.log 2>/dev/null" | grep -q "=== lab ab done" && break
  if ! sh_ "ps -A -o ARGS=" | grep -q "lab_chat.sh $N"; then
    log "board script gone: restarting the app"; sh_ 'for p in $(pidof htpd_v9e htpd_v9f); do kill -TERM $p; done; sleep 10; am start -n com.iiith.smartcityedge/.MainActivity' > /dev/null; break; fi
  [ $(( $(date +%s) - t0 )) -gt ${WINDOW_MAX:-2400} ] && { sh_ "touch $W/lab/ABORT"; log "window over: abort sent"; }
  sleep 15
done
mkdir -p $P/chatlab/out; "$A" -s 3ce9a4e2 pull $W/lab/$N "C:/Users/hp/Desktop/qidk/proofs/2026-10-31_night/chatlab/out" > /dev/null
for i in $(seq 1 40); do sh_ "ps -A -o NAME=" | grep -q "^htpd" && break; sleep 5; done
log "window $N done: app: $(sh_ 'ps -A -o NAME= | grep -E "^(edge-agent|htpd)" | tr "\n" " "')"
rm -f $P/PAUSE
