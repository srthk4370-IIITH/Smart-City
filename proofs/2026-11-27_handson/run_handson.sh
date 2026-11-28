#!/bin/bash
# Board check of the follow-up build: state backed up, feeder5 85 min (night hands-on), state kept as state_handson1127, original restored.
set -u
export MSYS_NO_PATHCONV=1
A=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
W=/data/local/tmp/smart_city_edge
HERE=$(cd "$(dirname "$0")" && pwd)
sh_(){ $A shell "$@" | tr -d '\r'; }
stop_(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9h); do kill -TERM $p; done; i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done; sleep 3; ps -A -o NAME= | grep -E "^(htpd|edge-agent)" || echo STOPPED'; }
start_(){ sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'; for i in $(seq 1 40); do sleep 5; curl -s -m 3 127.0.0.1:8000/api/status >/dev/null && break; done; }
echo "$(date +%T) stop: $(stop_)"
sh_ "cd $W && tar czf /data/local/tmp/handson_state_backup.tgz state && ls -la /data/local/tmp/handson_state_backup.tgz"
$A forward tcp:8000 tcp:8000 >/dev/null
start_; echo "$(date +%T) started"
cd "$HERE" && (bash tele.sh &) ; py -u feeder5.py 85 > feeder5.out 2>&1; touch STOP_FEEDER
curl -s 127.0.0.1:8000/api/incidents > end_incidents.json
for id in $(py -c "import json;print(' '.join(i['id'] for i in json.load(open('end_incidents.json')) if i['created_unix']>0))"); do curl -s 127.0.0.1:8000/api/incidents/$id > end_$id.json; done
echo "$(date +%T) stop: $(stop_)"
sh_ "cd $W && mv state state_handson1127 && tar xzf /data/local/tmp/handson_state_backup.tgz && ls state | wc -l"
start_; echo "$(date +%T) restored + started: $(sh_ 'pidof htpd_v9h edge-agent')"
