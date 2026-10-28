#!/usr/bin/env bash
# Whole QIDK part of the v2 evaluation (Git Bash on Windows, QIDK on USB), resumable:
#   push v2 Q4_0 -> htpd v2 standalone (app stopped) -> host400 (paired with the laptop eval) ->
#   placement study v2 at 4/8/12 h windows (+ clean false-alarm probes, latency per length) -> stop htpd,
#   relaunch the app. Proofs land in proofs/2026-10-20_v2_post/device/.
#   bash device_all.sh            (FULL_TEST=1 also runs all 2,965 test rows)
set -uo pipefail
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
P=/c/Users/hp/Desktop/qidk/proofs/2026-10-20_v2_post/device
W=C:/Users/hp/Desktop/qidk/proofs/2026-10-20_v2_post/device   # Windows form for py (MSYS_NO_PATHCONV keeps /c/... literal)
mkdir -p "$P"
exec > >(tee -a "$P/device_all.log") 2>&1
cd "$HERE"
echo "=== $(date '+%F %T') device_all start"
trap 'bash htpd_v2.sh stop' EXIT
bash htpd_v2.sh push || exit 1
bash htpd_v2.sh start || exit 1
py -3 eval_htpd_v2.py --set host400 --out "$W/host400"
[ -f "$W/placement_v2/prompts.jsonl" ] || py -3 placement_v2.py build --out "$W/placement_v2" --lengths 48,96,144
py -3 placement_v2.py run --out "$W/placement_v2"
py -3 placement_v2.py analyze --out "$W/placement_v2"
[ -n "${FULL_TEST:-}" ] && py -3 eval_htpd_v2.py --set test --out "$W/test_all"
echo "=== $(date '+%F %T') device_all done"
