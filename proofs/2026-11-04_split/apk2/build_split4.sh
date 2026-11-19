#!/bin/bash
# split4 = split3 + the GPU keep-warm also sends the hour's full prefix after the header (checkpoint just before the user turn).
export PATH=$HOME/go-sdk/go/bin:$PATH
APP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app; D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-04_split/apk4; mkdir -p $D
cd $APP/backend
{ gofmt -l chat.go chat_gpu.go chat_gpu_test.go; go vet ./... && echo "go vet: ok"; go test -count=1 -v -run 'ChatGPU|ChatURL|ReportsStay|ChatQueue|Warm' . 2>&1 | grep -E '^(---|ok|FAIL)'; go test -count=1 . 2>&1 | grep -E '^(--- FAIL|ok|FAIL)'; } > $D/go_test.txt 2>&1
grep -q "^ok" $D/go_test.txt && ! grep -q "FAIL" $D/go_test.txt || { echo "=== split4 done (tests failed)"; exit 1; }
{ bash $APP/build.sh && bash $APP/android/build_apk.sh; } > $D/build.log 2>&1 || { echo "=== split4 done (build failed)"; exit 1; }
cp $APP/android/out/SmartCityEdge.apk $D/SmartCityEdge.split4.apk; md5sum $D/SmartCityEdge.split4.apk | tee $D/SmartCityEdge.split4.apk.md5
echo "=== split4 done ok"
