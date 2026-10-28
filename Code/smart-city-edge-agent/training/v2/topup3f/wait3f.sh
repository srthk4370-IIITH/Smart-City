#!/usr/bin/env bash
# wait3f.sh PATTERN MIN : touch HEARTBEAT every 60 s until PATTERN appears in master.log / pipe_lora.log (new lines), the
# master8 queue is gone, or MIN minutes pass; prints one status line.
R=~/smartcity_runs/agents_v2_topup3f; P=$1; M=${2:-28}
n1=$(cat $R/master.log $R/pipe_lora.log 2>/dev/null | wc -l)
for i in $(seq 1 $M); do touch $R/HEARTBEAT
  new=$(cat $R/master.log $R/pipe_lora.log 2>/dev/null | tail -n +$((n1+1)))
  echo "$new" | grep -qE "$P" && { echo "HIT: $(echo "$new" | grep -E "$P" | tail -2 | tr '\n' ' ')"; exit 0; }
  pgrep -f "[m]aster8_3f.sh|[m]aster_v21.sh" >/dev/null || { echo "queue gone: $(tail -2 $R/master.log | tr '\n' ' ')"; exit 0; }
  sleep 60; done
echo "timeout; last: $(tail -1 $R/pipe_lora.log 2>/dev/null) | $(tail -1 $R/master.log | cut -c1-150)"
