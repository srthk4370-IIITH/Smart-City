t=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1)
n=$(for z in /sys/class/thermal/thermal_zone*; do case "$(cat $z/type)" in *nsp*|*NSP*) cat $z/temp;; esac; done | sort -rn | head -1)
a=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo); r=0
for p in $(pidof htpd_v9f); do r=$(awk '/VmRSS/ {print int($2/1024)}' /proc/$p/status); done
echo "t=$((${t:-0}/1000)) nsp=$((${n:-0}/1000)) avail=$a htpd_rss=$r"
