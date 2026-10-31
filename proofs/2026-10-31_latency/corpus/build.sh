source ~/venvs/rsn/bin/activate
P=/mnt/c/Users/hp/Desktop/qidk/proofs; D=$P/2026-10-30_spec_split; R=$P/2026-10-27_reasoner_fast/bench/rreq_split; O=$P/2026-10-31_latency/corpus
IN="$P/2026-10-28_master/rag_seed/gen_rsn_v1.jsonl $P/2026-10-25_reasoner_final/eval/results/v1_106/rwh.jsonl $P/2026-10-27_reasoner_fast/raw/board_incidents_b50.jsonl $P/2026-10-27_reasoner_fast/raw/board_incidents.jsonl $O/real_reports.jsonl"
X=$(ls $O/rreq_real/q10*.json | tr '\n' ',' | sed 's/,$//')
cd $D
nice python3 build_corpus.py --schema-req $R/q10.json --exclude-reqs $X --out $O/corpus_real_excl.jsonl $IN | tail -2
nice python3 build_corpus.py --schema-req $R/q10.json --out $O/corpus_real_all.jsonl $IN | tail -2
