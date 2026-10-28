#!/system/bin/sh
cd /data/local/tmp/rfast; [ -d ab ] && mv ab ab_prev_$(date +%H%M%S)
REQS="10 10 11 12 13 14 15 16 17 18 19" sh ab_board.sh "sp6x,htpd_v8x2,/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf,GGML_HEXAGON_OPPOLL=1" "sp4x,htpd_v8x2,/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf,GGML_HEXAGON_OPPOLL=1"
