#!/usr/bin/env bash
set -euo pipefail
Q=/mnt/c/Users/hp/Desktop/qidk; D=$Q/proofs/2026-11-02_2b_r2/data; mkdir -p "$D/test"
python3 -B $Q/proofs/2026-11-02_2b_r2/tools/gen_test_inc.py --out "$D/test/test_incidents_gen.jsonl" --n 640 --seed 6161 \
  --exclude $Q/proofs/2026-10-29_rsn_v3/kaggle/build/r2x/data/incidents3_train.jsonl $Q/proofs/2026-10-29_rsn_v3/kaggle/build/r1/heldout/incidents_rwh2.jsonl \
            $Q/proofs/2026-10-29_rsn_v3/kaggle/build/r1/data/incidents3_train.jsonl "$D/targeted/train.jsonl" "$D/heat_r2b/train.jsonl" \
  > "$D/test/test_incidents_gen.log"
cat "$D/test/test_incidents_gen.log"
