#!/bin/bash
# deploy28 (split2 APK 46c14b58: chat on the 2B GPU, reports 4B NPU) re-run of all 120 earlier questions (sweep1, held-out, blind) then the final blind set (questions_blind2.json).
# bash run_d25.sh [sets...]   default: s1 heldout blind blind2
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-01_chat; A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; cd $D
declare -A Q=([s1]=questions.json [heldout]=questions_heldout.json [blind]=questions_blind.json [blind2]=questions_blind2.json)
declare -A T=([s1]=20_s1_d28 [heldout]=21_heldout_d28 [blind]=22_blind_d28 [blind2]=23_blind2_d28)
for s in ${@:-s1 heldout blind blind2}; do
  t=${T[$s]}; echo "=== $s -> sweep$t $(date)"
  for e in incidents sensors status live; do $A shell "curl -s -m 20 http://127.0.0.1:8000/api/$e" > ${e/incidents/inc}_sweep${t}_start.json; done
  $A shell "curl -s -X POST http://127.0.0.1:8000/api/chat/warm" > /dev/null; sleep 15
  python3 -I sweep.py ${Q[$s]} sweep$t.jsonl > sweep$t.log 2>&1
  for e in incidents sensors status live; do $A shell "curl -s -m 20 http://127.0.0.1:8000/api/$e" > ${e/incidents/inc}_sweep${t}_end.json; done
done
echo ALLDONE
