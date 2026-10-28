#!/usr/bin/env bash
# gated.sh CMD... : owner on the laptop -> wait until Windows has >= GATE_MB (default 3072) MB free, then run CMD under
# nice -n 19 ionice -c3 (children inherit both).
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
winfree() { $PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -d '\r'; }
G=${GATE_MB:-3072}
while true; do f=$(winfree); [ -n "$f" ] && [ "$f" -ge "$G" ] && break; echo "$(date +%T) gated: Windows free ${f} MB < $G, waiting" >&2; sleep 30; done
exec nice -n 19 ionice -c3 "$@"
