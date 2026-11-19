#!/usr/bin/env bash
# full r3 build (CPU only): records -> verified rows -> final files. Log: ~/detached/r3build.log
set -euo pipefail
cd "$(dirname "$0")"
python3 make_store_r3.py
python3 make_tools_r3.py
python3 parity_r3.py
python3 gen_chat_r3.py --n-new 9000 --n-old 4800 --n-test 1100 --seed 1106
python3 build_r3.py
echo R3_DONE
