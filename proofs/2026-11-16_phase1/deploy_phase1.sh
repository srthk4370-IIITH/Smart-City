#!/bin/bash
# Phase 1 deploy to the QIDK (DEPLOY_R3.md stages, auto-rollback). NOT RUN by the builder; the owner runs it.
#   Stage 0 preflight -> 1 known_good snapshot -> A APK alone (profile unchanged) -> B models + htpd v9h (app stopped,
#   .part + md5 + mv) -> C profile keys + fastcheck -> D campus input on -> T live checks (<= 45 min list: README.md) ; any failure = rollback.
# usage (WSL):  LAPTOP_IP=10.x.y.z bash deploy_phase1.sh --go [--stage A|B|C|D|T|rollback-profile|rollback-full]
# Needs: proofs/2026-11-16_phase1/SmartCityEdge.phase1.apk(.md5); the reasoner GGUF staged in Code/models_stage (+.md5);
#        htpd v9h in proofs/2026-11-12_htpd_v9h/htpd (+htpd.md5). One NPU client at a time: no other laptop job on adb.
set -u
[ "${1:-}" = "--go" ] || { echo "refusing to run without --go (see README.md)"; exit 2; }
STAGE=${3:-all}
Q=/mnt/c/Users/hp/Desktop/qidk
P=$Q/proofs/2026-11-16_phase1; I=$P/deploy; mkdir -p $I/known_good
A=$Q/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; S=/data/local/tmp/chatgpu; BIN=/data/local/tmp/llama.cpp/bin
APK=$P/SmartCityEdge.phase1.apk
# reasoner: r3_edit_C1 Q4_0 (PLACEHOLDER name: the staged C1 export; confirm before running), rollback = r3-2800 / known_good
M=${REASONER_GGUF:-rsn_v3_4b_r3c1_q4_0.gguf}; G=$Q/Code/models_stage/$M
H9=$Q/proofs/2026-11-12_htpd_v9h/htpd
LIP=${LAPTOP_IP:-}
sh_(){ "$A" shell "$@" | tr -d '\r'; }
st(){ echo "$(TZ=Asia/Kolkata date +%H:%M:%S) $*" | tee -a $I/STATUS.md; }
tele(){ sh_ "echo avail=\$(awk '/MemAvailable/ {print int(\$2/1024)}' /proc/meminfo)MB t=\$(cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1 | cut -c1-2)C"; }
stop_app(){ sh_ "sh $S/chat_gpu.sh stop" > /dev/null 2>&1
  sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9h htpd_v9f htpd_v9e htpd_v9d htpd_v9c htpd_v9b htpd_v9 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL $(ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)") after $i s; else echo STOPPED; fi'; }
start_app(){ l0=$(sh_ "wc -l < $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; l=$(sh_ "wc -l < $W/state/htpd.log" | tail -1)
    if [ "${l:-0}" -lt "${l0:-0}" ]; then c=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)
    else c=$(sh_ "tail -n +$(( ${l0:-0} + 1 )) $W/state/htpd.log | grep -c 'htpd: ready in'" | tail -1); fi
    [ "${c:-0}" -ge 1 ] && return 0; done; return 1; }
api(){ curl -s -m 30 "http://127.0.0.1:18000$1"; }
push_md5(){ # local remote_dir name: .part + md5 + mv (app stopped)
  local L=$1 R=$2/$3 m; m=$(md5sum "$L" | cut -c1-32)
  [ "$(sh_ "md5sum $R 2>/dev/null" | cut -c1-32)" = "$m" ] && { st "  $3 already on the board (md5 ok)"; return 0; }
  "$A" push "$(wslpath -w "$L")" $R.part > /dev/null || return 1
  [ "$(sh_ "md5sum $R.part" | cut -c1-32)" = "$m" ] && sh_ "mv -f $R.part $R" && [ "$(sh_ "md5sum $R" | cut -c1-32)" = "$m" ]; }
rollback_profile(){ st "ROLLBACK (profile): known_good/htpd_profile"; stop_app
  "$A" push "$(wslpath -w $I/known_good/htpd_profile)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
  start_app && st "  rolled back (profile), app up" || st "  app did not come up after the profile rollback: run rollback-full"; }
rollback_full(){ st "ROLLBACK (full): known_good APK + profile"; stop_app
  "$A" install -r -d "$(wslpath -w $I/known_good/app.apk)" > /dev/null
  "$A" push "$(wslpath -w $I/known_good/htpd_profile)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
  start_app && st "  rolled back (full), app up" || st "  app did not come up: manual check needed"; }
fast(){ # fastcheck + chaos-lite (deploy32 scripts); rc 0 = pass
  local F=$Q/proofs/2026-10-27_reasoner_fast/scripts
  python3 -I $F/fastcheck.py > $I/fastcheck_$1.txt 2>&1 || return 1
  python3 -I $F/chaos2.py chaos 2 150 > $I/chaos_$1.txt 2>&1 || return 1; return 0; }

case $STAGE in rollback-profile) rollback_profile; exit;; rollback-full) rollback_full; exit;; esac
echo "# Phase 1 deploy $(TZ=Asia/Kolkata date '+%F %H:%M') IST" >> $I/STATUS.md

