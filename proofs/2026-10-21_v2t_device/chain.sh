#!/usr/bin/env bash
# Wait for (a) the phase-1 GGUF STATUS=done and (b) the recheck2 device test to finish, then run the device eval.
R=/c/Users/hp/Desktop/qidk/proofs/2026-10-21_v2_app/recheck2_console.txt
for i in $(seq 1 1080); do   # up to 9 h
  st=$(wsl.exe -d Ubuntu -- bash -c "cat ~/smartcity_runs/agents_v2_topup2/post/STATUS 2>/dev/null" | tr -d '\r')
  case "$st" in failed*) echo "$(date +%T) GGUF failed: $st"; exit 1;; esac
  if [[ "$st" == done* ]] && grep -q "hold:heat_buildup" "$R" 2>/dev/null; then
    echo "$(date +%T) starting device eval ($st)"; bash run_v2t.sh; exit $?
  fi
  sleep 30
done
echo "timed out"
