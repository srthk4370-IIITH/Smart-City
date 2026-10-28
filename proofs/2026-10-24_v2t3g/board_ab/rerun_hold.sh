#!/usr/bin/env bash
# v2 vs mixA50 (both + post_rules=all) compared INSIDE the app (2026-10-23, user): one NPU client only (the app's own htpd_v7).
# Per arm: clean switch -> through-the-app tests -> host400 + seed-24 placement sent to the app's htpd (port 8091).
set -uo pipefail
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
A=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge
T=/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/tools
E=/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post/device_eval_v2
P24=/c/Users/hp/Desktop/qidk/proofs/2026-10-21_v2_confirm/placement_s24
HERE=$(pwd -W 2>/dev/null || pwd)
log() { echo "=== $(date '+%F %T') $*"; }
up() { $A shell 'cat /proc/uptime; cat /sys/class/thermal/thermal_zone30/temp; pidof edge-agent htpd_v7' 2>&1 | tr '\n' ' '; echo; }
cool() { for i in $(seq 1 90); do t=$($A shell cat /sys/class/thermal/thermal_zone30/temp | tr -d '\r'); [ "${t:-99000}" -lt 50000 ] && return; sleep 10; done; }
switch() {  # $1 = "" (v2) or model path
  log "switch to ${1:-v2}"
  $A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; for i in $(seq 1 80); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; sleep 10; pgrep -fl htpd; true'
  $A shell "grep -v '^model=' $W/htpd_profile > $W/p.new; mv -f $W/p.new $W/htpd_profile; rm -f $W/state/htpd_args"
  [ -n "$1" ] && $A shell "echo model=$1 >> $W/htpd_profile"
  cool
  $A shell 'monkey -p com.iiith.smartcityedge -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1'
  for i in $(seq 1 40); do sleep 5; $A shell 'pidof htpd_v7' >/dev/null 2>&1 && curl -s -m 3 http://127.0.0.1:8000/api/status >/dev/null && break; $A forward tcp:8000 tcp:8000 >/dev/null 2>&1; done
  sleep 20; $A forward tcp:8000 tcp:8000 >/dev/null; $A forward tcp:8091 tcp:8091 >/dev/null
  $A shell 'cat /proc/$(pidof htpd_v7)/cmdline | tr "\0" " "' | cut -c1-120; up
}
# 2026-10-25: mixA50 hold rechecks gave "no incident" in the first A/B; rerun just them, then back to v2.
O=mixA50; log start; switch /data/local/tmp/gpu/ft_mixA50_q4_0.gguf; cool
(cd $T && py -3 -u recheck_check.py --out "$HERE/$O/recheck_hold" --cases hold:ventilation_failure,hold:power_throttling > "$HERE/$O/recheck_hold_console.txt" 2>&1); grep "^==\|no incident" "$O/recheck_hold_console.txt"; up
switch ""; log "all done"