# ---------------- Stage 0: preflight
if [ $STAGE = all ] || [ $STAGE = A ]; then
  (cd $P && md5sum -c SmartCityEdge.phase1.apk.md5) || { st "ABORT: APK md5"; exit 1; }
  [ -s $G ] && (cd $(dirname $G) && md5sum -c $M.md5) || { st "ABORT: reasoner GGUF $M missing / md5"; exit 1; }
  [ -n "$LIP" ] || { st "ABORT: set LAPTOP_IP (MQTT broker, heartbeat, alert, fog on the laptop)"; exit 1; }
  "$A" devices | tr -d '' | grep -q 'device$' || { st "ABORT: no board on adb"; exit 1; }
  pgrep -f 'chaos2.py|fastcheck.py|bench_|sweep' > /dev/null && { st "ABORT: another adb job runs (one NPU client at a time)"; exit 1; }
  st "preflight: $(tele) $(sh_ 'df -h /data | tail -1')"
  "$A" forward tcp:18000 tcp:8000 > /dev/null
  # ---------------- Stage 1: known_good
  if [ ! -s $I/known_good/app.apk ]; then
    "$A" pull "$(sh_ "pm path com.iiith.smartcityedge" | sed "s/^package://")" "$(wslpath -w $I/known_good/app.apk)" > /dev/null
    "$A" pull $W/htpd_profile "$(wslpath -w $I/known_good/htpd_profile)" > /dev/null
  fi
  md5sum $I/known_good/app.apk > $I/known_good/app.apk.md5; st "known_good: $(cat $I/known_good/app.apk.md5)"
  # ---------------- Stage A: APK alone, profile unchanged
  st "Stage A: $(stop_app)"
  "$A" install -r -d "$(wslpath -w $APK)" > $I/install.txt 2>&1 || { st "install failed"; rollback_full; exit 1; }
  start_app || { st "Stage A: htpd not ready"; rollback_full; exit 1; }
  fast A || { st "Stage A: fastcheck/chaos failed"; rollback_full; exit 1; }
  api /api/campus/status > $I/A_campus.json   # campus off without the key: {"campus_enabled":false,...}
  st "Stage A ok (Phase 1 APK, old profile = old behaviour)"
fi

# ---------------- Stage B: models + htpd v9h (app stopped)
if [ $STAGE = all ] || [ $STAGE = B ]; then
  st "Stage B: $(stop_app)"
  push_md5 $G /data/local/tmp/gpu $M || { st "push $M failed"; rollback_full; exit 1; }
  [ "$(md5sum $H9 | cut -c1-32)" = "$(cut -c1-32 $H9.md5)" ] && push_md5 $H9 $BIN htpd_v9h && sh_ "chmod 755 $BIN/htpd_v9h" || { st "push htpd_v9h failed"; rollback_full; exit 1; }
  # agents: B50 GGUF stays as deployed (agents key unset = B50); agt_v3 goes in later by profile switch after its re-gate
  st "Stage B ok"
fi

# ---------------- Stage C: Phase 1 profile
if [ $STAGE = all ] || [ $STAGE = C ]; then
  sh_ "sh $S/chat_gpu.sh stop" > /dev/null 2>&1   # retire the 2B split (split_off.sh does the same + removes its keys below)
  KEYS='reasoner_model|chat_think|chat_prompt|chat_url|chat_device|reason_ctx|reasoner_prompt|agents|bin|input|campus_url|campus_poll_s|campus_backfill_h|campus_fill_max_min|site_group|daily_summary|daily_summary_hour|health_stale_min|mqtt_url|mqtt_topics|time_sync|heartbeat_url|heartbeat_s|board_id|site_id|alert_webhook|alert_webhook_format|fog_upload|fog_url|fog_sync_s|warm_idle_min|ai_early_k|ai_early_shapes'
  ENV0=$(sh_ "grep '^env=' $W/htpd_profile" | sed 's/^env=//')
  ENV1="$ENV0"; for e in HTPD_REASON_POOL=12544 HTPD_REASON_CHAIN=1 HTPD_REASON_DISK_KEEP=6; do echo " $ENV1 " | grep -q " ${e%%=*}=" || ENV1="$ENV1 $e"; done
  NEWK="reasoner_model=/data/local/tmp/gpu/$M
