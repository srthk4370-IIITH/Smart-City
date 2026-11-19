#!/bin/bash
# v2 stage 2 (CPU only): waits for stage 1 (agt_v3 outputs), then build -> pass 2 -> pass 3 -> tokens -> finalize (READY on all-pass).
export CUDA_VISIBLE_DEVICES=
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn
D=data/final_v2
while p=$(cat ~/detached/rsn_v2_s1.pid 2>/dev/null) && kill -0 $p 2>/dev/null; do sleep 60; done
n=$(wc -l < $D/work/agent_out.jsonl); echo "agent outputs $n $(date)"
[ "$n" -ge 1900 ] || { echo "stage1 incomplete ($n)"; exit 2; }
nice -n 15 python3 build_v2.py > logs/build_v2.log 2>&1 || { echo build failed; exit 1; }
nice -n 15 python3 verify_final.py $D > logs/verify_v2_pass2.log 2>&1 || { echo pass2 crashed; exit 1; }
nice -n 15 python3 v2_verify.py $D > logs/verify_v2_pass3.log 2>&1; echo "pass3 rc $?"
nice -n 15 ~/venvs/rsn/bin/python tok_v4.py $D > logs/tok_v2.log 2>&1 || { echo tok failed; exit 1; }
nice -n 15 python3 v2_finalize.py $D; echo "finalize rc $? $(date)"
