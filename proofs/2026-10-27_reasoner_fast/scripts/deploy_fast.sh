#!/usr/bin/env bash
# Deploy / roll back the reasoner-fast build (run inside WSL). Safety as board.sh, plus: 30 s settle after the stop, no
# drop_caches/compact_memory, wait for boot to settle, never reboot.
#   deploy_fast.sh deploy <apk> [KEY=VAL | line:key=val ...]   install the APK, set htpd_profile env / lines, start
#   deploy_fast.sh rollback                     reinstall the 2026-10-27 reasoner APK (c42dac4f) + the saved profile
set -euo pipefail
ADB=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast
D=/data/local/tmp/smart_city_edge
PKG=com.iiith.smartcityedge
L=$P/logs/deploy.log
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$L"; }
sh_() { "$ADB" shell "$@" | tr -d '\r'; }
winp() { wslpath -w "$1"; }
settle() { while [ "$(sh_ 'getprop sys.boot_completed')" != 1 ] || [ "$(sh_ 'cut -d. -f1 /proc/uptime')" -lt 240 ]; do log "boot settling"; sleep 15; done; }
stop_all() {
  settle
  log "stop app, edge-agent, htpd; wait for exit + 30 s"
  out=$(sh_ 'am force-stop '$PKG'; pkill -x edge-agent; pkill -f "[b]in/htpd";
    for i in $(seq 1 90); do ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie)" || break; sleep 1; done; sleep 30;
    if ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)"; then echo STILL_RUNNING; else echo STOPPED; fi')
  echo "$out" | tee -a "$L"; echo "$out" | grep -q '^STOPPED' || { log "ABORT: NPU client still running"; exit 3; }
}
start_app() {
  log "start app"; n0=$(sh_ "grep -c 'htpd: ready in' $D/state/htpd.log" | tail -1)
  sh_ "am start -n $PKG/.MainActivity" | tee -a "$L"
  for i in $(seq 1 150); do sh_ "grep -c 'htpd: ready in' $D/state/htpd.log" | awk -v n0="$n0" '{exit !($1>n0)}' && { log "htpd ready"; break; }; sleep 2; done
  sh_ "ps -A -o NAME= | grep -E '^(htpd|edge)'; grep -E 'ready in|reasoner slot' $D/state/htpd.log | tail -2; md5sum $D/edge-agent; cat $D/htpd_profile" | tee -a "$L"
}
case "${1:-}" in
  deploy)
    APK=$2; shift 2
    stop_all
    [ -f "$P/rollback/htpd_profile.before_fast" ] || sh_ "cat $D/htpd_profile" > "$P/rollback/htpd_profile.before_fast"
    f=$P/logs/htpd_profile.fast; cp "$P/rollback/htpd_profile.before_fast" "$f"
    for kv in "$@"; do  # KEY=VAL into the env= line (replacing the same KEY); line:key=val replaces a profile line
      if [ "${kv#line:}" != "$kv" ]; then l=${kv#line:}; k=${l%%=*}; grep -v "^$k=" "$f" > "$f.t"; echo "$l" >> "$f.t"; mv "$f.t" "$f"; continue; fi
      k=${kv%%=*}
      sed -i -E "s/^env=(.*)$/env=\1 /; s/ $k=[^ ]*//g; s/^env=(.*[^ ]) *$/env=\1 $kv/" "$f"
    done
    "$ADB" push "$(winp "$f")" "$D/htpd_profile.part" >/dev/null; sh_ "mv $D/htpd_profile.part $D/htpd_profile"
    log "install $APK"; "$ADB" install -r -d "$(winp "$APK")" | tail -1 | tee -a "$L"
    start_app;;
  rollback)
    stop_all
    "$ADB" push "$(winp "$P/rollback/htpd_profile.before_fast")" "$D/htpd_profile.part" >/dev/null; sh_ "mv $D/htpd_profile.part $D/htpd_profile"
    "$ADB" install -r -d "$(winp "$P/rollback/SmartCityEdge.reasoner.c42dac4f.apk")" | tail -1 | tee -a "$L"
    start_app;;
  *) sed -n 2,6p "$0"; exit 2;;
esac
