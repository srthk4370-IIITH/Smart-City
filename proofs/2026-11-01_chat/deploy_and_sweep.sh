#!/bin/bash
# deploy23, then (only if deployed) the same 40-question sweep -> sweep2.jsonl
bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/deploy23.sh
S=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/deploy23/STATUS.md; cat $S
grep -q "DEPLOYED:" $S && bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-01_chat/run_sweep.sh 2
echo CHAIN_DONE
