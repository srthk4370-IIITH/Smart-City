#!/usr/bin/env bash
# 2026-10-31 deploy19: htpd_v9d = v9c + live draft corpus (HTPD_REASON_CORPUS_LIVE: every complete split report is added
# to the in-memory corpus and appended to reason_corpus_live.jsonl) + the draft corpus rebuilt with the app's own reasoner
# reports (reason_corpus_v2.jsonl = corpus_real_all, 576 docs). Lab live_ab2 (6 held-out real app incidents):
# reasoner 11.83 -> 9.61 s, sev+label 8/8. Extra env from the klong_ab window: $XENV (empty = K8 as deploy18).
# Rollback = deploy19/known_good = the live deploy18 state pulled from the board (APK + profile); the old corpus file stays.
# Check: chaos 2 + fastcheck x2 + chat check; any chaos/fastcheck failure -> previous APK + profile. Never reboots.
# usage (WSL): XENV="..." bash deploy19.sh
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency; I=$M/deploy19; mkdir -p $I/known_good
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; MM=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master
C=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_latency/corpus/corpus_real_all.jsonl; CMD5=93daf8775c671eea37193bce599ba0e9
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; BIN=/data/local/tmp/llama.cpp/bin
exec >> $I/deploy.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
setp(){ f=$1; k=$2; v=$3; grep -v "^$k=" $f > $f.t; echo "$k=$v" >> $f.t; mv $f.t $f; }
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9d htpd_v9c htpd_v9b htpd_v9 htpd_v8x5p htpd_v8x5 htpd_v8x4 htpd_v8x3 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL $(ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)") after $i s; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; c=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)
    [ "${c:-0}" -gt "${n0:-0}" ] && return 0; [ "${c:-0}" -ge 1 ] && [ "${c:-0}" -lt "${n0:-0}" ] && return 0; done; return 1; }

echo "# Deploy 19 (htpd_v9d: live draft corpus + corpus with the app's reports; XENV [$XENV]) ($(TZ=Asia/Kolkata date +%H:%M) IST)" > $I/STATUS.md
for f in $BIN/htpd_v9d /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf; do
  [ -n "$(sh_ "ls $f 2>/dev/null")" ] || { st "- ABORT: missing $f"; exit 1; }; done
[ "$(sh_ "md5sum $BIN/htpd_v9d" | cut -c1-32)" = 73ae89e2e8d2ac8bc67a6b9839950f94 ] || { st "- ABORT: htpd_v9d md5"; exit 1; }
[ "$(md5sum < $C | cut -c1-32)" = $CMD5 ] || { st "- ABORT: local corpus md5"; exit 1; }
$A pull "$(sh_ "pm path com.iiith.smartcityedge" | sed "s/^package://")" "$(w $I/known_good/app.apk)" > /dev/null
[ "$(sh_ "md5sum /data/local/tmp/llama.cpp/lib_rp29/libggml-hexagon.so" | cut -c1-32)" = c4e4598412e54469e9f387935de595bb ] || { st "- ABORT: lib_rp29 md5"; exit 1; }
$A pull $W/htpd_profile "$(w $I/known_good/htpd_profile)" > /dev/null; cp $I/known_good/htpd_profile $I/profile.new
setp $I/profile.new bin $BIN/htpd_v9d
e=$(grep "^env=" $I/profile.new | sed "s/^env=//; s/ *HTPD_REASON_SPLIT_SPEC=[^ ]*//; s/ *HTPD_REASON_SPEC_MIN=[^ ]*//; s/ *HTPD_REASON_CORPUS=[^ ]*//; s/ *HTPD_REASON_SPEC_ALIGN=[^ ]*//; s/ *HTPD_REASON_CORPUS_LIVE=[^ ]*//; s/ *HTPD_REASON_SPEC_KLONG=[^ ]*//; s/ *HTPD_REASON_SPEC_ROWS=[^ ]*//")
setp $I/profile.new env "$e HTPD_REASON_SPLIT_SPEC=8 HTPD_REASON_SPEC_MIN=2 HTPD_REASON_SPEC_ALIGN=1 HTPD_REASON_CORPUS=$W/reason_corpus_v2.jsonl HTPD_REASON_CORPUS_LIVE=$W/reason_corpus_live.jsonl $XENV"
r=$(stop_app); log "stop $r"
if [ "$r" != STOPPED ] || [ ! -s $I/known_good/app.apk ]; then st "- NOT DEPLOYED: app not stopped or snapshot missing"; start_app; exit 0; fi
$A push "$(w $C)" $W/reason_corpus_v2.jsonl.part > /dev/null
if [ "$(sh_ "md5sum $W/reason_corpus_v2.jsonl.part" | cut -c1-32)" != $CMD5 ]; then st "- NOT DEPLOYED: corpus push md5"; start_app; exit 0; fi
sh_ "mv -f $W/reason_corpus_v2.jsonl.part $W/reason_corpus_v2.jsonl"
$A push "$(w $I/profile.new)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
ok=1; start_app || ok=0; sleep 20
if [ $ok = 1 ]; then
  (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); crc=$?
  fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
  log "chaos rc=$crc fastcheck rc=$frc $fc"; [ $crc = 0 ] && [ $frc = 0 ] || ok=0
fi
if [ $ok = 1 ]; then  # second fastcheck: the same incident again (the live corpus now holds the first one's report)
  fc2=$(cd $RF/scripts && python3 -I fastcheck.py); frc2=$?
  log "fastcheck2 rc=$frc2 $fc2"; [ $frc2 = 0 ] || ok=0
fi
if [ $ok = 1 ]; then
  sh_ "curl -s -X POST http://127.0.0.1:8000/api/chat/warm" > /dev/null; sleep 15
  python3 $MM/chatcheck.py "What if occupancy increases by 50%, impact on other domains" "List the incidents" "How many incidents were there today?" > $I/chat.txt
  while read l; do st "- chat: $l"; done < $I/chat.txt
  grep -qE "^FAIL|error True|could not find an answer" $I/chat.txt && st "- CHAT WARNING: see chat lines (owner: fix forward, no rollback for chat)"
fi
if [ $ok = 1 ]; then
  st "- DEPLOYED: bin htpd_v9d (live corpus) + reason_corpus_v2 + lib_rp29, APK unchanged; chaos 2 rc=0; fastcheck $fc; fastcheck2 $fc2"
  sh_ "grep -E 'split-spec|live corpus|load phases|step profile|reason 3 streams' $W/state/htpd.log | tail -12" | while read l; do st "- htpd: $l"; done
else
  stop_app > /dev/null; $A install -r -d "$(w $I/known_good/app.apk)" | tail -1
  $A push "$(w $I/known_good/htpd_profile)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
  start_app; st "- FAILED (chaos rc=$crc fastcheck rc=$frc/$frc2) -> previous APK + profile restored"
fi
st "- board now: $(sh_ "grep -E '^(bin|reasoner_model|reasoner_split|env)=' $W/htpd_profile" | tr '\n' ' ')"
log "=== deploy19 done"
