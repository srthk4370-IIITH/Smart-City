#!/usr/bin/env bash
# Clean deploy of the current APK + through-the-app regression. Usage: bash deploy_and_test.sh OUTDIR
# One NPU client: app force-stopped, all htpd* stopped ([b]in pattern can't match this shell) and waited, then install + relaunch.
set -uo pipefail
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
A=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge
T=/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/tools
mkdir -p "$1"; O=$(cd "$1" && (pwd -W 2>/dev/null || pwd)); log() { echo "=== $(date '+%F %T') $*"; }
up() { $A shell 'cat /proc/uptime; cat /sys/class/thermal/thermal_zone30/temp; pidof edge-agent htpd_v7' 2>&1 | tr '\n' ' '; echo; }
cool() { for i in $(seq 1 90); do t=$($A shell cat /sys/class/thermal/thermal_zone30/temp | tr -d '\r'); [ "${t:-99000}" -ge 0 ] && [ "${t:-99000}" -lt 50000 ] && return; sleep 10; done; }
log deploy; up
$A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; sleep 10; true'
$A install -r -g C:/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/android/out/SmartCityEdge.apk | tail -1
$A shell "rm -f $W/state/htpd_args"; cool
$A shell 'monkey -p com.iiith.smartcityedge -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1'; sleep 70
$A forward tcp:8000 tcp:8000 >/dev/null
$A shell 'md5sum /data/local/tmp/smart_city_edge/edge-agent; cat /proc/$(pidof htpd_v7)/cmdline | tr "\0" " " | cut -c1-90'; up
log refine; cool; (cd $T && py -3 -u refine_check.py --out "$O/refine" --scenarios ventilation_failure,pm_spike,power_throttling,load_surge,tank_leak,pump_cycling,stuck_sensor,heat_buildup,off_hours_presence,crowded_room > "$O/refine_console.txt" 2>&1); tail -1 "$O/refine_console.txt"
py -3 C:/Users/hp/Desktop/qidk/proofs/2026-10-21_v2_app/check_windows.py "$O/refine" | tail -1; up
log recheck; cool; (cd $T && py -3 -u recheck_check.py --out "$O/recheck" --cases improve:power_throttling,improve:pm_spike,improve:ventilation_failure,hold:ventilation_failure,hold:power_throttling > "$O/recheck_console.txt" 2>&1); grep "^==" "$O/recheck_console.txt"; up
log chaos; cool; (cd $T && py -3 -u stress_app.py --quick --only chaos > "$O/chaos_console.txt" 2>&1; cp stress_report.json "$O/chaos_report.json"); grep -E "NPU agents|====" "$O/chaos_console.txt"; up
for i in 1 2 3; do $A shell "screencap -p /sdcard/s$i.png"; $A pull /sdcard/s$i.png "$O/board_$i.png" >/dev/null; $A shell "rm /sdcard/s$i.png; input keyevent 61"; sleep 3; done
log done
