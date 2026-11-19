#!/bin/bash
# v9d host test (WSL CPU, 2B base): live corpus off (= v9c behaviour) vs on vs on + KLONG 16
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split; O=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_latency/host
M=$HOME/q2bjob/gguf/q2b_base_q4_0.gguf; C=$D/v9/corpus_excl_q10_15.jsonl; B=$HOME/v9host/htpd_v9d
S=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_latency/STATUS.md
st() { echo "- $(date '+%m-%d %H:%M') host job: $*" >> $S; }
mkdir -p $O; rm -f /tmp/v9d_live*.jsonl
R="q10 q11 q12 q10 q11 q12"
E="HTPD_REASON_SPLIT_SPEC=8;HTPD_REASON_SPEC_MIN=2;HTPD_REASON_SPEC_ALIGN=1;HTPD_REASON_CORPUS=$C"
st "start ($(md5sum < $B | cut -c1-8))"
nice -n 10 python3 $D/host_test.py --brace --threads 4 --model $M --out $O --reqs "$R" --cfg "off,$B,$E" && st "off done"
nice -n 10 python3 $D/host_test.py --brace --threads 4 --model $M --out $O --reqs "$R" --cfg "live,$B,$E;HTPD_REASON_CORPUS_LIVE=/tmp/v9d_live1.jsonl" && st "live done"
nice -n 10 python3 $D/host_test.py --brace --threads 4 --model $M --out $O --reqs "$R" --cfg "livek16,$B,$E;HTPD_REASON_CORPUS_LIVE=/tmp/v9d_live2.jsonl;HTPD_REASON_SPEC_KLONG=16;HTPD_REASON_SPEC_ROWS=48" && st "livek16 done"
cp /tmp/v9d_live1.jsonl $O/live1.jsonl 2>/dev/null
st "DONE"
