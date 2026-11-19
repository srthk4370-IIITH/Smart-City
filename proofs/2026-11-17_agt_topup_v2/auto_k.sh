#!/usr/bin/env bash
# auto_k.sh: STAGE K = Kaggle evaluation of the top-up v2 snapshots (owner decision 2026-11-17) + automatic decision + max 1 error-driven continuation.
# Start detached:  bash proofs/detach.sh agt_k proofs/2026-11-17_agt_topup_v2/auto_k.sh      Stop: touch $PF/STOP.  Never deploys to the board.
# K1 stop the auto_v2 STAGE 6 wait | K2 eval round r1 (s0300 + v2 snapshots, newest first) | K3 decision (GOOD -> KAGGLE_PICK + re-arm auto_v2 from STAGE 6,
# restricted to that snapshot + s0300) | else K4 error-driven data (DATASET_V2B.md) + checks | K5 continuation training on Kaggle from snap_0200
# (LR 5e-5, ~300 steps, snap/50, early stop after 2 consecutive drops of the tool+hard dev score) | K6 eval round r2 | K7 decision again.
PF=$(dirname "$(readlink -f "$0")"); QP=/mnt/c/Users/hp/Desktop/qidk/proofs; KE=$PF/kaggle_eval
K2=$HOME/smartcity_runs/agt_topup_k2; K2B=$HOME/smartcity_runs/agt_topup_k2b; K1=$HOME/smartcity_runs/agt_topup_k
PY=${PY:-$HOME/venvs/rsn/bin/python}; V2LOG=$HOME/detached/agt_v2.log
st() { echo "STAGE K: $*"; echo "STAGE K: $*" >> $V2LOG; echo "- $(date -u +%FT%H:%MZ) [agt_topup_v2] STAGE K: $*" >> $QP/AGENT_REGISTRY.md; }
fail() { echo "$(date -Is) STAGE K FAILED: $*" > $PF/FAILED_K; st "FAILED: $*"; exit 1; }
stopped() { [ -e $PF/STOP ] && { st "STOP file found, leaving"; exit 0; }; }
rm -f $PF/FAILED_K
done_train() { python3 -c "import json,sys,os;d=json.load(open(os.path.expanduser('$K2B/run/status.json')));sys.exit(0 if d.get('stopped') or d.get('step',0)>=d.get('n_steps',1) else 1)" 2>/dev/null; }
tagargs() {  # tagargs PREFIX AREA -> TAG=DIR newest first
  for d in $(ls -d $2/run/snap_* 2>/dev/null | sort -r); do b=$(basename $d); echo "$1${b#snap_}=$d"; done; }
