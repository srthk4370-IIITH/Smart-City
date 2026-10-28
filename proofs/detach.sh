#!/usr/bin/env bash
# Start a job fully detached inside WSL (owner order 2026-10-28: jobs must survive Claude sessions/limits).
# usage: bash detach.sh <name> <script> [args...]   -> log ~/detached/<name>.log, pid ~/detached/<name>.pid
mkdir -p ~/detached; n=$1; shift
setsid nohup bash "$@" > ~/detached/$n.log 2>&1 < /dev/null &
echo $! > ~/detached/$n.pid; echo "started $n pid $(cat ~/detached/$n.pid)"
