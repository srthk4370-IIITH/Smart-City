#!/usr/bin/env bash
# static_test.sh: bash -n on every r4 script, py_compile, the gate scorer on cached r3 results (no GPU, no server):
#   A: r3-2800 vs itself on incidents_test_r2 (stands in for the r4 test) -> (a) FAIL (no gain);
#   B: r3-2800 vs rsn_v1 (ft612) on incidents_test_r2 -> (a) PASS; C: final stage, r3-2800 vs itself -> (b), (c) all ok, (a) FAIL.
T4=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/train; H=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local
R1=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/eval/results; W=$(mktemp -d)
for f in $T4/*.sh $T4/post/*.sh; do bash -n "$f" && echo "bash -n ok $(basename $f)" || echo "BASH SYNTAX FAIL $f"; done
python3 -m py_compile $T4/topup_train.py $T4/post/gate_score_r4.py $T4/post/run_think.py && echo "py_compile ok"
( set -a; . $T4/run_r4.env; . $T4/paths_r4.sh; echo "paths_r4 (data/final now): $(paths_show)" )
T2=$H/data/final/incidents_test_r2.jsonl
python3 $T4/post/gate_score_r4.py --stage a --out $W/A --test4-inc $T2 --t4-new $R1/rsn_v3_4b_r3/test_r2.jsonl --t4-base $R1/rsn_v3_4b_r3/test_r2.jsonl; echo "A rc $? (expect 1)"
python3 $T4/post/gate_score_r4.py --stage a --out $W/B --test4-inc $T2 --t4-new $R1/rsn_v3_4b_r3/test_r2.jsonl --t4-base $R1/ft612/test_r2.jsonl; echo "B rc $? (expect 0)"
grep -o '"combined_new": [0-9.]*, "combined_base": [0-9.]*' $W/B/gate.json
python3 $T4/post/gate_score_r4.py --stage final --out $W/C --new rsn_v3_4b_r3 --base rsn_v3_4b_r3 --test4-inc $T2 --t4-new $R1/rsn_v3_4b_r3/test_r2.jsonl \
  --t4-base $R1/rsn_v3_4b_r3/test_r2.jsonl --rwh2 /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/build/r1/heldout/incidents_rwh2.jsonl \
  --chatdev-new $H/post/gate_r3/chatdev3_r3.jsonl --chatdev-base $H/post/gate_r3/chatdev3_r3.jsonl \
  --r3-new $H/post/gate_r3/chat_test_r3_4b.jsonl --r3-base $H/post/gate_r3/chat_test_r3_4b.jsonl; echo "C rc $? (expect 1: only (a) fails)"
grep -c '| yes |' $W/C/GATE_r4.md; grep '\*\*NO\*\*' $W/C/GATE_r4.md; grep -A5 '(c) chat_test_r3' $W/C/GATE_r4.md | tail -3
rm -rf $W
