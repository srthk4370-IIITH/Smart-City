#!/bin/bash
# v9h host build + host test (WSL, CPU, nice). usage: bash host_run.sh [ERC]
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_htpd_v9h
H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/htpd
nice -n 15 bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split/v9work/build_host.sh $H ~/v9host/htpd_v9h 2>&1 | grep -E "error|warning|htpd_v9h"
free -m | head -2
nice -n 15 python3 $P/host_test_v9h.py --bin-f ~/v9host/htpd_v9f --bin-h ~/v9host/htpd_v9h \
  --model /mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v3_2b_r2_q4_0.gguf --work ~/v9h_test --out $P/host --only ${1:-ERC}
echo HOST_RUN_DONE
