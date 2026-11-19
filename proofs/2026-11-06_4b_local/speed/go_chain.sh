#!/usr/bin/env bash
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/speed
setsid nohup bash chain_eq.sh > chain_eq.log 2>&1 < /dev/null &
sleep 2; cat eq.pid
