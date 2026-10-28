#!/system/bin/sh
# split-N A/B (2026-10-28): sp3 (live) vs sp4 vs sp6 on the 30 RWH prompts (q10-q39, q10 doubles as warm-up). split_acc.py raw/split6
# Why: pp6/pp8 steps cost ~106-109 ms vs 113 ms for 3 rows (HMX path), so 6 streams decode ~2x the tokens per step;
# the longest group drops from ~450 to ~260 chars (observations). Accuracy gate = sev/label vs gold and vs sp3, 31/31 valid.
cd /data/local/tmp/rfast; [ -d ab ] && mv ab ab_prev_$(date +%H%M%S)
REQS="10 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39" sh ab_board.sh "sp3,htpd_v8x2,-,GGML_HEXAGON_OPPOLL=1" "sp6,htpd_v8x2,-,GGML_HEXAGON_OPPOLL=1" "sp4,htpd_v8x2,-,GGML_HEXAGON_OPPOLL=1"
