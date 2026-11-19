#!/usr/bin/env bash
# supervisor.sh: unattended guardian of the 4B r3 pipeline until the final eval (owner 2026-11-10: "automate everything ...
# without your supervision, with proper care and error mitigation ... keep guardrails"). Replaces the 30-min Claude watch.
# Launch: proofs/2026-11-06_4b_local/start_supervisor.ps1 (detach.sh + hidden keepalive). Stop: touch SUP_STOP (this dir).
# Every 10 min:
#   1. training phase (no chain/train.done): if neither chain_4b nor a trainer runs and no STOP file -> ctl_4b.sh start.
#      Rate limit: max 6 restarts per rolling 24 h; beyond that it stops restarting and writes ALERT (never loops a crash).
#   2. post phase (train.done or early stop): if post_chain.sh is not running and the gate is not finished (post/gate_r3
#      and no post/STOP -> relaunch post_chain (it resumes from its markers). Same rate limit.
#   3. keepalives: the run's keepalive (rsn3_4b_r3) is restarted from Windows via powershell.exe if the run is alive.
#   4. health: new Tracebacks / OOM STOP / GPU >= 92 C for 3 checks / Windows RAM < 400 MB for 3 checks -> ALERT lines.
#   5. writes AUTO_STATUS.md (one page: phase, step, tok/s, best, evals, ETA, post/gate progress, alerts) for the owner/Claude.
# Guardrails: never deletes anything, never touches the board, Kaggle (baton/STOP stays), Ollama or other projects; only
# starts/relaunches our own jobs through their own scripts (which keep their heat/RAM/disk guards).
set -u
SCRIPT=supervisor; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
H=$QIDK/proofs/2026-11-06_4b_local; R=$HOME/smartcity_runs/rsn3_4b_r3; P=$H/post; C=$H/chain
ST=$H/AUTO_STATUS.md; LOGR=$H/auto_restarts.log; PSX=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
touch "$LOGR"; tb0=$(grep -c Traceback "$R/stdout.log" 2>/dev/null || echo 0); hotn=0; lown=0; alerts=""
alert() { alerts="$alerts\n- $(date '+%F %T') $*"; status "ALERT: $*"; }
recent() { awk -v t=$(( $(date +%s) - 86400 )) -v k="$1" '$1>=t && $2==k' "$LOGR" | wc -l; }
restart_ok() { [ "$(recent "$1")" -lt 6 ] || { alert "$1: 6 restarts in 24 h, not restarting again (needs a human)"; return 1; }; echo "$(date +%s) $1" >> "$LOGR"; }
running() { pgrep -f "$1" > /dev/null; }
win_free() { free_mb; }
status "supervisor start (pid $$)"
while true; do
  [ -e "$H/SUP_STOP" ] && { status "SUP_STOP: supervisor exits"; exit 0; }
  done_train=0; [ -e "$C/train.done" ] && done_train=1
  grep -qE '"stopped": "(after_epoch1|early_stop)"|"done": true' "$R/status.json" 2>/dev/null && done_train=1
  # ---- 1. training
  if [ $done_train = 0 ]; then
    if ! running "bash .*chain_4b.sh" && ! running "python.*train_rsn3.py.*rsn3_4b_r3" && [ ! -e "$C/STOP" ]; then
      if restart_ok train; then status "training not running and not finished: ctl_4b.sh start"; bash "$H/ctl_4b.sh" start > /dev/null 2>&1; fi
    fi
    # keepalive for the run (WSL instanceIdleTimeout would otherwise kill detached jobs)
    if running "python.*train_rsn3.py.*rsn3_4b_r3" && ! running "keepalive.sh rsn3_4b_r3"; then
      timeout 60 "$PSX" -NoProfile -Command "Start-Process -WindowStyle Hidden wsl.exe -ArgumentList 'bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/distill_laptop/keepalive.sh rsn3_4b_r3 168'" < /dev/null > /dev/null 2>&1
      status "keepalive rsn3_4b_r3 restarted"
    fi
  else
  # ---- 2. post (export + gate)
    if [ ! -e "$P/markers/gate.done" ] && [ ! -e "$P/STOP" ] && ! running "bash .*post_chain.sh"; then
      if restart_ok post; then status "post chain not running, gate unfinished: relaunch"; bash "$QIDK/proofs/detach.sh" post_4b "$P/post_chain.sh" > /dev/null 2>&1; fi
    fi
  fi
  # ---- 4. health
  tb=$(grep -c Traceback "$R/stdout.log" 2>/dev/null || echo 0); [ "$tb" -gt "$tb0" ] && { alert "new Traceback in stdout.log ($tb0 -> $tb): $(grep -A1 -m1 Error "$R/stdout.log" | tail -1 | cut -c1-120)"; tb0=$tb; }
  grep -q "OOM STOP" "$R/train.log" 2>/dev/null && ! grep -q "OOM STOP seen" "$LOGR" && { alert "OOM STOP in train.log"; echo "$(date +%s) OOM STOP seen" >> "$LOGR"; }
  t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9)
  [ -n "$t" ] && [ "$t" -ge 92 ] && hotn=$((hotn+1)) || hotn=0; [ $hotn = 3 ] && alert "GPU >= 92 C for 30 min ($t C)"
  w=$(win_free); [ -n "$w" ] && [ "$w" -lt 400 ] && lown=$((lown+1)) || lown=0; [ $lown = 3 ] && alert "Windows available RAM < 400 MB for 30 min ($w MB)"
  # ---- 5. status page
  last=$(grep -E "step [0-9]+/" "$R/train.log" 2>/dev/null | tail -1 | cut -c1-110)
  {
    echo "# AUTO_STATUS (supervisor, updated $(date '+%F %T %Z'))"; echo
    echo "- phase: $([ $done_train = 1 ] && echo 'training finished -> post (export + gate)' || echo training)"
    echo "- last step: $last"
    echo "- best: $(tr -d ' \n' < "$R/best.json" 2>/dev/null | cut -c1-160)"
    echo "- last evals:"; grep -E "DEV step|GEN step" "$R/train.log" 2>/dev/null | tail -3 | cut -c1-170 | sed 's/^/  - /'
    echo "- processes: chain=$(pgrep -fc 'bash .*chain_4b.sh') trainer=$(pgrep -fc 'python.*train_rsn3.py.*rsn3_4b_r3') post=$(pgrep -fc 'bash .*post_chain.sh') gate=$(pgrep -fc 'bash .*gate_4b.sh') keepalive=$(pgrep -fc 'keepalive.sh')"
    echo "- GPU ${t:-?} C, Windows available ${w:-?} MB, WSL $(free -m | awk 'NR==2{print $7}') MB available"
    echo "- post markers: $(ls "$P/markers" 2>/dev/null | tr '\n' ' ') gate: $(ls "$P/gate_r3/.m" 2>/dev/null | tr '\n' ' ')"
    [ -s "$P/gate_r3/GATE.md" ] && echo "- gate verdict: $(head -1 "$P/gate_r3/GATE.md")"
    echo "- restarts (24 h): train $(recent train), post $(recent post)"
    echo "- recent status lines:"; grep -E "\[(chain_4b|laptop_train|post_4b|supervisor)" "$STATUS" | tail -6 | cut -c1-170 | sed 's/^/  /'
    printf "%b\n" "${alerts:+\n## ALERTS$alerts}"
  } > "$ST.part" && mv -f "$ST.part" "$ST"
  sleep 600
done
