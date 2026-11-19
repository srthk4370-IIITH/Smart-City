#!/usr/bin/env bash
# full r4 build (CPU only, nice 15): store -> incidents (+Go gate) -> chat records -> verified rows -> final files + tokens + MD5SUMS
# usage: bash run_r4.sh   (log via detach.sh: ~/detached/r4build.log)
set -euo pipefail
cd "$(dirname "$0")"
T=$(pwd); B=$T/../build; F=$T/../data/final
GATE=$T/../../2026-11-02_2b_r2/tools/go_gate.sh
free -m | head -2
[ -f $B/store_r4/device_store_r4.sqlite ] || nice -n 15 python3 -B make_store_r4.py
[ -f $B/inc/go_dev.jsonl ] && [ "${R4_REGEN_INC:-0}" = 0 ] || nice -n 15 python3 -B gen_r4_inc.py --out $B/inc --n 9300 --n-test 720 --n-dev 60 --seed 41112
[ "${R4_REGEN_INC:-0}" = 0 ] && [ -f $B/inc/go_dev.jsonl ] || for s in train test dev; do bash $GATE $B/inc/go_$s.jsonl $B/inc/$s.jsonl; done
nice -n 15 python3 -B gen_chat_r4.py --n-x 2600 --n-fix 3700 --n-test-x 700 --n-test-fix 300 --n-dev 60 --seed 41114 --out $B/records
free -m | head -2
nice -n 15 python3 -B build_r4.py
nice -n 15 ~/venvs/rsn/bin/python -B tok_r4.py
(cd $F && md5sum *.jsonl *.json | grep -v MD5SUMS > MD5SUMS)
echo R4_DONE
