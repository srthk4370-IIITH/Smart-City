#!/system/bin/sh
# Decision consistency: 6 prompts x 5 runs on the deployed config (htpd_v8r path + OPPOLL=1), via htpd_v8t (= v8r +
# HTPD_REASON_TRACE per-pick top-2 logits). Every request starts at <= 60 C (coordinator rule after the 02:11 reboot).
cd /data/local/tmp/rfast; [ -d ab ] && mv ab ab_prev_$(date +%H%M%S)
mkdir -p ab/trace
sed -i 's/cool 70$/cool 60/; s/cool 66$/cool 60/' ab_board.sh
R="1 0 4 7 8 9"
REQS="1 $R $R $R $R $R" sh ab_board.sh "cons,htpd_v8t,-,GGML_HEXAGON_OPPOLL=1 HTPD_REASON_TRACE=/data/local/tmp/rfast/ab/trace"
