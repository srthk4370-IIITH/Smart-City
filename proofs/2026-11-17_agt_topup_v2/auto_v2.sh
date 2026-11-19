#!/usr/bin/env bash
# auto_v2.sh: the AUTOMATED agt_v3 top-up v2 pipeline (owner-approved 2026-11-17). Start detached:  bash proofs/detach.sh agt_v2 <this file>
# generate -> checks (stop on fail, FAILED file) -> push private dataset + kernel (continue from snap_0300) -> poll/pull Kaggle -> wait for the reasoner
# fine-tune to finish + GPU lock free -> export + selection with no-harm vs s0300 (tool slice included) -> STOP. It NEVER deploys to the board.
# Status lines "STAGE x: ..." go to stdout (= ~/detached/agt_v2.log) and AGENT_REGISTRY.md. Stop it: touch $PF/STOP.  Dry run (no Kaggle/GPU): DRY_RUN=1 bash auto_v2.sh
# Real windows reach Kaggle only through check_data_v2.py's md5-pinned owner exception (replay of the v1 real rows; REAL_EXCEPTION.log, AGENT_REGISTRY.md).
PF=$(dirname "$(readlink -f "$0")")
QP=/mnt/c/Users/hp/Desktop/qidk/proofs
K2=${TOPUP_K:-$HOME/smartcity_runs/agt_topup_k2}
DRY=${DRY_RUN:-}
SCALE=${SCALE:-1.0}; [ -n "$DRY" ] && SCALE=${SCALE_DRY:-0.05}
PY=${PY:-$HOME/venvs/rsn/bin/python}
G=$K2/gen; GD=$K2/gen_dev; [ -n "$DRY" ] && { K2=$K2/dry_run; mkdir -p $K2; G=$K2/gen; GD=$K2/gen_dev; }
export TOPUP_K=$K2 NEW_FULL=$G/new_full.jsonl CHECKS_OUT=$PF/data REAL_APPROVED=$PF/REAL_APPROVED.json
[ -n "$DRY" ] && export REAL_EXCEPTION_LOG=$K2/dry_exception.log CHECKS_OUT=$PF/data_dry
st() { echo "STAGE $1: ${*:2}"; echo "- $(date -u +%FT%H:%MZ) [agt_topup_v2] STAGE $1: ${*:2}" >> $QP/AGENT_REGISTRY.md; }
fail() { echo "$(date -Is) STAGE $1 FAILED: ${*:2}" > $PF/FAILED; st "$1" "FAILED: ${*:2}"; exit 1; }
stopped() { [ -e $PF/STOP ] && { st stop "STOP file found, leaving"; exit 0; }; }
rm -f $PF/FAILED 2>/dev/null
st 0 "start (scale $SCALE${DRY:+, DRY RUN}); work area $K2; base adapter s0300 of the v1 top-up"
[ -z "$DRY" ] && [ -z "${FROM6:-}" ] && echo "- $(date -u +%FT%H:%MZ) [agt_topup_v2] OWNER EXCEPTION USED (as v1): replay of the v1 real windows goes to a PRIVATE Kaggle dataset agt3-topup2-data, md5-pinned by REAL_APPROVED.json, logged in $PF/REAL_EXCEPTION.log" >> $QP/AGENT_REGISTRY.md
if [ -z "${FROM6:-}" ]; then   # FROM6=1: only stages 6-8 (re-armed by auto_k.sh after a GOOD Kaggle eval)
# ---- 1 generate (CPU only, nice, 3 procs)
stopped
mkdir -p $G $GD
if [ ! -s $G/new_full.jsonl ]; then
  st 1 "generating NEW rows (dynamic windows, hard cases, weak roles, tool protocol) -> $G"
  nice -n 15 $PY $PF/gen_run.py --out $G --scale $SCALE --procs 3 --seed 1117 > $K2/gen.log 2>&1 || fail 1 "gen_run train: $(tail -n 2 $K2/gen.log | tr '\n' ' ')"
fi
if [ ! -s $GD/new_full.jsonl ]; then
  nice -n 15 $PY $PF/gen_run.py --out $GD --scale $(awk -v s=$SCALE 'BEGIN{printf "%.3f", 0.12*(s<0.3?0.4:1)}') --procs 3 --split dev --seed 4242 > $K2/gen_dev.log 2>&1 || fail 1 "gen_run dev: $(tail -n 2 $K2/gen_dev.log | tr '\n' ' ')"
