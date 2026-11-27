#!/bin/bash
# board telemetry every 30 s: thermals, mem, htpd/edge-agent RSS, load -> tele.log
A=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
while [ ! -e STOP_FEEDER ]; do
  MSYS_NO_PATHCONV=1 $A shell 'echo "$(date +%H:%M:%S) t=$(cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1) avail=$(awk "/MemAvailable/{print int(\$2/1024)}" /proc/meminfo) load=$(cut -d" " -f1 /proc/loadavg) htpd=$(pidof htpd_v9h) ea=$(pidof edge-agent)"' >> tele.log 2>&1
  sleep 30
done