arm_selection() {  # arm_selection AREA TAG WHY : write KAGGLE_PICK, re-arm auto_v2 from STAGE 6 restricted to that snapshot (+ s0300 reference)
  local area=$1 tag=$2 n=${2#?}
  printf 'snapshot=snap_%s\nadapter=%s/run/snap_%s\narea=%s\nsource=kaggle eval decision (%s)\n' "$n" "$area" "$n" "$area" "$3" > $K2/KAGGLE_PICK
  [ "$area" = "$K2" ] || cp $K2/KAGGLE_PICK $area/KAGGLE_PICK
  st "GOOD: $tag marked for local Q4_0 selection ($K2/KAGGLE_PICK); re-arming auto_v2.sh from STAGE 6 restricted to s$n + s0300"
  TOPUP_K=$area FROM6=1 ONLY_TAGS="s$n" SKIP_BELOW=0 bash $PF/auto_v2.sh
  st "auto_v2 selection ended rc=$? (see $area/FINAL_K2, else s0300 stays)"
}
decide() {  # decide OUTDIR RDIR REFDIR -> sets GOODTAG
  $PY -I $KE/ke_score.py "$@" > $1/score.out 2>&1; local rc=$?
  GOODTAG=$(awk '/^GOOD /{print $2}' $1/score.out); st "decision ($1): $(head -n 1 $1/score.out | cut -c1-120)"
  return $rc; }
# ---- K1
if tail -n 3 $V2LOG | grep -q "STAGE 6: waiting"; then
  P=$(cat $HOME/detached/agt_v2.pid 2>/dev/null)
  if [ -n "$P" ] && [ -r /proc/$P/cmdline ] && tr '\0' ' ' < /proc/$P/cmdline | grep -q auto_v2.sh; then
    pkill -P $P sleep 2>/dev/null; kill $P 2>/dev/null; st "stopped the auto_v2.sh STAGE 6 wait (pid $P): replaced by the Kaggle eval; selection is re-armed by this script"
  fi
fi
mkdir -p $PF/data/kaggle_eval
# ---- K2/K3 round 1
if [ ! -s $PF/data/kaggle_eval/DECISION.md ]; then
  stopped
  if [ ! -s $PF/data/kaggle_eval/EVAL_RESULT.json ]; then
    st "round 1: Kaggle eval of s0300 + v2 snapshots (HF fp16 greedy; val 200 real, hard 160, tool t1 90, tool t2 56; 45 min eval budget after setup; 2 GPUs)"
    bash $KE/ke_run.sh r1 s0300=$K1/run/snap_0300 $(tagargs s $K2) || fail "round 1 eval run (see $PF/STATUS.md)"
  fi
  decide $PF/data/kaggle_eval $PF/data/kaggle_eval; rc=$?
  cp $PF/data/kaggle_eval/SUMMARY.md $PF/SUMMARY.md 2>/dev/null; cp $PF/data/kaggle_eval/DECISION.md $PF/DECISION.md 2>/dev/null
  [ $rc = 4 ] && fail "round 1 produced no scores"
else
  GOODTAG=$(awk '/^best:/{print $2}' $PF/data/kaggle_eval/DECISION.md); [ "$GOODTAG" = None ] && GOODTAG=""
  rc=3; [ -n "$GOODTAG" ] && rc=0
fi
if [ $rc = 0 ] && [ -n "$GOODTAG" ]; then arm_selection $K2 $GOODTAG "round 1"; exit 0; fi
# ---- K4 error-driven data
stopped
if [ ! -e $K2B/checks_ok ]; then
  st "round 1 NOT GOOD: error-driven dataset v2b (DATASET_V2B.md): failed rows per set and family -> multipliers -> regenerate"
  mkdir -p $K2B $PF/b_pf
  $PY -I $KE/ke_regen.py $PF/data/kaggle_eval/errors.json $K2B/fam_mult.json $PF/DATASET_V2B.md > $K2B/regen.log 2>&1 || fail "ke_regen: $(tail -n 2 $K2B/regen.log)"
  st "family multipliers: $(cut -c1-300 $K2B/fam_mult.json)"
  [ -s $K2B/gen/new_full.jsonl ] || FAM_MULT="$(cat $K2B/fam_mult.json)" nice -n 15 $PY $PF/gen_run.py --out $K2B/gen --scale 1.0 --procs 3 --seed 2117 > $K2B/gen.log 2>&1 || fail "gen_run v2b: $(tail -n 2 $K2B/gen.log)"
  [ -s $K2B/gen_dev5/new_full.jsonl ] || nice -n 15 $PY $PF/gen_run.py --out $K2B/gen_dev5 --scale 0.1 --procs 3 --split dev --seed 5151 > $K2B/gen_dev5.log 2>&1 || fail "gen_run dev5: $(tail -n 2 $K2B/gen_dev5.log)"
  if [ ! -e $K2B/negs_done ]; then   # round 2: more clear "no call needed" negatives (dyn rows), dedup by id/prompt against gen
    [ -s $K2B/gen_neg/new_full.jsonl ] || nice -n 15 $PY $PF/gen_run.py --out $K2B/gen_neg --scale 0.8 --procs 3 --seed 3117 --only dyn > $K2B/gen_neg.log 2>&1 || fail "gen_run neg: $(tail -n 2 $K2B/gen_neg.log)"
    cp -n $K2B/gen/new_full.jsonl $K2B/gen/new_full_orig.jsonl; touch $K2B/negs_pending
    $PY - $K2B <<'P' || fail "concat negatives"
import json,sys
d=sys.argv[1]; rows=[json.loads(l) for l in open(d+"/gen/new_full_orig.jsonl")]; ids={r["id"] for r in rows}; ps={r["prompt"] for r in rows}; n=0
for l in open(d+"/gen_neg/new_full.jsonl"):
    r=json.loads(l)
    if r["id"] in ids or r["prompt"] in ps: continue
    ids.add(r["id"]); ps.add(r["prompt"]); rows.append(r); n+=1
open(d+"/gen/new_full.jsonl","w",newline=chr(10)).write("".join(json.dumps(r,ensure_ascii=False)+chr(10) for r in rows)); print("added",n,"negatives, total",len(rows))
P
    touch $K2B/negs_done
    st "round 2: added clear no-call negatives: $(tail -n 1 $K2B/gen_neg.log | cut -c1-100)"
  fi
  REAL_APPROVED=$PF/b_pf/REAL_APPROVED.json $PY $PF/build_mix_v2.py --out=$K2B --new=$K2B/gen/new_full.jsonl --dev=$K2/gen_dev/new_full.jsonl --pf=$PF/b_pf --replay-frac=0.55 > $K2B/mix.log 2>&1 || fail "build_mix v2b: $(tail -n 2 $K2B/mix.log)"
  $PY -I $KE/ke_gendev.py $K2B > $K2B/gendev.log 2>&1 || fail "gendev v2b: $(tail -n 2 $K2B/gendev.log)"
  $PY - $PF/b_pf/REAL_APPROVED.json $K2B/mixdata <<'P' || fail "re-pin approval"   # same exception scope: gendev was rewritten by ke_gendev AFTER build_mix pinned it
import json,sys,hashlib
f=sys.argv[1]; d=json.load(open(f)); m=lambda p: hashlib.md5(open(p,"rb").read()).hexdigest()
d["train_md5"]=m(sys.argv[2]+"/train.jsonl"); d["gendev_md5"]=m(sys.argv[2]+"/gendev.jsonl"); d["n_real_gendev"]=sum(1 for l in open(sys.argv[2]+"/gendev.jsonl") if json.loads(l).get("synthetic") is False); d["n_real_train"]=sum(1 for l in open(sys.argv[2]+"/train.jsonl") if json.loads(l).get("synthetic") is False); json.dump(d,open(f,"w",newline=chr(10)),indent=1)
P
  echo "- $(date -u +%FT%H:%MZ) [train v2b] OWNER EXCEPTION re-pinned (same scope as v2, replay of v1 real rows, private dataset): md5 of train/gendev updated after ke_gendev" >> $PF/REAL_EXCEPTION.log
  st "v2b mix: $(tail -n 1 $K2B/mix.log | cut -c1-260); continuation dev: $(tail -n 1 $K2B/gendev.log)"
  TOPUP_K=$K2B NEW_FULL=$K2B/gen/new_full.jsonl CHECKS_OUT=$PF/data_b REAL_APPROVED=$PF/b_pf/REAL_APPROVED.json \
    $PY -I $PF/check_data_v2.py $K2B/mixdata/train.jsonl $K2B/mixdata/gendev.jsonl $QP/2026-11-13_v3_data/calib_stats.json 0 $K2B/precheck_stage > $K2B/precheck.log 2>&1 \
    || fail "v2b checks: $(grep -E 'FAIL|REFUSED' $K2B/precheck.log | head -n 4 | tr '\n' ' ')"
  touch $K2B/checks_ok
  st "v2b checks PASSED (schema, tool protocol, gold consistency, leakage, 904+240+136<=1280); DATASET_V2B.md written"
  { echo; echo "Result: $(tail -n 1 $K2B/mix.log | cut -c1-300)"; echo "Checks: PASSED ($PF/data_b/checks_report.json). Continuation dev (fixed, seed 5151, disjoint from the eval sets): $(tail -n 1 $K2B/gendev.log)."; } >> $PF/DATASET_V2B.md
fi
# ---- K5 continuation training (max 1)
stopped
export TOPUP_K=$K2B SNAP0=$K2/run/snap_0200 LR=5e-5 EPOCHS=2 PATIENCE=2 BUDGET_H=6 TOTAL_CAP_H=8 GEN_N=100
if ! done_train; then
  for k in 1 2 3; do
    stopped
    st "continuation training #$k on Kaggle from snap_0200 (LR 5e-5, patience 2 on the tool+hard dev score, snapshots every 50)"
    bash $PF/push_v2b.sh; rc=$?; st "continuation push #$k rc=$rc"
    [ $rc = 0 ] || fail "continuation push rc=$rc: $(tail -n 2 $PF/STATUS.md | cut -c1-200 | tr '\n' ' ')"
    bash $PF/pull_v2.sh; st "continuation pull #$k rc=$?: $(tail -n 1 $PF/STATUS.md | cut -c1-200)"
    done_train && break
  done
fi
unset TOPUP_K SNAP0 LR EPOCHS PATIENCE BUDGET_H TOTAL_CAP_H GEN_N
st "continuation finished; snapshots: $(ls $K2B/run | grep snap_ | tr '\n' ' ')"
# ---- K6/K7 round 2
if [ ! -s $PF/data/kaggle_eval_r2/DECISION.md ]; then
  stopped
  st "round 2: Kaggle eval of the continuation snapshots"
  bash $KE/ke_run.sh r2 $(tagargs b $K2B) || fail "round 2 eval run (see $PF/STATUS.md)"
  decide $PF/data/kaggle_eval_r2 $PF/data/kaggle_eval_r2 $PF/data/kaggle_eval; rc=$?
  cp $PF/data/kaggle_eval_r2/DECISION.md $PF/DECISION_r2.md 2>/dev/null
  [ $rc = 4 ] && fail "round 2 produced no scores"
  if [ $rc = 0 ] && [ -n "$GOODTAG" ]; then arm_selection $K2B $GOODTAG "round 2 (continuation)"; exit 0; fi
fi
st "NOT GOOD after the continuation too: s0300 stays; stopping (max 1 continuation)"
