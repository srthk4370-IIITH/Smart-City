#!/usr/bin/env bash
# 2026-10-31 deploy20: htpd_v9e = v9d + agent draft index (HTPD_AGENT_NGMAX=8: n-gram orders 8..1; HTPD_AGENT_RECENT_MAX=500:
# hashed index of the last 500 agent outputs instead of a linear scan of 64; HTPD_AGENT_CORPUS: seeded at start from
# agent_corpus.txt = the app's 1134 past agent outputs (token ids), every new agent output appended). Drafts are verified
# and rows per step are unchanged, so agent outputs are unchanged. Reasoner settings = deploy19 (kept from the profile).
# Lab: proofs/2026-10-31_agents_latency/VERDICT.md. Rollback = deploy20/known_good (live deploy19 profile + APK from the board).
# Check: chaos 2 + fastcheck x2 + chat check; any chaos/fastcheck failure -> previous APK + profile. Never reboots.
# usage (WSL): bash deploy20.sh
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency; I=$M/deploy20; mkdir -p $I/known_good
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; MM=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master
C=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_agents_latency/agent_corpus_all.txt; CMD5=a136e22adca3a23d01ba78cad943dd19
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; BIN=/data/local/tmp/llama.cpp/bin
exec >> $I/deploy.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
setp(){ f=$1; k=$2; v=$3; grep -v "^$k=" $f > $f.t; echo "$k=$v" >> $f.t; mv $f.t $f; }
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9e htpd_v9d htpd_v9c htpd_v9b htpd_v9 htpd_v8x5p htpd_v8x5 htpd_v8x4 htpd_v8x3 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL $(ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)") after $i s; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; c=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)
    [ "${c:-0}" -gt "${n0:-0}" ] && return 0; [ "${c:-0}" -ge 1 ] && [ "${c:-0}" -lt "${n0:-0}" ] && return 0; done; return 1; }

echo "# Deploy 20 (htpd_v9e: agent draft index + agent corpus) ($(TZ=Asia/Kolkata date +%H:%M) IST)" > $I/STATUS.md
for f in $BIN/htpd_v9e /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf; do
  [ -n "$(sh_ "ls $f 2>/dev/null")" ] || { st "- ABORT: missing $f"; exit 1; }; done
[ "$(sh_ "md5sum $BIN/htpd_v9e" | cut -c1-32)" = 0080ce237487c898b7fe2d4fe71303af ] || { st "- ABORT: htpd_v9e md5"; exit 1; }
[ "$(md5sum < $C | cut -c1-32)" = $CMD5 ] || { st "- ABORT: local corpus md5"; exit 1; }
$A pull "$(sh_ "pm path com.iiith.smartcityedge" | sed "s/^package://")" "$(w $I/known_good/app.apk)" > /dev/null
[ "$(sh_ "md5sum /data/local/tmp/llama.cpp/lib_rp29/libggml-hexagon.so" | cut -c1-32)" = c4e4598412e54469e9f387935de595bb ] || { st "- ABORT: lib_rp29 md5"; exit 1; }
$A pull $W/htpd_profile "$(w $I/known_good/htpd_profile)" > /dev/null; cp $I/known_good/htpd_profile $I/profile.new
setp $I/profile.new bin $BIN/htpd_v9e
e=$(grep "^env=" $I/profile.new | sed "s/^env=//; s/ *HTPD_AGENT_NGMAX=[^ ]*//; s/ *HTPD_AGENT_RECENT_MAX=[^ ]*//; s/ *HTPD_AGENT_CORPUS=[^ ]*//")
setp $I/profile.new env "$e HTPD_AGENT_NGMAX=8 HTPD_AGENT_RECENT_MAX=500 HTPD_AGENT_CORPUS=$W/agent_corpus.txt"
r=$(stop_app); log "stop $r"
if [ "$r" != STOPPED ] || [ ! -s $I/known_good/app.apk ]; then st "- NOT DEPLOYED: app not stopped or snapshot missing"; start_app; exit 0; fi
$A push "$(w $C)" $W/agent_corpus.txt.part > /dev/null
if [ "$(sh_ "md5sum $W/agent_corpus.txt.part" | cut -c1-32)" != $CMD5 ]; then st "- NOT DEPLOYED: corpus push md5"; start_app; exit 0; fi
sh_ "mv -f $W/agent_corpus.txt.part $W/agent_corpus.txt"
$A push "$(w $I/profile.new)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
ok=1; start_app || ok=0; sleep 20
if [ $ok = 1 ]; then
  (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); crc=$?
  fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
  log "chaos rc=$crc fastcheck rc=$frc $fc"; [ $crc = 0 ] && [ $frc = 0 ] || ok=0
fi
if [ $ok = 1 ]; then  # second fastcheck: the same incident again
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
  st "- DEPLOYED: bin htpd_v9e (agent draft index + agent_corpus.txt), reasoner env as deploy19, APK unchanged; chaos 2 rc=0; fastcheck $fc; fastcheck2 $fc2"
  sh_ "grep -E 'v9e agent|draft steps|split-spec|load phases|reasoner loaded in' $W/state/htpd.log | tail -12" | while read l; do st "- htpd: $l"; done
else
  stop_app > /dev/null; $A install -r -d "$(w $I/known_good/app.apk)" | tail -1
  $A push "$(w $I/known_good/htpd_profile)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
  start_app; st "- FAILED (chaos rc=$crc fastcheck rc=$frc/$frc2) -> previous APK + profile restored"
fi
st "- board now: $(sh_ "grep -E '^(bin|reasoner_model|reasoner_split|env)=' $W/htpd_profile" | tr '\n' ' ')"
log "=== deploy20 done"
