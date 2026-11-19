#!/usr/bin/env bash
# Laptop driver for the agents lab window (pattern of proofs/2026-10-29_latency/lab_run.sh), Git Bash.
# usage: lab_ag_run.sh <window name> "cfg" ...   proofs/2026-10-29_latency/DEMO_NOW aborts (app back within ~1 min).
export MSYS_NO_PATHCONV=1
P=/c/Users/hp/Desktop/qidk/proofs/2026-10-31_agents_latency; DN=/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/DEMO_NOW
A=C:/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/rfast; N=$1; shift
sh_() { "$A" -s 3ce9a4e2 shell "$@" | tr -d '\r'; }
log() { echo "$(date +%T) $*" | tee -a $P/lab_run.log; }
[ -e $DN ] && { log "DEMO_NOW present: not starting"; exit 1; }
sed 's/\r$//' $P/lab_ag.sh > $P/.lab_ag.sh
sh_ "mkdir -p $W/lab/agl"
"$A" -s 3ce9a4e2 push "C:/Users/hp/Desktop/qidk/proofs/2026-10-31_agents_latency/.lab_ag.sh" $W/lab/lab_ag.sh > /dev/null
"$A" -s 3ce9a4e2 push "C:/Users/hp/Desktop/qidk/proofs/2026-10-31_agents_latency/agent_corpus_lab.txt" $W/lab/agent_corpus_lab.txt > /dev/null
for f in $P/agl/a*.json; do "$A" -s 3ce9a4e2 push "C:/Users/hp/Desktop/qidk/proofs/2026-10-31_agents_latency/agl/$(basename $f)" $W/lab/agl/ > /dev/null; done
q=""; for c in "$@"; do q="$q '$c'"; done
log "window $N start: $*"
sh_ "cd $W/lab && rm -rf $N && setsid nohup sh lab_ag.sh $N $q > /dev/null 2>&1 < /dev/null &"
sleep 20; t0=$(date +%s)
while true; do
  [ -e $DN ] && { sh_ "touch $W/lab/ABORT"; log "DEMO_NOW: abort sent"; }
  sh_ "tail -1 $W/lab/$N/ab.log 2>/dev/null" | grep -q "=== lab ab done" && break
  if ! sh_ "ps -A -o ARGS=" | grep -q "lab_ag.sh $N"; then
    log "board script gone: restarting the app from the laptop"
    sh_ "for p in \$(pidof htpd_v8x5 htpd_v8x5p htpd_v8x3 htpd_v9 htpd_v9b htpd_v9c htpd_v9d htpd_v9e); do kill -TERM \$p; done; sleep 10; am start -n com.iiith.smartcityedge/.MainActivity" > /dev/null
    break
  fi
  [ $(( $(date +%s) - t0 )) -gt ${WINDOW_MAX:-2400} ] && { sh_ "touch $W/lab/ABORT"; log "window over ${WINDOW_MAX:-2400} s: abort sent"; }
  sleep 15
done
mkdir -p $P/lab; rm -rf $P/lab/$N; "$A" -s 3ce9a4e2 pull $W/lab/$N "C:/Users/hp/Desktop/qidk/proofs/2026-10-31_agents_latency/lab" > /dev/null
for i in $(seq 1 30); do sh_ "grep -c 'htpd: ready in' /data/local/tmp/smart_city_edge/state/htpd.log" | grep -qE '^[1-9]' && break; sleep 5; done
log "window $N done: $(tail -1 $P/lab/$N/ab.log); app: $(sh_ 'ps -A -o NAME= | grep -E "^(edge-agent|htpd)" | tr "\n" " "')"
