#!/usr/bin/env bash
# P2 decision: per candidate, E2 gate on dev3f (cand+P1 rules vs mixA50+P1 rules, new leak definition) + E1 stories.
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; source ~/venvs/train/bin/activate; cd $D
for t in ${*:-B20 B35 B50 T20 T30}; do
  python scripts/e2.py --cand $t --sets dev --cand-rules ALL_P1 --ref-rules ALL_P1 --regold --out e2/p2_$t.json 2>&1 | head -1
  python scripts/score_e1.py --tags $t --rules ALL_P1 --regold --quiet 2>&1 | tail -1
done
python scripts/score_e1.py --tags mixA50cuda --rules ALL_P1 --regold --quiet 2>&1 | tail -1
