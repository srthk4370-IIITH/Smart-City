#!/bin/bash
# rsn_v3 chat data pipeline (WSL python3, stdlib only). Usage: wsl bash /mnt/c/.../2026-10-29_rsn_v3/pipeline/run_all.sh
set -e
cd "$(dirname "$0")"
python3 -B make_store_v3.py | tail -c 400; echo  # -> ../data/train_store_v3.sqlite (copy of the round-1 store + today/yesterday + noise)
python3 -B make_tools_v4.py                      # -> tools_v4.json
python3 -B parity_py.py                          # -> parity_out_py.json (Go side: backend chat_tools_v3_parity_test.go)
python3 -B gen_chat_v3.py --n 8000 --n-dev 300   # -> ../data/chat3_{train,dev}.jsonl + chat3_manifest.json (~2 min)
python3 -B verify_chat.py --selftest --out ../data/chat3_verify_selftest.json | tail -1
