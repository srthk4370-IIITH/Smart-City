#!/usr/bin/env bash
# Standalone (bash proofs/detach.sh split6 <this>): wait for the board, take BOARD_LOCK, run the split-N A/B
# (sp3 live vs sp6 vs sp4, 30 RWH prompts, board-side ab_board.sh: app stopped, one NPU client, <= 60 C, app restarted),
# pull raw/split6, write the accuracy table. Nothing is deployed. Log: split6_ab.log
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; K=$M/BOARD_LOCK; W=/data/local/tmp/rfast
exec >> $M/split6_ab.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
w(){ wslpath -w "$1"; }
log "=== split6 A/B: wait for board"
until $A get-state 2>/dev/null | grep -q device; do sleep 60; done
while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do log "BOARD_LOCK held: wait"; sleep 120; done
echo split6 > $K; ( while [ -e $K ]; do touch $K; sleep 600; done ) & TP=$!
trap 'kill $TP 2>/dev/null; rm -f $K' EXIT
sed -i 's/\r$//' $RF/scripts/ab_board.sh $RF/scripts/run_split6.sh
$A push "$(w $RF/scripts/ab_board.sh)" $W/ab_board.sh > /dev/null
$A push "$(w $RF/scripts/run_split6.sh)" $W/run_split6.sh > /dev/null
for d in rreq_split4 rreq_split6; do $A shell "rm -rf $W/$d"; $A push "$(w $RF/bench/$d)" $W/ > /dev/null; done
$A shell "ls $W/rreq_split6 | wc -l; ls $W/rreq | wc -l" | tr -d '\r'
$A shell "rm -f $W/ab/DONE; cd $W && setsid nohup sh run_split6.sh > /dev/null 2>&1 &"; log "started on board"
sleep 120
until $A shell "tail -1 $W/ab/ab.log 2>/dev/null" | grep -qE "=== ab done|restart app"; do
  $A get-state 2>/dev/null | grep -q device || log "board offline (run continues on board)"; sleep 120; done
sleep 30; rm -rf $RF/raw/split6; $A pull $W/ab "$(w $RF/raw)" > /dev/null; mv $RF/raw/ab $RF/raw/split6
(cd $RF/scripts && REF=sp3 python3 -I split_acc.py ../raw/split6 10) | tee $RF/raw/split6/acc.md
grep -hE "reason stream|split at" $RF/raw/split6/htpd_sp6.log | tail -6
log "=== split6 done"
