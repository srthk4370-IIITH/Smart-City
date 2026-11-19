#!/usr/bin/env bash
p=$(cat /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/speed/eq.pid 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo y
