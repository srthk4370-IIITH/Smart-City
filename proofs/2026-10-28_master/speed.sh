#!/usr/bin/env bash
# 2026-10-29 ~11:50 IST (owner: "reduce latency as much as possible", eval 13:00). Standalone (detach.sh speed).
#  S0 laptop: APK with chat keep-warm + reasoner_pad support (Go); htpd_v8x4 (row padding, env HTPD_PAD_ROWS) already built.
#  S1 board A/B (ab_board.sh, q10-q15 + warm-up): v8x3 split-3 vs v8x4 pad 6 vs v8x4 pad 5 (4 reason streams).
#  S2 deploy: APK always (chat warm); padding only if >= 5% faster with parse n/n and severity+label identical on >= n-1.
#     App check (chaos 2 + fastcheck) + timed chat check; any failure -> previous APK + profile. Never reboots.
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; I=$M/speed; K=$M/BOARD_LOCK; mkdir -p $I/known_good
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; APP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; RB=/data/local/tmp/rfast; BIN=/data/local/tmp/llama.cpp/bin
exec >> $I/speed.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
setp(){ f=$1; k=$2; v=$3; grep -v "^$k=" $f > $f.t; echo "$k=$v" >> $f.t; mv $f.t $f; }
CUT=$(date -d "2026-10-29 07:05 UTC" +%s)
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x4 htpd_v8x3 htpd_v8x2 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; c=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)
    [ "${c:-0}" -gt "${n0:-0}" ] && return 0; [ "${c:-0}" -ge 1 ] && [ "${c:-0}" -lt "${n0:-0}" ] && return 0; done; return 1; }

echo "# Speed build ($(TZ=Asia/Kolkata date +%H:%M) IST start)" > $I/STATUS.md
# S0 build (laptop)
cp $APP/device/edge-agent $I/slot.edge-agent; cp $APP/android/out/SmartCityEdge.apk $I/slot.apk
if bash $APP/build.sh > $I/build.log 2>&1 && bash $APP/android/build_apk.sh > $I/apk_build.log 2>&1; then
  cp $APP/android/out/SmartCityEdge.apk $I/SmartCityEdge.new.apk
  st "- S0 APK $(md5sum $I/SmartCityEdge.new.apk | cut -c1-8), edge-agent $(md5sum $APP/device/edge-agent | cut -c1-8); htpd_v8x4 $(cut -c1-8 $M/v8x4/htpd.md5)"
else st "- S0 build FAILED"; exit 1; fi
cp $I/slot.edge-agent $APP/device/edge-agent; cp $I/slot.apk $APP/android/out/SmartCityEdge.apk
while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do sleep 20; done
echo speed > $K; trap 'rm -f $K' EXIT

# S1 push htpd_v8x4 (.part + md5 + mv; different file name from the running htpd) and board A/B
m=$(cut -c1-32 $M/v8x4/htpd.md5)
$A push "$(w $M/v8x4/htpd)" $BIN/htpd_v8x4.part > /dev/null
if [ "$(sh_ "md5sum $BIN/htpd_v8x4.part" | cut -c1-32)" = "$m" ]; then sh_ "chmod 755 $BIN/htpd_v8x4.part; mv -f $BIN/htpd_v8x4.part $BIN/htpd_v8x4"
else st "- S1 push failed (md5)"; fi
sed -i 's/\r$//' $RF/scripts/ab_board.sh
$A push "$(w $RF/scripts/ab_board.sh)" $RB/ab_board.sh > /dev/null
printf '#!/system/bin/sh\ncd %s; [ -d ab ] && mv ab ab_prev_$(date +%%H%%M%%S)\nREQS="10 10 11 12 13 14 15" sh ab_board.sh "spxa,htpd_v8x3,-,GGML_HEXAGON_OPPOLL=1" "sppa,htpd_v8x4,-,GGML_HEXAGON_OPPOLL=1 HTPD_PAD_ROWS=6" "sppb,htpd_v8x4,-,GGML_HEXAGON_OPPOLL=1 HTPD_PAD_ROWS=5"\n' $RB > $I/run.sh
$A push "$(w $I/run.sh)" $RB/run_speed.sh > /dev/null
$A shell "cd $RB; (setsid nohup sh run_speed.sh > /dev/null 2>&1 < /dev/null &)"
log "S1 started"; sleep 120
t0=$(date +%s)
until sh_ "tail -1 $RB/ab/ab.log 2>/dev/null" | grep -q "=== ab done" || [ $(( $(date +%s) - t0 )) -gt 2400 ]; do sleep 20; done
rm -rf $I/raw; $A pull $RB/ab "$(w $I)" > /dev/null; mv $I/ab $I/raw
python3 $M/speed_ab.py $I/raw > $I/ab_result.txt
st "- S1 A/B: $(grep -E '^(base|sppa|sppb)' $I/ab_result.txt | tr '\n' ' ')"
PAD=$(grep -oE "^BEST [0-9]+" $I/ab_result.txt | cut -d' ' -f2); PAD=${PAD:-0}

