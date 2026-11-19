#!/system/bin/sh
# Board side of the OTA update (ROADMAP 2026-11-09 §4 "OTA app + models"). POSIX sh (Android mksh / toybox).
# NOT run yet: written 2026-11-09 while the board was away; tested on the laptop with stubs (tools/ota/test_ota.sh).
#
#   sh ota_board.sh apply <stage_dir>
#
# <stage_dir>/manifest.txt, one line per file:  <md5> <name in stage_dir> <destination path | APK>
# Steps: verify every staged md5 -> stop the app and wait until no edge-agent/htpd process is left (one NPU client;
# nothing changes if they do not exit) -> APK: keep the installed APK as rollback.apk, pm install -r; files: copy to
# <dest>.part, verify md5, mv <dest> <dest>.prev, mv <dest>.part <dest> (atomic rename on the same filesystem) ->
# start the app -> self-test (GET /api/prod/selftest == 200; an older app without it: /api/status == 200) within
# SELFTEST_S -> on failure restore every .prev and rollback.apk, start the app, self-test again.
# The last line is OTA_RESULT=ok | rolled_back | rollback_failed | aborted:<why>. Exit 0 only for ok.
# Env: PKG, ACTIVITY, URL (http://127.0.0.1:8000), SELFTEST_S (240), STOP_WAIT_S (120), KEEP_PREV (1: keep *.prev).

PKG=${PKG:-com.iiith.smartcityedge}
ACTIVITY=${ACTIVITY:-.MainActivity}
URL=${URL:-http://127.0.0.1:8000}
SELFTEST_S=${SELFTEST_S:-240}
STOP_WAIT_S=${STOP_WAIT_S:-120}
KEEP_PREV=${KEEP_PREV:-1}

log() { echo "ota: $*"; }
result() { echo "OTA_RESULT=$1"; [ "$1" = ok ] && exit 0; exit 1; }
md5of() { md5sum "$1" 2>/dev/null | cut -c1-32; }

npu_procs() { ps -A -o NAME= 2>/dev/null | grep -E '^(edge-agent|htpd|genie|llama)'; }

stop_app() {
  am force-stop "$PKG" >/dev/null 2>&1
  pkill -x edge-agent >/dev/null 2>&1
  for p in $(pidof htpd htpd_v9f htpd_v9e htpd_v9 htpd_v8x5 2>/dev/null); do kill -TERM "$p" 2>/dev/null; done
  i=0
  while [ $i -lt "$STOP_WAIT_S" ] && [ -n "$(npu_procs)" ]; do sleep 1; i=$((i+1)); done
  [ -z "$(npu_procs)" ]
}

start_app() { am start -n "$PKG/$ACTIVITY" >/dev/null 2>&1; }

selftest() {
  i=0
  while [ $i -lt "$SELFTEST_S" ]; do
    c=$(curl -s -o /dev/null -w '%{http_code}' "$URL/api/prod/selftest" 2>/dev/null)
    [ "$c" = 200 ] && return 0
    if [ "$c" = 404 ]; then
      c=$(curl -s -o /dev/null -w '%{http_code}' "$URL/api/status" 2>/dev/null)
      [ "$c" = 200 ] && return 0
    fi
    sleep 2; i=$((i+2))
  done
  return 1
}

rollback() {
  log "rolling back"
  stop_app || log "app did not stop cleanly before rollback"
  # journal lines: F <dest> (had .prev) | N <dest> (new file, no .prev) | A (APK replaced)
  sed -n '1!G;h;$p' "$J" > "$J.rev"   # reverse order
  ok=1
  while read -r kind dest; do
    case "$kind" in
      F) mv -f "$dest.prev" "$dest" || ok=0 ;;
      N) rm -f "$dest" ;;
      A) pm install -r -d "$S/rollback.apk" >/dev/null 2>&1 || ok=0 ;;
    esac
  done < "$J.rev"
  start_app
  if [ $ok = 1 ] && selftest; then result rolled_back; fi
  result rollback_failed
}

[ "$1" = apply ] && [ -d "$2" ] || { echo "usage: sh ota_board.sh apply <stage_dir>"; result aborted:usage; }
S=$2; M=$S/manifest.txt; J=$S/journal
[ -s "$M" ] || result aborted:no_manifest
: > "$J"

# 1. every staged file present and intact before anything is touched
while read -r sum name dest; do
  [ -z "$sum" ] && continue
  [ "$(md5of "$S/$name")" = "$sum" ] || result "aborted:md5_$name"
done < "$M"

# 2. stop the app (and with it htpd: one NPU client at a time)
stop_app || { start_app; result aborted:app_did_not_stop; }

# 3. swap
fail=0
while read -r sum name dest; do
  [ -z "$sum" ] && continue
  if [ "$dest" = APK ]; then
    cur=$(pm path "$PKG" 2>/dev/null | sed 's/^package://' | head -1)
    [ -n "$cur" ] && cp -f "$cur" "$S/rollback.apk" || { log "no installed APK to keep for rollback"; fail=1; break; }
    echo A >> "$J"
    pm install -r "$S/$name" >/dev/null 2>&1 || { log "pm install failed"; fail=1; break; }
    log "APK installed ($sum)"
  else
    mkdir -p "$(dirname "$dest")"
    cp -f "$S/$name" "$dest.part" && [ "$(md5of "$dest.part")" = "$sum" ] || { log "copy/md5 failed for $dest"; rm -f "$dest.part"; fail=1; break; }
    if [ -e "$dest" ]; then
      mv -f "$dest" "$dest.prev" && echo "F $dest" >> "$J" || { fail=1; break; }
    else
      echo "N $dest" >> "$J"
    fi
    mv -f "$dest.part" "$dest" || { fail=1; break; }
    log "swapped $dest ($sum)"
  fi
done < "$M"
[ $fail = 1 ] && rollback

# 4. start and self-test
start_app
if selftest; then
  if [ "$KEEP_PREV" != 1 ]; then
    grep '^F ' "$J" | while read -r kind dest; do rm -f "$dest.prev"; done
  fi
  result ok
fi
log "self-test failed within ${SELFTEST_S} s"
rollback
