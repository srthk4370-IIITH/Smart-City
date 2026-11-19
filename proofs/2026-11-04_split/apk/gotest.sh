#!/bin/bash
# go vet + full go test + the split tests verbose (WSL Go SDK) -> go_test.txt
export PATH=$HOME/go-sdk/go/bin:$PATH
cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/backend
{ go vet ./... && echo "go vet: ok"
  go test -count=1 . 2>&1 | grep -E '^(--- FAIL|ok|FAIL|    chat_fixes)'
  go test -count=1 -v -run 'ChatGPU|ChatURL|ReportsStay|ReasonerModelLabel|HtpdReason|ChatQueue' . 2>&1 | grep -E '^(---|ok|FAIL)'
} > /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-04_split/apk/go_test.txt 2>&1
