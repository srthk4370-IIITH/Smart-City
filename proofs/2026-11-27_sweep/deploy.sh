#!/bin/bash
# deploy.sh (Git Bash on Windows): restore the pre-sweep board state and install the swept APK.
#   1 stop the app (activity, edge-agent, htpd) and wait for exit
#   2 keep the sweep's state as state_sweep1127_<n> (nothing deleted), restore state/ from /data/local/tmp/sweep_state_backup.tgz
#     (htpd_profile is NOT restored: it already has reasoner_think=adaptive from the 2026-11-26 deploy)
#   3 adb install -r -d the new APK (known-good APK pulled first)   4 start, wait for "htpd: ready in"
# usage: bash deploy.sh [apk]
set -u
export MSYS_NO_PATHCONV=1
A=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
W=/data/local/tmp/smart_city_edge
HERE=$(cd "$(dirname "$0")" && pwd)
APK=${1:-/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/android/out/SmartCityEdge.apk}
sh_(){ $A shell "$@" | tr -d '\r'; }
log(){ echo "$(date +%H:%M:%S) $*" | tee -a "$HERE/deploy.log"; }
mkdir -p "$HERE/deploy"
p=$(sh_ pm path com.iiith.smartcityedge | head -1 | sed 's/package://')
$A pull "$p" "$(cygpath -w "$HERE/deploy/known_good.apk")" > /dev/null && log "known-good APK saved ($(md5sum "$HERE/deploy/known_good.apk" | cut -c1-8))"
log "stop: $(sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9h); do kill -TERM $p; done; i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done; sleep 3; ps -A -o NAME= | grep -E "^(htpd|edge-agent)" || echo STOPPED')"
n=$(date +%H%M)
log "state: $(sh_ "cd $W && mv state state_sweep1127_$n && mkdir state && tar xzf /data/local/tmp/sweep_state_backup.tgz -C $W state && ls state | wc -l && ls -d state_sweep1127_$n")"
log "install: $($A install -r -d "$(cygpath -w "$APK")" 2>&1 | tail -1)"
l0=$(sh_ "wc -l < $W/state/htpd.log" | tail -1)
sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
for i in $(seq 1 60); do
  sleep 5
  c=$(sh_ "tail -n +$(( ${l0:-0} + 1 )) $W/state/htpd.log | grep -c 'htpd: ready in'" | tail -1)
  [ "${c:-0}" -ge 1 ] && break
done
log "start: ready=${c:-0} pids=$(sh_ 'pidof htpd_v9h edge-agent') edge-agent=$(sh_ "md5sum $W/edge-agent" | cut -c1-8)"
