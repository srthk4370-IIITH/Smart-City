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
arm() {  # $1 tag, $2 model path or ""
  local O=$1; mkdir -p "$O"
  switch "$2"
  log "$O: refine_check 10 scenarios"; cool
  (cd $T && py -3 -u refine_check.py --out "$HERE/$O/refine" --scenarios ventilation_failure,pm_spike,power_throttling,load_surge,tank_leak,pump_cycling,stuck_sensor,heat_buildup,off_hours_presence,crowded_room > "$HERE/$O/refine_console.txt" 2>&1)
  py -3 C:/Users/hp/Desktop/qidk/proofs/2026-10-21_v2_app/check_windows.py "$O/refine" > "$O/refine/window_check.txt" 2>&1; tail -1 "$O/refine_console.txt"; up
  log "$O: recheck curb/elevate"; cool
  (cd $T && py -3 -u recheck_check.py --out "$HERE/$O/recheck" --cases improve:power_throttling,improve:pm_spike,improve:ventilation_failure,hold:ventilation_failure,hold:power_throttling > "$HERE/$O/recheck_console.txt" 2>&1); grep "^==" "$O/recheck_console.txt"; up
  log "$O: quick chaos"; cool
  (cd $T && py -3 -u stress_app.py --quick --only chaos > "$HERE/$O/chaos_console.txt" 2>&1; cp stress_report.json "$HERE/$O/chaos_report.json"); grep -E "NPU agents|====" "$O/chaos_console.txt"; up
  log "$O: idle the app (reset drops pending refinements), then large sets on the app's htpd"
  (cd $T && py -3 -c "import stress_app as S; S.reset('10:00')"); sleep 15; cool
  (cd $E && py -3 eval_htpd_v2.py --set host400 --out "$HERE/$O/host400" --port 8091 --hot 74 --cool 65) > "$O/host400.log" 2>&1; up
  mkdir -p "$O/placement_s24"; cp $P24/{prompts.jsonl,cases.jsonl,manifest.json} "$O/placement_s24/"
  (cd $E && py -3 placement_v2.py run --out "$HERE/$O/placement_s24" --port 8091 --hot 74 --cool 65 && py -3 placement_v2.py analyze --out "$HERE/$O/placement_s24") > "$O/placement.log" 2>&1; up
  log "$O: done"
}
log "start"; up
arm v2 ""
arm mixA50 /data/local/tmp/gpu/ft_mixA50_q4_0.gguf
switch ""   # leave the app on v2
log "all done"
