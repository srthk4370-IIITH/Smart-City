#!/bin/bash
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn
nice -n 15 python3 build_rsn.py --out /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn/data/final > logs/build.log 2>&1
echo "exit $?" >> logs/build.log
