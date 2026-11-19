#!/usr/bin/env bash
# 2026-11-04 deploy28: EVAL-ONLY split. Chat runs on the 2B rsn_v3 r2 on the GPU (llama-server, chat dev v3 0.737 vs 0.477);
# reports and agents stay on the NPU (4B reasoner and ft_B50 3B, unchanged). The 4B stays the general model.
# Based on deploy27_apk.sh. Steps:
#  1. snapshot known_good (live APK e0ccda2b + profile)
#  2. stop chat_gpu, then the app
#  3. install the split2 APK 46c14b58 (= split d956b903 + GPU timeout 60 s, GPU keep-warm every 30 s; chat_url unset = same htpd requests as before)
#  4. chaos 2 + fastcheck: the APK on its own
#  5. split_on.sh (GPU server up -> chat_think=adaptive + chat_url)
#  6. fastcheck with the 2B resident on the GPU, plus a chat check with labels
# Chaos/fastcheck failure -> known_good APK + profile, GPU stopped.
# GPU chat failure -> split_off.sh (chat back on the 4B), a warning only (owner: chat problems = fix forward).
# Never reboots. Status: deploy28/STATUS.md. usage (WSL): bash deploy28_split.sh
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-04_split; I=$P/deploy28; mkdir -p $I/known_good
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; NP=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_night
NEW=$P/apk2/SmartCityEdge.split2.apk; S=/data/local/tmp/chatgpu
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge
exec >> $I/deploy.log 2>&1 < /dev/null
touch $NP/PAUSE; trap "rm -f $NP/PAUSE" EXIT; while [ -e $NP/BUSY ]; do sleep 5; done
log(){ echo "$(date -u +%FT%TZ) $*"; }
st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
stop_app(){ sh_ "sh $S/chat_gpu.sh stop" > /dev/null 2>&1
  sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9f htpd_v9e htpd_v9d htpd_v9c htpd_v9b htpd_v9 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL $(ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)") after $i s; else echo STOPPED; fi'; }
start_app(){ l0=$(sh_ "wc -l < $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; l=$(sh_ "wc -l < $W/state/htpd.log" | tail -1)
    if [ "${l:-0}" -lt "${l0:-0}" ]; then c=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)
    else c=$(sh_ "tail -n +$(( ${l0:-0} + 1 )) $W/state/htpd.log | grep -c 'htpd: ready in'" | tail -1); fi
    [ "${c:-0}" -ge 1 ] && return 0; done; return 1; }
tele(){ sh_ "echo avail=\$(awk '/MemAvailable/ {print int(\$2/1024)}' /proc/meminfo)MB t=\$(cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1 | cut -c1-2)C"; }

echo "# Deploy 28: eval-only split, 2B chat on the GPU, 4B reports on the NPU ($(TZ=Asia/Kolkata date +%H:%M) IST)" > $I/STATUS.md
[ -s $NEW ] && [ "$(md5sum $NEW | cut -c1-32)" = 46c14b58854db79ace170e62935d813d ] || { st "- ABORT: split APK missing or md5"; exit 1; }
[ "$(sh_ "md5sum /data/local/tmp/llama.cpp/lib_rp29/libggml-hexagon.so" | cut -c1-32)" = c4e4598412e54469e9f387935de595bb ] || { st "- ABORT: lib_rp29 md5"; exit 1; }
[ "$(sh_ "ls $S/llama-server $S/chat_gpu.sh /data/local/tmp/gpu/rsn_v3_2b_r2_q4_0.gguf 2>/dev/null | wc -l")" = 3 ] || { st "- ABORT: GPU files not on the board (run gpu_stage.sh first)"; exit 1; }
$A pull "$(sh_ "pm path com.iiith.smartcityedge" | sed "s/^package://")" "$(w $I/known_good/app.apk)" > /dev/null
$A pull $W/htpd_profile "$(w $I/known_good/htpd_profile)" > /dev/null
grep -qE '^(chat_url|chat_think)=' $I/known_good/htpd_profile && { st "- ABORT: known_good profile already has split keys"; exit 1; }
st "- snapshot: APK $(md5sum $I/known_good/app.apk | cut -c1-8), new APK $(md5sum $NEW | cut -c1-8)"
r=$(stop_app); log "stop $r"
if [ "$r" != STOPPED ] || [ ! -s $I/known_good/app.apk ] || [ ! -s $I/known_good/htpd_profile ]; then st "- NOT DEPLOYED: app not stopped or snapshot missing ($r)"; start_app; exit 0; fi
$A install -r -d "$(w $NEW)" | tail -1
ok=1; start_app || ok=0; sleep 20
if [ $ok = 1 ]; then
  (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); crc=$?
  fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
  st "- split APK alone (chat_url unset): chaos rc=$crc fastcheck rc=$frc $fc"; [ $crc = 0 ] && [ $frc = 0 ] || ok=0
fi
gpu=0
if [ $ok = 1 ]; then
  st "- before GPU: $(tele)"; on=$(bash $P/split_on.sh); st "- $on"; echo "$on" | grep -q "^split on" && gpu=1
  st "- GPU resident: $(tele)"
  fc2=$(cd $RF/scripts && python3 -I fastcheck.py); frc2=$?
  st "- fastcheck with 2B on GPU: rc=$frc2 $fc2 | $(tele)"; [ $frc2 = 0 ] || ok=0
fi
if [ $ok = 1 ]; then
  python3 $P/chatcheck2.py "Which domains have open incidents right now?" "CO2 theek hai KH level 3 pe?" "Close all open incidents." \
    "Has the KH level 2 AC unit 24 had repeated problems?" "Compare air quality and water incidents this week." \
    "Give me a quick status of the whole campus in two lines." > $I/chat.txt
  while read l; do st "- chat: $l"; done < $I/chat.txt
  st "- after chat: $(tele); guard kills: $(sh_ "grep -c 'GUARD KILL' $S/chat_gpu.log")"
  if [ $gpu = 1 ] && ! grep -q "model qwen3.5-2b rsn_v3 (gpu)" $I/chat.txt; then st "- CHAT WARNING: no GPU-labelled answer -> split_off"; gpu=0; fi
  grep -qE "^FAIL|error True" $I/chat.txt && { st "- CHAT WARNING: failed chat -> split_off"; gpu=0; }
  [ $gpu = 1 ] || st "- $(bash $P/split_off.sh)"
fi
if [ $ok = 1 ]; then
  st "- DEPLOYED: APK $(md5sum $NEW | cut -c1-8) (split), GPU chat $([ $gpu = 1 ] && echo ON || echo OFF, chat on 4B); chaos 2 rc=0; fastchecks ok"
else
  stop_app > /dev/null; $A install -r -d "$(w $I/known_good/app.apk)" | tail -1
  $A push "$(w $I/known_good/htpd_profile)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
  start_app; st "- FAILED (chaos rc=$crc fastcheck rc=$frc/${frc2:-}) -> previous APK + profile restored, GPU stopped"
fi
st "- board now: APK $(sh_ "md5sum \$(pm path com.iiith.smartcityedge | sed s/^package://)" | cut -c1-8); $(sh_ "grep -E '^(reasoner_model|chat_url|chat_think)=' $W/htpd_profile" | tr '\n' ' '); llama-server $(sh_ "pidof llama-server || echo none")"
log "=== deploy28 done"
