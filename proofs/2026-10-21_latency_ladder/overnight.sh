#!/usr/bin/env bash
# Overnight device sequence (2026-10-22), unattended. Board safety: every step's own scripts cool the NSP
# (< 50-55 C) before runs, run one model on the NPU at a time, push via /sdcard + md5, never reboot, and relaunch
# the app at the end. If the board drops off USB, wait for it (up to 30 min) instead of failing the rest.
set -uo pipefail
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8 MSYS_NO_PATHCONV=1
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
W=/data/local/tmp/smart_city_edge
EVAL=/c/Users/hp/Desktop/qidk/proofs/2026-10-21_v2t_device
APK=C:/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/android/out/SmartCityEdge.apk
log() { echo "=== $(date '+%F %T') $*"; }
board() { for i in $(seq 1 180); do [ "$("$ADB" get-state 2>/dev/null)" = device ] && return 0; sleep 10; done; log "board missing 30 min"; return 1; }
push() { "$ADB" push "$1" /sdcard/_x >/dev/null && "$ADB" shell "cp -f /sdcard/_x $2 && rm -f /sdcard/_x && chmod 644 $2"; }
relaunch() { "$ADB" shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; sleep 2; monkey -p com.iiith.smartcityedge -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; true'; sleep 40; "$ADB" forward tcp:8000 tcp:8000 >/dev/null; }

log "1. wait for the phase-1 device eval"
for i in $(seq 1 480); do grep -qE "app relaunched|not connected|mismatch" $EVAL/run_v2t.log 2>/dev/null && break; sleep 30; done
tail -3 $EVAL/run_v2t.log
board || exit 1
log "2. deploy new APK + live profile + warm-up"
"$ADB" install -r -g "$APK"
push profiles/live.txt $W/htpd_profile
push htpd_warmup.jsonl $W/htpd_warmup.jsonl
"$ADB" shell "rm -f $W/state/htpd_args"
relaunch
"$ADB" shell "pidof edge-agent htpd_v7; md5sum $W/edge-agent; cat $W/htpd_profile"
log "3. through-the-app latency baseline (live profile, warm-up on)"
board && bash run_app_ab.sh LIVE profiles/live.txt htpd_warmup.jsonl
log "4. htpd ladder, env-only arms"
board && bash run_ladder.sh envA
board && bash run_ladder.sh ksweep
log "5. phase-2c GGUF (if training produced one)"
for i in $(seq 1 240); do
  st=$(wsl.exe -d Ubuntu -- bash -c "cat ~/smartcity_runs/agents_v2_topup3c/post/STATUS 2>/dev/null" | tr -d '\r')
  case "$st" in done*) log "2c GGUF $st"; board && bash $EVAL/run_v2t3c.sh > $EVAL/run_v2t3c.log 2>&1; break;;
                 failed*|no*) log "2c: $st"; break;; esac
  sleep 60
done
log "6. leave the app running on the live profile"
board && { push profiles/live.txt $W/htpd_profile; relaunch; "$ADB" shell "pidof edge-agent htpd_v7"; }
log "overnight done"
