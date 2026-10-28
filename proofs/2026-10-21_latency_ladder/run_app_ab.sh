#!/usr/bin/env bash
# Through-the-app A/B (PLAN.md section 4, step 3). Same method as the v1 reference (2026-10-16 v6: 20.7 s chaos was
# measured by `stress_app.py --only scenarios,chaos`, i.e. after the scenarios phase, htpd warm): scenarios (single-agent
# Mode 3 incidents + Mode 2) then chaos 2 simultaneous + 1 staggered. Before it, one COLD chaos round right after an
# htpd restart (the demo case: first incident after the app starts).
#   bash run_app_ab.sh TAG PROFILE_FILE [WARMUP_FILE]
#     PROFILE_FILE  key=value lines for /data/local/tmp/smart_city_edge/htpd_profile (see profiles/*.txt)
#     WARMUP_FILE   optional htpd_warmup.jsonl (needs the backend patch: htpdWarmup); "-" = none
# The previous htpd_profile is saved to app_<TAG>/htpd_profile.before and restored at the end.
set -uo pipefail
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8 MSYS_NO_PATHCONV=1
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
TOOLS=/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/tools
W=/data/local/tmp/smart_city_edge
TAG=${1:?tag}; PROF=${2:?profile file}; WU=${3:--}
OUT=app_$TAG
mkdir -p "$OUT"
MB=$(grep -E '^agents=' "$PROF" | cut -d= -f2); MB=${MB:-10}   # backend batch size = htpd streams
[ "$("$ADB" get-state 2>/dev/null)" = device ] || { echo "QIDK not connected"; exit 1; }
nsp() { "$ADB" shell 'for z in /sys/class/thermal/thermal_zone*; do case $(cat $z/type 2>/dev/null) in nsp*) cat $z/temp;; esac; done' | tr -d '\r' | sort -n | tail -1; }
cool() { for i in $(seq 1 90); do t=$(nsp); { [ -z "$t" ] || [ "$t" -lt 15000 ]; } && { sleep 180; return; }; [ "$t" -lt "${1:-55000}" ] && { echo "nsp $t"; return; }; sleep 10; done; }
restart_app() {
  "$ADB" shell am force-stop com.iiith.smartcityedge
  "$ADB" shell 'pkill -x edge-agent; pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; for i in $(seq 1 80); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; sleep 10; true'
  "$ADB" shell 'monkey -p com.iiith.smartcityedge -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; true'
  "$ADB" forward tcp:8000 tcp:8000 >/dev/null
  for i in $(seq 1 60); do "$ADB" shell "grep -q 'htpd: started' $W/state/agent.log 2>/dev/null" && break; sleep 3; done
  # the backend warm-up (if any) logs "htpd: warm-up N requests in ..."; give it up to 60 s
  for i in $(seq 1 30); do "$ADB" shell "grep -qE 'warm-up [0-9]+ requests|warm-up stopped' $W/state/agent.log 2>/dev/null" && break; [ "$WU" = "-" ] && break; sleep 2; done
}

"$ADB" shell "cat $W/htpd_profile 2>/dev/null" | tr -d '\r' > "$OUT/htpd_profile.before"
restore() {
  if [ -s "$OUT/htpd_profile.before" ]; then "$ADB" push "$OUT/htpd_profile.before" "$W/htpd_profile" >/dev/null; else "$ADB" shell "rm -f $W/htpd_profile"; fi
  "$ADB" shell "rm -f $W/htpd_warmup.jsonl"
  echo "profile restored; restart the app to apply"
}
trap restore EXIT
"$ADB" push "$PROF" "$W/htpd_profile" >/dev/null
cp "$PROF" "$OUT/htpd_profile.used"
if [ "$WU" != "-" ]; then "$ADB" push "$WU" "$W/htpd_warmup.jsonl" >/dev/null; else "$ADB" shell "rm -f $W/htpd_warmup.jsonl"; fi
"$ADB" shell "mv $W/state/agent.log $W/state/agent.log.pre_$TAG 2>/dev/null; true"

echo "=== $(date +%T) $TAG cold: fresh app + htpd, one chaos round"
cool 55000
restart_app
py -3 "$TOOLS/stress_app.py" --only chaos 2>&1 | tee "$OUT/cold_console.txt" | grep -E "NPU agents|checks passed|Mode 3"
cp "$TOOLS/stress_report.json" "$OUT/cold_stress_report.json"
py -3 app_breakdown.py "$OUT/cold" --report "$OUT/cold_stress_report.json" --max-batch "$MB"

echo "=== $(date +%T) $TAG warm: scenarios then chaos (v1 method)"
cool 55000
py -3 "$TOOLS/stress_app.py" --only scenarios,chaos 2>&1 | tee "$OUT/warm_console.txt" | grep -E "NPU agents|checks passed|Mode 3"
cp "$TOOLS/stress_report.json" "$OUT/warm_stress_report.json"
py -3 app_breakdown.py "$OUT/warm" --report "$OUT/warm_stress_report.json" --max-batch "$MB" --pull-logs
echo "=== $(date +%T) $TAG done -> $OUT"
