#!/usr/bin/env bash
# smoke test of the build on small trial data (temp; build/ is scratch)
set -euo pipefail
B=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/build
for s in train test dev; do bash $B/../../2026-11-02_2b_r2/tools/go_gate.sh $B/inc/go_$s.jsonl $B/inc/$s.jsonl | grep "r2 gate" || true; done
cd $B/../tools && nice -n 15 python3 -B build_r4.py --replay-inc 300 --replay-chat 300 2>&1 | tail -4 | cut -c1-900
