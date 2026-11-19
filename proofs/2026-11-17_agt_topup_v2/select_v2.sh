#!/usr/bin/env bash
# select_v2.sh: selection + no-harm of the top-up v2 snapshots on the DEPLOYED form (merged Q4_0, shared imatrix) against s0300 (the deployed v1 winner).
# Derived from select_topup.sh (v1). Differences: conf agt_topup2.conf; six eval sets (val_sel/syn_slice/unseen100 as v1, + hard_val, tool_t2 via
# hosteval.py and tool_t1 via hosteval_tool.py: the app-equivalent multi-turn eval, turn 1 free + turn 2 with the gold call and result teacher-forced, which
# is exactly what the app does after a correct call); references = s0300 (v1 post samples reused for val/syn/unk, the other three evaluated once on the
# s0300 GGUF); snapshots below SKIP_BELOW (default 100) are skipped; waits for free C: space (>= 21000 MB) before each export; FINAL_K2 (NOT the board's
# FINAL_K) gets the winner. The laptop GPU lock is WAITED for (lib.sh gpu_take), nothing is killed. The caller (auto_v2.sh) waits for the reasoner
# fine-tune to be done first. Test hooks: EXPORT_CMD, EVAL_CMD, EVAL_TOOL_CMD, GPU_LOCK, GPU_ASSUME_FREE=1, FINAL_K2, TOPUP_K, G0, OLD_POST, SKIP_BELOW.
# exit: 0 winner | 3 no winner | 2 failed export/eval
TK=$(dirname "$(readlink -f "$0")")
export AGT_CONF=$TK/agt_topup2.conf
source "${AGT_DIR:-/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt}/lib.sh"
export POST
mkdir -p "$WORK" "$PLOGS" "$POST/ref"
EXPORT=${EXPORT_CMD:-bash $A/export.sh}
EVAL=${EVAL_CMD:-python3 $A/hosteval.py}
EVALT=${EVAL_TOOL_CMD:-python3 $TK/hosteval_tool.py}
FINAL_K2=${FINAL_K2:-$TOPUP_K/FINAL_K2}
LOC=$TOPUP_K/local
OLD_POST=${OLD_POST:-$HOME/smartcity_runs/agt_topup_k/post}
G0=${G0:-$OLD_POST/s0300/agt3_s0300_q4_0.gguf}
SKIP_BELOW=${SKIP_BELOW:-100}
export AGT_TRAIN=$SYN_TRAIN            # export.sh calibration = SYNTHETIC rows only (no real text in the imatrix)
trap gpu_release EXIT
for f in imatrix_agt3_shared.gguf imatrix_agt3_shared.gguf.json calib_agt3.txt; do
  [ -s "$POST/$f" ] || { [ -s "$OLD_POST/$f" ] && cp "$OLD_POST/$f" "$POST/$f"; } || true
done
ev() {   # ev KIND GGUF ROWS OUT : resumable host eval under the GPU lock (KIND ans|t1)
  [ -e "$4.done" ] && return 0
  gpu_take || return 1
  if [ "$1" = t1 ]; then $EVALT --model "$2" --rows "$3" --out "$4" > "$4.log" 2>&1; else $EVAL --model "$2" --rows "$3" --out "$4" > "$4.log" 2>&1; fi
  local e=$?
  gpu_release; [ $e = 0 ] && touch "$4.done"; return $e
}
space() {   # wait for >= 21000 MB free on C: (the WSL vhdx lives there; export.sh refuses below 20480)
  local said=0
  while [ "$(df -Pm /mnt/c | awk 'NR==2{print $4}')" -lt "${MIN_FREE_MB:-21000}" ]; do
    [ -e "$STOPF" ] && return 1
    [ $said = 0 ] && status "top-up v2 selection: waiting for C: free space ($(df -Pm /mnt/c | awk 'NR==2{print $4}') MB < ${MIN_FREE_MB:-21000})"; said=1
    sleep 600
  done
}
declare -A SETFILE=( [val]=val_sel [syn]=syn_slice [unk]=unseen100 [hard]=hard_val [t2]=tool_t2 [t1]=tool_t1 )
for n in val syn unk hard t2 t1; do                     # s0300 references: v1 samples reused where they exist
  r=$POST/ref/${n}_s0300.jsonl
  if [ ! -e "$r.done" ] && [ -e "$OLD_POST/s0300/$n.jsonl" ] && [ "$n" != hard ] && [ "$n" != t2 ] && [ "$n" != t1 ]; then
    cp "$OLD_POST/s0300/$n.jsonl" "$r" && touch "$r.done"
  fi
  [ -e "$r.done" ] && continue
  [ -s "$G0" ] || die "s0300 Q4_0 missing at $G0" 2
  status "top-up v2 selection: reference eval $n on s0300"
  ev $([ $n = t1 ] && echo t1 || echo ans) "$G0" "$LOC/${SETFILE[$n]}.jsonl" "$r" || die "s0300 reference eval $n failed (see $r.log)" 2
done
for d in $(ls -d "$R"/snap_* 2>/dev/null | sort); do
  t=$(basename "$d"); tag=s${t#snap_}; P=$POST/$tag
  [ $((10#${tag#s})) -lt "$SKIP_BELOW" ] && continue
  [ -s "$P/score.json" ] && continue
  [ -n "${ONLY_TAGS:-}" ] && ! echo " $ONLY_TAGS " | grep -q " $tag " && continue   # Kaggle-eval pick only (auto_k.sh)
  [ -e "$STOPF" ] && exit 0
  g=$P/agt3_${tag}_q4_0.gguf
  if [ ! -s "$g" ]; then
    space || exit 0
    status "top-up v2 selection: exporting $tag (merged Q4_0, shared imatrix)"
    $EXPORT "$d" "$tag" shared || { status "export of $tag failed (see $P/export.log)"; exit 2; }
  fi
  for n in val syn unk hard t2 t1; do
    ev $([ $n = t1 ] && echo t1 || echo ans) "$g" "$LOC/${SETFILE[$n]}.jsonl" "$P/$n.jsonl" || { status "eval $n of $tag failed: $(tail -n 2 "$P/$n.jsonl.log" | tr '\n' ' ')"; exit 2; }
  done
  python3 - "$TK" "$P" "$tag" > "$P/score.json" <<'PY'
import json, subprocess, sys
tk, P, tag = sys.argv[1:4]
out = {"step": int(tag[1:])}
for n in ("val", "syn", "unk", "hard", "t2", "t1"):
    out[n] = json.loads(subprocess.check_output(["python3", tk + "/select_v2.py", "score", "%s/%s.jsonl" % (P, n)] + (["call"] if n == "t1" else [])))
print(json.dumps(out))
PY
  status "top-up v2 selection: $tag $(cut -c1-300 "$P/score.json")"
done
python3 "$TK/select_v2.py" pick "$POST" "$POST/ref" "$POST/selection_v2.json" "$FINAL_K2" "$R" s0300 2>&1 | tee "$POST/pick.log"
rc=${PIPESTATUS[0]}
status "top-up v2 selection result (rc $rc): $(tail -n 1 "$POST/pick.log")"
exit "$rc"
