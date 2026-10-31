#!/bin/bash
# v9 host test job (WSL CPU, 2B base Q4_0, answers started at "{"): base vs v9 K=0 vs v9 K=8 (+ non-unified KV)
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split
M=$HOME/q2bjob/gguf/q2b_base_q4_0.gguf
C=$D/v9/corpus_excl_q10_15.jsonl
O=$D/host
st() { echo "- $(date '+%m-%d %H:%M') host job: $*" >> $D/STATUS.md; }
md5sum $M $HOME/v9host/htpd_base $HOME/v9host/htpd_v9 $C > $O.inputs.md5 2>&1
st "start (2B base Q4_0 CPU -t 6; base, v9k0, v9k8, v9k8 kv streams)"
R="a2 q10 q10 q11 q12 q13 q14 q15 s14 a2"
python3 $D/host_test.py --brace --model $M --out $O --reqs "$R" --cfg "base,$HOME/v9host/htpd_base," && st "base done"
python3 $D/host_test.py --brace --model $M --out $O --reqs "$R" --cfg "v9k0,$HOME/v9host/htpd_v9," && st "v9k0 done"
python3 $D/host_test.py --brace --model $M --out $O --reqs "$R q14 q14 q14" --cfg "v9k8,$HOME/v9host/htpd_v9,HTPD_REASON_SPLIT_SPEC=8;HTPD_REASON_SPEC_MIN=2;HTPD_REASON_CORPUS=$C" && st "v9k8 done"
python3 $D/host_test.py --brace --model $M --out $O --reqs "q10 q14" --cfg "v9k8s,$HOME/v9host/htpd_v9,HTPD_REASON_SPLIT_SPEC=8;HTPD_REASON_SPEC_MIN=2;HTPD_REASON_SPEC_KVU=0;HTPD_REASON_CORPUS=$C" && st "v9k8s (kv streams) done"
st "DONE"
