#!/usr/bin/env bash
# chain.sh: gate one candidate, or compare two gated candidates, and write READY_FOR_BOARD. Never touches the board: the board
# A/B window and the deploy are separate, owner-approved steps.
#   gate:    RUN_ID=t4b [NAME=rsn_v3]    bash chain.sh [adapter.zip]   (import when a zip is given) -> gate_eval.sh -> gate/t4b
#   compare: RUN_ID=c1 bash chain.sh compare <4b gate run id> <2b gate run id>
#            -> compare_candidates.py (only gate-passing candidates; the more accurate on RWH + RWH-2, then chat, then the
#               faster 2B) -> READY_FOR_BOARD_c1.json naming the winner's GGUF
# usage via proofs/detach.sh, e.g. RUN_ID=t4b bash detach.sh chain_t4b .../local/chain.sh /mnt/c/Users/hp/Downloads/rsn_v3_adapter_epoch1.zip
SCRIPT=chain; source "$(dirname "$0")/guard.sh"
check_run_id
D=$(dirname "$0")
ready() {   # ready <gguf> <decision json>
  python3 - "$1" "$2" "$KG/READY_FOR_BOARD_$RUN_ID.json" <<'EOF'
import json, sys, time
md5 = open(sys.argv[1] + ".md5").read().split()[0]
json.dump({"gguf": sys.argv[1], "md5": md5, "decision": sys.argv[2], "t": time.strftime("%F %T"),
           "next": "owner-approved board A/B window, then deploy with rollback snapshot (not automated)"}, open(sys.argv[3], "w"), indent=1)
EOF
  status "READY_FOR_BOARD written: $KG/READY_FOR_BOARD_$RUN_ID.json ($1; board steps need owner approval)"
}
if [ "${1:-}" = compare ]; then
  A=${2:?4b gate run id}; B=${3:?2b gate run id}
  for r in "$A" "$B"; do [ -s "$KG/gate/$r/gate.json" ] || die "no gate.json for run $r"; done
  python3 "$D/compare_candidates.py" --a "4b=$KG/gate/$A" --b "2b=$KG/gate/$B" --fast 2b --out "$KG/gate/compare_$RUN_ID"; rc=$?
  [ $rc = 0 ] || { status "compare: no candidate passed"; exit 1; }
  W=$(python3 -c "import json;print(json.load(open('$KG/gate/compare_$RUN_ID/compare.json'))['winner'])")
  R=$([ "$W" = 4b ] && echo "$A" || echo "$B")
  G=$(cat "$KG/gate/$R/gguf.txt")
  status "compare: winner $W ($G)"
  ready "$G" "$KG/gate/compare_$RUN_ID/compare.json"
  exit 0
fi
G=$QIDK/Code/models_stage/${NAME:-rsn_v3}_q4_0.gguf
status "start${1:+ (import $1)}"
if [ -n "${1:-}" ]; then
  bash "$D/import_adapter.sh" "$1" || die "import failed"
fi
bash "$D/gate_eval.sh" "$G"; rc=$?
[ -d "$KG/gate/$RUN_ID" ] && echo "$G" > "$KG/gate/$RUN_ID/gguf.txt"
if [ $rc = 0 ]; then
  if [ "${SINGLE:-0}" = 1 ]; then ready "$G" "$KG/gate/$RUN_ID/gate.json"
  else status "gate PASS for $G; run 'chain.sh compare <4b run> <2b run>' once both candidates are gated (SINGLE=1 to skip the comparison)"; fi
else
  status "no READY_FOR_BOARD (gate rc=$rc)"
fi
exit $rc
