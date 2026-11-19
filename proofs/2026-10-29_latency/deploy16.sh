#!/usr/bin/env bash
# 2026-10-30 deploy16: htpd_v9 split-spec (K=8, m=2, corpus = 463 past board reports). Board A/B spec_ab: reasoner 23.3 -> 14.2 s,
# sev+label 6/6, text identity 3/6 (base vs itself 2/6). Libs stay lib_rp29. APK unchanged (deploy14 458cffb5).
# Rollback = deploy16/known_good = the live deploy15 state pulled from the board (APK + profile).
# Check: chaos 2 + fastcheck + chat check; any failure -> previous APK + profile. Never reboots. Log: deploy8/deploy.log
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency; I=$M/deploy16; mkdir -p $I/known_good
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; MM=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; BIN=/data/local/tmp/llama.cpp/bin
exec >> $I/deploy.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
setp(){ f=$1; k=$2; v=$3; grep -v "^$k=" $f > $f.t; echo "$k=$v" >> $f.t; mv $f.t $f; }
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9b htpd_v9 htpd_v8x5p htpd_v8x5 htpd_v8x4 htpd_v8x3 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL $(ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)") after $i s; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; c=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)
    [ "${c:-0}" -gt "${n0:-0}" ] && return 0; [ "${c:-0}" -ge 1 ] && [ "${c:-0}" -lt "${n0:-0}" ] && return 0; done; return 1; }

echo "# Deploy 16 (htpd_v9b: split-spec drafts on split requests only; chat back on the plain path) ($(TZ=Asia/Kolkata date +%H:%M) IST)" > $I/STATUS.md
for f in $BIN/htpd_v9b /data/local/tmp/smart_city_edge/reason_corpus.jsonl /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf; do
  [ -n "$(sh_ "ls $f 2>/dev/null")" ] || { st "- ABORT: missing $f"; exit 1; }; done
[ "$(sh_ "md5sum $BIN/htpd_v9b" | cut -c1-32)" = bc66d7d37eff1bcca4cc6686de640e30 ] || { st "- ABORT: htpd_v9b md5"; exit 1; }
$A pull "$(sh_ "pm path com.iiith.smartcityedge" | sed "s/^package://")" "$(w $I/known_good/app.apk)" > /dev/null
[ "$(sh_ "md5sum /data/local/tmp/llama.cpp/lib_rp29/libggml-hexagon.so" | cut -c1-32)" = c4e4598412e54469e9f387935de595bb ] || { st "- ABORT: lib_rp29 md5"; exit 1; }
$A pull $W/htpd_profile "$(w $I/known_good/htpd_profile)" > /dev/null; cp $I/known_good/htpd_profile $I/profile.new
setp $I/profile.new bin $BIN/htpd_v9b
e=$(grep "^env=" $I/profile.new | sed "s/^env=//; s/ *HTPD_REASON_SPLIT_SPEC=[^ ]*//; s/ *HTPD_REASON_SPEC_MIN=[^ ]*//; s/ *HTPD_REASON_CORPUS=[^ ]*//")
setp $I/profile.new env "$e HTPD_REASON_SPLIT_SPEC=8 HTPD_REASON_SPEC_MIN=2 HTPD_REASON_CORPUS=/data/local/tmp/smart_city_edge/reason_corpus.jsonl"
r=$(stop_app); log "stop $r"
if [ "$r" != STOPPED ] || [ ! -s $I/known_good/app.apk ]; then st "- NOT DEPLOYED: app not stopped or snapshot missing"; start_app; exit 0; fi
: # APK unchanged
$A push "$(w $I/profile.new)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
ok=1; start_app || ok=0; sleep 20
if [ $ok = 1 ]; then
  (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); crc=$?
  fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
  log "chaos rc=$crc fastcheck rc=$frc $fc"; [ $crc = 0 ] && [ $frc = 0 ] || ok=0
fi
if [ $ok = 1 ]; then
  sh_ "curl -s -X POST http://127.0.0.1:8000/api/chat/warm" > /dev/null; sleep 15
  python3 $MM/chatcheck.py "What if occupancy increases by 50%, impact on other domains" "List the incidents" "How many incidents were there today?" > $I/chat.txt
  while read l; do st "- chat: $l"; done < $I/chat.txt
  grep -qE "^FAIL|error True|could not find an answer" $I/chat.txt && st "- CHAT WARNING: see chat lines (owner: fix forward, no rollback for chat)"
fi
if [ $ok = 1 ]; then
  st "- DEPLOYED: APK $(md5sum $M/apk9/SmartCityEdge.new.apk | cut -c1-8), bin htpd_v9b split-spec K=8 (split only) + lib_rp29; chaos 2 rc=0; fastcheck $fc"
  sh_ "grep -E 'split-spec|load phases|step profile|reason 3 streams' $W/state/htpd.log | tail -6" | while read l; do st "- htpd: $l"; done
else
  stop_app > /dev/null; $A install -r -d "$(w $I/known_good/app.apk)" | tail -1
  $A push "$(w $I/known_good/htpd_profile)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
  start_app; st "- FAILED (chaos rc=$crc fastcheck rc=$frc) -> previous APK + profile restored"
fi
st "- board now: $(sh_ "grep -E '^(bin|reasoner_model|reasoner_split|env)=' $W/htpd_profile" | tr '\n' ' ')"
log "=== deploy16 done"
