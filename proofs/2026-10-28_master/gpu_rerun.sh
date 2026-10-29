#!/usr/bin/env bash
# GPU-alone reasoner bench rerun (kernel cache now warm), after v2_deploy finishes; never after 10:45 IST. Numbers only.
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; I=$M/improve; K=$M/BOARD_LOCK; A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; G=/data/local/tmp/rfast/gpu
exec >> $I/gpu_rerun.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }; st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
until grep -q "=== v2 done\|V2 skipped\|V2 abort" $I/v2_deploy.log $I/STATUS.md 2>/dev/null; do sleep 30; done
[ $(date +%s) -lt $(date -d "2026-10-29 05:15 UTC" +%s) ] || { st "- GPU rerun skipped: after 10:45 IST"; exit 0; }
while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do sleep 30; done
echo gpu > $K; trap 'rm -f $K' EXIT
sed -i 's/\r$//' $M/gpu_bench.sh; $A shell "rm -f $G/DONE"; $A push "$(wslpath -w $M/gpu_bench.sh)" $G/gpu_bench.sh > /dev/null
$A shell "cd $G && (setsid nohup sh gpu_bench.sh > /dev/null 2>&1 < /dev/null &)"; log started; sleep 90
t0=$(date +%s); until $A shell "cat $G/DONE 2>/dev/null" | grep -q . || [ $(( $(date +%s) - t0 )) -gt 2400 ]; do sleep 60; done
rm -rf $M/gpu_bench_out; mkdir -p $M/gpu_bench_out; $A pull $G/. "$(wslpath -w $M/gpu_bench_out)" > /dev/null
st "- GPU rerun: $(cat $M/gpu_bench_out/DONE 2>/dev/null || echo timeout); max temp $(grep -oE 't=[0-9]+' $M/gpu_bench_out/telemetry.log | cut -d= -f2 | sort -n | tail -1) C; min avail $(grep -oE 'avail=[0-9]+' $M/gpu_bench_out/telemetry.log | cut -d= -f2 | sort -n | head -1) MB; max kgsl $(grep -oE 'kgslMB=[0-9]+' $M/gpu_bench_out/telemetry.log | cut -d= -f2 | sort -n | tail -1) MB"
grep "|" $M/gpu_bench_out/out.md >> $I/STATUS.md
sleep 60; $A shell 'ps -A -o NAME= | grep -E "^(htpd|edge-agent)"' | tr -d '\r' | grep -q edge || { $A shell 'am start -n com.iiith.smartcityedge/.MainActivity' >/dev/null; st "- app restarted after GPU rerun"; }
log "=== gpu rerun done"
