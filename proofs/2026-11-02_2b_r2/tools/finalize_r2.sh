#!/usr/bin/env bash
# final r2 files: chat train (+ r1 replay rows), chat test, tools_r2.json, dev mix (loss only), MD5SUMS
set -euo pipefail
Q=/mnt/c/Users/hp/Desktop/qidk; D=$Q/proofs/2026-11-02_2b_r2/data; F=$D/final; V3=$Q/proofs/2026-10-29_rsn_v3
cat $D/chat/chat_train.jsonl $V3/kaggle/build/r1/replay/replay_train.jsonl > $F/chat_train.jsonl
cp $D/chat/chat_test.jsonl $F/chat_test_r2.jsonl
cp $D/chat/tools_r2.json $F/tools_r2.json
cp $V3/kaggle/build/r1/mix_laptop/dev_mix3.jsonl $F/dev_mix3.jsonl
cp $V3/kaggle/build/r2x/data/incidents_dev60.jsonl $F/incidents_dev60.jsonl
(cd $F && rm -f go_gate_*.jsonl.part && md5sum *.jsonl *.json > MD5SUMS)
wc -l $F/*.jsonl
