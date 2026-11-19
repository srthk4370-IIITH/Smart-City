#!/bin/bash
# Offline replay of the four deploy25 board sweeps through the current router (one incident snapshot per set).
export PATH=$HOME/go-sdk/go/bin:$PATH
cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/backend
R=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-03_fixes/replay
for s in "questions.json:sweep10_s1_d25.jsonl:inc_sweep10_s1_d25_start.json" "questions_heldout.json:sweep11_heldout_d25.jsonl:inc_sweep11_heldout_d25_start.json" \
         "questions_blind.json:sweep12_blind_d25.jsonl:inc_sweep12_blind_d25_start.json" "questions_blind2.json:sweep9_blind2.jsonl:inc_sweep9_blind2_start.json"; do
  IFS=: read q w i <<< "$s"
  SCE_CHAT_REPLAY=$R SCE_CHAT_INC=$i SCE_CHAT_SETS=$q:$w go test -count=1 -run 'TestChatReplay$' . 2>&1 | tail -2
done
