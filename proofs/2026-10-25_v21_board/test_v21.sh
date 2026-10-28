#!/usr/bin/env bash
# v2.1 on board (2026-10-25): push, switch, sim stories + host400 + placement, then back to mixA50 unless told otherwise.
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
SRC=${1:?local gguf}; MD5=${2:?md5}; G=/data/local/tmp/gpu/ft_v21_q4_0.gguf; O=v21
log "stop app + htpd"; $A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; sleep 10'
log push; $A push "$SRC" $G.part || exit 1
R=$($A shell "md5sum $G.part" | cut -c1-32); [ "$R" = "$MD5" ] || { log "md5 mismatch $R"; exit 1; }
$A shell "mv -f $G.part $G && echo $MD5 > $G.md5"
switch $G; mkdir -p $O
log "sim stories"; SIM_OUT="$HERE/$O" py -3 -u ../2026-10-25_mixA50_realworld/sim.py > $O/sim_console.txt 2>&1; grep "^##" $O/sim_console.txt
(cd $T && py -3 -c "import stress_app as S; S.reset('10:00')"); sleep 15; cool; $A forward tcp:8091 tcp:8091 >/dev/null
(cd $E && py -3 eval_htpd_v2.py --set host400 --out "$HERE/$O/host400" --port 8091 --hot 74 --cool 65) > "$O/host400.log" 2>&1; up
mkdir -p "$O/placement_s24"; cp $P24/{prompts.jsonl,cases.jsonl,manifest.json} "$O/placement_s24/"; $A forward tcp:8091 tcp:8091 >/dev/null
(cd $E && py -3 placement_v2.py run --out "$HERE/$O/placement_s24" --port 8091 --hot 74 --cool 65 && py -3 placement_v2.py analyze --out "$HERE/$O/placement_s24") > "$O/placement.log" 2>&1; up
switch /data/local/tmp/gpu/ft_mixA50_q4_0.gguf; log "all done"
