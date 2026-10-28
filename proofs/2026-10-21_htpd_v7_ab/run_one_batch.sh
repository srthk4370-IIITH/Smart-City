#!/usr/bin/env bash
# Fair ABAB: lean v7 at 10x1280 (13 agents = 10 + 3) vs 14x1024 with layouts (13 agents in one batch), NSP < 50 C.
set -uo pipefail
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
cool() { for i in $(seq 1 90); do t=$(MSYS_NO_PATHCONV=1 "$ADB" shell cat /sys/class/thermal/thermal_zone30/temp | tr -d '\r'); [ "${t:-99000}" -lt 50000 ] && { echo "nsp ${t}"; return; }; sleep 10; done; echo "still hot ${t}"; }
L="HTPD_AGENT_MAX_NEW=160 HTPD_JSON_ABORT=2"
for r in 1 2; do
  echo "=== $(date +%T) S10r$r"; cool; bash htpd_ab.sh htpd_v7 "--agents 10 --agent-ctx 1280" "$L"; py -3 ab_v2.py S10r$r --only B13,B8,M10 --base V6 --stream --max-batch 10
  echo "=== $(date +%T) O14r$r"; cool; bash htpd_ab.sh htpd_v7 "--agents 14 --agent-ctx 1024 --agent-layouts 14x1024,10x1280" "$L"; py -3 ab_v2.py O14r$r --only B13,B8,M10 --base V6 --stream --max-batch 14
done
bash htpd_ab.sh stop
echo "=== $(date +%T) done"