fi
st 1 "generated: $(wc -l < $G/new_full.jsonl) new rows, $(wc -l < $GD/new_full.jsonl) dev-slice rows"
# ---- 2 mix (replay 60 % of the v1 mix that fits the board context)
PFOUT=$PF; [ -n "$DRY" ] && { PFOUT=$PF/dry_pf; mkdir -p $PFOUT; export REAL_APPROVED=$PFOUT/REAL_APPROVED.json; }
$PY $PF/build_mix_v2.py --out=$K2 --new=$G/new_full.jsonl --dev=$GD/new_full.jsonl --pf=$PFOUT > $K2/mix.log 2>&1 || fail 2 "build_mix_v2: $(tail -n 2 $K2/mix.log | tr '\n' ' ')"
st 2 "mix: $(tail -n 1 $K2/mix.log | cut -c1-300)"
[ -n "$DRY" ] && D=$PF/data_dry || D=$PF/data; mkdir -p $D
$PY $PF/review_sample.py $K2/mixdata/train.jsonl $D/REVIEW_SAMPLE.md > /dev/null 2>&1 || st 2 "review sample failed (non-fatal)"
# ---- 3 checks (hard gate before anything leaves the laptop)
stopped
st 3 "checks: schema, tool protocol, gold consistency, leakage, per-turn token limit (904 + 240 + 136 <= 1280)"
$PY -I $PF/check_data_v2.py $K2/mixdata/train.jsonl $K2/mixdata/gendev.jsonl $QP/2026-11-13_v3_data/calib_stats.json 100 $K2/precheck_stage > $K2/precheck.log 2>&1 \
  || fail 3 "$(grep -E 'FAIL|REFUSED' $K2/precheck.log | head -n 4 | tr '\n' ' ')"
st 3 "checks PASSED ($(tail -n 1 $K2/precheck.log | cut -c1-120)); report $D/checks_report.json"
[ -n "$DRY" ] && { st dry "dry run finished: checks passed, nothing pushed (no Kaggle, no GPU)"; exit 0; }
# ---- 4/5 push + pull (re-push when the kernel stopped early, max 3 sessions, as auto_k.sh)
for k in 1 2 3; do
  stopped
  bash $PF/push_v2.sh; rc=$?; st 4 "push #$k rc=$rc (0 pushed | 20 quota | 21 push | 22 upload | 23 check)"
  [ $rc = 0 ] || fail 4 "push rc=$rc: $(tail -n 2 $PF/STATUS.md | cut -c1-200 | tr '\n' ' ')"
  bash $PF/pull_v2.sh; rc=$?; st 5 "pull #$k rc=$rc: $(tail -n 1 $PF/STATUS.md | cut -c1-200)"
  python3 -c "import json,sys,os;d=json.load(open(os.path.expanduser('$K2/run/status.json')));sys.exit(0 if d.get('stopped') or d.get('step',0)>=d.get('n_steps',1) else 1)" && break
done
st 5 "training finished; snapshots: $(ls $K2/run | grep snap_ | tr '\n' ' ')"
fi
# ---- 6 wait for the reasoner fine-tune (NOT touched) and the GPU
FT=$HOME/smartcity_runs/rsn3_4b_v3ft/status.json; n=0
ft_done() { python3 -c "import json,sys;sys.exit(0 if json.load(open('$FT')).get('done') else 1)" 2>/dev/null; }
until ft_done; do stopped; [ $((n % 12)) = 0 ] && st 6 "waiting for the reasoner fine-tune to finish: $(cut -c1-80 $FT 2>/dev/null)"; n=$((n+1)); sleep 300; done
st 6 "reasoner fine-tune done; selection waits for the GPU lock/free GPU and C: space itself"
# ---- 7 selection (export on CPU, host eval on the GPU, no-harm vs s0300, tool slice)
stopped
bash $PF/select_v2.sh; rc=$?
st 7 "selection rc=$rc: $(tail -n 1 $K2/post/pick.log 2>/dev/null | cut -c1-200)"
if [ $rc = 0 ]; then st 8 "WINNER ready (NOT deployed): $(tr '\n' ' ' < $K2/FINAL_K2 | cut -c1-300)"; else st 8 "no winner / failed (rc $rc): s0300 stays on the board"; fi
