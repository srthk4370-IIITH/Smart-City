#!/usr/bin/env bash
# rsn_v2 retry with htpd_v8x3 (2026-10-29). Standalone: bash proofs/detach.sh v2retry <this>. Log rsn_v2_retry.log.
#  V0 wait for RAG (RAG_STATUS.md) and BOARD_LOCK; do not START board work after 09:30 IST (04:00Z); nothing after 10:15 IST (04:45Z)
#  V1 known-good snapshot (profile, installed APK, edge-agent md5)
#  V2 push htpd_v8x3 (.part+md5+mv) + v8x3_board.sh; board runs par (v1 q10-q14), v2 (q10-q19), cons (q11-13 x3)
#  V3 gates: parity = v8x3+v1 parse 5/5 and sev/label = v8x2 sp3 on >= 4/5 (1 known HTP-noise flip allowed);
#     v2 = parse 10/10 (stop json) and sev/label vs gold >= v1 on the same 10; consistency = same severity on >= 8/9
#  V4 deploy: parity+v2 -> bin=htpd_v8x3 + reasoner_model=rsn_v2; parity only -> bin=htpd_v8x3 + rsn_v1; else nothing.
#     App check chaos2 3 + fastcheck; any failure -> restore the snapshot profile (+APK) and re-check.
#  V5 RSN_V2_RETRY.md + HANDBOOK 2.58 from the numbers.
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; V=$M/v8x3; RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; K=$M/BOARD_LOCK; W=/data/local/tmp/smart_city_edge; R=/data/local/tmp/rfast
G=/data/local/tmp/gpu; BIN=/data/local/tmp/llama.cpp/bin
START_BY=$(date -u -d "2026-10-29 04:00" +%s); STOP_AT=$(date -u -d "2026-10-29 04:45" +%s)
exec >> $M/rsn_v2_retry.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
late(){ [ $(date +%s) -gt ${1:-$STOP_AT} ]; }
TP=
lock(){ until $A get-state 2>/dev/null | grep -q device; do late && return 1; sleep 60; done
  while [ -e $K ] && [ "$(cat $K 2>/dev/null)" != v2retry ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do late && return 1; sleep 60; done
  echo v2retry > $K; ( while [ "$(cat $K 2>/dev/null)" = v2retry ]; do touch $K; sleep 300; done ) & TP=$!; return 0; }
unlock(){ [ -n "$TP" ] && kill $TP 2>/dev/null; TP=; [ "$(cat $K 2>/dev/null)" = v2retry ] && rm -f $K; }
trap unlock EXIT
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x3 htpd_v8x2 htpd_v8r htpd_v8s htpd_v8t htpd_v8p htpd_v8p2 htpd_v7 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; [ "$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)" -gt "${n0:-0}" ] && return 0; done; return 1; }
setp(){ f=$1; k=$2; v=$3; grep -v "^$k=" $f > $f.t; [ -n "$v" ] && echo "$k=$v" >> $f.t; mv $f.t $f; }
status(){ echo "$2" > $V/$1; }

