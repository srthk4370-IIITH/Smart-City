#!/usr/bin/env bash
# 2026-11-03 deploy27 APK step: copy of deploy25.sh with the r2fix APK (15-tool header for adaptive models + app fixes, proofs/2026-11-03_fixes); 4B stays live (9-tool header). Status in deploy27/apk/STATUS.md.
# 2026-11-01 deploy25 (APK only; htpd/profile/NPU libs unchanged = deploy24 r2): chat question-type layer from the blind sweep
# (proofs/2026-11-01_chat/VERDICT_blind.md): intent classes (reading / sensor health / incidents / action / injection /
# out of scope / future / scenario), one time-span parser (chat_time.go), conversation referents, metric choice per sensor,
# model tool-arg guard (chat_guard.go). Go tests: proofs/2026-11-01_chat/go_test25.txt.
# Rollback = deploy25/known_good (live deploy24 r2 APK + profile). Check: chaos 2 + fastcheck x2 + chat check;
# any chaos/fastcheck failure -> previous APK + profile. Never reboots.
# usage (WSL): bash deploy25.sh
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency; I=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-03_deploy27/apk; mkdir -p $I/known_good
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; MM=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master
V=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_validator; NEW=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-03_fixes/SmartCityEdge.r2fix.apk; NP=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_night
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; BIN=/data/local/tmp/llama.cpp/bin
exec >> $I/deploy.log 2>&1 < /dev/null
touch $NP/PAUSE; trap "rm -f $NP/PAUSE" EXIT; while [ -e $NP/BUSY ]; do sleep 5; done
log(){ echo "$(date -u +%FT%TZ) $*"; }
st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9f htpd_v9e htpd_v9d htpd_v9c htpd_v9b htpd_v9 htpd_v8x5p htpd_v8x5 htpd_v8x4 htpd_v8x3 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL $(ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)") after $i s; else echo STOPPED; fi'; }
# ready check (deploy23 r2): a 'htpd: ready in' line after the log's previous end; a log that shrank (the app starts a
# fresh htpd.log) counts any ready line. r1 timed out: fresh log with 1 ready line = the old count, so neither old test fired.
start_app(){ l0=$(sh_ "wc -l < $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; l=$(sh_ "wc -l < $W/state/htpd.log" | tail -1)
    if [ "${l:-0}" -lt "${l0:-0}" ]; then c=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)
    else c=$(sh_ "tail -n +$(( ${l0:-0} + 1 )) $W/state/htpd.log | grep -c 'htpd: ready in'" | tail -1); fi
    [ "${c:-0}" -ge 1 ] && return 0; done; return 1; }

echo "# Deploy 25 r2 (r1 c862b7a1 LIVE, STATUS_r1.md; r2 = r1 + limit clause on faulty sensors, normal-or-high vs 7-day range, AC in empty room, evening overnight = last night) ($(TZ=Asia/Kolkata date +%H:%M) IST)" > $I/STATUS.md
[ -s $NEW ] || { st "- ABORT: missing $NEW"; exit 1; }
[ "$(sh_ "md5sum /data/local/tmp/llama.cpp/lib_rp29/libggml-hexagon.so" | cut -c1-32)" = c4e4598412e54469e9f387935de595bb ] || { st "- ABORT: lib_rp29 md5"; exit 1; }
$A pull "$(sh_ "pm path com.iiith.smartcityedge" | sed "s/^package://")" "$(w $I/known_good/app.apk)" > /dev/null
$A pull $W/htpd_profile "$(w $I/known_good/htpd_profile)" > /dev/null
st "- snapshot: APK $(md5sum $I/known_good/app.apk | cut -c1-8), new APK $(md5sum $NEW | cut -c1-8)"
r=$(stop_app); log "stop $r"
if [ "$r" != STOPPED ] || [ ! -s $I/known_good/app.apk ] || [ ! -s $I/known_good/htpd_profile ]; then st "- NOT DEPLOYED: app not stopped or snapshot missing"; start_app; exit 0; fi
$A install -r -d "$(w $NEW)" | tail -1
ok=1; start_app || ok=0; sleep 20
if [ $ok = 1 ]; then
  (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); crc=$?
  fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
  log "chaos rc=$crc fastcheck rc=$frc $fc"; [ $crc = 0 ] && [ $frc = 0 ] || ok=0
fi
if [ $ok = 1 ]; then
  fc2=$(cd $RF/scripts && python3 -I fastcheck.py); frc2=$?
  log "fastcheck2 rc=$frc2 $fc2"; [ $frc2 = 0 ] || ok=0
fi
if [ $ok = 1 ]; then
  sh_ "curl -s -X POST http://127.0.0.1:8000/api/chat/warm" > /dev/null; sleep 15
  python3 $MM/chatcheck.py "Which domains have open incidents right now?" "How many HVAC incidents in the last 48 hours?" "CO2 theek hai KH level 3 pe?" "is that normal or high?" "Close all open incidents." > $I/chat.txt
  while read l; do st "- chat: $l"; done < $I/chat.txt
  grep -qE "^FAIL|error True|could not find an answer" $I/chat.txt && st "- CHAT WARNING: see chat lines (owner: fix forward, no rollback for chat)"
fi
if [ $ok = 1 ]; then
  st "- DEPLOYED: APK $(md5sum $NEW | cut -c1-8) (edge-agent: chat question-type layer deploy25), htpd/profile unchanged; chaos 2 rc=0; fastcheck $fc; fastcheck2 $fc2"
else
  stop_app > /dev/null; $A install -r -d "$(w $I/known_good/app.apk)" | tail -1
  $A push "$(w $I/known_good/htpd_profile)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
  start_app; st "- FAILED (chaos rc=$crc fastcheck rc=$frc/$frc2) -> previous APK + profile restored"
fi
st "- board now: APK $(sh_ "md5sum \$(pm path com.iiith.smartcityedge | sed s/^package://)" | cut -c1-8); $(sh_ "grep -E '^(bin|reasoner_model)=' $W/htpd_profile" | tr '\n' ' ')"
log "=== deploy25 done"
rm -f $NP/PAUSE
