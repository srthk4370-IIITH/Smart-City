#!/bin/bash
for f in ~/detached/*.pid; do p=$(cat $f); kill -0 $p 2>/dev/null && echo RUNNING $f; done
ls /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_night/ | grep -E 'PAUSE|BUSY'; echo checked
