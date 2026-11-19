#!/usr/bin/env bash
# kill_eq.sh: stop MY CPU test (process group led by the pid in eq.pid: go.sh starts it with setsid) and nothing else
p=$(cat /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/speed/eq.pid 2>/dev/null)
[ -n "$p" ] && ps -o args= -p "$p" | grep -qE "eq_|resume_test|estimate|pretok|chain_eq" && { kill -- -"$p" 2>/dev/null || kill "$p"; echo "killed group $p"; }
