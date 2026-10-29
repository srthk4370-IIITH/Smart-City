#!/usr/bin/env bash
# Owner 2026-10-29 ~08:40 IST: deploy rsn_v2 (better reasoning range; board gate tie once the contract repairs fix its
# label/title slips: sev 10/10, label 10/10 with repairs, 22.7 s vs v1 25.2 s). Runs after improve.sh deployed the repair
# build. Swap reasoner_model only (htpd_v8x3, split 3, B50 unchanged) -> chaos 2 + fastcheck; fail -> v1 profile back.
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; I=$M/improve; K=$M/BOARD_LOCK
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
W=/data/local/tmp/smart_city_edge; G=/data/local/tmp/gpu
exec >> $I/v2_deploy.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }; st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
w(){ wslpath -w "$1"; }; sh_(){ $A shell "$@" | tr -d '\r'; }
setp(){ f=$1; k=$2; v=$3; grep -v "^$k=" $f > $f.t; echo "$k=$v" >> $f.t; mv $f.t $f; }
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x3 htpd_v8x2 htpd_v8r htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; [ "$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)" -gt "${n0:-0}" ] && return 0; done; return 1; }
until grep -q "=== improve done" $I/improve.log 2>/dev/null; do sleep 30; done
grep -q "I2 DEPLOYED" $I/STATUS.md || { st "- V2 skipped: the repair build is not live (rsn_v2 needs its title/label repairs)"; exit 0; }
[ $(date +%s) -lt $(date -d "2026-10-29 05:45 UTC" +%s) ] || { st "- V2 skipped: after 11:15 IST"; exit 0; }
while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do sleep 30; done
echo v2 > $K; trap 'rm -f $K' EXIT
[ "$(sh_ "stat -c %s $G/rsn_v2_q4_0.gguf")" = 2611783520 ] || { st "- V2 abort: rsn_v2 GGUF missing"; exit 3; }
sh_ "cat $W/htpd_profile" > $I/profile.v1; cp $I/profile.v1 $I/profile.v2; setp $I/profile.v2 reasoner_model $G/rsn_v2_q4_0.gguf
r=$(stop_app); log "stop $r"; [ "$r" = STOPPED ] || { start_app; st "- V2 abort: app not stopped"; exit 3; }
$A push "$(w $I/profile.v2)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
ok=0; start_app && ok=1; sleep 20
if [ $ok = 1 ]; then (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); crc=$?; fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
  log "chaos rc=$crc fastcheck rc=$frc $fc"; [ $crc = 0 ] && [ $frc = 0 ] || ok=0; fi
if [ $ok = 1 ]; then st "- V2 DEPLOYED: rsn_v2 live; chaos 2 rc=0; fastcheck $fc"
else stop_app > /dev/null; $A push "$(w $I/profile.v1)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"; start_app
  st "- V2 FAILED app check (chaos rc=$crc fastcheck rc=$frc) -> rsn_v1 profile restored"; fi
st "- board after V2: $(sh_ "grep -E '^(bin|reasoner_model|reasoner_split)=' $W/htpd_profile" | tr '\n' ' ')"
log "=== v2 done"
