#!/usr/bin/env bash
# Reasoner-on-board deploy / rollback for the QIDK (run inside WSL). Follows
# proofs/2026-10-26_reasoner_deploy/htpd_v8/BOARD_TEST.md and the safety rules:
#   - one NPU client: stop the app, edge-agent and every htpd, WAIT for exit, then 10 s;
#   - big files go up as .part, are checked (size + host md5 sidecar), then mv'd; nothing goes through /sdcard;
#   - never reboot.
#
#   board.sh prep                    build the backend + APK (CPU, -p 2), keep the rollback APK (cf0da165)
#   board.sh deploy <gguf> <md5>     stop, push htpd_v8r + GGUF, back up and edit htpd_profile, install the APK, start
#   board.sh status                  processes, temperature, memory, htpd.log tail
#   board.sh rollback                stop, restore the profile + the cf0da165 APK, start (htpd_v7 comes back)
set -euo pipefail
ADB=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
Q=/mnt/c/Users/hp/Desktop/qidk
APP=$Q/Code/smart-city-edge-agent/app
P=$Q/proofs/2026-10-27_reasoner_board
RB=$P/rollback
D=/data/local/tmp/smart_city_edge
BIN=/data/local/tmp/llama.cpp/bin
G=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf
HTPD_LOCAL=$Q/proofs/2026-10-26_reasoner_deploy/htpd_v8/htpd
PKG=com.iiith.smartcityedge
mkdir -p "$RB" "$P/logs"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$P/logs/board_sh.log"; }
sh_() { "$ADB" shell "$@" | tr -d '\r'; }
winp() { case "$1" in /mnt/*) wslpath -w "$1";; /*) wslpath -w "$1";; *) echo "$1";; esac; }

stop_all() {
  log "stop: app, edge-agent, every htpd; wait for exit"
  local out
  out=$(sh_ 'am force-stop '$PKG'; pkill -x edge-agent; pkill -f "[b]in/htpd";
      for i in $(seq 1 90); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 1; done;
      if ps -A -o NAME= | grep -E "^(htpd|genie|edge-agent)"; then echo STILL_RUNNING; else sleep 10; echo STOPPED; fi')
  echo "$out" | tee -a "$P/logs/board_sh.log"
  echo "$out" | grep -q '^STOPPED' || { log "ABORT: an NPU client is still running"; exit 3; }
  sh_ 'sync; (echo 3 > /proc/sys/vm/drop_caches; echo 1 > /proc/sys/vm/compact_memory) 2>/dev/null; grep -E "MemAvailable" /proc/meminfo' | tee -a "$P/logs/board_sh.log"
}

start_app() {
  log "start app"
  local n0
  n0=$(sh_ "grep -c 'htpd: ready in' $D/state/htpd.log 2>/dev/null || echo 0" | tail -1)
  sh_ "am start -n $PKG/.MainActivity" | tee -a "$P/logs/board_sh.log"
  "$ADB" forward tcp:8000 tcp:8000 >/dev/null
  for i in $(seq 1 120); do
    sh_ "curl -s -m 2 http://127.0.0.1:8000/api/status" | grep -q . && { log "backend up after ${i}x2 s"; break; }
    sleep 2
  done
  for i in $(seq 1 150); do  # htpd ready (model loaded): the agents' model, plus the reasoner slot line on v8
    if sh_ "grep -c 'htpd: ready in' $D/state/htpd.log" | awk -v n0="$n0" '{exit !($1>n0)}'; then log "htpd ready"; break; fi
    sleep 2
  done
  sh_ "pgrep -fl '[b]in/htpd|edge-agent'; tail -5 $D/state/htpd.log" | tee -a "$P/logs/board_sh.log"
}

push_checked() {  # local remote: .part + size + md5 (host sidecar for big files) + mv
  local src=$1 dst=$2 size md5 bsize
  size=$(stat -c %s "$src")
  md5=$(md5sum "$src" | cut -d' ' -f1)
  if [ "$(sh_ "stat -c %s $dst 2>/dev/null")" = "$size" ] && [ "$(sh_ "cat $dst.md5 2>/dev/null" | cut -d' ' -f1)" = "$md5" ]; then
    log "already there: $dst ($size B, md5 $md5)"; return 0
  fi
  log "push $src -> $dst.part ($size B)"
  "$ADB" push "$(winp "$src")" "$dst.part" | tail -1
  bsize=$(sh_ "stat -c %s $dst.part")
  [ "$bsize" = "$size" ] || { log "ABORT: size $bsize != $size"; sh_ "rm -f $dst.part"; exit 4; }
  if [ "$size" -lt 100000000 ]; then  # small: on-board md5 is fine; multi-GB: host md5 sidecar only (HANDBOOK)
    [ "$(sh_ "md5sum $dst.part" | cut -d' ' -f1)" = "$md5" ] || { log "ABORT: md5 mismatch"; exit 4; }
  fi
  echo "$md5  $(basename "$dst")" > "$P/logs/sidecar.md5"
  "$ADB" push "$(winp "$P/logs/sidecar.md5")" "$dst.md5" >/dev/null
  sh_ "mv $dst.part $dst"
  log "ok: $dst md5 $md5"
}

set_profile() {  # rewrite htpd_profile: keep other lines, set the reasoner keys
  local f=$P/logs/htpd_profile.new
  sh_ "cat $D/htpd_profile 2>/dev/null" > "$RB/htpd_profile.before" || true
  sh_ "[ -f $D/htpd_profile.bak_reasoner ] || cp $D/htpd_profile $D/htpd_profile.bak_reasoner 2>/dev/null; true"
  grep -vE '^(bin|reasoner|reasoner_engine|reasoner_model)=' "$RB/htpd_profile.before" > "$f" || true
  printf 'bin=%s/htpd_v8r\nreasoner=v3\nreasoner_engine=htpd\nreasoner_model=%s\n' "$BIN" "$G" >> "$f"
  "$ADB" push "$(winp "$f")" "$D/htpd_profile.part" >/dev/null
  sh_ "mv $D/htpd_profile.part $D/htpd_profile && cat $D/htpd_profile" | tee "$P/logs/htpd_profile.deployed"
}

case "${1:-}" in
  prep)
    [ -f "$RB/SmartCityEdge.cf0da165.apk" ] || cp "$APP/android/out/SmartCityEdge.apk" "$RB/SmartCityEdge.cf0da165.apk"
    [ -f "$RB/edge-agent.cf0da165" ] || cp "$APP/device/edge-agent" "$RB/edge-agent.cf0da165"
    md5sum "$RB/edge-agent.cf0da165" | grep -q '^cf0da165' || { echo "rollback binary is not cf0da165"; exit 5; }
    export GOMAXPROCS=2 GOFLAGS=-p=2
    bash "$APP/build.sh"
    bash "$APP/android/build_apk.sh"
    cp "$APP/android/out/SmartCityEdge.apk" "$P/SmartCityEdge.reasoner.apk"
    md5sum "$APP/device/edge-agent" "$P/SmartCityEdge.reasoner.apk" "$HTPD_LOCAL" | tee "$P/logs/build_md5.txt"
    # the deployed APK slot keeps the rollback build so nothing else picks up the reasoner APK by accident
    cp "$RB/SmartCityEdge.cf0da165.apk" "$APP/android/out/SmartCityEdge.apk"
    cp "$RB/edge-agent.cf0da165" "$APP/device/edge-agent"
    ;;
  deploy)
    GGUF=$2; GMD5=$3
    [ -f "$P/SmartCityEdge.reasoner.apk" ] || { echo "run prep first"; exit 2; }
    [ "$(md5sum "$GGUF" | cut -d' ' -f1)" = "$GMD5" ] || { echo "GGUF md5 != $GMD5"; exit 2; }
    "$ADB" get-state | grep -q device
    stop_all
    sh_ "df -h /data | tail -1" | tee -a "$P/logs/board_sh.log"
    push_checked "$HTPD_LOCAL" "$BIN/htpd_v8r"; sh_ "chmod 755 $BIN/htpd_v8r"
    push_checked "$GGUF" "$G"
    set_profile
    log "install reasoner APK (app stopped)"
    "$ADB" install -r -d "$(winp "$P/SmartCityEdge.reasoner.apk")" | tail -1
    sh_ 'sync; (echo 3 > /proc/sys/vm/drop_caches) 2>/dev/null; true'
    start_app
    sh_ "grep -E 'v8 reasoner slot|ready in' $D/state/htpd.log | tail -2"
    ;;
  status)
    sh_ "pgrep -fl '[b]in/htpd|edge-agent|genied'; cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1; grep MemAvailable /proc/meminfo; tail -8 $D/state/htpd.log"
    ;;
  rollback)
    log "ROLLBACK to cf0da165 + previous profile (htpd_v7)"
    stop_all
    if [ -s "$RB/htpd_profile.before" ]; then
      "$ADB" push "$(winp "$RB/htpd_profile.before")" "$D/htpd_profile.part" >/dev/null
      sh_ "mv $D/htpd_profile.part $D/htpd_profile"
    else
      sh_ "[ -f $D/htpd_profile.bak_reasoner ] && cp $D/htpd_profile.bak_reasoner $D/htpd_profile; true"
    fi
    "$ADB" install -r -d "$(winp "$RB/SmartCityEdge.cf0da165.apk")" | tail -1
    start_app
    sh_ "md5sum $D/edge-agent; cat $D/htpd_profile" | tee -a "$P/logs/board_sh.log"
    ;;
  *) sed -n 2,13p "$0"; exit 2;;
esac
