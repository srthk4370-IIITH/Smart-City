#!/usr/bin/env bash
# gate.sh [SNAP_DIR]: final agt_v3 candidate -> STRICT gate vs B50 -> agt/GATE_agt.md + agt/gate.json (+ raw samples under
# post/gate/). Candidate = the best snapshot of post/selection.json (or SNAP_DIR), re-exported with its OWN imatrix (final form).
# Host GPU (GPU lock), every gate set of gate_config.json for the candidate, and for B50 on its v2 renders (B50 samples are cached
# by GGUF md5 + rows md5, so a re-gate does not re-run B50). Exit 0 PASS | 1 FAIL | 2 could not run.
source "$(dirname "$(readlink -f "$0")")/lib.sh"
OUTD=${OUTD:-$A}
EXPORT=${EXPORT_CMD:-bash $A/export.sh}
EVAL=${EVAL_CMD:-python3 $A/hosteval.py}
trap gpu_release EXIT
SNAP=${1:-$(python3 -c "import json,sys;s=json.load(open(sys.argv[1]))['best_step'];print('%s/snap_%04d' % (sys.argv[2], s))" "$POST/selection.json" "$R" 2>/dev/null)}
[ -d "$SNAP" ] || die "no candidate snapshot (selection.json missing?): $SNAP" 2
T=final_$(basename "$SNAP")
status "gate: final export of $(basename "$SNAP") (own imatrix)"
$EXPORT "$SNAP" "$T" own || die "final export failed (see $POST/$T/export.log)" 2
G=$POST/$T/agt3_${T}_q4_0.gguf; [ -s "$G" ] || die "no GGUF $G" 2
SD=$POST/gate/$T; mkdir -p "$SD" "$POST/gate/b50cache"
bmd5=$(md5sum < "$B50_GGUF" | cut -c1-12)
gpu_take || exit 2
for set in $(python3 -c "import json,sys;print(' '.join(json.load(open(sys.argv[1]))['sets']))" "$GATE_CFG"); do
  for which in v3 b50; do
    f=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['sets'][sys.argv[2]].get(sys.argv[3],''))" "$GATE_CFG" "$set" "$which")
    [ -n "$f" ] || continue
    [ -s "$GATE_DIR/$f" ] || { status "gate: missing set file $GATE_DIR/$f (counts as FAIL)"; continue; }
    if [ $which = v3 ]; then M=$G; O=$SD/${set}_v3.jsonl
    else M=$B50_GGUF; O=$POST/gate/b50cache/${set}_${bmd5}_$(md5sum < "$GATE_DIR/$f" | cut -c1-12).jsonl; fi
    status "gate: $set/$which on $(basename "$M")"
    $EVAL --model "$M" --rows "$GATE_DIR/$f" --out "$O" > "$SD/${set}_${which}.log" 2>&1 || die "eval $set/$which failed: $(tail -n 2 "$SD/${set}_${which}.log" | tr '\n' ' ')" 2
    [ $which = b50 ] && cp "$O" "$SD/${set}_b50.jsonl"
  done
done
gpu_release
python3 "$A/gate.py" "$GATE_CFG" "$GATE_DIR" "$SD" "$OUTD/GATE_agt.md" "$OUTD/gate.json" "agt_v3 $(basename "$SNAP") ($(cat "$G.md5"))"
rc=$?
cp "$POST/selection.json" "$OUTD/selection.json" 2>/dev/null; cp "$POST/$T/gguf_check.json" "$OUTD/gguf_check_final.json" 2>/dev/null
status "gate: $(head -n 1 "$OUTD/GATE_agt.md")"
exit $rc
