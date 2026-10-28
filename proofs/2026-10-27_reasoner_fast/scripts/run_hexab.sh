#!/system/bin/sh
# Board A/B (self-contained): split-3 reasoner + 10-stream agents on the deployed build vs the upstream ggml-hexagon
# (htpd_new) vs upstream + Q4_0 32x4 HVX kernel (htpd_k4), and k4 with HVX up to 8 rows. Agents' model B50.
cd /data/local/tmp/rfast; [ -d ab ] && mv ab ab_prev_$(date +%H%M%S)
REQS="0 0 1 2 3 4 5 6 7 8 9" sh ab_board.sh "sp3old,htpd_v8x2,-,GGML_HEXAGON_OPPOLL=1" "sp3new,htpd_new,-,GGML_HEXAGON_OPPOLL=1" \
  "sp3k4,htpd_k4,-,GGML_HEXAGON_OPPOLL=1" "sp3k4r8,htpd_k4,-,GGML_HEXAGON_OPPOLL=1 GGML_HEXAGON_MM_HVX_ROWS=8"