log "=== rsn_v2 retry start"
until [ -e $M/RAG_STATUS.md ] || late $START_BY; do sleep 120; done
log "V0 RAG status: $([ -e $M/RAG_STATUS.md ] && head -3 $M/RAG_STATUS.md | tr '\n' ' ' || echo 'not written (start-by reached)')"
late $START_BY && { log "V0 past 09:30 IST: no board work"; status result "skipped: past the 09:30 IST start limit"; }
if ! late $START_BY && lock; then
  # V1 snapshot
  mkdir -p $V/known_good; sh_ "cat $W/htpd_profile" > $V/known_good/htpd_profile
  p=$(sh_ 'pm path com.iiith.smartcityedge' | head -1 | sed 's/^package://'); $A pull "$p" "$(w $V/known_good/app.apk)" > /dev/null
  sh_ "md5sum $W/edge-agent" > $V/known_good/edge-agent.md5
  log "V1 known-good: $(cut -c1-8 $V/known_good/edge-agent.md5) $(grep -E '^(bin|model|reasoner_model|reasoner_split)=' $V/known_good/htpd_profile | tr '\n' ' ')"
  # V2 push + board runs
  m=$(md5sum $V/android/htpd | cut -c1-32)
  $A push "$(w $V/android/htpd)" $BIN/htpd_v8x3.part > /dev/null
  [ "$(sh_ "md5sum $BIN/htpd_v8x3.part" | cut -c1-32)" = "$m" ] && sh_ "mv -f $BIN/htpd_v8x3.part $BIN/htpd_v8x3 && chmod 755 $BIN/htpd_v8x3 && echo $m > $BIN/htpd_v8x3.md5" || { log "V2 htpd_v8x3 md5 mismatch: abort"; status result "abort: htpd_v8x3 push"; exit 3; }
  [ "$(sh_ "stat -c %s $G/rsn_v2_q4_0.gguf")" = 2611783520 ] || { log "V2 rsn_v2 GGUF missing on the board: abort"; status result "abort: rsn_v2 not on board"; exit 3; }
  sed -i 's/\r$//' $RF/scripts/ab_board.sh $V/v8x3_board.sh
  $A push "$(w $RF/scripts/ab_board.sh)" $R/ab_board.sh > /dev/null; $A push "$(w $V/v8x3_board.sh)" $R/v8x3_board.sh > /dev/null
  sh_ "rm -f $R/v8x3_DONE; cd $R && (setsid nohup sh v8x3_board.sh > /dev/null 2>&1 < /dev/null &)"; log "V2 board runs started (htpd_v8x3 $m)"
  sleep 120
  until [ "$(sh_ "cat $R/v8x3_DONE 2>/dev/null")" = done ]; do sleep 60; done
  for t in par v2 cons sp6; do rm -rf $V/raw_$t; $A pull $R/v8x3_$t "$(w $V)" > /dev/null; mv $V/v8x3_$t $V/raw_$t; done
  log "V2 board runs done; picks: $(grep -h 'reason picks' $V/raw_*/htpd_*.log | sort | uniq -c | tr '\n' ' ')"
  # V3 gates
  G3=$(python3 $V/gates.py $V $RF)
  echo "$G3" > $V/gates.json; log "V3 gates: $G3"
  PAR=$(python3 -c "import json;print(int(json.load(open('$V/gates.json'))['parity']))" 2>/dev/null || echo 0)
  V2P=$(python3 -c "import json;print(int(json.load(open('$V/gates.json'))['v2_pass']))" 2>/dev/null || echo 0)
  # V4 deploy
  if [ "$PAR" = 1 ] && ! late; then
    RM=$G/qwen35_reasoner_q4_0.gguf; what="htpd_v8x3 + rsn_v1"; [ "$V2P" = 1 ] && { RM=$G/rsn_v2_q4_0.gguf; what="htpd_v8x3 + rsn_v2"; }
    cp $V/known_good/htpd_profile $V/htpd_profile.new; setp $V/htpd_profile.new bin $BIN/htpd_v8x3; setp $V/htpd_profile.new reasoner_model $RM
    r=$(stop_app); log "V4 deploy $what: stop $r"
    if [ "$r" = STOPPED ]; then
      $A push "$(w $V/htpd_profile.new)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
      ok=0; start_app && ok=1
      if [ $ok = 1 ]; then t0=$(date +%s)
        (cd $RF/scripts && python3 -I chaos2.py chaos 3 150); crc=$?
        n=$(python3 $V/chaos_count.py $t0)
        fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
        set -- $n; log "V4 app check: chaos rc=$crc (n done valid: $n); fastcheck rc=$frc $fc"
        if [ $crc = 0 ] && [ "${2:-0}" -ge 3 ] && [ "${3:-0}" -ge 3 ] && [ $frc = 0 ]; then status result "DEPLOYED $what: app check PASS (chaos $n, fastcheck $fc)"
        else ok=0; fi
      fi
      if [ $ok = 0 ]; then log "V4 FAIL -> rollback"; r=$(stop_app)
        $A push "$(w $V/known_good/htpd_profile)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
        $A install -r -d "$(w $V/known_good/app.apk)" | tail -1; start_app
        (cd $RF/scripts && python3 -I chaos2.py chaos 1 60); status result "ROLLED BACK after $what failed the app check"; fi
    else status result "not deployed: app would not stop"; start_app; fi
  elif [ "$PAR" = 1 ]; then status result "not deployed: past 10:15 IST"
  else status result "not deployed: v8x3 parity with rsn_v1 failed"; fi
  log "V4 result: $(cat $V/result)"
  sh_ "md5sum $W/edge-agent; grep -E '^(bin|model|reasoner_model|reasoner_split)=' $W/htpd_profile" > $V/board_state.txt
  unlock
fi
# V5 report
python3 $V/report.py $V $M
log "=== rsn_v2 retry done: $(cat $V/result 2>/dev/null)"
