#!/bin/bash
# offline router replay (deploy25 regression check): bash replay25.sh <inc snapshot> <q:sweep,...>
export PATH=$HOME/go-sdk/go/bin:/usr/bin:/bin
cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/backend
SCE_CHAT_REPLAY=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-01_chat SCE_CHAT_INC=$1 SCE_CHAT_SETS=$2 go test -count=1 -run TestChatReplay . 2>&1 | tail -20
