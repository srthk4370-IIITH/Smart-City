#!/system/bin/sh
# Board-side: the reasoner (Qwen3.5-4B Q4_0) on the Adreno GPU ALONE (app stopped, no NPU model loaded = the safe
# GPU-only class, HANDBOOK 2.37). Measures pp/tg single stream and batched decode (npl 1,3,6) to cost "reasoner on
# GPU, agents on NPU". Records kgsl MB + Normal-zone free while the model is loaded (the coexistence risk).
# Guards: one NPU/GPU client, start < 60 C, llama oom_score_adj 1000, MemAvailable < 800 MB -> kill llama. Never reboots.
D=/data/local/tmp/llama.cpp; M=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf; W=/data/local/tmp/rfast/gpu; mkdir -p $W/clcache; rm -f $W/DONE
LOG=$W/gpu.log; log() { echo "$(date +%T) $*" >> $LOG; }
tmax() { cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1 | awk '{print int($1/1000)}'; }
mavail() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
nfree() { awk '/zone   Normal/ {z=1} z && /pages free/ {print int($3*4/1024); exit}' /proc/zoneinfo; }
kgsl() { echo $(( $(cat /sys/class/kgsl/kgsl/page_alloc 2>/dev/null || echo 0) / 1048576 )); }
log "=== gpu_bench start"
am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -f "[b]in/htpd"
for i in $(seq 1 90); do ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie)" || break; sleep 1; done
if ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)"; then log "ABORT: client still running"; echo abort > $W/DONE; exit 3; fi
sleep 30
( while [ ! -e $W/DONE ]; do a=$(mavail); echo "$(date +%T) t=$(tmax) avail=$a normal=$(nfree) kgslMB=$(kgsl)" >> $W/telemetry.log
    [ "$a" -lt 800 ] && { pkill -9 -f "bin/llama-"; log "GUARD KILL avail=$a"; }; sleep 1; done ) &
export LD_LIBRARY_PATH=$D/lib:/vendor/lib64 ADSP_LIBRARY_PATH=$D/lib GGML_OPENCL_KERNEL_CACHE_DIR=$W/clcache
$D/bin/llama-bench --list-devices > $W/devices.txt 2>&1
G=$(grep -oE "^ *GPU[A-Za-z0-9]*" $W/devices.txt | head -1 | tr -d ' '); [ -n "$G" ] || G=GPUOpenCL; log "device $G"
run() { while [ "$(tmax)" -ge 60 ]; do sleep 20; done; echo "## $1" >> $W/out.md; log "$1 (avail $(mavail), normal $(nfree))"; shift
  sh -c "echo 1000 > /proc/self/oom_score_adj; exec $*" >> $W/out.md 2>> $W/err.txt; log "  rc=$?"; sleep 20; }
N=/data/local/tmp/llama.cpp-new
B="-m $M --device $G -ngl 99 -p 1,2,3,4,6,8,512 -n 64 -r 2 -o md"
# old tree (Oct 16, 620d222) vs upstream 338fce65 (Qwen3.5 GDN/SSM OpenCL ops, multi-column GEMV, DP4A paths)
run old_fa0 "$D/bin/llama-bench $B -fa 0"
run new_fa0 "env LD_LIBRARY_PATH=$N/lib:/vendor/lib64 $N/bin/llama-bench $B -fa 0"
run new_mc3 "env LD_LIBRARY_PATH=$N/lib:/vendor/lib64 GGML_OPENCL_Q40_MC3=1 GGML_OPENCL_Q6K_MC3=1 GGML_OPENCL_ADRENO_USE_LARGE_BUFFER=1 $N/bin/llama-bench $B -fa 0"
run new_mc3_dp4a "env LD_LIBRARY_PATH=$N/lib:/vendor/lib64 GGML_OPENCL_Q40_MC3=1 GGML_OPENCL_Q6K_MC3=1 GGML_OPENCL_ADRENO_USE_LARGE_BUFFER=1 GGML_OPENCL_Q4_0_DENSE_DP4A=1 GGML_OPENCL_Q4_0_DP4A_ACT_VLOAD4=1 $N/bin/llama-bench $B -fa 0"
run new_mc3_fa1 "env LD_LIBRARY_PATH=$N/lib:/vendor/lib64 GGML_OPENCL_Q40_MC3=1 GGML_OPENCL_Q6K_MC3=1 GGML_OPENCL_ADRENO_USE_LARGE_BUFFER=1 $N/bin/llama-bench $B -fa 1"
log "restart app"; am start -n com.iiith.smartcityedge/.MainActivity >> $LOG 2>&1
log "=== gpu_bench done"; echo ok > $W/DONE
