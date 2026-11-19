#!/bin/bash
# Phase 1 APK (build_r3.sh pattern): gofmt/vet, parity + unit tests (go test ./... green), arm64 + host build, APK,
# copy -> proofs/2026-11-16_phase1/SmartCityEdge.${TAG:-phase1}.apk + md5. No board access.
# Waits (no build) while Windows available RAM < MIN_AVAIL_MB (2 GB; go build + APK need < 1 GB) or a model export / quantize runs. CPU only.
# usage (WSL): nice -n 15 bash build_phase1.sh
export PATH=$HOME/go-sdk/go/bin:$PATH GOMAXPROCS=2 GOFLAGS=-p=2
APP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app; D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1; mkdir -p $D
log(){ echo "$(date -u +%FT%TZ) $*" >> $D/build_wait.log; }
ok_to_run(){
  pgrep -f 'merge_any\.py|convert_hf_to_gguf|llama-quantize' > /dev/null && { why="export/quantize process running"; return 1; }
  av=$(timeout 30 /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command "(Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes" < /dev/null 2>/dev/null | tr -dc 0-9)
  [ "${av:-0}" -ge ${MIN_AVAIL_MB:-2048} ] || { why="Windows available ${av:-?} MB < ${MIN_AVAIL_MB:-2048}"; return 1; }
  return 0; }
waitok(){ last=""; n=0; while [ $n -lt 3 ]; do if ok_to_run; then n=$((n+1)); else n=0; [ "$why" != "$last" ] && log "wait: $why"; last=$why; fi; [ $n -lt 3 ] && sleep 30; done; }
waitok
log "start: Windows available $av MB"
cd $APP/backend
NEW="campus.go cards.go chat_site.go features_v3.go phase1.go reasoner_v4.go site.go campus_test.go chat_site_test.go features_v3_test.go reasoner_v4_test.go"
{ echo "gofmt -l (new files): $(gofmt -l $NEW)"
  go vet ./... && echo "go vet: ok"
  go test -count=1 -v -run 'CardRender|CardsMatch|AgentV3|SitePrompt|ReasonerPromptV4|SiteTools|SiteRelation|ChatHeaderR5|BuildSiteFromAPI|ParseValue|CampusBackfill|SiteGrouping|PromptParityV2|ChatR3OffIsDeploy32|ChatHeaderR3' . 2>&1 | grep -E '^(---|ok|FAIL)|_test.go:[0-9]+: [0-9]+ '
  go test -count=1 -skip 'TestChatRouterBlind2Fixes' ./... 2>&1 | grep -E '^(--- FAIL|ok|FAIL)'; } > $D/go_test.txt 2>&1
{ go test -count=1 -v -run 'TestChatRouterBlind2Fixes' . 2>&1 | grep -E '^(---|ok|FAIL)'
  echo "(informational, calendar-dependent: build_r3.sh note; run $(TZ=Asia/Kolkata date '+%F %a %H:%M') IST)"; } > $D/go_test_blind2.txt 2>&1
grep -q "^ok" $D/go_test.txt && ! grep -q "FAIL" $D/go_test.txt || { log "tests failed"; echo "=== phase1 done (tests failed)"; exit 1; }
waitok; log "build: Windows available $av MB"
{ bash $APP/build.sh && bash $APP/android/build_apk.sh; } > $D/build.log 2>&1 || { log "build failed"; echo "=== phase1 done (build failed)"; exit 1; }
cp $APP/android/out/SmartCityEdge.apk $D/SmartCityEdge.${TAG:-phase1}.apk; (cd $D && md5sum SmartCityEdge.${TAG:-phase1}.apk > SmartCityEdge.${TAG:-phase1}.apk.md5)
log "done: $(cat $D/SmartCityEdge.${TAG:-phase1}.apk.md5)"; echo "=== phase1 done ok $(cat $D/SmartCityEdge.${TAG:-phase1}.apk.md5)"
