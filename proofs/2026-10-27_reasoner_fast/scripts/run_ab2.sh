#!/system/bin/sh
cd /data/local/tmp/rfast; rm -rf ab2_prev; [ -d ab ] && mv ab ab1_done
O=/data/local/tmp/gpu/rsn_v1_q4_0_outq4.gguf
REQS="0 0 1 2 3 4 5 6 7 8 9" sh ab_board.sh "base,htpd_v8r,-,X=0" "poll,htpd_v8r,-,GGML_HEXAGON_OPPOLL=1" "outq4,htpd_v8r,$O,X=0" "outq4poll,htpd_v8r,$O,GGML_HEXAGON_OPPOLL=1"
