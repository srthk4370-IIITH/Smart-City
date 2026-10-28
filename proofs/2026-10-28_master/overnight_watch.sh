#!/usr/bin/env bash
# Overnight watchdog (standalone: bash proofs/detach.sh watch <this>), 2026-10-29 until 12:00 IST.
# Every 10 min writes OVERNIGHT_STATUS.md: job states, final/split/rag/retry results, board temp + processes, lock holder.
# One safety action only: an htpd on the board that has used >= 90% CPU for 10 min while its log did not grow
# (the rsn_v2 q11 stall, 2026-10-28) gets SIGTERM (never SIGKILL, never reboot), logged here. Nothing else is touched.
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
S=$M/OVERNIGHT_STATUS.md; L=$M/overnight_watch.log
END=$(date -u -d "2026-10-29 06:30" +%s)
log(){ echo "$(date -u +%FT%TZ) $*" >> $L; }
sh_(){ timeout 60 $A shell "$@" 2>/dev/null | tr -d '\r'; }
alive(){ kill -0 $(cat ~/detached/$1.pid 2>/dev/null) 2>/dev/null && echo alive || echo stopped; }
prev_cpu=""; prev_lines=""; stuck=0
log "=== watch start"
while [ $(date +%s) -lt $END ]; do
  online=$($A get-state 2>/dev/null | grep -c device)
  if [ "$online" = 1 ]; then
    procs=$(sh_ 'ps -A -o PID=,NAME= | grep -E " (htpd|edge-agent|llama)"' | tr '\n' ' ')
    temp=$(sh_ 'cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1'); temp=$(( ${temp:-0} / 1000 ))
    avail=$(sh_ "awk '/MemAvailable/ {print int(\$2/1024)}' /proc/meminfo")
    hp=$(echo "$procs" | grep -oE "[0-9]+ htpd[^ ]*" | head -1 | cut -d' ' -f1)
    if [ -n "$hp" ]; then
      cpu=$(sh_ "cut -d' ' -f14,15 /proc/$hp/stat" | awk '{print $1+$2}')
      lines=$(sh_ "cat /data/local/tmp/smart_city_edge/state/htpd.log /data/local/tmp/rfast/ab/htpd_*.log 2>/dev/null | wc -l")
      if [ -n "$prev_cpu" ] && [ "$prev_hp" = "$hp" ] && [ -n "$cpu" ]; then
        rate=$(( (cpu - prev_cpu) / 6 ))   # clock ticks (100/s) over 600 s -> percent
        if [ "$rate" -ge 90 ] && [ "$lines" = "$prev_lines" ]; then
          stuck=$((stuck + 1)); log "htpd $hp: ${rate}% CPU for 10 min, no log growth (temp ${temp} C) -> SIGTERM"
          sh_ "kill -TERM $hp"
        fi
      fi
      prev_cpu=$cpu; prev_hp=$hp; prev_lines=$lines
    else prev_cpu=""; fi
  fi
  {
    echo "# Overnight status ($(date -u +%FT%TZ), IST $(TZ=Asia/Kolkata date +%H:%M))"
    echo
    echo "| job | state |"; echo "|---|---|"
    for n in final split_post rag_deploy rag_seed website_final; do [ -e ~/detached/$n.pid ] && echo "| $n | $(alive $n) |"; done
    ls ~/detached/*.pid 2>/dev/null | xargs -n1 basename | sed 's/.pid$//' | grep -vE "^(final|split_post|rag_deploy|rag_seed|website_final)$" | while read n; do [ "$(alive $n)" = alive ] && echo "| $n | alive |"; done
    echo
    echo "**Board:** $([ "$online" = 1 ] && echo "online, ${temp} C, MemAvailable ${avail} MB, procs: ${procs:-none}" || echo OFFLINE)"
    echo "**BOARD_LOCK:** $(cat $M/BOARD_LOCK 2>/dev/null || echo free)"
    echo "**Stalled-htpd SIGTERMs tonight:** $stuck"
    echo
    echo "## final.sh"; echo '```'; grep -E "F[0-9]|ROLLBACK|result" $M/final.log | tail -6 | cut -c1-200; echo '```'
    echo "result: $(cat $M/final/result 2>/dev/null || echo pending)"
    echo; echo "## split_post"; echo '```'; tail -3 $M/split_post.log 2>/dev/null | cut -c1-200; echo '```'
    echo; echo "## rag_deploy"; echo '```'; tail -3 ~/detached/rag_deploy.log 2>/dev/null | cut -c1-200; echo '```'
    [ -s $M/RAG_STATUS.md ] && echo "RAG_STATUS.md written"
    echo; echo "## rag_seed"; echo '```'; tail -2 ~/detached/rag_seed.log 2>/dev/null | cut -c1-200; echo '```'
    echo; echo "## rsn_v2 retry"; [ -s $M/RSN_V2_RETRY.md ] && head -15 $M/RSN_V2_RETRY.md || echo "pending"
  } > $S.part && mv $S.part $S
  sleep 600
done
log "=== watch end"
