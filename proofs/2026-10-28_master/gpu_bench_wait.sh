#!/usr/bin/env bash
# Standalone: after split6_ab finishes, take BOARD_LOCK and run gpu_bench.sh on the board; pull to proofs/2026-10-28_master/gpu_bench_out.
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; K=$M/BOARD_LOCK; W=/data/local/tmp/rfast/gpu
exec >> $M/gpu_bench.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
log "=== wait for split6"
until grep -q "=== split6 done" $M/split6_ab.log 2>/dev/null; do sleep 120; done
until $A get-state 2>/dev/null | grep -q device; do sleep 60; done
while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do sleep 120; done
echo gpu > $K; trap 'rm -f $K' EXIT
sed -i 's/\r$//' $M/gpu_bench.sh
$A shell "mkdir -p $W; rm -f $W/DONE"; $A push "$(wslpath -w $M/gpu_bench.sh)" $W/gpu_bench.sh > /dev/null
$A shell "cd $W && setsid nohup sh gpu_bench.sh > /dev/null 2>&1 &"; log "started"; sleep 60
until $A shell "cat $W/DONE 2>/dev/null" | grep -q .; do sleep 60; done
rm -rf $M/gpu_bench_out; mkdir -p $M/gpu_bench_out; $A pull $W/. "$(wslpath -w $M/gpu_bench_out)" > /dev/null
grep -E "\|" $M/gpu_bench_out/out.md | tail -12; sort -t= -k4 -n $M/gpu_bench_out/telemetry.log | head -1
log "=== gpu_bench done"
