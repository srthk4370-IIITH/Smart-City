source ~/venvs/rsn/bin/activate
P=/mnt/c/Users/hp/Desktop/qidk/proofs; D=$P/2026-10-30_spec_split; R=$P/2026-10-27_reasoner_fast/bench/rreq_split
IN="$P/2026-10-28_master/rag_seed/gen_rsn_v1.jsonl $P/2026-10-25_reasoner_final/eval/results/v1_106/rwh.jsonl $P/2026-10-27_reasoner_fast/raw/board_incidents_b50.jsonl $P/2026-10-27_reasoner_fast/raw/board_incidents.jsonl"
cd $D
python3 build_corpus.py --schema-req $R/q10.json --exclude-reqs $R/q10.json,$R/q11.json,$R/q12.json,$R/q13.json,$R/q14.json,$R/q15.json --out v9/corpus_excl_q10_15.jsonl $IN
python3 build_corpus.py --schema-req $R/q10.json --out v9/corpus_all.jsonl $IN
