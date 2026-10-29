#!/usr/bin/env bash
# 2026-10-29 morning (standalone: bash proofs/detach.sh improve <this>). Owner: "improve everything", "reduce latency", GPU+NPU.
#  I0 laptop: build edge-agent with the reasoner contract repairs (normal+needs_more_data -> label unknown; title location
#     must come from the input) + APK.  I1 board: GPU-alone reasoner bench (upstream llama.cpp OpenCL; app stopped; safe
#     class HANDBOOK 2.37; numbers only).  I2 board: install the APK, keep the seed library, fastcheck + chaos 2; any
#     failure -> reinstall the snapshot APK.  No board change starts after 11:00 IST. Never reboots. One NPU/GPU client.
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; I=$M/improve; K=$M/BOARD_LOCK; mkdir -p $I/known_good
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; APP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; G=/data/local/tmp/rfast/gpu
exec >> $I/improve.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
CUT=$(date -d "2026-10-29 05:30 UTC" +%s); late(){ [ $(date +%s) -ge $CUT ]; }
st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x3 htpd_v8x2 htpd_v8r htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; [ "$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)" -gt "${n0:-0}" ] && return 0; done; return 1; }
SEEDMD5=$(md5sum $M/rag_seed/rag_seed.json | cut -c1-32)
seed_ok(){ [ "$(sh_ "md5sum $W/data/rag_seed.json 2>/dev/null" | cut -c1-32)" = "$SEEDMD5" ]; }
echo "# Morning improvements ($(TZ=Asia/Kolkata date +%H:%M) IST start)" > $I/STATUS.md
log "=== improve start"
# I0 build
cp $APP/device/edge-agent $I/slot.edge-agent; cp $APP/android/out/SmartCityEdge.apk $I/slot.apk
if bash $APP/build.sh > $I/build.log 2>&1 && bash $APP/android/build_apk.sh > $I/apk_build.log 2>&1; then
  cp $APP/device/edge-agent $I/edge-agent.new; cp $APP/android/out/SmartCityEdge.apk $I/SmartCityEdge.new.apk; st "- I0 build OK: apk $(md5sum $I/SmartCityEdge.new.apk | cut -c1-8), edge-agent $(md5sum $I/edge-agent.new | cut -c1-8)"
else st "- I0 build FAILED (see build.log / apk_build.log)"; BUILD_FAIL=1; fi
until $A get-state 2>/dev/null | grep -q device; do sleep 60; done
while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do sleep 60; done
echo improve > $K; trap 'rm -f $K' EXIT
# I1 GPU-alone bench (the bench stops the app itself and restarts it at the end)
if ! late; then
  sed -i 's/\r$//' $M/gpu_bench.sh; sh_ "mkdir -p $G; rm -f $G/DONE"; $A push "$(w $M/gpu_bench.sh)" $G/gpu_bench.sh > /dev/null
  $A shell "cd $G && (setsid nohup sh gpu_bench.sh > /dev/null 2>&1 < /dev/null &)"; log "I1 gpu bench started"; sleep 90
  t0=$(date +%s); until sh_ "cat $G/DONE 2>/dev/null" | grep -q . || [ $(( $(date +%s) - t0 )) -gt 3000 ]; do sleep 60; done
  rm -rf $M/gpu_bench_out; mkdir -p $M/gpu_bench_out; $A pull $G/. "$(w $M/gpu_bench_out)" > /dev/null
  st "- I1 GPU bench: $(cat $M/gpu_bench_out/DONE 2>/dev/null || echo timeout); results in gpu_bench_out/out.md; min MemAvailable $(grep -oE 'avail=[0-9]+' $M/gpu_bench_out/telemetry.log | cut -d= -f2 | sort -n | head -1) MB"
  sleep 60; seed_ok || log "seed missing after bench?"
fi
# I2 deploy-if-pass
if [ -z "$BUILD_FAIL" ] && ! late; then
  p=$(sh_ 'pm path com.iiith.smartcityedge' | head -1 | sed 's/^package://'); $A pull "$p" "$(w $I/known_good/app.apk)" > /dev/null
  sh_ "md5sum $W/edge-agent" > $I/known_good/edge-agent.md5
  r=$(stop_app); log "I2 stop: $r"
  if [ "$r" = STOPPED ] && [ -s $I/known_good/app.apk ]; then
    $A install -r -d "$(w $I/SmartCityEdge.new.apk)" | tail -1
    seed_ok || { $A push "$(w $M/rag_seed/rag_seed.json)" $W/data/rag_seed.json.part > /dev/null; sh_ "mv -f $W/data/rag_seed.json.part $W/data/rag_seed.json"; log "seed re-pushed"; }
    ok=1; start_app || ok=0; sleep 20
    if [ $ok = 1 ]; then
      (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); rc=$?
      fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
      log "I2 chaos rc=$rc fastcheck rc=$frc $fc"; [ $rc = 0 ] && [ $frc = 0 ] || ok=0
    fi
    if [ $ok = 1 ]; then st "- I2 DEPLOYED: edge-agent $(sh_ "md5sum $W/edge-agent" | cut -c1-8), seed ok=$(seed_ok && echo yes || echo no); chaos 2 rc=$rc; fastcheck $fc"
    else
      stop_app > /dev/null; $A install -r -d "$(w $I/known_good/app.apk)" | tail -1; seed_ok || { $A push "$(w $M/rag_seed/rag_seed.json)" $W/data/rag_seed.json > /dev/null; }
      start_app; st "- I2 FAILED -> rolled back to $(cat $I/known_good/edge-agent.md5 | cut -c1-8) (chaos rc=$rc fastcheck rc=$frc)"
    fi
  else st "- I2 NOT DEPLOYED: app not stopped ($r) or snapshot missing"; start_app; fi
else st "- I2 skipped (build failed or after 11:00 IST)"; fi
cp $I/slot.edge-agent $APP/device/edge-agent; cp $I/slot.apk $APP/android/out/SmartCityEdge.apk
st "- board now: $(sh_ "md5sum $W/edge-agent; grep -E '^(bin|reasoner_model|reasoner_split)=' $W/htpd_profile" | tr '\n' ' ')"
log "=== improve done"
