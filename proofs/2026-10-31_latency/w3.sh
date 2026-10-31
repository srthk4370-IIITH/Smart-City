#!/usr/bin/env bash
# lab window klong_ab (2026-10-31): real corpus + live (fresh file per config): K8 vs K8+KLONG16 (rows 48) vs K12 (rows 40)
E="LD_LIBRARY_PATH=/data/local/tmp/llama.cpp/lib_rp29 ADSP_LIBRARY_PATH=/data/local/tmp/llama.cpp/lib_rp29 GGML_HEXAGON_REPACK_THREADS=8 HTPD_REASON_SPEC_MIN=2 HTPD_REASON_SPEC_ALIGN=1 HTPD_REASON_CORPUS=/data/local/tmp/rfast/corpus_real_excl.jsonl"
L=/data/local/tmp/rfast/lab
export REQS="100 100 101 102 103 104 105 101 103" WINDOW_MAX=4000
bash /c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/lab_run.sh klong_ab \
 "rl,htpd_v9d,qwen35_reasoner_q4_0.gguf,$E HTPD_REASON_SPLIT_SPEC=8 HTPD_REASON_CORPUS_LIVE=$L/live_w3a.jsonl" \
 "rlk16,htpd_v9d,qwen35_reasoner_q4_0.gguf,$E HTPD_REASON_SPLIT_SPEC=8 HTPD_REASON_SPEC_KLONG=16 HTPD_REASON_SPEC_ROWS=48 HTPD_REASON_CORPUS_LIVE=$L/live_w3b.jsonl" \
 "rlk12,htpd_v9d,qwen35_reasoner_q4_0.gguf,$E HTPD_REASON_SPLIT_SPEC=12 HTPD_REASON_SPEC_ROWS=40 HTPD_REASON_CORPUS_LIVE=$L/live_w3c.jsonl"
