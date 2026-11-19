#!/usr/bin/env bash
# Unit check of gate_score_4b.py on existing results (CPU, seconds): the g2b_r2 inputs must reproduce the g2b_r2 GATE.md
# check table exactly; test_r2 per-slice scoring runs on g2b_r2's 628 test_r2 items; chat slices on its chat dev file.
# usage: bash t_gate_score.sh <outdir>
P=/mnt/c/Users/hp/Desktop/qidk/proofs; K=$P/2026-10-29_rsn_v3/kaggle; O=${1:?outdir}
nice -n 15 python3 $P/2026-11-06_4b_local/post/gate_score_4b.py --new rsn_v3_g2b_r2 --base ft612 \
  --chat-new $K/gate/g2b_r2/chatdev3_v3.jsonl --chat-base $K/gate/rsn_v1_chatdev3_3059c98f8956.jsonl --out $O \
  --rwh2 $K/build/r1/heldout/incidents_rwh2.jsonl --r3-new $K/gate/g2b_r2/chatdev3_v3.jsonl \
  --test-r2 $P/2026-11-06_4b_local/data/final/incidents_test_r2.jsonl --p0 $K/gate/g2b_r2/p0.txt
echo "rc=$? (expected 1 = FAIL, as g2b_r2)"
if diff <(grep -E '^\| (rwh|rwh2|dev|chatdev3) ' $K/gate/g2b_r2/GATE.md | cut -d'|' -f2-5,7) <(grep -E '^\| (rwh|rwh2|dev|chatdev3) ' $O/GATE.md | cut -d'|' -f2-5,7); then
  echo "CHECK TABLE IDENTICAL to g2b_r2/GATE.md ($(grep -cE '^\| (rwh|rwh2|dev|chatdev3) ' $O/GATE.md) rows)"
else echo "CHECK TABLE DIFFERS"; fi
