#!/usr/bin/env bash
# Standalone (bash proofs/detach.sh pruned <this>): guarded retry of the pruned lm_head (owner-approved 2026-10-28).
# Waits for the board + BOARD_LOCK (shared with split6_ab / gpu_bench_wait), takes and refreshes the lock, pushes
# htpd_v8p2 (current htpd + libllama_p) and the board script, runs it, watches for a reboot (uptime reset), pulls
# raw/pruned_ab and writes the table. Nothing is deployed. Log: pruned_ab.log
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; K=$M/BOARD_LOCK; W=/data/local/tmp/rfast
exec >> $M/pruned_ab.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
log "=== pruned A/B: wait for board"
until $A get-state 2>/dev/null | grep -q device; do sleep 60; done
while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do log "BOARD_LOCK held ($(cat $K 2>/dev/null)): wait"; sleep 120; done
echo pruned > $K; ( while [ -e $K ]; do touch $K; sleep 600; done ) & TP=$!
trap 'kill $TP 2>/dev/null; rm -f $K' EXIT
m=$(md5sum $RF/htpd_v8p2/htpd | cut -d' ' -f1)
$A push "$(w $RF/htpd_v8p2/htpd)" /data/local/tmp/llama.cpp/bin/htpd_v8p2.part > /dev/null
[ "$(sh_ 'md5sum /data/local/tmp/llama.cpp/bin/htpd_v8p2.part' | cut -d' ' -f1)" = "$m" ] || { log "ABORT: htpd_v8p2 md5"; exit 3; }
sh_ 'cd /data/local/tmp/llama.cpp/bin && mv htpd_v8p2.part htpd_v8p2 && chmod 755 htpd_v8p2'
[ "$(sh_ 'md5sum /data/local/tmp/llama.cpp/lib/libllama_p.so' | cut -d' ' -f1)" = 482f27697fef6cef0f93a70090616aa2 ] || { log "ABORT: libllama_p md5 on board"; exit 3; }
sed -i 's/\r$//' $RF/scripts/pruned_ab.sh
$A push "$(w $RF/scripts/pruned_ab.sh)" $W/pruned_ab.sh > /dev/null
$A shell "rm -f $W/rreq_split/*.part; ls $W/rreq_split | wc -l" | tr -d '\r'
up0=$(sh_ 'cut -d. -f1 /proc/uptime')
sh_ "rm -rf $W/prab; cd $W && (setsid nohup sh pruned_ab.sh > /dev/null 2>&1 < /dev/null &)"; log "started on board (uptime $up0 s)"
sleep 90
while true; do
  if $A get-state 2>/dev/null | grep -q device; then
    up=$(sh_ 'cut -d. -f1 /proc/uptime')
    if [ -n "$up" ] && [ "$up" -lt "$up0" ]; then log "REBOOT DETECTED: uptime $up < $up0 (board rebooted during the pruned run)"; break; fi
    up0=$up
    sh_ "tail -1 $W/prab/ab.log 2>/dev/null" | grep -q "=== pruned ab done" && break
  else log "board offline"; fi
  sleep 60
done
sleep 20; rm -rf $RF/raw/pruned_ab; $A pull $W/prab "$(w $RF/raw)" > /dev/null; mv $RF/raw/prab $RF/raw/pruned_ab
(cd $RF/scripts && python3 -I ab_table.py ../raw/pruned_ab full) | tee $RF/raw/pruned_ab/table.md | grep -E "mean|ABORT"
grep -E "ABORT|probe passed|done" $RF/raw/pruned_ab/ab.log
log "=== pruned done"
