#!/system/bin/sh
cd /data/local/tmp/rfast; [ -d ab ] && mv ab ab_prev_$(date +%H%M%S)
REQS="12 12 13 14" sh ab_board.sh "spxa2,htpd_v8x2,-,GGML_HEXAGON_OPPOLL=1" "spxa3,htpd_v8x3,-,GGML_HEXAGON_OPPOLL=1" "spxb2,htpd_v8x2,-,GGML_HEXAGON_OPPOLL=1" "spxb3,htpd_v8x3,-,GGML_HEXAGON_OPPOLL=1"
