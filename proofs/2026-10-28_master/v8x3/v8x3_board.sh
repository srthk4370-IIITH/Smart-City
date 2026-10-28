#!/system/bin/sh
# Board side of the rsn_v2 retry (owner: small runs). All configs split-3 + OPPOLL on htpd_v8x3 (bounded pick, 150 s guard):
#   par  : rsn_v1, q10-q14 (parity vs the existing v8x2 sp3 files)
#   v2   : rsn_v2, q10-q19 (q11 = the board stall case)
#   cons : rsn_v2, q11 q12 q13 x 3 (severity consistency)
# ab_board.sh does the safety: app stopped (one NPU client), <= 60 C per request, app restarted after each run.
cd /data/local/tmp/rfast
run() { tag=$1; shift; [ -d ab ] && mv ab ab_prev_$(date +%H%M%S); REQS="$1" sh ab_board.sh "$2"; rm -rf v8x3_$tag; mv ab v8x3_$tag; }
run par "10 10 11 12 13 14" "sp3x,htpd_v8x3,-,GGML_HEXAGON_OPPOLL=1"
run v2 "10 10 11 12 13 14 15 16 17 18 19" "sp3v2,htpd_v8x3,/data/local/tmp/gpu/rsn_v2_q4_0.gguf,GGML_HEXAGON_OPPOLL=1"
run cons "11 11 12 13 11 12 13 11 12 13" "sp3c,htpd_v8x3,/data/local/tmp/gpu/rsn_v2_q4_0.gguf,GGML_HEXAGON_OPPOLL=1"
run sp6 "10 10 11 12 13 14" "sp6c,htpd_v8x3,-,GGML_HEXAGON_OPPOLL=1"   # numbers only (split-6 at 6 x 3200 ctx)
echo done > v8x3_DONE