# S2 deploy
if [ $(date +%s) -ge $CUT ]; then
  st "- S2 skipped: after 12:35 IST"; sh_ 'ps -A -o NAME= | grep -q edge-agent' || start_app; exit 0
fi
p=$(sh_ 'pm path com.iiith.smartcityedge' | head -1 | sed 's/^package://'); $A pull "$p" "$(w $I/known_good/app.apk)" > /dev/null
sh_ "cat $W/htpd_profile" > $I/known_good/htpd_profile; cp $I/known_good/htpd_profile $I/profile.new
if [ "$PAD" -gt 0 ]; then
  setp $I/profile.new bin $BIN/htpd_v8x4; setp $I/profile.new reasoner_pad 1
  e=$(grep '^env=' $I/known_good/htpd_profile | cut -d= -f2-); setp $I/profile.new env "$e HTPD_PAD_ROWS=$PAD"
fi
r=$(stop_app); log "S2 stop $r"
if [ "$r" != STOPPED ] || [ ! -s $I/known_good/app.apk ]; then st "- S2 NOT DEPLOYED: app not stopped or snapshot missing"; start_app; exit 0; fi
$A install -r -d "$(w $I/SmartCityEdge.new.apk)" | tail -1
$A push "$(w $I/profile.new)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
SEEDMD5=$(md5sum $M/rag_seed/rag_seed.json | cut -c1-32)
[ "$(sh_ "md5sum $W/data/rag_seed.json 2>/dev/null" | cut -c1-32)" = "$SEEDMD5" ] || { $A push "$(w $M/rag_seed/rag_seed.json)" $W/data/rag_seed.json > /dev/null; log "seed re-pushed"; }
ok=1; start_app || ok=0; sleep 20
if [ $ok = 1 ]; then
  (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); crc=$?
  fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
  log "S2 chaos rc=$crc fastcheck rc=$frc $fc"; [ $crc = 0 ] && [ $frc = 0 ] || ok=0
fi
if [ $ok = 1 ]; then
  st "- S2 DEPLOYED: edge-agent $(sh_ "md5sum $W/edge-agent" | cut -c1-8), pad rows ${PAD} (0 = off); chaos 2 rc=0; fastcheck $fc"
  sh_ "curl -s -X POST http://127.0.0.1:8000/api/chat/warm" > /dev/null; sleep 15
  python3 $M/chatcheck.py "How many incidents were there today?" "Which domains have open incidents right now?" | while read l; do st "- chat check (warm): $l"; done
  sh_ "grep -E 'reason padded|reason 3 streams|reason 1 streams|reasoner loaded' $W/state/htpd.log | tail -6" | while read l; do st "- htpd: $l"; done
else
  stop_app > /dev/null; $A install -r -d "$(w $I/known_good/app.apk)" | tail -1
  $A push "$(w $I/known_good/htpd_profile)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
  start_app; st "- S2 FAILED (chaos rc=$crc fastcheck rc=$frc) -> previous APK + profile restored"
fi
st "- board now: $(sh_ "md5sum $W/edge-agent; grep -E '^(bin|reasoner_split|reasoner_pad|env)=' $W/htpd_profile" | tr '\n' ' ')"
log "=== speed done"
