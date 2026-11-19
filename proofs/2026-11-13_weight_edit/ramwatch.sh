#!/usr/bin/env bash
# ramwatch.sh (owner OK 2026-11-13): drop the WSL page cache (cache only, no data) when Windows free RAM < 1 GB. Every 2 min.
# Run as root inside WSL (detached). Stop: touch /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit/RAMWATCH_STOP
LOG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit/ramwatch.log
STOP=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit/RAMWATCH_STOP
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
while [ ! -e "$STOP" ]; do
  f=$($PS -NoProfile -Command '[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)' 2>/dev/null | tr -dc 0-9)
  c=$(awk '/^Cached:/{print int($2/1024)}' /proc/meminfo)
  if [ -n "$f" ] && [ "$f" -lt 1536 ] && [ "${c:-0}" -gt 500 ]; then
    sync; echo 1 > /proc/sys/vm/drop_caches
    echo "$(date -Is) win_free=${f}MB wsl_cache=${c}MB -> dropped" >> "$LOG"
  fi
  sleep 120
done
