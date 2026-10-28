#!/usr/bin/env bash
# Resume the 3d arm after the user's reboot (2026-10-22 ~19:xx): app already runs htpd_v7 with ft_v2t3d.
# Finish placement_s24 on the app's htpd (resumable), analyze, then switch the app back to v2 cleanly.
set -uo pipefail
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
A=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge
T=/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/tools
E=/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post/device_eval_v2
HERE=$(pwd -W 2>/dev/null || pwd)
log() { echo "=== $(date '+%F %T') $*"; }
up() { $A shell 'cat /proc/uptime; cat /sys/class/thermal/thermal_zone30/temp; pidof edge-agent htpd_v7' 2>&1 | tr '\n' ' '; echo; }
cool() { for i in $(seq 1 90); do t=$($A shell cat /sys/class/thermal/thermal_zone30/temp | tr -d '\r'); [ "${t:-99000}" -lt 50000 ] && return; sleep 10; done; }
log "resume 3d arm"; $A shell 'cat /proc/$(pidof htpd_v7)/cmdline | tr "\0" " "' | cut -c1-100; up
$A forward tcp:8000 tcp:8000 >/dev/null; $A forward tcp:8091 tcp:8091 >/dev/null
(cd $T && py -3 -c "import stress_app as S; S.reset('10:00')"); sleep 15; cool
(cd $E && py -3 placement_v2.py run --out "$HERE/v2t3d/placement_s24" --port 8091 && py -3 placement_v2.py analyze --out "$HERE/v2t3d/placement_s24") >> v2t3d/placement.log 2>&1
wc -l v2t3d/placement_s24/samples.jsonl; up
log "switch back to v2"
$A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; sleep 10; true'
$A shell "grep -v '^model=' $W/htpd_profile > $W/p.new; mv -f $W/p.new $W/htpd_profile; rm -f $W/state/htpd_args"
cool; $A shell 'monkey -p com.iiith.smartcityedge -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1'; sleep 60
$A shell 'cat /proc/$(pidof htpd_v7)/cmdline | tr "\0" " "' | cut -c1-100; up
log "resume done"
