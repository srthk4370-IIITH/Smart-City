#!/bin/bash
# keepalive.sh <detached-name> <max_hours>: holds one wsl.exe session open (instanceIdleTimeout=15 s would otherwise
# shut the distro down and kill detached jobs) while ~/detached/<name>.pid is alive; at most <max_hours>.
n=$1; end=$(( $(date +%s) + ${2:-15} * 3600 )); sleep 20
while [ $(date +%s) -lt $end ]; do
  p=$(cat ~/detached/$n.pid 2>/dev/null); [ -n "$p" ] && kill -0 $p 2>/dev/null || break
  sleep 30
done
echo "keepalive $n exit $(date)" >> ~/detached/keepalive_$n.log
