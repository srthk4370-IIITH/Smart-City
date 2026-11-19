#!/system/bin/sh
# per-zone sampler (2 s): time, top-4 zones by temp with names, NSP max, MemAvailable, NPU-client process names. Stop: touch /data/local/tmp/rfast/ZSTOP
O=/data/local/tmp/rfast/zones_2b.log; rm -f /data/local/tmp/rfast/ZSTOP
while [ ! -e /data/local/tmp/rfast/ZSTOP ]; do
  top=$(for z in /sys/class/thermal/thermal_zone*; do echo "$(cat $z/temp) $(cat $z/type)"; done 2>/dev/null | sort -rn | head -4 | awk '{printf "%s=%d ", $2, $1/1000}')
  a=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
  echo "$(date +%T) $top avail=$a procs=$(ps -A -o NAME= | grep -E '^(htpd|edge-agent)' | tr '\n' ',')" >> $O
  sleep 2
done
