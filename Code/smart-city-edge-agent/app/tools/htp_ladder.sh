#!/usr/bin/env bash
# llama.cpp Hexagon (HTP/NPU) bring-up + batched-decode ladder on the QIDK (HANDBOOK 2.37).
# Same safety rules as gpu_ladder.sh, plus an ON-DEVICE watchdog that kills llama if the Normal zone
# (where NPU dma-buf and GPU memory must live) drops below 800 MB free - the board may be unattended.
#   bash htp_ladder.sh <out_dir> [first] [last]
set -u
OUT=${1:?out dir}; FIRST=${2:-1}; LAST=${3:-99}
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
mkdir -p "$OUT"
D=/data/local/tmp/llama.cpp
M=/data/local/tmp/gpu/ft_device_q4exact.gguf
ENV="LD_LIBRARY_PATH=$D/lib ADSP_LIBRARY_PATH=$D/lib GGML_HEXAGON_POWER_MODE=sustained_high_performance"

sh_dev() { MSYS_NO_PATHCONV=1 "$ADB" shell "$@"; }

sh_dev 'pkill -f htpguard.sh; cat > /data/local/tmp/htpguard.sh <<"EOF"
while true; do
  n=$(awk "/zone   Normal/ {z=1} z && /pages free/ {print int(\$3*4/1024); exit}" /proc/zoneinfo)
  if [ "$n" -lt 800 ]; then pkill -9 -x llama-batched-bench; pkill -9 -x llama-server; pkill -9 -x llama-bench; echo "$(date +%T) GUARD KILL normal=$n" >> /data/local/tmp/htpguard.log; fi
  sleep 0.3
done
EOF
chmod 755 /data/local/tmp/htpguard.sh; (setsid nohup sh /data/local/tmp/htpguard.sh >/dev/null 2>&1 </dev/null &)'

sh_dev "dmesg -w" > "$OUT/dmesg.log" 2>&1 &
P1=$!
MSYS_NO_PATHCONV=1 "$ADB" logcat -b all -v time > "$OUT/logcat.log" 2>&1 &
P2=$!
sh_dev 'while true; do
  t=0; tz=-; for z in /sys/class/thermal/thermal_zone*; do v=$(cat $z/temp 2>/dev/null); [ -n "$v" ] && [ "$v" -gt "$t" ] && t=$v && tz=$(cat $z/type); done
  echo "$(date +%s.%N | cut -c1-14) iBat=$(cat /sys/class/power_supply/battery/current_now) vph=$(cat /sys/bus/iio/devices/iio:device0/in_voltage_pm8550_vph_pwr_input) tmax=$((t/1000)) tzone=$tz normalFreeMB=$(awk "/zone   Normal/ {n=1} n && /pages free/ {print int(\$3*4/1024); exit}" /proc/zoneinfo) $(pgrep -l llama | tr "\n" " ")"
  sleep 0.5; done' > "$OUT/telemetry.log" 2>&1 &
P3=$!
trap 'kill $P1 $P2 $P3 2>/dev/null' EXIT

BB="./bin/llama-batched-bench -m $M --device HTP0 -ngl 99"
STEPS=(
  "01_htp_tiny_np1|$BB -fa on -c 1024 -b 256 -ub 256 -npp 128 -ntg 16 -npl 1"
  "02_htp_real_np1|$BB -fa on -c 2048 -b 512 -ub 512 -npp 600 -ntg 80 -npl 1"
  "03_htp_real_np124|$BB -fa on -c 4096 -b 512 -ub 512 -npp 600 -ntg 80 -npl 1,2,4"
  "04_htp_real_np8|$BB -fa on -c 8192 -b 512 -ub 512 -npp 600 -ntg 80 -npl 8"
  "05_htp_real_np13|$BB -fa on -c 12288 -ctk q8_0 -ctv q8_0 -b 512 -ub 512 -npp 600 -ntg 80 -npl 13"
  "06_htp_shared_prefix_np13|$BB -fa on -pps -c 4096 -b 512 -ub 512 -npp 600 -ntg 80 -npl 1,4,8,13"
)

alive() { timeout 20 "$ADB" shell true >/dev/null 2>&1; }

for s in "${STEPS[@]}"; do
  name=${s%%|*}; cmd=${s#*|}
  n=${name%%_*}; n=$((10#$n))
  [ "$n" -lt "$FIRST" ] && continue
  [ "$n" -gt "$LAST" ] && break
  sh_dev "sync; echo 3 > /proc/sys/vm/drop_caches; echo 1 > /proc/sys/vm/compact_memory"
  nf=$(sh_dev "awk '/zone   Normal/ {n=1} n && /pages free/ {print int(\$3*4/1024); exit}' /proc/zoneinfo" | tr -d '\r')
  echo "[$(date +%T)] $name  (Normal free ${nf} MB)" | tee -a "$OUT/ladder.log"
  echo "$cmd" > "$OUT/step_$name.cmd"
  t0=$(date +%s)
  sh_dev "cd $D && echo 1000 > /proc/self/oom_score_adj && $ENV timeout 900 sh -c '$cmd'" > "$OUT/step_$name.log" 2>&1
  rc=$?
  dt=$(( $(date +%s) - t0 ))
  if ! alive; then
    echo "[$(date +%T)] $name: DEVICE LOST after ${dt}s (rc=$rc)" | tee -a "$OUT/ladder.log"
    exit 2
  fi
  echo "[$(date +%T)] $name: rc=$rc ${dt}s" | tee -a "$OUT/ladder.log"
  grep -E '^\|' "$OUT/step_$name.log" | grep -v -- '---' | tee -a "$OUT/ladder.log"
  sh_dev "cat /data/local/tmp/htpguard.log 2>/dev/null | tail -2" | tee -a "$OUT/ladder.log"
  [ $rc -ne 0 ] && { echo "stopping at failed step" | tee -a "$OUT/ladder.log"; exit 1; }
  sleep 20
done
echo "[$(date +%T)] ladder complete" | tee -a "$OUT/ladder.log"
