#!/usr/bin/env bash
# Laptop driver for one lab window (Git Bash; adb.exe). usage: lab_run.sh <window name> "cfg" ...  (cfg as in lab_ab.sh)
# Pushes lab_ab.sh + agents10.json, starts the window on the board (setsid, survives adb drops), polls every 15 s.
# touch proofs/2026-10-29_latency/DEMO_NOW -> the board stops the window and restarts the real app within ~1 min.
# At the end: pulls the window's files to proofs/2026-10-29_latency/<window>/ and checks the app's htpd is back.
export MSYS_NO_PATHCONV=1
P=/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency; A=C:/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
W=/data/local/tmp/rfast; N=$1; shift
sh_() { "$A" shell "$@" | tr -d '\r'; }
log() { echo "$(date +%T) $*" | tee -a $P/lab_run.log; }
sed 's/\r$//' $P/lab_ab.sh > $P/.lab_ab.sh
sh_ "mkdir -p $W/lab"
"$A" push "C:/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/.lab_ab.sh" $W/lab/lab_ab.sh > /dev/null
"$A" push "C:/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/bench/agents10.json" $W/lab/agents10.json > /dev/null
q=""; for c in "$@"; do q="$q '$c'"; done
log "window $N start: $*"
sh_ "cd $W/lab && rm -rf $N && REQS='${REQS:-10 10 11 12 13 14 15}' setsid nohup sh lab_ab.sh $N $q > /dev/null 2>&1 < /dev/null &"
sleep 20
t0=$(date +%s)
while true; do
  [ -e $P/DEMO_NOW ] && { sh_ "touch $W/lab/ABORT"; log "DEMO_NOW: abort sent"; }
  sh_ "tail -1 $W/lab/$N/ab.log 2>/dev/null" | grep -q "=== lab ab done" && break
  if ! sh_ "ps -A -o ARGS=" | grep -q "lab_ab.sh $N"; then  # board script gone without "done": bring the app back here
    log "board script gone: restarting the app from the laptop"
    sh_ "for p in \$(pidof htpd_v8x5 htpd_v8x5p htpd_v8x3 htpd_v9 htpd_v9b htpd_v9c htpd_v9d htpd_v9e htpd_v9f); do kill -TERM \$p; done; sleep 10; am start -n com.iiith.smartcityedge/.MainActivity" > /dev/null
    break
  fi
  [ $(( $(date +%s) - t0 )) -gt ${WINDOW_MAX:-1500} ] && { sh_ "touch $W/lab/ABORT"; log "window over ${WINDOW_MAX:-1500} s: abort sent"; }
  sleep 15
done
rm -rf $P/$N; "$A" pull $W/lab/$N "C:/Users/hp/Desktop/qidk/proofs/2026-10-29_latency" > /dev/null
for i in $(seq 1 30); do sh_ "grep -c 'htpd: ready in' /data/local/tmp/smart_city_edge/state/htpd.log" | grep -qE '^[1-9]' && break; sleep 5; done
log "window $N done: $(tail -1 $P/$N/ab.log); app: $(sh_ 'ps -A -o NAME= | grep -E "^(edge-agent|htpd)" | tr "\n" " "')"
grep -E "q[0-9]+#|ABORT|HEAT|stopped" $P/$N/ab.log | tee -a $P/lab_run.log
