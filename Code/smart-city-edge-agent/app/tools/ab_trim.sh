#!/usr/bin/env bash
# Lean A/B of SCE_TRIM_ACTION on the real app path.
#
# policy.go derives `action` from (cause,status), so tokens spent emitting `, "action": "..."`
# are pure latency. This measures the saving and proves nothing breaks.
#
# Fixed sleeps instead of polling /api/status: the poll loop cost ~25 min for one call because
# each adb round-trip is slow. An agent call is ~5-7 s, so 16 s between requests is ample.
# The backend is started manually (app force-stopped) because EdgeService would overwrite the
# binary with the APK copy, which has no trim code. The genie prompt cache is per-process and we
# restart between arms, so arm 1 cannot be served from arm 0's cache.
set -u
export MSYS_NO_PATHCONV=1
A=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
D=/data/local/tmp/smart_city_edge
SENSORS="SR-AQ-KH03-03:co2 WM-WD-KH98-00:ph WE-VN04-00:temp EM-CR-SB00-00:pf"

run_arm() {
  trim=$1
  echo "===== arm trim=$trim ====="
  $A shell "am force-stop com.iiith.smartcityedge; pkill -x edge-agent; sleep 2; rm -f $D/state/incidents.jsonl; cd $D && SCE_TRIM_ACTION=$trim setsid nohup ./edge-agent --dir $D --genie /data/local/tmp/genie_bundle --mode 3 --clock-unix \$(date +%s) > state/agent.log 2>&1 < /dev/null & sleep 10; echo started" >/dev/null 2>&1
  sleep 6
  for s in $SENSORS; do
    n=${s%%:*}; m=${s##*:}
    $A shell "curl -s -m 5 -X POST -d '{\"node\":\"$n\",\"metric\":\"$m\",\"mode\":3}' http://127.0.0.1:8000/api/analyze" >/dev/null 2>&1
    sleep 16
  done
  sleep 6
  $A shell "cat $D/state/incidents.jsonl" > "/tmp/rows_$trim.txt" 2>/dev/null
  echo "arm $trim: $(grep -c 'INC-' "/tmp/rows_$trim.txt" 2>/dev/null) incident records"
  $A shell "cat /proc/\$(pgrep -x edge-agent)/environ | tr '\\0' '\\n' | grep SCE_TRIM" 2>/dev/null
}

run_arm 0
run_arm 1
echo "RAW CAPTURED"
