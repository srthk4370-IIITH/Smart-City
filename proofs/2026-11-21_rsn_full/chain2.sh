#!/bin/bash
# chain2.sh: steps 4-5 of chain.sh (prep failed on system python: no transformers) with the rsn venv
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full; S=$D/STATUS.md; Q=/mnt/c/Users/hp/Desktop/qidk/proofs
st(){ echo "- $(date "+%F %T") [chain2] $*" >> $S; echo "- rsn_full chain2 $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
cd $D
st "4 prep_data (12.8k rows seen, 800 steps, owner speed)"
~/venvs/rsn/bin/python prep_data.py --seen 12800 >> logs/prep.log 2>&1 || { st "FAIL prep_data (logs/prep.log)"; exit 1; }
# fast evals (owner): every 200 steps, 12 rows, stop after 2 evals without improvement; keep-best not blocked by the r3 floor
sed -i -E 's/--eval-every [0-9]+/--eval-every 200/; s/--gen-every [0-9]+/--gen-every 200/; s/--patience [0-9]+/--patience 2/; s/--r3-tol [0-9.]+/--r3-tol 1.0/; s/--save-every [0-9]+/--save-every 50/' run_full.sh
st "5 launch: $(grep -o -- '--eval-every [0-9]*\|--patience [0-9]*\|--micro-tokens [0-9]*' run_full.sh | tr '\n' ' ')"
touch GO
MAX_STEPS=800 setsid nohup bash run_full.sh >> logs/run_full.log 2>&1 < /dev/null &
st "launched pid $!"
