#!/usr/bin/env bash
# 2026-10-29 afternoon (owner: "Deploy now"): pruned lm_head reasoner (htpd_v8x5p + libllama_p + rsn_v1_q4_0_keep.gguf),
# htpd v8x5 (step/load profile, LRU prefix cache) and the APK with the "AI so far" panel. Lab A/B: proofs/2026-10-29_latency
# (base/, prune/): reasoner 22.6 -> 20.2 s, load 3.67 -> 2.82 s, severity+label 6/6.
# Check: chaos 2 + fastcheck + chat check; any failure -> previous APK + profile. Never reboots. Log: deploy8/deploy.log
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency; I=$M/deploy8; mkdir -p $I/known_good
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; MM=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; BIN=/data/local/tmp/llama.cpp/bin
exec >> $I/deploy.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
setp(){ f=$1; k=$2; v=$3; grep -v "^$k=" $f > $f.t; echo "$k=$v" >> $f.t; mv $f.t $f; }
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x5p htpd_v8x5 htpd_v8x4 htpd_v8x3 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL $(ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)") after $i s; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; c=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)
    [ "${c:-0}" -gt "${n0:-0}" ] && return 0; [ "${c:-0}" -ge 1 ] && [ "${c:-0}" -lt "${n0:-0}" ] && return 0; done; return 1; }

echo "# Deploy 8: pruned head + v8x5 + AI-so-far UI ($(TZ=Asia/Kolkata date +%H:%M) IST)" > $I/STATUS.md
for f in $BIN/htpd_v8x5p /data/local/tmp/llama.cpp/lib/libllama_p.so /data/local/tmp/gpu/rsn_v1_q4_0_keep.gguf; do
  [ -n "$(sh_ "ls $f 2>/dev/null")" ] || { st "- ABORT: missing $f"; exit 1; }; done
[ "$(sh_ "md5sum $BIN/htpd_v8x5p" | cut -c1-32)" = "$(cut -c1-32 $M/v8x5p/htpd.md5)" ] || { st "- ABORT: htpd_v8x5p md5"; exit 1; }
p=$(sh_ 'pm path com.iiith.smartcityedge' | head -1 | sed 's/^package://'); $A pull "$p" "$(w $I/known_good/app.apk)" > /dev/null
sh_ "cat $W/htpd_profile" > $I/known_good/htpd_profile; cp $I/known_good/htpd_profile $I/profile.new
setp $I/profile.new bin $BIN/htpd_v8x5p
setp $I/profile.new reasoner_model /data/local/tmp/gpu/rsn_v1_q4_0_keep.gguf
r=$(stop_app); log "stop $r"
if [ "$r" != STOPPED ] || [ ! -s $I/known_good/app.apk ]; then st "- NOT DEPLOYED: app not stopped or snapshot missing"; start_app; exit 0; fi
$A install -r -d "$(w $M/apk/SmartCityEdge.new.apk)" | tail -1
$A push "$(w $I/profile.new)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
ok=1; start_app || ok=0; sleep 20
if [ $ok = 1 ]; then
  (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); crc=$?
  fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
  log "chaos rc=$crc fastcheck rc=$frc $fc"; [ $crc = 0 ] && [ $frc = 0 ] || ok=0
fi
if [ $ok = 1 ]; then
  sh_ "curl -s -X POST http://127.0.0.1:8000/api/chat/warm" > /dev/null; sleep 15
  python3 $MM/chatcheck.py "How many incidents were there today?" "Which sensors look faulty right now?" "What should I check first in the server room?" > $I/chat.txt
  while read l; do st "- chat: $l"; done < $I/chat.txt
  grep -q "^FAIL" $I/chat.txt && ok=0
fi
if [ $ok = 1 ]; then
  st "- DEPLOYED: APK $(md5sum $M/apk/SmartCityEdge.new.apk | cut -c1-8), bin htpd_v8x5p, reasoner rsn_v1_q4_0_keep; chaos 2 rc=0; fastcheck $fc"
  sh_ "grep -E 'pruned lm_head|load phases|step profile|reason 3 streams' $W/state/htpd.log | tail -6" | while read l; do st "- htpd: $l"; done
else
  stop_app > /dev/null; $A install -r -d "$(w $I/known_good/app.apk)" | tail -1
  $A push "$(w $I/known_good/htpd_profile)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
  start_app; st "- FAILED (chaos rc=$crc fastcheck rc=$frc) -> previous APK + profile restored"
fi
st "- board now: $(sh_ "grep -E '^(bin|reasoner_model|reasoner_split)=' $W/htpd_profile" | tr '\n' ' ')"
log "=== deploy8 done"
