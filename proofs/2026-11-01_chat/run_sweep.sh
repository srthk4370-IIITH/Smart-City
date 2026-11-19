#!/bin/bash
# usage: bash run_sweep.sh <tag>   -> sweep<tag>.jsonl + inc snapshots
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-01_chat; A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; cd $D
$A shell 'curl -s -m 20 http://127.0.0.1:8000/api/incidents' > inc_sweep$1_start.json
$A shell 'curl -s -m 20 http://127.0.0.1:8000/api/sensors' > sensors_sweep$1_start.json
$A shell 'curl -s -m 20 http://127.0.0.1:8000/api/status' > status_sweep$1_start.json
$A shell "curl -s -X POST http://127.0.0.1:8000/api/chat/warm" > /dev/null; sleep 15
python3 -I sweep.py questions.json sweep$1.jsonl
$A shell 'curl -s -m 20 http://127.0.0.1:8000/api/incidents' > inc_sweep$1_end.json
$A shell 'curl -s -m 20 http://127.0.0.1:8000/api/status' > status_sweep$1_end.json
echo ALLDONE
