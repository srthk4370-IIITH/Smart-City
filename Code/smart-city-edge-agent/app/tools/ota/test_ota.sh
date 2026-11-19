#!/usr/bin/env bash
# Laptop test of ota_push.sh + ota_board.sh with a fake adb shim: no board, no adb, no APK install.
# "adb push" copies into a temp dir, "adb shell" runs the command locally with stub am/pm/curl/ps/pkill/pidof.
# A fake app whose installed APK contains BAD fails the self-test (HTTP 500) -> the board script must roll back.
#   bash tools/ota/test_ota.sh      (prints PASS/FAIL per scenario; exit 0 = all pass)
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
STUB=$T/stub; mkdir -p "$STUB" "$T/board/models" "$T/stage"
export FAKE=$T/board
fails=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fails=$((fails+1)); fi; }

cat > "$STUB/adb" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  push) if [[ "$2" == *corrupt* ]]; then { cat "$2"; echo x; } > "$3"; else cp "$2" "$3"; fi ;;
  shell) shift; sh -c "$*" ;;
  *) echo "fake adb: $*" >&2; exit 1 ;;
esac
EOF
cat > "$STUB/pm" <<'EOF'
#!/bin/sh
case "$1" in
  path) echo "package:$FAKE/installed.apk" ;;
  install) for a; do f=$a; done; cp "$f" "$FAKE/installed.apk.new" && mv "$FAKE/installed.apk.new" "$FAKE/installed.apk"; echo Success ;;
esac
EOF
cat > "$STUB/am" <<'EOF'
#!/bin/sh
echo "am $*" >> "$FAKE/am.log"
EOF
cat > "$STUB/curl" <<'EOF'
#!/bin/sh
if grep -q BAD "$FAKE/installed.apk" "$FAKE/models/m.gguf" 2>/dev/null; then echo 500; else echo 200; fi
EOF
cat > "$STUB/ps" <<'EOF'
#!/bin/sh
[ -e "$FAKE/stuck" ] && echo htpd
exit 0
EOF
printf '#!/bin/sh\nexit 0\n' > "$STUB/pkill"; printf '#!/bin/sh\nexit 0\n' > "$STUB/pidof"
chmod +x "$STUB"/*
export PATH="$STUB:$PATH" ADB="$STUB/adb" STAGE="$T/stage" SELFTEST_S=4 STOP_WAIT_S=1

echo "GOOD v1" > "$FAKE/installed.apk"; echo "model v1" > "$FAKE/models/m.gguf"
bundle() { # name apk-content model-content
  d=$T/$1; mkdir -p "$d"; echo "$2" > "$d/app.apk"; echo "$3" > "$d/m.gguf"
  printf 'app.apk APK\nm.gguf %s\n' "$FAKE/models/m.gguf" > "$d/bundle.txt"; echo "$d"
}

# 1. a good update: both swapped, previous model kept as .prev
out=$(bash "$HERE/ota_push.sh" "$(bundle good 'GOOD v2' 'model v2')" 2>&1); rc=$?
check "good update ok" '[ $rc = 0 ] && echo "$out" | grep -q "OTA_RESULT=ok"'
check "good update swapped" '[ "$(cat $FAKE/installed.apk)" = "GOOD v2" ] && [ "$(cat $FAKE/models/m.gguf)" = "model v2" ] && [ "$(cat $FAKE/models/m.gguf.prev)" = "model v1" ]'
check "app restarted" 'grep -q "am start" $FAKE/am.log'

# 2. a broken update (self-test fails): automatic rollback of the APK and the model
out=$(bash "$HERE/ota_push.sh" "$(bundle bad 'BAD v3' 'model v3')" 2>&1); rc=$?
check "bad update rolled back" '[ $rc != 0 ] && echo "$out" | grep -q "OTA_RESULT=rolled_back"'
check "bad update restored" '[ "$(cat $FAKE/installed.apk)" = "GOOD v2" ] && [ "$(cat $FAKE/models/m.gguf)" = "model v2" ]'

# 3. a push corrupted in transit: md5 mismatch, nothing on the board changes
d=$(bundle corrupt 'GOOD v4' 'model v4'); mv "$d/m.gguf" "$d/m_corrupt.gguf"; printf 'm_corrupt.gguf %s\n' "$FAKE/models/m.gguf" > "$d/bundle.txt"
out=$(bash "$HERE/ota_push.sh" "$d" 2>&1); rc=$?
check "corrupt push refused" '[ $rc = 4 ] && echo "$out" | grep -q "md5 mismatch"'
check "corrupt push changed nothing" '[ "$(cat $FAKE/models/m.gguf)" = "model v2" ]'

# 4. the app (htpd) does not stop: abort before touching anything (one NPU client rule)
touch "$FAKE/stuck"
out=$(bash "$HERE/ota_push.sh" "$(bundle stuck 'GOOD v5' 'model v5')" 2>&1); rc=$?
rm -f "$FAKE/stuck"
check "stuck app aborts" '[ $rc != 0 ] && echo "$out" | grep -q "OTA_RESULT=aborted:app_did_not_stop"'
check "stuck app changed nothing" '[ "$(cat $FAKE/installed.apk)" = "GOOD v2" ] && [ "$(cat $FAKE/models/m.gguf)" = "model v2" ]'

# 5. a staged file damaged on the board after the push: the board re-checks md5 before stopping the app
d=$(bundle late 'GOOD v6' 'model v6')
sum=$(md5sum "$d/m.gguf" | cut -c1-32)
mkdir -p "$T/stage2"; cp "$d/m.gguf" "$T/stage2/m.gguf"; echo junk >> "$T/stage2/m.gguf"
echo "$sum m.gguf $FAKE/models/m.gguf" > "$T/stage2/manifest.txt"
out=$(sh "$HERE/ota_board.sh" apply "$T/stage2" 2>&1); rc=$?
check "board md5 re-check" '[ $rc != 0 ] && echo "$out" | grep -q "OTA_RESULT=aborted:md5_m.gguf" && [ "$(cat $FAKE/models/m.gguf)" = "model v2" ]'

[ $fails = 0 ] && echo "ALL PASS" || echo "$fails FAILED"
exit $fails
