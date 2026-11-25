#!/bin/bash
# Push whisper.cpp tiny.en voice files to the board. Run ONLY with the app stopped (one NPU/adb client at a time). Not run by the agent.
set -e
SRC="${SRC:-/c/Users/hp/Desktop/qidk/Code/models_stage/voice}"
DST=/data/local/tmp/smart_city_edge/voice
adb shell "mkdir -p $DST"
for f in whisper-cli ggml-tiny.en.bin; do
  want=$(md5sum "$SRC/$f" | cut -d' ' -f1)
  adb push "$SRC/$f" "$DST/$f.part"
  got=$(adb shell "md5sum $DST/$f.part" | cut -d' ' -f1)
  [ "$want" = "$got" ] || { echo "md5 mismatch $f"; exit 1; }
  adb shell "mv $DST/$f.part $DST/$f"
done
adb shell "chmod 755 $DST/whisper-cli"
echo "voice pushed: $(adb shell "ls -l $DST")"
