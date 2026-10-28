#!/usr/bin/env bash
# Interleaved v6 vs lean v7 (cap 160 + JSON abort 2 + streaming), NSP below 50 C before each run, ABAB x2.
set -uo pipefail
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
cool() { for i in $(seq 1 90); do t=$(MSYS_NO_PATHCONV=1 "$ADB" shell cat /sys/class/thermal/thermal_zone30/temp | tr -d '\r'); [ "${t:-99000}" -lt 50000 ] && { echo "nsp ${t}"; return; }; sleep 10; done; echo "still hot ${t}"; }
L="HTPD_AGENT_MAX_NEW=160 HTPD_JSON_ABORT=2"
for r in 1 2; do
  echo "=== $(date +%T) V6r$r"; cool; bash htpd_ab.sh htpd "--agents 10 --agent-ctx 1280" ""; py -3 ab_v2.py V6r$r --only B1,B4,B8,B13,M10 --base V6
  echo "=== $(date +%T) L7r$r"; cool; bash htpd_ab.sh htpd_v7 "--agents 10 --agent-ctx 1280" "$L"; py -3 ab_v2.py L7r$r --only B1,B4,B8,B13,M10 --base V6 --stream
done
bash htpd_ab.sh stop
echo "=== $(date +%T) done"
