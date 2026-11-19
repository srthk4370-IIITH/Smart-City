#!/usr/bin/env bash
# baton_auto.sh: the unattended baton loop (BATON.md). Launch from Windows with start_auto.ps1:
# detach.sh + a hidden keepalive wsl.exe (.wslconfig instanceIdleTimeout=15 s otherwise shuts WSL down and kills the loop).
# Rule: Kaggle trains while its weekly GPU quota lasts; then the laptop; back to Kaggle after the quota refresh.
#   holder=kaggle : poll the session (laptop GPU stays free); when it ends -> from_kaggle.sh (pull + install)
#   holder=laptop : if Kaggle can run (token, quota >= MIN_KAGGLE_H, not inside a back-off) -> to_kaggle.sh (clean laptop stop,
#                   push); otherwise make sure the laptop trains (ctl_4b.sh start) and retry Kaggle at the quota refresh time
#                   (`kaggle quota`) or after RETRY_H hours, whichever is later.
# Ends when training is finished (epoch 1 done / early stop) or on the STOP file (baton/STOP). Status: [baton] in STATUS.md.
source "$(dirname "$(readlink -f "$0")")/lib.sh"
PIDF=${BATON_PIDF:-$B/auto.pid}
if [ -s "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then die "baton_auto already running (pid $(cat "$PIDF"))" 8; fi
echo $$ > "$PIDF"; trap 'rm -f "$PIDF"' EXIT
status "auto loop start (holder $(bget holder || true), step $(bget step || true))"
next_try=0; said=""
say() { [ "$1" = "$said" ] || status "$1"; said=$1; }      # one status line per state change, not per poll
nap() { local s=$1; while [ "$s" -gt 0 ] && [ ! -e "$STOPF" ]; do sleep $(( s < 60 ? s : 60 )); s=$((s - 60)); done; }
when() { date -d "@$1" '+%F %H:%M'; }

while true; do
  [ -e "$STOPF" ] && { status "STOP file: loop stops (holder $(bget holder), step $(bget step)); remove baton/STOP and relaunch to continue"; exit 0; }
  h=$(bget holder || true)
  case "$h" in
  kaggle)
    bash "$B/from_kaggle.sh" --once; rc=$?
    case $rc in
      30) say "Kaggle session seq $(bget seq) running; laptop GPU free"; nap $POLL_S ;;
      0|32|34) next_try=0 ;;                       # back on the laptop: decide again right away
      33) die "holder=conflict: owner must resolve (BATON.md 'Conflict'); loop stops" 33 ;;
      10) say "waiting for token"; nap 1800 ;;
      *) say "from_kaggle rc $rc: retry in $POLL_S s"; nap $POLL_S ;;
    esac ;;
  conflict) die "holder=conflict: owner must resolve (BATON.md 'Conflict'); loop stops" 33 ;;
  laptop|"")
    if train_finished; then status "training finished (status.json / chain train.done) at step $(run_step "$R"): loop ends"; exit 0; fi
    now=$(date +%s)
    if [ "$now" -ge "$next_try" ] && token_ok; then
      bash "$B/to_kaggle.sh"; rc=$?
      case $rc in
        0) said=""; continue ;;
        20) rf=$(date -d "$(cat "$WORK/quota_refresh" 2>/dev/null)" +%s 2>/dev/null || echo 0)
            next_try=$(( rf > now + RETRY_H * 3600 ? rf : now + RETRY_H * 3600 ))
            status "Kaggle quota used up: laptop trains; next Kaggle try $(when $next_try)" ;;
        12) next_try=$((now + 1800)) ;;
        11) next_try=$((now + 3600)); say "no laptop checkpoint yet: laptop trains first" ;;
        *) next_try=$((now + RETRY_H * 3600)); status "to_kaggle rc $rc: laptop trains; next Kaggle try $(when $next_try)" ;;
      esac
    elif ! token_ok; then say "waiting for token (~/.kaggle/access_token or kaggle.json): laptop trains"
    fi
    h=$(bget holder || true)
    if [ "$h" = laptop ] || [ -z "$h" ]; then
      if ! laptop_running && ! train_finished; then
        status "laptop holds the baton: ctl_4b.sh start"
        bash "$CTL" start || status "ctl_4b.sh start failed: retry in $POLL_S s"
      fi
      now=$(date +%s); w=$(( next_try > now ? next_try - now : POLL_S )); [ $w -gt $POLL_S ] && w=$POLL_S
      nap "$w"
    fi ;;
  *) die "unknown baton holder '$h' in $BATON" 9 ;;
  esac
done
