#!/usr/bin/env bash
# supervisor_r4.sh: unattended guardian of the r4 top-up (training -> post: pick, export, STRICT gate). A separate supervisor,
# so the running 2026-11-06_4b_local/supervisor.sh is untouched (that one only watches the r3 run, whose gate is done).
# Launch: start_r4.ps1 (detach.sh supervisor_r4 + hidden keepalive). Stop: touch SUP_STOP (this dir). Every 10 min:
#   1. training (no chain/train.done and status.json not stopped): chain_r4 and trainer both gone and no STOP file
#      -> ctl_r4.sh start. Not when the chain died on a data/init check (rc 9/10 in STATUS: needs a human).
#   2. post (training finished): post_r4.sh not running and no post/markers/gate.done and no post/STOP -> relaunch (resumes).
#   rate limit for 1 and 2: max 6 restarts per rolling 24 h each, then an ALERT and no more restarts.
#   3. keepalive of the detached run / post chain (WSL instanceIdleTimeout).
#   4. health: new Traceback, OOM STOP, GPU >= 92 C for 3 checks, Windows RAM < 400 MB for 3 checks -> ALERT lines.
#   5. AUTO_STATUS_r4.md (this dir): phase, step, ETA, best, evals, gate progress, alerts.
# Never deletes anything, never touches the board, Ollama, the r3 run/supervisor or other projects.
set -u
SCRIPT=supervisor_r4; RUN_ID=r4topup; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
T4=$QIDK/proofs/2026-11-12_topup_r4/train; R=$HOME/smartcity_runs/rsn3_4b_r4topup; P=$T4/post; C=$T4/chain
ST=$T4/AUTO_STATUS_r4.md; LOGR=$T4/auto_restarts_r4.log; PSX=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
mkdir -p "$C" "$P"; touch "$LOGR"; tb0=$(grep -c Traceback "$R/stdout.log" 2>/dev/null || echo 0); hotn=0; lown=0; alerts=""
alert() { alerts="$alerts\n- $(date '+%F %T') $*"; status "ALERT: $*"; }
recent() { awk -v t=$(( $(date +%s) - 86400 )) -v k="$1" '$1>=t && $2==k' "$LOGR" | wc -l; }
restart_ok() { [ "$(recent "$1")" -lt 6 ] || { alert "$1: 6 restarts in 24 h, not restarting again (needs a human)"; return 1; }; echo "$(date +%s) $1" >> "$LOGR"; }
running() { pgrep -f "$1" > /dev/null; }
keepalive() {   # keepalive <detached name>
  running "keepalive.sh $1 " || { timeout 60 "$PSX" -NoProfile -Command "Start-Process -WindowStyle Hidden wsl.exe -ArgumentList 'bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/distill_laptop/keepalive.sh $1 168'" < /dev/null > /dev/null 2>&1; status "keepalive $1 restarted"; }
}
status "supervisor_r4 start (pid $$)"
while true; do
  [ -e "$T4/SUP_STOP" ] && { status "SUP_STOP: supervisor_r4 exits"; exit 0; }
  done_train=0; [ -e "$C/train.done" ] && done_train=1
  grep -qE '"stopped": "(early_stop|done)"' "$R/status.json" 2>/dev/null && done_train=1
  if [ $done_train = 0 ]; then
    if ! running "bash .*chain_r4.sh" && ! running "python.*topup_train.py.*rsn3_4b_r4topup" && [ ! -e "$C/STOP" ]; then
      lastc=$(grep -E '\[chain_r4 r4topup\]' "$STATUS" | tail -1)
      if echo "$lastc" | grep -qE 'FAIL: (start adapter|data or init check)'; then
        :   # the trainer refused the data or the start adapter: a restart cannot help (shown in AUTO_STATUS)
      elif ! ( set +u; set -a; . "$T4/run_r4.env"; . "$T4/paths_r4.sh"; [ -s "$NEW" ] && [ -s "$REPLAY" ] \
               && [ -z "$(find "$D4" -type f -mmin -30 2>/dev/null)" ] ); then
        :   # r4 data not complete in data/final yet (or written < 30 min ago): training starts by itself once it is there
      elif restart_ok train; then status "training not running and not finished: ctl_r4.sh start"; bash "$T4/ctl_r4.sh" start > /dev/null 2>&1; fi
    fi
    running "bash .*chain_r4.sh" && keepalive rsn3_4b_r4topup
  else
    if [ ! -e "$P/markers/gate.done" ] && [ ! -e "$P/STOP" ] && ! running "bash .*post_r4.sh"; then
      if restart_ok post; then status "post chain not running, gate unfinished: relaunch"; bash "$QIDK/proofs/detach.sh" post_r4 "$P/post_r4.sh" > /dev/null 2>&1; fi
    fi
    running "bash .*post_r4.sh" && keepalive post_r4
  fi
  tb=$(grep -c Traceback "$R/stdout.log" 2>/dev/null || echo 0); [ "$tb" -gt "$tb0" ] && { alert "new Traceback in stdout.log ($tb0 -> $tb): $(grep -A1 -m1 Error "$R/stdout.log" | tail -1 | cut -c1-120)"; tb0=$tb; }
  grep -q "OOM STOP" "$R/train.log" 2>/dev/null && ! grep -q "OOM STOP seen" "$LOGR" && { alert "OOM STOP in train.log"; echo "$(date +%s) OOM STOP seen" >> "$LOGR"; }
  t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1 | tr -dc 0-9)
  [ -n "$t" ] && [ "$t" -ge 92 ] && hotn=$((hotn+1)) || hotn=0; [ $hotn = 3 ] && alert "GPU >= 92 C for 30 min ($t C)"
  w=$(free_mb); [ -n "$w" ] && [ "$w" -lt 400 ] && lown=$((lown+1)) || lown=0; [ $lown = 3 ] && alert "Windows available RAM < 400 MB for 30 min ($w MB)"
  {
    echo "# AUTO_STATUS r4 top-up (supervisor_r4, updated $(date '+%F %T %Z'))"; echo
    echo "- phase: $([ $done_train = 1 ] && echo 'training finished -> post (pick, export, STRICT gate)' || echo training)"
    echo "- last step: $(grep -E 'step [0-9]+/' "$R/train.log" 2>/dev/null | tail -1 | cut -c1-110)"
    echo "- best: $(tr -d ' \n' < "$R/best.json" 2>/dev/null | cut -c1-200)"
    echo "- last evals:"; grep -E "GEN step" "$R/train.log" 2>/dev/null | tail -3 | cut -c1-200 | sed 's/^/  - /'
    echo "- processes: chain=$(pgrep -fc 'bash .*chain_r4.sh') trainer=$(pgrep -fc 'python.*topup_train.py') post=$(pgrep -fc 'bash .*post_r4.sh') gate=$(pgrep -fc 'bash .*gate_r4.sh')"
    echo "- GPU ${t:-?} C, Windows available ${w:-?} MB, WSL $(free -m | awk 'NR==2{print $7}') MB available"
    echo "- post markers: $(ls "$P/markers" 2>/dev/null | tr '\n' ' ') gate steps: $(ls "$P/gate_r4/.m" 2>/dev/null | tr '\n' ' ')"
    [ -s "$P/gate_r4/GATE_r4.md" ] && echo "- gate verdict: $(head -1 "$P/gate_r4/GATE_r4.md")"
    echo "- restarts (24 h): train $(recent train), post $(recent post)"
    echo "- recent status lines:"; grep -E "\[(chain_r4|topup_chunk|post_r4|supervisor_r4)" "$STATUS" | tail -6 | cut -c1-170 | sed 's/^/  /'
    printf "%b\n" "${alerts:+\n## ALERTS$alerts}"
  } > "$ST.part" && mv -f "$ST.part" "$ST"
  sleep 600
done
