#!/usr/bin/env bash
# Laptop driver for the chat-spec lab window (from lab_run.sh). usage: run_chat.sh <window> "cfg" ...
export MSYS_NO_PATHCONV=1
P=/c/Users/hp/Desktop/qidk/proofs/2026-10-31_night; Q=/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency; A=C:/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
W=/data/local/tmp/rfast; BIN=/data/local/tmp/llama.cpp/bin; N=$1; shift
sh_() { "$A" -s 3ce9a4e2 shell "$@" | tr -d '\r'; }
log() { echo "$(date +%T) $*" | tee -a $P/chatlab/run.log; }
touch $P/PAUSE; while [ -e $P/BUSY ]; do sleep 5; done
log "soak paused; stopping app for pushes"
sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9e htpd_v9d htpd_v9f htpd); do kill -TERM $p; done; i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done; echo stopped after $i s'
sed 's/\r$//' $P/chatlab/lab_chat.sh > $P/chatlab/.lab_chat.sh
sh_ "mkdir -p $W/lab $W/chatlab"
"$A" -s 3ce9a4e2 push "C:/Users/hp/Desktop/qidk/proofs/2026-10-31_night/chatlab/.lab_chat.sh" $W/lab/lab_chat.sh > /dev/null
for f in $P/chatlab/req/*.json; do "$A" -s 3ce9a4e2 push "$(cygpath -w $f)" $W/chatlab/ > /dev/null; done
"$A" -s 3ce9a4e2 push "C:/Users/hp/Desktop/qidk/proofs/2026-10-31_night/chatlab/chat_corpus_lab.jsonl" $W/chatlab/chat_corpus_lab.jsonl > /dev/null
if [ -z "$(sh_ "ls $BIN/htpd_v9f 2>/dev/null")" ]; then
  "$A" -s 3ce9a4e2 push "C:/Users/hp/Desktop/qidk/proofs/2026-10-31_night/v9f/htpd" $BIN/htpd_v9f.part > /dev/null
  m=$(sh_ "md5sum $BIN/htpd_v9f.part" | cut -c1-32); log "v9f md5 $m"
  [ "$m" = "$(md5sum < $P/v9f/htpd | cut -c1-32)" ] && sh_ "chmod 755 $BIN/htpd_v9f.part && mv -f $BIN/htpd_v9f.part $BIN/htpd_v9f" || { log "ABORT md5"; sh_ 'am start -n com.iiith.smartcityedge/.MainActivity'; rm $P/PAUSE; exit 1; }
fi
q=""; for c in "$@"; do q="$q '$c'"; done
log "window $N start: $*"
sh_ "cd $W/lab && rm -rf $N && REQS='${REQS}' setsid nohup sh lab_chat.sh $N $q > /dev/null 2>&1 < /dev/null &"
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
