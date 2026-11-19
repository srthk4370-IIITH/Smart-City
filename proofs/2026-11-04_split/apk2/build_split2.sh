#!/bin/bash
# split2 = split + GPU chat timeout 60 s (was 2 min) + GPU keep-warm ping every 30 s (was 2 s). go vet + full tests, then APK.
export PATH=$HOME/go-sdk/go/bin:$PATH
APP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app; D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-04_split/apk2
cd $APP/backend
{ gofmt -l . ; go vet ./... && echo "go vet: ok"; go test -count=1 . 2>&1 | grep -E '^(--- FAIL|ok|FAIL)'; } > $D/go_test.txt 2>&1
grep -q "^ok" $D/go_test.txt || { echo "TESTS FAILED" >> $D/go_test.txt; echo "=== split2 done (tests failed)"; exit 1; }
{ bash $APP/build.sh && bash $APP/android/build_apk.sh; } > $D/build.log 2>&1 || { echo "=== split2 done (build failed)"; exit 1; }
cp $APP/android/out/SmartCityEdge.apk $D/SmartCityEdge.split2.apk; md5sum $D/SmartCityEdge.split2.apk | tee $D/SmartCityEdge.split2.apk.md5
echo "=== split2 done ok"
