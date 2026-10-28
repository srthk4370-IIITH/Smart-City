#!/system/bin/sh
cd /data/local/tmp/rfast; [ -d ab ] && mv ab ab_prev_$(date +%H%M%S)
REQS="10 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39" sh ab_board.sh "sp3v2,htpd_v8x2,/data/local/tmp/gpu/rsn_v2_q4_0.gguf,GGML_HEXAGON_OPPOLL=1"
