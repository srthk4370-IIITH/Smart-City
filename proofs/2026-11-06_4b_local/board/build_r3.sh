#!/bin/bash
# r3 APK = split7 (deploy32, live) + rsn_v3 r3 chat (21 tools, fog fallback, r3 prompt) behind chat_prompt=r3,
# + htpd_profile reason_ctx (htpd --reason-ctx; unset = 4096 as today). No new profile keys = deploy32 behaviour
# (TestChatR3OffIsDeploy32). Waits (no build) while Windows available RAM < 3 GB or an export/gate process runs.
# usage (WSL): nice -n 15 bash build_r3.sh
export PATH=$HOME/go-sdk/go/bin:$PATH GOMAXPROCS=2 GOFLAGS=-p=2
APP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app; D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/board; mkdir -p $D
log(){ echo "$(date -u +%FT%TZ) $*" >> $D/build_wait.log; }
ok_to_run(){
  pgrep -f 'merge_any\.py|convert_hf_to_gguf|llama-quantize|llama-server' > /dev/null && { why="export/gate process running"; return 1; }
  av=$(timeout 30 /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command "(Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes" < /dev/null 2>/dev/null | tr -dc 0-9)
  [ "${av:-0}" -ge 3072 ] || { why="Windows available ${av:-?} MB < 3072"; return 1; }
  return 0; }
# ok only after 3 clean checks 30 s apart (a gate restarts llama-server between steps)
waitok(){ last=""; n=0; while [ $n -lt 3 ]; do if ok_to_run; then n=$((n+1)); else n=0; [ "$why" != "$last" ] && log "wait: $why"; last=$why; fi; [ $n -lt 3 ] && sleep 30; done; }
waitok
log "start: Windows available $av MB"
cd $APP/backend
{ echo "gofmt -l: $(gofmt -l chat.go chat_fog.go htpdclient.go chat_r3_default_test.go fog_serve_test.go htpd_reason_ctx_test.go chat_fog_parity_test.go)"
  go vet ./... && echo "go vet: ok"
  go test -count=1 -v -run 'ChatR3OffIsDeploy32|HtpdReasonCtx|ChatFog|ChatHeaderR3|ChatHeader15|ChatGPU|ChatURL|ReportsStay|ChatQueue|Warm' . 2>&1 | grep -E '^(---|ok|FAIL)'
  go test -count=1 -skip 'TestChatRouterBlind2Fixes' ./... 2>&1 | grep -E '^(--- FAIL|ok|FAIL)'; } > $D/go_test.txt 2>&1
# TestChatRouterBlind2Fixes uses the real clock and expects INC-0505 (30 h back) inside "this week", so it fails from
# Monday 00:00 to Tuesday 06:00 (pre-existing calendar flake in chat_fixes_1103_test.go, unrelated to r3; it failed on
# Monday 2026-11-09 09:00 IST). Run separately and recorded, not gating.
{ go test -count=1 -v -run 'TestChatRouterBlind2Fixes' . 2>&1 | grep -E '^(---|ok|FAIL|    )'
  echo "(informational, calendar-dependent; run $(TZ=Asia/Kolkata date '+%F %a %H:%M') IST)"; } > $D/go_test_blind2.txt 2>&1
grep -q "^ok" $D/go_test.txt && ! grep -q "FAIL" $D/go_test.txt || { log "tests failed"; echo "=== r3 done (tests failed)"; exit 1; }
waitok; log "build: Windows available $av MB"
{ bash $APP/build.sh && bash $APP/android/build_apk.sh; } > $D/build.log 2>&1 || { log "build failed"; echo "=== r3 done (build failed)"; exit 1; }
cp $APP/android/out/SmartCityEdge.apk $D/SmartCityEdge.r3.apk; (cd $D && md5sum SmartCityEdge.r3.apk > SmartCityEdge.r3.apk.md5)
log "done: $(cat $D/SmartCityEdge.r3.apk.md5)"; echo "=== r3 done ok $(cat $D/SmartCityEdge.r3.apk.md5)"
