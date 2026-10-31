#!/usr/bin/env bash
# waits for deploy20 to finish, then runs the overnight soak
S=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/deploy20/STATUS.md
until grep -qE "^- (DEPLOYED|FAILED|NOT DEPLOYED|ABORT)" $S; do sleep 30; done
grep -q "board now" $S || sleep 120
sleep 60
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_night && exec python3 -I soak.py 1200
