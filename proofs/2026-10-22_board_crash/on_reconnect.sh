#!/usr/bin/env bash
# Run the moment the QIDK is back: stop the app FIRST, revert htpd_profile to the stable v2 model (drop the
# model= line), collect evidence of why it went down, relaunch the app on v2 and watch it for 5 min.
export MSYS_NO_PATHCONV=1
A=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge
for i in $(seq 1 720); do [ "$($A get-state 2>/dev/null)" = device ] && break; sleep 5; done
echo "== $(date +%T) visible"
$A shell "am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -x htpd_v7; pkill -x htpd; echo stopped; cat /proc/uptime"
$A shell "grep -v '^model=' $W/htpd_profile > $W/htpd_profile.new; mv -f $W/htpd_profile.new $W/htpd_profile; rm -f $W/state/htpd_args; cat $W/htpd_profile"
echo "== evidence"; $A shell 'for p in sys.boot.reason sys.boot.reason.last persist.sys.boot.reason.history; do echo "$p=$(getprop $p)"; done; head -3 /proc/meminfo'
$A shell 'tail -40 /data/local/tmp/smart_city_edge/state/htpd.log 2>/dev/null | grep -vE "llama_graph_n_input|sched_reserve" | tail -15'
$A shell 'tail -30 /data/local/tmp/smart_city_edge/state/agent.log 2>/dev/null'
$A shell 'dumpsys dropbox --print SYSTEM_TOMBSTONE 2>/dev/null | grep -E "^Timestamp|^Cmdline|Abort message" | tail -6'
$A shell 'logcat -d -b crash 2>/dev/null | tail -20'
echo "== $(date +%T) relaunch on v2"
$A shell 'monkey -p com.iiith.smartcityedge -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1'
for k in $(seq 1 10); do sleep 30; echo "$(date +%T) $($A shell 'cat /proc/uptime; pidof edge-agent htpd_v7; cat /sys/class/thermal/thermal_zone30/temp' 2>&1 | tr '\n' ' ')"; done
$A shell 'cat /proc/$(pidof htpd_v7)/cmdline | tr "\0" " " | cut -c1-110'
echo "== $(date +%T) done"
