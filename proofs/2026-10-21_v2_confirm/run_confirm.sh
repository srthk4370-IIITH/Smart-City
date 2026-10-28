#!/usr/bin/env bash
# Seed-24 placement confirmation of the window policy + HTPD_DRAFT_K=8 latency/identity check (host400),
# v2 Q4_0 on htpd standalone (8 x 1408, as the 2026-10-20 eval). App stopped during the run, relaunched after.
set -uo pipefail
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8 DRAFT_K=8
E=/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post/device_eval_v2
W=C:/Users/hp/Desktop/qidk/proofs/2026-10-21_v2_confirm
cd "$E"
echo "=== $(date '+%F %T') start (DRAFT_K=$DRAFT_K)"
trap 'bash htpd_v2.sh stop' EXIT
bash htpd_v2.sh start || exit 1
py -3 eval_htpd_v2.py --set host400 --out "$W/host400_k8"
py -3 placement_v2.py run --out "$W/placement_s24"
py -3 placement_v2.py analyze --out "$W/placement_s24"
echo "=== $(date '+%F %T') done"
