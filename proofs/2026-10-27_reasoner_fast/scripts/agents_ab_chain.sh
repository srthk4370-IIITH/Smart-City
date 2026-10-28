#!/usr/bin/env bash
# STANDALONE (detach.sh): BOARD_LOCK, push agents requests + agents_ab.sh, run it on the board, pull raw/agab, unlock.
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; L=$RF/logs/agents_ab_chain.log; exec >> $L 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }; sh_(){ "$A" shell "$@" | tr -d '\r'; }
while [ -e $M/BOARD_LOCK ]; do log "lock held: wait"; sleep 60; done
touch $M/BOARD_LOCK; trap 'rm -f $M/BOARD_LOCK' EXIT
for f in agents4.json agents10.json; do "$A" push "$(wslpath -w $RF/bench/$f)" /data/local/tmp/rfast/$f >/dev/null; done
"$A" push "$(wslpath -w $RF/scripts/agents_ab.sh)" /data/local/tmp/rfast/agents_ab.sh >/dev/null
sh_ 'cd /data/local/tmp/rfast; rm -rf agab; (setsid nohup sh agents_ab.sh > /dev/null 2>&1 < /dev/null &)'; log "started"; sleep 60
while [ "$(sh_ 'grep -cE "agents ab done|ABORT" /data/local/tmp/rfast/agab/ab.log')" != "1" ]; do sleep 60; done
mkdir -p $RF/raw/agab; sh_ 'cd /data/local/tmp/rfast/agab && tar cf /data/local/tmp/rfast/agab.tar .'
"$A" pull /data/local/tmp/rfast/agab.tar "$(wslpath -w $RF/raw/agab)" >/dev/null; (cd $RF/raw/agab && tar xf agab.tar && rm agab.tar)
log "=== done"
