#!/bin/bash
# every 5 min: board screen shot (home), status/gate/progress snapshot; every 15 min: API sweep
A=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
n=0
while [ ! -e STOP_FEEDER ]; do
  t=$(date +%H%M)
  $A shell "input keyevent KEYCODE_WAKEUP" >/dev/null 2>&1
  $A exec-out screencap -p > ui/auto_$t.png 2>/dev/null
  curl -s -m 10 127.0.0.1:8000/api/status | py -c "import json,sys,time;d=json.load(sys.stdin);print(json.dumps(dict(t=time.strftime('%H:%M:%S'),dev=d['device'],npu=d['npu'],gate=d['gate'],progress=d.get('progress'))))" >> status_snaps.jsonl 2>/dev/null
  if [ $((n % 3)) -eq 0 ]; then py api_sweep.py p$t > api_sweep_p$t.out 2>&1; fi
  n=$((n+1))
  timeout 300 tail -f /dev/null
done
