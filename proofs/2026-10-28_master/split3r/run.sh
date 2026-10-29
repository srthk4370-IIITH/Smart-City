#!/system/bin/sh
cd /data/local/tmp/rfast; [ -d ab ] && mv ab ab_prev_$(date +%H%M%S)
REQS="10 10 11 12 13 14 15 16 17 18 19" sh ab_board.sh "spxa,htpd_v8x3,-,GGML_HEXAGON_OPPOLL=1" "spra,htpd_v8x3,-,GGML_HEXAGON_OPPOLL=1"
