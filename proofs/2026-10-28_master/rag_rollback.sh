#!/usr/bin/env bash
# roll back the retrieval-preliminary APK: reinstall the snapshot APK taken by rag_deploy.sh (models/profile unchanged). Never reboots.
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; B=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/rag_build; W=/data/local/tmp/smart_city_edge
r=$($A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x3 htpd_v8x2 htpd_v8r htpd_v8s htpd_v8t htpd_v8p htpd_v8p2 htpd_v7 htpd); do kill -TERM $p; done; i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done; sleep 30; echo done' | tr -d '\r')
$A install -r -d "$(wslpath -w $B/known_good/app.apk)" | tail -1; $A shell 'am start -n com.iiith.smartcityedge/.MainActivity' > /dev/null; sleep 60
$A shell "md5sum $W/edge-agent" | tr -d '\r'
