#!/usr/bin/env bash
# runner.sh: the unattended agt_v3 chain (launch with start_runner.ps1 = detach.sh + hidden keepalive wsl.exe).
#   0. waits (does nothing else) until the owner approval file $APPROVAL (proofs/2026-11-13_v3_data/APPROVED_AGENTS) exists
#   1. push.sh -> Kaggle session; pull.sh --once every POLL_S; while Kaggle trains, select.sh scores finished snapshots on the
#      laptop (merged Q4_0, host GPU under the GPU lock)
#   2. next session until: the trainer stopped (2 epochs / gen-dev early stop), the merged-Q4_0 dev selection stops (PATIENCE evals
#      without gain), or the Kaggle hours cap TOTAL_CAP_H; quota used up -> waits for the weekly refresh
#   3. select.sh (rest) -> gate.sh -> GATE_agt.md. Never deploys anything, never touches the board / app / Ollama.
# Stop: touch agt/STOP (the loop exits at the next check; a running Kaggle session finishes and is pulled on the next start).
source "$(dirname "$(readlink -f "$0")")/lib.sh"
PIDF=${RUNNER_PID:-$A/runner.pid}
if [ -s "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then die "runner already running (pid $(cat "$PIDF"))" 8; fi
echo $$ > "$PIDF"; trap 'rm -f "$PIDF"' EXIT
said=""; say() { [ "$1" = "$said" ] || status "$1"; said=$1; }
nap() { local s=$1; while [ "$s" -gt 0 ] && [ ! -e "$STOPF" ]; do sleep $(( s < 60 ? s : 60 )); s=$((s - 60)); done; }
stopcheck() { [ -e "$STOPF" ] && { status "STOP file: runner exits (holder $(sget holder), step $(sget step))"; exit 0; }; }
status "runner start (holder $(sget holder), step $(sget step))"

# ---- 0. owner approval
until [ -e "$APPROVAL" ]; do stopcheck; say "waiting for owner approval: $APPROVAL does not exist (nothing uploaded, nothing trained)"; nap "${APPROVAL_POLL_S:-600}"; done
status "owner approval found: $APPROVAL ($(stat -c %y "$APPROVAL" | cut -c1-19))"
for f in "$AGT_TRAIN" "$AGT_GENDEV" "$CALIB_STATS" "$DEV600"; do [ -s "$f" ] || die "approved, but data file missing: $f" 23; done

# ---- 1-2. sessions
fails=0
while true; do
  stopcheck
  case "$(sget holder)" in
  kaggle)
    bash "$A/pull.sh" --once; rc=$?
    case $rc in
      30) say "Kaggle session seq $(sget seq) running"; GPU_NOWAIT=1 bash "$A/select.sh" > /dev/null 2>&1; nap "$POLL_S" ;;
      0) fails=0; said=""; GPU_NOWAIT=1 bash "$A/select.sh" || status "select.sh rc $? (retried later)" ;;
      32|34) fails=$((fails + 1)); [ $fails -ge 3 ] && die "3 sessions in a row without a usable lineage: owner check (STATUS.md, logs/)" 32 ;;
      10) die "Kaggle token missing" 10 ;;
      *) say "pull rc $rc: retry"; nap "$POLL_S" ;;
    esac ;;
  laptop|"")
    if train_stopped; then status "trainer finished: $(python3 -c "import json;d=json.load(open('$R/status.json'));print(d.get('stopped'), 'step', d['step'], d['why'])")"; break; fi
    if python3 -c "import json,sys;sys.exit(0 if json.load(open('$POST/selection.json')).get('stop') else 1)" 2>/dev/null; then
      status "merged-Q4_0 dev selection: $PATIENCE evals without gain: no more sessions"; break; fi
    bash "$A/push.sh"; rc=$?
    case $rc in
      0) said="" ;;
      19) break ;;
      20) rf=$(date -d "$(cat "$WORK/quota_refresh" 2>/dev/null)" +%s 2>/dev/null || echo 0); now=$(date +%s)
          w=$(( rf > now ? rf - now + 600 : 4 * 3600 )); status "quota: next try $(date -d "@$((now + w))" '+%F %H:%M')"; nap $w ;;
      10|11|23) die "push rc $rc: owner check (STATUS.md)" $rc ;;
      *) fails=$((fails + 1)); [ $fails -ge 4 ] && die "push failed 4 times (last rc $rc)" $rc; nap 1800 ;;
    esac ;;
  *) die "unknown holder '$(sget holder)'" 9 ;;
  esac
done

# ---- 3. selection + gate
stopcheck
bash "$A/select.sh" || die "selection failed" 2
bash "$A/gate.sh"; rc=$?
status "runner done: gate rc $rc ($(head -n 1 "${OUTD:-$A}/GATE_agt.md" 2>/dev/null))"
exit $rc
