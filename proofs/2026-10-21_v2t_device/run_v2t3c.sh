#!/usr/bin/env bash
# Device eval of the top-up GGUF (ft_v2t3c_q4_0.gguf) on exactly the sets v2 was judged on: host400 + seed-24
# placement (same prompts, htpd 8 x 1408, DRAFT_K=8). Pushed under its own name; the deployed v2 is untouched.
set -uo pipefail
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8 DRAFT_K=8
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
E=/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post/device_eval_v2
W=C:/Users/hp/Desktop/qidk/proofs/2026-10-22_v2t3c_device
SRC=//wsl.localhost/Ubuntu/home/hp_srthk4370/smartcity_runs/agents_v2_topup3c/post/gguf/ft_v2t3c_q4_0.gguf
DEV=/data/local/tmp/gpu/ft_v2t3c_q4_0.gguf
L=$(md5sum "$SRC" | cut -d' ' -f1); echo "local md5 $L"
R=$("$ADB" shell "cat $DEV.md5 2>/dev/null" | tr -d '\r')   # sidecar: no whole-file md5 on the board (2026-10-22 shutdowns)
if [ "$L" != "$R" ]; then
  # no /sdcard staging: multi-GB copies out of FUSE /sdcard stalled system_server and the watchdog
  # rebooted the board (2026-10-22, twice). adbd writes /data directly; .part keeps the target safe.
  "$ADB" shell 'am force-stop com.iiith.smartcityedge; pkill -x htpd; pkill -x htpd_v7; pkill -x edge-agent; true'
  "$ADB" push "$SRC" "$DEV.part" || exit 1
  [ "$("$ADB" shell md5sum "$DEV.part" | cut -d' ' -f1)" = "$L" ] || { echo "md5 mismatch on $DEV.part"; exit 1; }
  "$ADB" shell "mv -f $DEV.part $DEV && echo $L > $DEV.md5" || exit 1
fi
echo "on device: $DEV $L"
mkdir -p "$W/placement_s24"; cp /c/Users/hp/Desktop/qidk/proofs/2026-10-21_v2_confirm/placement_s24/{prompts.jsonl,cases.jsonl,manifest.json} "$W/placement_s24/"
cd "$E"; trap 'bash htpd_v2.sh stop' EXIT
bash htpd_v2.sh start "$DEV" || exit 1
py -3 eval_htpd_v2.py --set host400 --out "$W/host400"
py -3 placement_v2.py run --out "$W/placement_s24"
py -3 placement_v2.py analyze --out "$W/placement_s24"
echo "=== $(date '+%F %T') done"
