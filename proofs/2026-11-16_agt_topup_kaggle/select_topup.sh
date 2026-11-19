#!/usr/bin/env bash
# select_topup.sh: selection + no-harm of the Kaggle top-up on the DEPLOYED form (merged Q4_0), run on the laptop after pull_topup.sh.
# For every pulled snapshot run/snap_XXXX not scored yet:
#   export.sh (merged bf16 -> f16 GGUF -> Q4_0 with the SHARED agt_v3 imatrix, CPU)  ->  hosteval.py (host GPU, GPU lock, heat/RAM
#   guards) on REAL VAL 400 + synthetic slice 120 + unseen_metric 100  ->  post/sXXXX/{val,syn,unk}.jsonl
# then select_k.py pick: best REAL VAL score among snapshots with NO harm on syn / unseen (paired sign test p < 0.05, per field,
# vs snap_1750) and above snap_1750 on REAL VAL; writes ~/smartcity_runs/agt_topup/FINAL_K (gguf, md5, adapter, step).
# snap_1750 references: finished laptop top-up evals are reused (same 400 / 120 rows), unseen100 is evaluated once
# Test hooks (dry run, no GPU / no llama): EXPORT_CMD, EVAL_CMD, GPU_LOCK=<tmp>, GPU_ASSUME_FREE=1, FINAL_K=<tmp>, TOPUP_K=<tmp>.
# The laptop GPU lock is waited for (never taken over); nothing is killed. exit: 0 winner | 3 no winner | 2 failed export/eval
TK=$(dirname "$(readlink -f "$0")")
export AGT_CONF=$TK/agt_topup.conf
source "${AGT_DIR:-/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt}/lib.sh"
export POST
mkdir -p "$WORK" "$PLOGS" "$POST/ref"
EXPORT=${EXPORT_CMD:-bash $A/export.sh}
EVAL=${EVAL_CMD:-python3 $A/hosteval.py}
FINAL_K=${FINAL_K:-$HOME/smartcity_runs/agt_topup/FINAL_K}
LOC=$TOPUP_K/local
OLDPOST=${OLDPOST:-$HOME/smartcity_runs/agt_v3/post}; OLDREF=${OLDREF:-$HOME/smartcity_runs/agt_topup/post/ref}
G0=${G0:-$OLDPOST/snap_1750/agt3_snap_1750_q4_0.gguf}
export AGT_TRAIN=$SYN_TRAIN            # export.sh calibration = SYNTHETIC rows only (no real text in the imatrix)
trap gpu_release EXIT
# shared imatrix + calibration text of agt_v3 (as in the original selection): copied, never recomputed from real rows
for f in imatrix_agt3_shared.gguf imatrix_agt3_shared.gguf.json calib_agt3.txt; do
  [ -s "$POST/$f" ] || { [ -s "$OLDPOST/$f" ] && cp "$OLDPOST/$f" "$POST/$f"; } || true
done
ev() {   # ev GGUF ROWS OUT : resumable host eval under the GPU lock
  [ -e "$3.done" ] && return 0
  gpu_take || return 1
  $EVAL --model "$1" --rows "$2" --out "$3" > "$3.log" 2>&1; local e=$?
  gpu_release; [ $e = 0 ] && touch "$3.done"; return $e
}
for k in val:val_sel syn:syn_slice unk:unseen100; do
  n=${k%%:*}; f=${k##*:}; r=$POST/ref/${n}_s1750.jsonl
  if [ ! -e "$r.done" ] && [ -e "$OLDREF/${n}_s1750.jsonl.done" ]; then cp "$OLDREF/${n}_s1750.jsonl" "$r" && touch "$r.done"; fi
  [ -e "$r.done" ] && continue
  [ -s "$G0" ] || die "snap_1750 Q4_0 missing at $G0" 2
  ev "$G0" "$LOC/$f.jsonl" "$r" || die "snap_1750 reference eval $n failed (see $r.log)" 2
done
for d in $(ls -d "$R"/snap_* 2>/dev/null | sort); do
  t=$(basename "$d"); tag=s${t#snap_}; P=$POST/$tag
  [ -s "$P/score.json" ] && continue
  [ -e "$STOPF" ] && exit 0
  status "top-up selection: exporting $tag (merged Q4_0, shared imatrix)"
  $EXPORT "$d" "$tag" shared || { status "export of $tag failed (see $P/export.log)"; exit 2; }
  g=$P/agt3_${tag}_q4_0.gguf
  for k in val:val_sel syn:syn_slice unk:unseen100; do
    ev "$g" "$LOC/${k##*:}.jsonl" "$P/${k%%:*}.jsonl" || { status "eval ${k%%:*} of $tag failed: $(tail -n 2 "$P/${k%%:*}.jsonl.log" | tr '\n' ' ')"; exit 2; }
  done
  echo "{\"step\": $((10#${tag#s})), \"val\": $(python3 "$TK/select_k.py" score "$P/val.jsonl"), \"syn\": $(python3 "$TK/select_k.py" score "$P/syn.jsonl"), \"unk\": $(python3 "$TK/select_k.py" score "$P/unk.jsonl")}" > "$P/score.json"
  status "top-up selection: $tag $(cat "$P/score.json" | cut -c1-260)"
done
python3 "$TK/select_k.py" pick "$POST" "$POST/ref" "$POST/selection_k.json" "$FINAL_K" "$R" 2>&1 | tee "$POST/pick.log"
rc=${PIPESTATUS[0]}
status "top-up selection result (rc $rc): $(tail -n 1 "$POST/pick.log")"
exit "$rc"
