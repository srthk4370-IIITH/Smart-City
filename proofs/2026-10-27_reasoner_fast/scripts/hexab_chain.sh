#!/usr/bin/env bash
# STANDALONE (detach.sh): wait for the hex builds + chain step 2, take BOARD_LOCK, push htpd_new/htpd_k4 + k4 libs
# (.part + md5 + mv), run run_hexab.sh on the board (paced <= 60 C, one NPU client), pull results, release the lock.
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; K4=/mnt/c/Users/hp/gpu_work/llama.cpp-k4/pkg-android/llama.cpp
L=$RF/logs/hexab_chain.log; exec >> $L 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
sh_(){ "$A" shell "$@" | tr -d '\r'; }
push(){ src=$1; dst=$2; m=$(md5sum "$src" | cut -d' ' -f1); "$A" push "$(wslpath -w "$src")" "$dst.part" >/dev/null
  [ "$(sh_ "md5sum $dst.part" | cut -d' ' -f1)" = "$m" ] || { log "ABORT md5 $dst"; return 1; }; sh_ "mv $dst.part $dst; chmod 755 $dst"; log "pushed $dst $m"; }
log "=== hexab start"
until grep -q SKELS_DONE $RF/logs/build_skels.log 2>/dev/null; do sleep 120; done
NW=/mnt/c/Users/hp/gpu_work/llama.cpp-new/pkg-android/llama.cpp
[ -s $RF/htpd_new/htpd ] && [ -s $RF/htpd_k4/htpd ] && [ -s $K4/lib/libggml-htp-v75.so ] && [ -s $NW/lib/libggml-htp-v75.so ] || { log "ABORT: a build is missing"; exit 2; }
until [ -e $M/.s2 ]; do sleep 120; done
log "chain step 2 done: $(grep '2 bench' $M/chain.log | tail -1)"
while [ -e $M/BOARD_LOCK ]; do log "BOARD_LOCK held: wait"; sleep 120; done
touch $M/BOARD_LOCK; trap 'rm -f $M/BOARD_LOCK' EXIT
sh_ 'mkdir -p /data/local/tmp/llama.cpp-k4/lib'
for f in $K4/lib/*.so; do push "$f" /data/local/tmp/llama.cpp-k4/lib/$(basename "$f") || exit 3; done
sh_ "mkdir -p /data/local/tmp/llama.cpp-new/lib"; for f in $NW/lib/*.so; do push "$f" /data/local/tmp/llama.cpp-new/lib/$(basename "$f") || exit 3; done
push $RF/htpd_new/htpd /data/local/tmp/llama.cpp/bin/htpd_new || exit 3
push $RF/htpd_k4/htpd /data/local/tmp/llama.cpp/bin/htpd_k4 || exit 3
"$A" push "$(wslpath -w $RF/scripts/ab_board.sh)" /data/local/tmp/rfast/ab_board.sh >/dev/null
"$A" push "$(wslpath -w $RF/scripts/run_hexab.sh)" /data/local/tmp/rfast/run_hexab.sh >/dev/null
sh_ 'cd /data/local/tmp/rfast; (setsid nohup sh run_hexab.sh > /dev/null 2>&1 < /dev/null &)'; log "board A/B started"
sleep 120
until sh_ 'grep -qE "ab done|ABORT" /data/local/tmp/rfast/ab/ab.log' >/dev/null 2>&1; do sleep 60; done
mkdir -p $RF/raw/hexab; sh_ 'cd /data/local/tmp/rfast/ab && tar cf /data/local/tmp/rfast/hexab.tar .'
"$A" pull /data/local/tmp/rfast/hexab.tar "$(wslpath -w $RF/raw/hexab)" >/dev/null; (cd $RF/raw/hexab && tar xf hexab.tar && rm hexab.tar)
log "=== hexab done: $(grep -E 'config|stopped|ABORT' $RF/raw/hexab/ab.log | cut -c1-100 | tr '\n' '|')"
