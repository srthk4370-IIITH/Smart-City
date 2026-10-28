#!/usr/bin/env bash
# Device A/B for the v2 latency ladder (PLAN.md section 4). htpd direct, app stopped (htpd_ab.sh stops it and
# `stop` relaunches it). Every arm starts a FRESH htpd (so COLD13 = first request = cold start), waits until the
# hottest NSP zone is < 50 C, and is interleaved with the L7 baseline (ABAB). Run from Git Bash:
#   bash run_ladder.sh envA      # v7 binary, env/args only: role drafts, one batch 14x1024, ubatch-synth 1024
#   bash run_ladder.sh ksweep    # v7: single-stream step cost vs draft rows (HTPD_DRAFT_K 1/4/8/16)
#   bash run_ladder.sh v8        # needs bin/htpd_v8 (patches/htpd_v8.patch): rows 64, one batch + rows 64, dynamic rows
#   bash run_ladder.sh acc ARM   # host400 accuracy + identity for one arm (ARM = L7|RD|O14R64|DYN|R64|US)
set -uo pipefail
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8 MSYS_NO_PATHCONV=1
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
HAB=../2026-10-21_htpd_v7_ab/htpd_ab.sh
EVAL=C:/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post/device_eval_v2/eval_htpd_v2.py
[ "$("$ADB" get-state 2>/dev/null)" = device ] || { echo "QIDK not connected"; exit 1; }

# live profile today (HANDBOOK 2.42 + /data/local/tmp/smart_city_edge/htpd_profile)
L7ENV="HTPD_AGENT_MAX_NEW=160 HTPD_JSON_ABORT=2 HTPD_SYNTH_PREFIX_CACHE=1"
A10="--agents 10 --agent-ctx 1280"
A14="--agents 14 --agent-ctx 1024 --agent-layouts 14x1024,10x1280"
RD="HTPD_ROLE_DRAFT=1 HTPD_ROLE_DRAFT_FILE=/data/local/tmp/llama.cpp/role_draft_v2.jsonl"
WL="COLD13,N1,N4,N13,C13,NM10,S2,CR,SC,B13"   # COLD13 first: htpd was just started

nsp() { "$ADB" shell 'for z in /sys/class/thermal/thermal_zone*; do case $(cat $z/type 2>/dev/null) in nsp*) cat $z/temp;; esac; done' | tr -d '\r' | sort -n | tail -1; }
cool() {
  for i in $(seq 1 90); do
    t=$(nsp)
    if [ -z "$t" ] || [ "$t" -lt 15000 ]; then echo "NSP read failed ('$t'): fixed 180 s wait"; sleep 180; return; fi
    [ "$t" -lt 50000 ] && { echo "nsp $t"; return; }
    sleep 10
  done
  echo "still hot $t"
}
# arm TAG BIN "ARGS" "ENV" [ab_ladder args...]   (ARGS may carry --ubatch-synth: htpd takes the last value)
arm() {
  tag=$1; bin=$2; args=$3; envs=$4; shift 4
  echo "=== $(date +%T) $tag  bin=$bin args=[$args] env=[$envs]"
  cool
  # htpd_ab.sh only kills htpd / htpd_v7: never leave a v8 daemon beside a new one (two models rebooted the board)
  "$ADB" shell 'pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; for i in $(seq 1 80); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; sleep 10; true'
  bash "$HAB" "$bin" "$args" "$envs"
  "$ADB" shell "grep -E 'v7 flags|ready in|role draft' /data/local/tmp/htpd_ab.log" | tr -d '\r'
  py -3 ab_ladder.py "$tag" "$@"
  "$ADB" pull /data/local/tmp/htpd_ab.log "logs/htpd_$tag.log" >/dev/null 2>&1
}
mkdir -p logs
trap '"$ADB" shell "pkill -TERM -f [b]in/htpd_v8; sleep 15; true"; bash "$HAB" stop' EXIT

case "${1:-}" in
envA)
  for r in 1 2; do
    arm L7r$r   htpd_v7 "$A10" "$L7ENV"      --only $WL --stream
    arm RDr$r   htpd_v7 "$A10" "$L7ENV $RD"  --only $WL --stream --base L7r$r
    arm O14r$r  htpd_v7 "$A14" "$L7ENV"      --only $WL --stream --base L7r$r --max-batch 14
    arm USr$r   htpd_v7 "$A10 --ubatch-synth 1024" "$L7ENV" --only S2,SC --stream --base L7r$r
  done ;;
ksweep)
  for r in 1 2; do
    for k in 1 4 8 16; do arm K${k}r$r htpd_v7 "$A10" "$L7ENV HTPD_DRAFT_K=$k" --only N1,S2 --stream; done
  done ;;
v8)
  for r in 1 2; do
    arm L7r$r     htpd_v7 "$A10" "$L7ENV"                          --only $WL --stream
    arm V8r$r     htpd_v8 "$A10" "$L7ENV"                          --only $WL --stream --base L7r$r   # v8, all off: must equal v7
    arm R64r$r    htpd_v8 "$A10" "$L7ENV HTPD_DRAFT_ROWS=64"       --only $WL --stream --base L7r$r
    arm O14R64r$r htpd_v8 "$A14" "$L7ENV HTPD_DRAFT_ROWS=64"       --only $WL --stream --base L7r$r --max-batch 14
    arm DYNr$r    htpd_v8 "$A10" "$L7ENV HTPD_DRAFT_DYN=1"         --only $WL --stream --base L7r$r
  done ;;
acc)
  a=${2:?arm}
  case $a in
    L7) b=htpd_v7; g="$A10"; e="$L7ENV" ;;
    RD) b=htpd_v7; g="$A10"; e="$L7ENV $RD" ;;
    US) b=htpd_v7; g="$A10 --ubatch-synth 1024"; e="$L7ENV" ;;
    R64) b=htpd_v8; g="$A10"; e="$L7ENV HTPD_DRAFT_ROWS=64" ;;
    O14R64) b=htpd_v8; g="$A14"; e="$L7ENV HTPD_DRAFT_ROWS=64" ;;
    DYN) b=htpd_v8; g="$A10"; e="$L7ENV HTPD_DRAFT_DYN=1" ;;
    *) echo "unknown arm $a"; exit 1 ;;
  esac
  cool; "$ADB" shell 'pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; for i in $(seq 1 80); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; sleep 10; true'; bash "$HAB" "$b" "$g" "$e"
  # same rows and scoring as proofs/2026-10-21_v2_confirm/host400_k8; batch 10 (mixed-role batches are what the app
  # sends, but the eval keeps one role per batch so the prefix cache serves the batch, exactly as before)
  py -3 "$EVAL" --set host400 --batch 10 --out "C:/Users/hp/Desktop/qidk/proofs/2026-10-21_latency_ladder/acc_$a"
  ;;
*) sed -n 2,10p "$0"; exit 1 ;;
esac
echo "=== $(date +%T) done"
