#!/usr/bin/env bash
# Roll the board back to the known-good snapshot taken by final.sh F0 (profile + installed APK). WSL. Never reboots.
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; F=$M/final/known_good; A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
W=/data/local/tmp/smart_city_edge; [ -s $F/app.apk ] && [ -s $F/htpd_profile ] || { echo "no known-good snapshot"; exit 2; }
r=$($A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -TERM -f "[b]in/htpd"
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL; else echo STOPPED; fi' | tr -d '\r')
[ "$r" = STOPPED ] || { echo "NPU client still running: abort"; exit 3; }
$A push "$(wslpath -w $F/htpd_profile)" $W/htpd_profile.part > /dev/null && $A shell "mv -f $W/htpd_profile.part $W/htpd_profile"
$A install -r -d "$(wslpath -w $F/app.apk)" | tail -1
$A shell 'am start -n com.iiith.smartcityedge/.MainActivity' > /dev/null; sleep 60
$A shell "md5sum $W/edge-agent; grep -E 'ready in|reasoner slot' $W/state/htpd.log | tail -2; grep -E '^(bin|model|reasoner_model|reasoner_split)=' $W/htpd_profile" | tr -d '\r'
