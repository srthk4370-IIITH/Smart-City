#!/usr/bin/env bash
# Deploy a staged agents' model GGUF (WSL). usage: deploy_model.sh <staged.gguf> <md5>   |   deploy_model.sh rollback
# App stopped (verified, else abort), .part + md5 + mv, profile backup htpd_profile.bak_chain, clean start. Never reboots.
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge
L=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/chain.log; log(){ echo "$(date +%T) deploy: $*" >> $L; }
stop(){ $A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -TERM -f "[b]in/htpd"
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL; else echo STOPPED; fi' | tr -d '\r'; }
start(){ $A shell 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 40); do sleep 5; $A shell "tail -3 $W/state/htpd.log" | grep -q "ready in" && break; done
  $A shell 'for p in $(pidof htpd_v8x2 htpd_v8r); do tr "\0" " " < /proc/$p/cmdline | cut -c1-140; echo; done' | tr -d '\r' >> $L; }
# board lock: an agent's board experiment holds proofs/2026-10-28_master/BOARD_LOCK (stale after 3 h)
K=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/BOARD_LOCK
while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do log "BOARD_LOCK held: wait"; sleep 120; done
if [ "$1" = rollback ]; then
  B=${2:-htpd_profile.bak_chain}; log "rollback to $B"; [ "$(stop)" = STOPPED ] || { log "ABORT stop"; exit 3; }
  $A shell "[ -f $W/$B ] && cp $W/$B $W/htpd_profile"; start; log "rollback done"; exit 0
fi
SRC=$1; MD5=$2; G=/data/local/tmp/gpu/$(basename $SRC)
[ "$(md5sum $SRC | cut -c1-32)" = "$MD5" ] || { log "local md5 mismatch"; exit 2; }
r=$(stop); log "stop: $r"; [ "$r" = STOPPED ] || { log "ABORT: NPU client still running"; exit 3; }
$A push "$(wslpath -w $SRC)" $G.part >> $L 2>&1 || { log "push failed"; start; exit 4; }
R=$($A shell "md5sum $G.part" | cut -c1-32); [ "$R" = "$MD5" ] || { log "board md5 mismatch $R"; $A shell "rm -f $G.part"; start; exit 4; }
$A shell "mv -f $G.part $G && echo $MD5 > $G.md5 && cp $W/htpd_profile $W/htpd_profile.bak_chain && sed -i 's|^model=.*|model=$G|' $W/htpd_profile && grep model= $W/htpd_profile" | tr -d '\r' >> $L
start; log "deployed $G"
