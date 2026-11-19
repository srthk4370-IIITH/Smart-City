#!/bin/bash
# v9 host job 2 (after job 1): final binary htpd_v9b: K=0 identity spot check, spec machinery without drafts
# (unified KV + seq_cp fork only: numerics effect), K=8 align
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split
M=$HOME/q2bjob/gguf/q2b_base_q4_0.gguf; C=$D/v9/corpus_excl_q10_15.jsonl; O=$D/host; B=$HOME/v9host/htpd_v9b
until grep -q "host job: DONE" $D/STATUS.md; do sleep 30; done
st() { echo "- $(date '+%m-%d %H:%M') host job2: $*" >> $D/STATUS.md; }
st "start (htpd_v9b $(md5sum < $B | cut -c1-8))"
python3 $D/host_test.py --brace --model $M --out $O --reqs "q10 q14 q12" --cfg "v9k0b,$B," && st "v9k0b done"
python3 $D/host_test.py --brace --model $M --out $O --reqs "q10 q10 q11 q12 q13 q14 q15" --cfg "v9k8n,$B,HTPD_REASON_SPLIT_SPEC=8;HTPD_REASON_SPEC_MIN=1000" && st "v9k8n (no drafts) done"
python3 $D/host_test.py --brace --model $M --out $O --reqs "q10 q10 q11 q12 q13 q14 q15" --cfg "v9k8a,$B,HTPD_REASON_SPLIT_SPEC=8;HTPD_REASON_SPEC_MIN=2;HTPD_REASON_SPEC_ALIGN=1;HTPD_REASON_CORPUS=$C" && st "v9k8a (align) done"
st "DONE"
