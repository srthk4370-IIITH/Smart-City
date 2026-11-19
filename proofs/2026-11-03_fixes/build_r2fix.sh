#!/bin/bash
# r2fix build (same path as proofs/2026-11-01_chat/build25.sh): edge-agent (Go) then the APK, copied here with md5.
set -e
APP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app; D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-03_fixes
bash $APP/build.sh
bash $APP/android/build_apk.sh
cp $APP/android/out/SmartCityEdge.apk $D/SmartCityEdge.r2fix.apk
md5sum $D/SmartCityEdge.r2fix.apk | tee $D/SmartCityEdge.r2fix.apk.md5
