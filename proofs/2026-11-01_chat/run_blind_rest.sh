#!/bin/bash
# blind sweep 7 resume (Q12-40) on deploy24 r2 -> sweep7_blind.jsonl
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-01_chat; A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; cd $D; T=7_blind
for e in incidents sensors status live; do $A shell "curl -s -m 20 http://127.0.0.1:8000/api/$e" > ${e/incidents/inc}_sweep${T}_rest_start.json; done
$A shell "curl -s -X POST http://127.0.0.1:8000/api/chat/warm" > /dev/null; sleep 15
python3 -I sweep.py questions_blind.json sweep$T.jsonl 12
for e in incidents sensors status live; do $A shell "curl -s -m 20 http://127.0.0.1:8000/api/$e" > ${e/incidents/inc}_sweep${T}_rest_end.json; done
echo ALLDONE
