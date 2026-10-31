#!/usr/bin/env bash
# lab window live_ab (2026-10-31): current corpus vs + real-app reports vs + live growth, on 6 held-out real app incidents
E="LD_LIBRARY_PATH=/data/local/tmp/llama.cpp/lib_rp29 ADSP_LIBRARY_PATH=/data/local/tmp/llama.cpp/lib_rp29 GGML_HEXAGON_REPACK_THREADS=8 HTPD_REASON_SPLIT_SPEC=8 HTPD_REASON_SPEC_MIN=2 HTPD_REASON_SPEC_ALIGN=1"
W=/data/local/tmp/rfast
export REQS="100 100 101 102 103 104 105 101 103" WINDOW_MAX=4800
bash /c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/lab_run.sh live_ab2 \
 "cur,htpd_v9d,qwen35_reasoner_q4_0.gguf,$E HTPD_REASON_CORPUS=/data/local/tmp/smart_city_edge/reason_corpus.jsonl" \
 "real,htpd_v9d,qwen35_reasoner_q4_0.gguf,$E HTPD_REASON_CORPUS=$W/corpus_real_excl.jsonl" \
 "reallive,htpd_v9d,qwen35_reasoner_q4_0.gguf,$E HTPD_REASON_CORPUS=$W/corpus_real_excl.jsonl HTPD_REASON_CORPUS_LIVE=$W/lab/live_w2.jsonl"
