#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
cool() { for i in $(seq 1 60); do t=$(MSYS_NO_PATHCONV=1 "$ADB" shell cat /sys/class/thermal/thermal_zone30/temp | tr -d '\r'); [ "${t:-99000}" -lt 50000 ] && { echo "board ${t}"; return; }; sleep 10; done; echo "still hot ${t}"; }
RD="HTPD_ROLE_DRAFT=1 HTPD_ROLE_DRAFT_FILE=/data/local/tmp/llama.cpp/role_draft_v2.jsonl"
run() { tag=$1; bin=$2; args=$3; envs=$4; shift 4; echo "=== $(date +%T) $tag"; cool; bash htpd_ab.sh "$bin" "$args" "$envs"; py -3 ab_v2.py "$tag" "$@"; }
trap 'bash htpd_ab.sh stop' EXIT
run V6 htpd "--agents 10 --agent-ctx 1280" ""
run A0 htpd_v7 "--agents 10 --agent-ctx 1280" "" --base V6
run A1 htpd_v7 "--agents 10 --agent-ctx 1280" "$RD" --base V6
run A2 htpd_v7 "--agents 10 --agent-ctx 1280" "$RD HTPD_LOGITS_READ=1" --base V6
run A3 htpd_v7 "--agents 10 --agent-ctx 1280" "$RD HTPD_LOGITS_READ=1 HTPD_AGENT_MAX_NEW=160 HTPD_JSON_ABORT=2" --base V6
run A5 htpd_v7 "--agents 10 --agent-ctx 1280" "$RD HTPD_LOGITS_READ=1 HTPD_AGENT_MAX_NEW=160 HTPD_JSON_ABORT=2" --base V6 --stream
run A6 htpd_v7 "--agents 14 --agent-ctx 1024 --agent-layouts 14x1024,10x1280" "$RD HTPD_LOGITS_READ=1 HTPD_AGENT_MAX_NEW=160 HTPD_JSON_ABORT=2" --base V6 --stream --max-batch 14
MSYS_NO_PATHCONV=1 "$ADB" logcat -d | grep -iE "fastrpc|dma_buf" | tail -20 > logcat_a6.txt
echo "=== $(date +%T) done"
