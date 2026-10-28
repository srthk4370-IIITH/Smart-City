#!/system/bin/sh
cd /data/local/tmp/rfast
until grep -q "prof done" prof/prof.log 2>/dev/null; do sleep 10; done
sleep 60
REQS="0 0 1 2" sh ab_board.sh "v8r,htpd_v8r,X=0" "v8s0,htpd_v8s,HTPD_REASON_SPEC=0" "s8,htpd_v8s,HTPD_REASON_SPEC=8" "s4,htpd_v8s,HTPD_REASON_SPEC=4"