chat_think=adaptive
chat_prompt=r3
reason_ctx=8192
reasoner_prompt=r3
agents=b50
bin=$BIN/htpd_v9h
env=$(echo $ENV1)
site_group=1
daily_summary=1
daily_summary_hour=8
health_stale_min=30
mqtt_url=tcp://$LIP:1883
mqtt_topics=sce/#
time_sync=1
heartbeat_url=http://$LIP:8787/heartbeat
heartbeat_s=60
board_id=qidk-1
site_id=iiith
alert_webhook=${ALERT_URL:-http://$LIP:8094/alert}
alert_webhook_format=json
fog_upload=1
fog_url=http://$LIP:8092
fog_sync_s=60
warm_idle_min=30"
  st "Stage C: $(stop_app)"
  printf '%s\n' "$NEWK" > $I/profile_keys.txt
  "$A" push "$(wslpath -w $I/profile_keys.txt)" $W/profile_keys.txt > /dev/null
  sh_ "grep -vE '^($KEYS|env)=' $W/htpd_profile > $W/htpd_profile.part && cat $W/profile_keys.txt >> $W/htpd_profile.part && mv -f $W/htpd_profile.part $W/htpd_profile && rm -f $W/profile_keys.txt"
  "$A" pull $W/htpd_profile "$(wslpath -w $I/htpd_profile.phase1)" > /dev/null
  start_app || { st "Stage C: htpd not ready"; rollback_profile; exit 1; }
  sh_ "cat $W/state/htpd_args" > $I/htpd_args.txt
  grep -q "htpd_v9h" $I/htpd_args.txt && grep -q -- "--reason-ctx 8192" $I/htpd_args.txt || { st "Stage C: htpd args wrong"; rollback_profile; exit 1; }
  sh_ "grep -E 'buffer mapping failed|split-spec reasoner context|v9h:' $W/state/htpd.log | tail -5" > $I/htpd_ctx.txt
  grep -q 'buffer mapping failed' $I/htpd_ctx.txt && { st "Stage C: reasoner context failed to map"; rollback_profile; exit 1; }
  # fastcheck drives the held /api/ingest slider path, which only the simulated engine reads: run it before the
  # campus input switches the engine to the wall clock (models, v9h, reason_ctx, production keys are all live here)
  fast C || { st "Stage C: fastcheck/chaos failed"; rollback_profile; exit 1; }
  st "Stage C ok (models + v9h + production keys; campus input next)"
fi

# ---------------- Stage D: campus input on (sliders gone; scenario injections still ride on the real readings)
if [ $STAGE = all ] || [ $STAGE = D ]; then
  st "Stage D: $(stop_app)"
  printf 'input=campus\ncampus_url=${CAMPUS_URL:-http://10.2.203.214:9999}\ncampus_poll_s=5\ncampus_backfill_h=12\ncampus_fill_max_min=20\n' > $I/profile_campus.txt
  "$A" push "$(wslpath -w $I/profile_campus.txt)" $W/profile_campus.txt > /dev/null
  sh_ "grep -vE '^(input|campus_url|campus_poll_s|campus_backfill_h|campus_fill_max_min)=' $W/htpd_profile > $W/htpd_profile.part && cat $W/profile_campus.txt >> $W/htpd_profile.part && mv -f $W/htpd_profile.part $W/htpd_profile && rm -f $W/profile_campus.txt"
  "$A" pull $W/htpd_profile "$(wslpath -w $I/htpd_profile.phase1)" > /dev/null
  start_app || { st "Stage D: htpd not ready"; rollback_profile; exit 1; }
  st "Stage D ok"
fi

# ---------------- T: fast checks (the rest of the <= 45 min list is manual, README.md)
if [ $STAGE = all ] || [ $STAGE = T ]; then
  "$A" forward tcp:18000 tcp:8000 > /dev/null
  for i in $(seq 1 24); do api /api/campus/status > $I/T_campus.json; grep -q '"backfill":"done' $I/T_campus.json && break; sleep 10; done
  grep -q '"online":true' $I/T_campus.json || st "T: campus API not reachable (board on Wi-Fi? expect the No-network page)"
  api /api/health/data > $I/T_health.json; api /api/site > $I/T_site.json; api /api/site/status > $I/T_site_status.json
  api /api/prod/status > $I/T_prod.json
  python3 -I $Q/proofs/2026-10-27_reasoner_fast/scripts/chaos2.py chaos 2 150 > $I/chaos_T.txt 2>&1 || { st "T: chaos (live injections) failed"; rollback_profile; exit 1; }
  st "T ok: $(python3 -c "import json;d=json.load(open('$I/T_health.json'));print('health',d.get('counts'))" 2>/dev/null) $(tele)"
fi
st "done (stage $STAGE)"
