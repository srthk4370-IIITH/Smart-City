#!/bin/bash
# deploy24 build: edge-agent (Go) then the APK (repo build path), sequential.
set -e
APP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app; D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-01_chat
bash $APP/build.sh
bash $APP/android/build_apk.sh
cp $APP/android/out/SmartCityEdge.apk $D/SmartCityEdge.deploy24.apk
md5sum $D/SmartCityEdge.deploy24.apk
