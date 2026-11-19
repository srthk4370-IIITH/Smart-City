#!/bin/bash
# split build (same path as proofs/2026-11-03_fixes/build_r2fix.sh): edge-agent (Go) then the APK, copied here with md5.
set -e
APP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app; D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-04_split/apk
bash $APP/build.sh
bash $APP/android/build_apk.sh
cp $APP/android/out/SmartCityEdge.apk $D/SmartCityEdge.split.apk
md5sum $D/SmartCityEdge.split.apk | tee $D/SmartCityEdge.split.apk.md5
