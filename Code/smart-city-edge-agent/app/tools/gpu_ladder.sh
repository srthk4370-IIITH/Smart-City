#!/usr/bin/env bash
# GPU bring-up ladder for llama.cpp OpenCL on the QIDK (HANDBOOK 2.37).
#
# Two earlier attempts rebooted the board and left no trace, because every log was written ON the
# device. Here everything streams to the laptop while each step runs:
#   dmesg.log     kernel log (adb root)            logcat.log  all logcat buffers
#   telemetry.log every 0.5 s: battery current/voltage, VPH rail, GPU clock + busy, hottest zone, MemAvailable
#   step_*.log    the llama.cpp output of each step
# Steps go from tiny to the configuration that crashed, one variable at a time; the ladder stops at the
# first step that fails or loses the device. llama runs with oom_score_adj=1000 so Android's
# low-memory killer takes it first instead of system processes.
#
#   bash gpu_ladder.sh <out_dir> [first_step] [last_step]
set -u
OUT=${1:?out dir}; FIRST=${2:-1}; LAST=${3:-99}
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
mkdir -p "$OUT"
D=/data/local/tmp/gpu
M=ft_device_q4exact.gguf
ENV="LD_LIBRARY_PATH=$D:/vendor/lib64 GGML_OPENCL_KERNEL_CACHE_DIR=$D/clcache"

sh_dev() { MSYS_NO_PATHCONV=1 "$ADB" shell "$@"; }

# ---- streams to the host
sh_dev "dmesg -w" > "$OUT/dmesg.log" 2>&1 &
P1=$!
MSYS_NO_PATHCONV=1 "$ADB" logcat -b all -v time > "$OUT/logcat.log" 2>&1 &
P2=$!
sh_dev 'mkdir -p /data/local/tmp/gpu/clcache; while true; do
  t=0; tz=-; for z in /sys/class/thermal/thermal_zone*; do v=$(cat $z/temp 2>/dev/null); [ -n "$v" ] && [ "$v" -gt "$t" ] && t=$v && tz=$(cat $z/type); done
  echo "$(date +%s.%N | cut -c1-14) iBat=$(cat /sys/class/power_supply/battery/current_now) vBat=$(cat /sys/class/power_supply/battery/voltage_now) vph=$(cat /sys/bus/iio/devices/iio:device0/in_voltage_pm8550_vph_pwr_input) gpuHz=$(cat /sys/class/kgsl/kgsl-3d0/devfreq/cur_freq) gpuBusy=$(cat /sys/class/kgsl/kgsl-3d0/gpu_busy_percentage | tr -d " %") tmax=$((t/1000)) tzone=$tz kgslMB=$(( $(cat /sys/class/kgsl/kgsl/page_alloc) / 1048576 )) memMB=$(awk "/MemAvailable/ {print int(\$2/1024)}" /proc/meminfo) normalFreeMB=$(awk "/zone   Normal/ {n=1} n && /pages free/ {print int(\$3*4/1024); exit}" /proc/zoneinfo) $(pgrep -l llama | tr "\n" " ")"
  sleep 0.5; done' > "$OUT/telemetry.log" 2>&1 &
P3=$!
trap 'kill $P1 $P2 $P3 2>/dev/null' EXIT

# ---- the ladder: name | command (run in $D)
STEPS=(
  "01_bb_tiny_np1|./llama-batched-bench -m $M -ngl 99 -fa off -c 1024 -b 256 -ub 256 -npp 128 -ntg 16 -npl 1"
  "02_bb_tiny_np12|./llama-batched-bench -m $M -ngl 99 -fa off -c 1024 -b 256 -ub 256 -npp 128 -ntg 16 -npl 1,2"
  "03_bb_tiny_kvu_np124|./llama-batched-bench -m $M -ngl 99 -fa off -kvu -c 1024 -b 256 -ub 256 -npp 128 -ntg 16 -npl 1,2,4"
  "04_bb_real_kvu_np124|./llama-batched-bench -m $M -ngl 99 -fa off -kvu -c 4096 -b 512 -ub 512 -npp 600 -ntg 80 -npl 1,2,4"
  "05_bb_real_kvu_np124_mc3|GGML_OPENCL_Q40_MC3=1 ./llama-batched-bench -m $M -ngl 99 -fa off -kvu -c 4096 -b 512 -ub 512 -npp 600 -ntg 80 -npl 1,2,4"
  "06_bb_real_kvu_np123468_mc3|GGML_OPENCL_Q40_MC3=1 ./llama-batched-bench -m $M -ngl 99 -fa off -kvu -c 8192 -b 512 -ub 512 -npp 600 -ntg 80 -npl 1,2,3,4,6,8"
  "07_bb_shared_prefix_mc3|GGML_OPENCL_Q40_MC3=1 ./llama-batched-bench -m $M -ngl 99 -fa off -kvu -pps -c 4096 -b 512 -ub 512 -npp 600 -ntg 80 -npl 1,2,4"
  "08_bb_split_kv_mc3|GGML_OPENCL_Q40_MC3=1 ./llama-batched-bench -m $M -ngl 99 -fa off -c 4096 -b 512 -ub 512 -npp 600 -ntg 80 -npl 1,2,4"
  "09_bench_baseline|./llama-bench -m $M -ngl 99 -fa 0 -p 600 -n 80 -r 3"
  "10_bench_dp4a|GGML_OPENCL_Q4_0_DENSE_DP4A=1 ./llama-bench -m $M -ngl 99 -fa 0 -p 600 -n 80 -r 3"
  "11_bench_ubatch|./llama-bench -m $M -ngl 99 -fa 0 -p 600 -n 0 -ub 128,256,1024 -b 1024 -r 2"
  "12_bench_fa_on|./llama-bench -m $M -ngl 99 -fa 1 -p 600 -n 80 -r 2"
)

alive() { timeout 20 "$ADB" shell true >/dev/null 2>&1; }

for s in "${STEPS[@]}"; do
  name=${s%%|*}; cmd=${s#*|}
  n=${name%%_*}; n=$((10#$n))
  [ "$n" -lt "$FIRST" ] && continue
  [ "$n" -gt "$LAST" ] && break
  mem=$(sh_dev "awk '/MemAvailable/ {print int(\$2/1024)}' /proc/meminfo" | tr -d '\r')
  echo "[$(date +%T)] $name  (MemFree ${mem} MB after drop_caches+compact)" | tee -a "$OUT/ladder.log"
  echo "$cmd" > "$OUT/step_$name.cmd"
  t0=$(date +%s)
  sh_dev "cd $D && echo 1000 > /proc/self/oom_score_adj && $ENV timeout 600 sh -c '$cmd'" > "$OUT/step_$name.log" 2>&1
  rc=$?
  dt=$(( $(date +%s) - t0 ))
  if ! alive; then
    echo "[$(date +%T)] $name: DEVICE LOST after ${dt}s (rc=$rc) - stopping; host logs kept" | tee -a "$OUT/ladder.log"
    exit 2
  fi
  echo "[$(date +%T)] $name: rc=$rc ${dt}s" | tee -a "$OUT/ladder.log"
  grep -E '^\|' "$OUT/step_$name.log" | tee -a "$OUT/ladder.log"
  [ $rc -ne 0 ] && { echo "stopping at failed step" | tee -a "$OUT/ladder.log"; exit 1; }
  sleep 20   # let clocks and temperature settle between steps
done
echo "[$(date +%T)] ladder complete" | tee -a "$OUT/ladder.log"
