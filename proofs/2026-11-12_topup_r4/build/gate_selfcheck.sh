#!/usr/bin/env bash
# r3-2800 vs itself through gate_score_r4.py (cached outputs only; no model, no GPU)
Q=/mnt/c/Users/hp/Desktop/qidk/proofs
G=$Q/2026-11-06_4b_local/post/gate_r3
cd $Q/2026-11-12_topup_r4/train/post
python3 -B gate_score_r4.py --stage final --out $Q/2026-11-12_topup_r4/build/gate_selfcheck --new rsn_v3_4b_r3 --base rsn_v3_4b_r3 \
  --rwh2 $Q/2026-10-29_rsn_v3/kaggle/build/r1/heldout/incidents_rwh2.jsonl --chatdev-new $G/chatdev3_r3.jsonl --chatdev-base $G/chatdev3_r3.jsonl \
  --r3-new $G/chat_test_r3_4b.jsonl --r3-base $G/chat_test_r3_4b.jsonl; echo "exit $?"
