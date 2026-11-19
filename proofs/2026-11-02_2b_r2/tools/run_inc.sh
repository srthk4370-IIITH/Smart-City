#!/usr/bin/env bash
set -euo pipefail
Q=/mnt/c/Users/hp/Desktop/qidk; T=$Q/proofs/2026-11-02_2b_r2/tools; F=$Q/proofs/2026-11-02_2b_r2/data/final
python3 -B $T/build_inc_r2.py --out $F
bash $T/go_gate.sh $F/go_gate_train.jsonl $F/incidents_train.jsonl
bash $T/go_gate.sh $F/go_gate_test.jsonl $F/incidents_test_r2.jsonl
python3 -B $T/build_inc_r2.py --out $F --drop-gate $F/go_gate_train.jsonl $F/go_gate_test.jsonl
