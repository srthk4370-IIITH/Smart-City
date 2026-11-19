#!/bin/bash
# Offline replay of the blind2 board sweep through the current router; writes replay/replay_sweep9_blind2.jsonl
export PATH=$HOME/go-sdk/go/bin:$PATH
cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/backend
SCE_CHAT_REPLAY=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-03_fixes/replay SCE_CHAT_INC=inc_sweep9_blind2_start.json \
SCE_CHAT_SETS=questions_blind2.json:sweep9_blind2.jsonl go test -count=1 -run 'TestChatReplay$' . 2>&1 | tail -5
