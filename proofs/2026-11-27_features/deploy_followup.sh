#!/bin/bash
# deploy.sh (Git Bash): install the 2026-11-27 follow-up build (early look, AGREE line, report repairs), keeping the board's current state.
#   1 save the running APK (rollback)  2 stop app/edge-agent/htpd, wait for exit
#   3 back up htpd_profile, add agent_prefetch=shadow if absent   4 adb install -r -d   5 start, wait "htpd: ready in"
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
[ -f "$HERE/deploy/before_followup.apk" ] || $A pull "$p" "$(cygpath -w "$HERE/deploy/before_followup.apk")" > /dev/null && log "running APK saved ($(md5sum "$HERE/deploy/before_followup.apk" | cut -c1-8))"
log "stop: $(sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9h); do kill -TERM $p; done; i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done; sleep 3; ps -A -o NAME= | grep -E "^(htpd|edge-agent)" || echo STOPPED')"
n=$(date +%m%d%H%M)
log "profile: $(sh_ "cd $W && cp htpd_profile htpd_profile.before_followup.$n && sed -i -e '/^ai_early_k=/d' -e '/^ai_early_shapes=/d' htpd_profile && echo ai_early_k=3 >> htpd_profile && echo ai_early_shapes=spike,step,trend,flatline,noisy,fault,limit >> htpd_profile && grep -E '^(agent_prefetch|ai_early_k|ai_early_shapes|reasoner_think)=' htpd_profile | tr '\n' ' '")"
log "install: $($A install -r -d "$(cygpath -w "$APK")" 2>&1 | tail -1)"
l0=$(sh_ "wc -l < $W/state/htpd.log" | tail -1)
sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
for i in $(seq 1 60); do
  sleep 5
  c=$(sh_ "tail -n +$(( ${l0:-0} + 1 )) $W/state/htpd.log | grep -c 'htpd: ready in'" | tail -1)
  [ "${c:-0}" -ge 1 ] && break
done
log "start: ready=${c:-0} pids=$(sh_ 'pidof htpd_v9h edge-agent') edge-agent=$(sh_ "md5sum $W/edge-agent" | cut -c1-8)"
