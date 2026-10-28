#!/system/bin/sh
# split decoding A/B, fixed v8x2 (group sentinels): single stream vs 3 parallel continuation streams; deployed env
cd /data/local/tmp/rfast
until grep -qE "ab done|ABORT" ab/ab.log 2>/dev/null; do sleep 15; done
sleep 30; mv ab ab_split1_$(date +%H%M%S)
REQS="0 0 1 2 3 4 5 6 7 8 9" sh ab_board.sh "sp3,htpd_v8x2,-,GGML_HEXAGON_OPPOLL=1"
