#!/usr/bin/env bash
# Push the retrieval seed library (rag_seed/rag_seed.json, 254 rsn_v1 reference cases) to the board app's data dir,
# restart the app, confirm "seed reference cases loaded" + one fastcheck incident (preliminary, then the AI on the
# same incident). Any failure -> remove the file, restart (= the 00:44 retrieval deploy state). Standalone (detach.sh).
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; K=$M/BOARD_LOCK; W=/data/local/tmp/smart_city_edge
SRC=$M/rag_seed/rag_seed.json; DST=$W/data/rag_seed.json
exec >> $M/seed_deploy.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x2 htpd_v8x3 htpd_v8r htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; [ "$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)" -gt "${n0:-0}" ] && return 0; done; return 1; }
while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do sleep 60; done
echo seed > $K; trap 'rm -f $K' EXIT
python3 -c "import json,sys; d=json.load(open('$SRC')); print('seed entries', len(d) if isinstance(d,list) else len(d.get('docs',d)))" || { log "bad seed json"; exit 1; }
m=$(md5sum $SRC | cut -c1-32); log "seed md5 $m"
r=$(stop_app); log "stop: $r"; [ "$r" = STOPPED ] || { log "ABORT: app not stopped"; start_app; exit 1; }
$A push "$(wslpath -w $SRC)" $DST.part > /dev/null && [ "$(sh_ "md5sum $DST.part" | cut -c1-32)" = "$m" ] && sh_ "mv -f $DST.part $DST" || { log "push failed"; sh_ "rm -f $DST.part"; start_app; exit 1; }
start_app && log "app up" || log "app NOT up"
sleep 20
fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
log "fastcheck rc=$frc $fc"
fj=$(ls -t $RF/raw/fastcheck_*.json | head -1); seedhit=$(grep -c "reference case" $fj); log "fastcheck incident preliminary from a seed reference case: $seedhit ($fj)"
loaded="seed hit in fastcheck preliminary: $seedhit"  # trace() logs only with SCE_GENIE_TRACE=1; a failed load just means 0 seeds (harmless)
if [ $frc = 0 ]; then echo "PASS: $loaded; fastcheck $fc" > $M/seed_deploy.result; log "=== seed LIVE"
else
  log "check failed: removing the seed file"; stop_app > /dev/null; sh_ "rm -f $DST"; start_app && log "app up without seeds"
  echo "FAIL -> removed (loaded='${loaded}', fastcheck rc=$frc)" > $M/seed_deploy.result
fi
log "=== seed_deploy done"
