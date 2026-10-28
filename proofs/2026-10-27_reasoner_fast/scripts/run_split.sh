#!/system/bin/sh
# split decoding A/B: same binary (htpd_v8x), single stream vs 3 parallel continuation streams; deployed env (OPPOLL)
cd /data/local/tmp/rfast; [ -d ab ] && mv ab ab_prev_$(date +%H%M%S)
REQS="0 0 1 2 3 4 5 6 7 8 9" sh ab_board.sh "single,htpd_v8x,-,GGML_HEXAGON_OPPOLL=1" "sp3,htpd_v8x,-,GGML_HEXAGON_OPPOLL=1"
