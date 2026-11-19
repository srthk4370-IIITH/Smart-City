#!/usr/bin/env bash
# 2026-10-31 deploy22 (owner-approved backend fixes, APK only; htpd/profile/NPU libs unchanged = deploy21):
#  1. reasoner validator (reasoner_v3.go v3ActionFloor): a weather-only critical incident (every flagged sensor is a
#     weather sensor, e.g. INC-0564 outdoor 45 C) may start its checklist with monitor or review_schedule; everything
#     else still needs inspect_* / request_facility_review.
#  2. event gate (engine.go window): a CRITICAL reading skips the 4 h window-coverage rule (<= 3 of 48 missing), so a
#     critical value after a sensor silence opens the fast incident at once (deploy21: 44-46 s after 17 min silence).
#     Non-critical readings: unchanged.
# r2 (15:5x IST): the gap-filled window opens the FAST incident only; the AI/batch gate waits for real coverage (r1 fed the
# AI a filled window and it read outdoor 45 C as a stuck sensor, INC-0583). r1 status: deploy22/STATUS_r1.md, r1 snapshot = known_good_deploy21.
# Go tests: proofs/2026-10-31_validator/go_test_new.txt. Rollback = deploy22/known_good (live deploy21 APK + profile).
# Check: chaos 2 + fastcheck x2 + chat check; any chaos/fastcheck failure -> previous APK + profile. Never reboots.
# usage (WSL): bash deploy22.sh
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency; I=$M/deploy22; mkdir -p $I/known_good
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; MM=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master
V=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_validator; NEW=$V/SmartCityEdge.deploy22.apk; NP=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_night
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
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; c=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)
    [ "${c:-0}" -gt "${n0:-0}" ] && return 0; [ "${c:-0}" -ge 1 ] && [ "${c:-0}" -lt "${n0:-0}" ] && return 0; done; return 1; }

echo "# Deploy 22 r2 (APK: weather-only validator rule + critical skips the coverage gate) ($(TZ=Asia/Kolkata date +%H:%M) IST)" > $I/STATUS.md
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
  python3 $MM/chatcheck.py "Which domains have open incidents right now?" "How many sensor faults were there this week?" "What if occupancy increases by 50%, impact on other domains" > $I/chat.txt
  while read l; do st "- chat: $l"; done < $I/chat.txt
  grep -qE "^FAIL|error True|could not find an answer" $I/chat.txt && st "- CHAT WARNING: see chat lines (owner: fix forward, no rollback for chat)"
fi
if [ $ok = 1 ]; then
  st "- DEPLOYED: APK $(md5sum $NEW | cut -c1-8) (edge-agent: weather-only validator rule + critical gap bypass), htpd/profile unchanged; chaos 2 rc=0; fastcheck $fc; fastcheck2 $fc2"
else
  stop_app > /dev/null; $A install -r -d "$(w $I/known_good/app.apk)" | tail -1
  $A push "$(w $I/known_good/htpd_profile)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
  start_app; st "- FAILED (chaos rc=$crc fastcheck rc=$frc/$frc2) -> previous APK + profile restored"
fi
st "- board now: APK $(sh_ "md5sum \$(pm path com.iiith.smartcityedge | sed s/^package://)" | cut -c1-8); $(sh_ "grep -E '^(bin|reasoner_model)=' $W/htpd_profile" | tr '\n' ' ')"
log "=== deploy22 done"
rm -f $NP/PAUSE
