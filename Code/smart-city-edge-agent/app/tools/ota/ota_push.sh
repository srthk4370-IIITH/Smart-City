#!/usr/bin/env bash
# Laptop side of the OTA update (ROADMAP 2026-11-09 §4). Pushes a bundle over adb, verifies md5 on the board, then runs
# ota_board.sh there (stop app -> atomic swap -> start -> self-test -> automatic rollback). NOT run yet (board away
# until Nov 15); tested with a fake adb shim by tools/ota/test_ota.sh.
#
#   ota_push.sh <bundle_dir>
#
# <bundle_dir>/bundle.txt, one line per file:  <file in bundle_dir> <destination path on the board | APK>
#   e.g.  SmartCityEdge.apk APK
#         rsn_v3_4b_r3_q4_0.gguf /data/local/tmp/gpu/rsn_v3_4b_r3_q4_0.gguf
#         htpd_profile /data/local/tmp/smart_city_edge/htpd_profile
# Env: ADB (adb), STAGE (/data/local/tmp/ota_stage), and PKG/URL/SELFTEST_S/KEEP_PREV passed through to the board.
# Big files: pushed as <name>.part and renamed only after the board's md5 matches (memory rule: .part + md5 + mv).
set -euo pipefail
B=${1:?usage: ota_push.sh <bundle_dir>}
ADB=${ADB:-adb}
STAGE=${STAGE:-/data/local/tmp/ota_stage}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
[ -s "$B/bundle.txt" ] || { echo "no $B/bundle.txt"; exit 2; }
sh_() { "$ADB" shell "$@" | tr -d '\r'; }
# adb.exe from WSL (as the deploy scripts use it) needs Windows paths for local files
lp() { case "$ADB" in *.exe) wslpath -w "$1" ;; *) echo "$1" ;; esac; }

man=$(mktemp)
trap 'rm -f "$man"' EXIT
while read -r name dest; do
  [ -z "${name:-}" ] && continue
  [ -s "$B/$name" ] || { echo "missing $B/$name"; exit 2; }
  echo "$(md5sum "$B/$name" | cut -c1-32) $name $dest" >> "$man"
done < "$B/bundle.txt"

sh_ "mkdir -p $STAGE && rm -f $STAGE/*.part $STAGE/journal*"
# free space on the stage filesystem (KB) vs the bundle
need=$(du -sk "$B" | cut -f1)
free=$(sh_ "df -k $STAGE | tail -1" | awk '{print $4}')
if [ -n "$free" ] && [ "$free" -lt $((need + 1048576)) ] 2>/dev/null; then
  echo "board has ${free} KB free on $STAGE, bundle needs ${need} KB + 1 GB margin"; exit 3
fi
"$ADB" push "$(lp "$HERE/ota_board.sh")" "$STAGE/ota_board.sh" > /dev/null
while read -r sum name dest; do
  if [ "$(sh_ "md5sum $STAGE/$name 2>/dev/null" | cut -c1-32)" = "$sum" ]; then
    echo "already staged: $name"; continue
  fi
  "$ADB" push "$(lp "$B/$name")" "$STAGE/$name.part" > /dev/null
  got=$(sh_ "md5sum $STAGE/$name.part" | cut -c1-32)
  [ "$got" = "$sum" ] || { echo "md5 mismatch for $name after push ($got != $sum)"; sh_ "rm -f $STAGE/$name.part"; exit 4; }
  sh_ "mv -f $STAGE/$name.part $STAGE/$name"
  echo "staged: $name ($sum)"
done < "$man"
"$ADB" push "$(lp "$man")" "$STAGE/manifest.txt" > /dev/null

out=$(sh_ "PKG=${PKG:-com.iiith.smartcityedge} URL=${URL:-http://127.0.0.1:8000} SELFTEST_S=${SELFTEST_S:-240} KEEP_PREV=${KEEP_PREV:-1} sh $STAGE/ota_board.sh apply $STAGE") || true
echo "$out"
res=$(echo "$out" | sed -n 's/^OTA_RESULT=//p' | tail -1)
echo "result: ${res:-unknown}"
[ "$res" = ok ]
