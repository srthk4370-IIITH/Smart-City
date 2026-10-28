#!/usr/bin/env bash
# Wait for the QIDK; FIRST force-stop the app + NPU daemons, THEN collect read-only crash evidence.
export MSYS_NO_PATHCONV=1
A=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
for i in $(seq 1 720); do [ "$($A get-state 2>/dev/null)" = device ] && break; sleep 5; done
echo "== $(date +%T) board visible"
$A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -x htpd_v7; pkill -x htpd; pkill -x genied; sleep 1; echo stopped; pidof edge-agent htpd_v7 htpd genied; true'
echo "== basics"; $A shell 'uptime; date; for p in sys.boot.reason sys.boot.reason.last ro.boot.bootreason persist.sys.boot.reason persist.sys.boot.reason.history ro.boot.bootreason_history; do echo "$p=$(getprop $p)"; done'
echo "== memory"; $A shell 'head -5 /proc/meminfo; df -h /data | tail -1'
echo "== thermal now"; $A shell 'for z in /sys/class/thermal/thermal_zone*; do t=$(cat $z/type); case $t in *nsp*|*cpu-0-0*|*skin*|*pmic*|*xo*|*battery*|*sys-therm*) echo "$t $(cat $z/temp)";; esac; done'
echo "== logcat crash/system (previous events since boot)"; $A shell 'logcat -d -b crash 2>/dev/null | tail -60'
$A shell 'logcat -d -b system 2>/dev/null | grep -iE "shutdown|reboot|watchdog|thermal|lowmem|lmkd|kill|panic|fatal" | tail -60'
echo "== kernel log this boot"; $A shell 'dmesg 2>/dev/null | grep -iE "reset|reason|pon|thermal|shutdown|panic|watchdog|wdog|oom|ocp|uvlo|brown" | head -60'
echo "== dropbox"; $A shell 'dumpsys dropbox 2>/dev/null | grep -E "SYSTEM_|kernel|crash|panic|watchdog|thermal" | tail -40'
echo "== previous boot logs (needs root; read-only)"; $A root 2>&1 | head -2; sleep 6; $A wait-for-device
$A shell 'ls -la /sys/fs/pstore/ 2>&1; for f in /sys/fs/pstore/*; do echo "--- $f"; tail -120 $f; done; ls /proc/last_kmsg 2>/dev/null && tail -120 /proc/last_kmsg' 2>&1 | tail -260
$A shell 'cat /proc/sys/kernel/tainted; ls -la /data/vendor/ramdump /data/vendor/ssrdump 2>/dev/null | tail -10'
$A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -x htpd_v7; true'
echo "== $(date +%T) done (app left stopped)"
