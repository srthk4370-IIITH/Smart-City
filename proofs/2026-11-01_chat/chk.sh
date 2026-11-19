#!/bin/bash
cat ~/detached/deploy23r3.log; p=$(cat ~/detached/deploy23r3.pid); kill -0 $p 2>/dev/null && echo ALIVE || echo DEAD; ps aux | grep -E "deploy23|sweep|chaos|fastcheck" | grep -v grep | head
ls /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_night/ | grep -E 'PAUSE|BUSY'
