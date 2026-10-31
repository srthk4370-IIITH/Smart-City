D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split
M=$HOME/q2bjob/gguf/q2b_base_q4_0.gguf
python3 $D/host_test.py --model $M --out $D/v9work/smoke2 --brace --reqs "q14" \
  --cfg "k8,$HOME/v9host/htpd_v9,HTPD_REASON_SPLIT_SPEC=8;HTPD_REASON_SPEC_MIN=2;HTPD_REASON_CORPUS=$D/v9/corpus_excl_q10_15.jsonl"
grep -E "split-spec|corpus|split at|step profile|reason stream|decode steps|error|assert" $D/v9work/smoke2/k8/htpd.log | cut -c1-600
