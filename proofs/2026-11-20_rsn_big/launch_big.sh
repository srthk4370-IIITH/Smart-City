#!/usr/bin/env bash
# launch_big.sh <check|stage|push|pull|auto|status|cleanup --yes>: Kaggle launcher of the reasoner big top-up (2 sessions, resume via lineage).
#   check   : prerequisites (data CHECK.md PASS, tokens plan, token file chmod 600 (never read), quota, C: >= 20 GB, base dataset ready) -> exit 0 only when all hold
#   stage   : build the upload dirs (data tar .bin, run dir) in ~/smartcity_runs/rsn_big_k/stage + secret scan
#   push    : upload private datasets rsn-big-data (once, when data changed), rsn-big-run (cfg + lineage of the previous session), push kernel rsn-big-train
#   pull    : poll the kernel until it ends, download the output, check md5, install the lineage into ~/smartcity_runs/rsn_big_k/run; prints DONE or NEXT
#   auto    : push -> pull -> (not done and quota) push -> pull ... until the plan is done (detached; poll every 10 min)
#   cleanup : delete the private datasets + kernel from Kaggle (owner rule: delete after the run; needs --yes; asks nothing else)
# Private datasets only (owner exception 2026-11-20, logged in proofs/POLISH.md). The Kaggle token is never read here: the CLI reads it.
QIDK=/mnt/c/Users/hp/Desktop/qidk; BIG=$QIDK/proofs/2026-11-20_rsn_big; D=$BIG/data/final_big
K=${KAGGLE:-$HOME/venvs/kaggle/bin/kaggle}; KDIR=$HOME/.kaggle; PY=$HOME/venvs/rsn/bin/python
W=$HOME/smartcity_runs/rsn_big_k; RUNL=$W/run; STAGE=$W/stage; mkdir -p $W $RUNL
STATUS=$BIG/STATUS.md; REG=$QIDK/proofs/AGENT_REGISTRY.md; STATE=$W/STATE
DATA_SLUG=rsn-big-data; RUN_SLUG=rsn-big-run; BASE_SLUG=rsn-big-base; KERNEL_SLUG=rsn-big-train; R3_SLUG=rsn3-r3-data
BUDGET_H=${BUDGET_H:-11.3}; MIN_H=${MIN_H:-2.0}; MARGIN_H=${MARGIN_H:-0.3}; POLL_S=${POLL_S:-600}
status() { local l="- $(date '+%F %T') [launch_big] $*"; echo "$l" >> $STATUS; echo "$l"; }
die() { status "FAIL: $1"; exit "${2:-1}"; }
reg() { echo "- rsn-big: $* ($(date '+%F %H:%M'))" >> $REG; }
sget() { [ -f $STATE ] && sed -n "s/^$1=//p" $STATE | tail -1; }
sset() { local kv; touch $STATE; for kv in "$@"; do sed -i "/^${kv%%=*}=/d" $STATE; echo "$kv" >> $STATE; done; }
U=$($K config view 2>/dev/null | sed -n 's/^- username: *//p' | head -1)
free_c() { df -Pm /mnt/c | awk 'NR==2{print $4}'; }
ready() { $K datasets status $U/$1 2>&1 | tr A-Z a-z | grep -q ready; }
quota() { $K quota -v 2>&1 | awk -F, '$1=="GPU"{gsub(/h/,"",$3); print $3}' | head -1; }
kds() {  # kds DIR SLUG MSG : private dataset create/version, wait for ready
  local out i
  if $K datasets status $U/$2 > /dev/null 2>&1; then out=$($K datasets version -p "$1" -m "$3" -t -r zip -q 2>&1); else out=$($K datasets create -p "$1" -t -r zip -q 2>&1); fi
  echo "$(date -Is) $2: $out" >> $W/upload.log
  echo "$out" | grep -Eqi 'error|denied|forbidden|exception|failed' && { echo "$out" | tail -n 3; return 1; }
  for i in $(seq 1 120); do ready $2 && return 0; sleep 30; done; return 1
}
meta() { printf '{"title": "%s", "id": "%s/%s", "licenses": [{"name": "other"}]}\n' "$2" "$U" "$2" > "$1/dataset-metadata.json"; }

cmd_check() {
  local bad=0 q
  grep -q "^RESULT: PASS" $D/CHECK.md 2>/dev/null || { echo "data audit not PASS ($D/CHECK.md)"; bad=1; }
  [ -s $D/PLAN.json ] || { echo "no PLAN.json (plan_big.py)"; bad=1; }
  [ -s $D/MANIFEST.json ] && grep -q '"D:' $D/MANIFEST.json || { echo "MANIFEST has no block D (agent rows not built in)"; bad=1; }
  [ -s $KDIR/access_token ] && [ "$(stat -c %a $KDIR/access_token)" = 600 ] || { echo "token file missing or not chmod 600"; bad=1; }
  [ "$(free_c)" -ge 20000 ] || { echo "C: free $(free_c) MB < 20000"; bad=1; }
  ready $BASE_SLUG || { echo "$BASE_SLUG not ready (kaggle_upload_base.sh)"; bad=1; }
  ready $R3_SLUG || { echo "$R3_SLUG (r3 tool tree) not ready"; bad=1; }
  q=$(quota); [ -n "$q" ] && awk -v l="$q" -v m=$MIN_H 'BEGIN{exit !(l >= m)}' || { echo "GPU quota left '${q:-?}' h < $MIN_H"; bad=1; }
  echo "quota left ${q:-?} h"; return $bad
}

cmd_stage() {
  local T=$STAGE/tree; rm -rf $STAGE; mkdir -p $T/trainer $T/data $T/p2 $STAGE/data_up $STAGE/run_up
  cp $QIDK/proofs/2026-10-29_rsn_v3/kaggle/train_rsn3.py $QIDK/proofs/2026-11-13_v3_train/rsn_ft/rsn_ft_train.py $T/trainer/
  cp $D/train_new.jsonl $D/replay.jsonl $D/tools_v4.json $D/tests/dev_hole_inc.jsonl $T/data/
  cp $QIDK/proofs/2026-11-12_topup_r4/data/final/dev_gen_chat.jsonl $T/data/
  P2=$HOME/smartcity_runs/rsn3_4b_v3ft_p2/ckpt_best_0220; cp $P2/adapter_model.safetensors $P2/adapter_config.json $T/p2/
  (cd $T && find . -type f ! -name BIG_DATA_OK | sed 's|^\./||' | sort | xargs -d '\n' md5sum) > $T/BIG_DATA_OK
  tar -cf $STAGE/data_up/big_data.bin -C $T . && cp $T/BIG_DATA_OK $STAGE/data_up/
  meta $STAGE/data_up $DATA_SLUG
  echo "$(md5sum < $T/BIG_DATA_OK | cut -c1-32)" > $STAGE/data_id
  local hit; hit=$(grep -rIlE "(api[_-]?key|secret|password|Bearer )" $T/trainer $T/p2 2>/dev/null | head -3)
  [ -z "$hit" ] || die "secret-like text in $hit"
  [ ! -s $D/work/D.jsonl ] || true
  status "stage ok: data id $(cat $STAGE/data_id), big_data.bin $(du -m $STAGE/data_up/big_data.bin | cut -f1) MB"
}

cmd_push() {
  cmd_check || die "check failed: nothing pushed" 10
  [ -d $STAGE/tree ] || cmd_stage
  local seq step budget nonce q left DID
  seq=$(( $(sget seq || echo 0) + 1 )); step=$(sget step || echo 0); step=${step:-0}
  q=$(quota); budget=$(awk -v l="$q" -v m=$MARGIN_H -v b=$BUDGET_H 'BEGIN{x=l-m; if(x>b)x=b; printf "%.2f", x}')
  [ "$seq" -gt 1 ] && [ -z "$(sget lineage_ok)" ] && die "pull the previous session first" 11
  DID=$(cat $STAGE/data_id)
  if [ "$(sget data_uploaded)" != "$DID" ]; then
    status "uploading $DATA_SLUG (private, id $DID, $(du -m $STAGE/data_up/big_data.bin | cut -f1) MB)"
    kds $STAGE/data_up $DATA_SLUG "big data $DID" || die "data upload failed ($W/upload.log)" 22
    sset data_uploaded=$DID
  fi
  nonce=$(od -An -N8 -tx1 /dev/urandom | tr -dc '0-9a-f'); rm -rf $STAGE/run_up; mkdir -p $STAGE/run_up
  [ "$seq" -gt 1 ] && cp $RUNL/lineage.bin $RUNL/lineage.bin.md5 $STAGE/run_up/ 2>/dev/null
  [ -d $W/wheels ] && cp $W/wheels/*.whl $STAGE/run_up/ 2>/dev/null
  $PY - $STAGE/run_up/big_cfg.json $seq $step $budget $DID $nonce <<PYEOF
import json, sys, hashlib
o, seq, step, budget, did, nonce = sys.argv[1:]
md = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
plan = json.load(open("$D/PLAN.json"))
json.dump({"seq": int(seq), "step": int(step), "budget_h": float(budget), "data_id": did, "nonce": nonce, "flags": plan["flags"],
           "train_rsn3_md5": md("$QIDK/proofs/2026-10-29_rsn_v3/kaggle/train_rsn3.py"), "rsn_ft_md5": md("$QIDK/proofs/2026-11-13_v3_train/rsn_ft/rsn_ft_train.py")}, open(o, "w"), indent=1)
PYEOF
  meta $STAGE/run_up $RUN_SLUG
  status "uploading $RUN_SLUG seq $seq (step $step, budget $budget h)"
  kds $STAGE/run_up $RUN_SLUG "seq $seq step $step" || die "run dataset upload failed" 22
  for i in $(seq 1 60); do
    $K datasets download $U/$RUN_SLUG -f big_cfg.json -p $W/live -o -q > /dev/null 2>&1
    f=$(ls $W/live/big_cfg.json* 2>/dev/null | head -1)
    [ -n "$f" ] && python3 -c "import json,sys,zipfile;p=sys.argv[1];d=json.loads(zipfile.ZipFile(p).read('big_cfg.json')) if p.endswith('.zip') else json.load(open(p));sys.exit(0 if (d['seq'],d['nonce'])==(int(sys.argv[2]),sys.argv[3]) else 1)" "$f" $seq $nonce && break
    rm -rf $W/live; sleep 30
  done
  rm -rf $W/live
  local KD=$STAGE/kernel; rm -rf $KD; mkdir -p $KD
  sed "s/@@SEQ@@/$seq/; s/@@NONCE@@/$nonce/" $BIG/kernel_big.py > $KD/kernel_big.py
  cat > $KD/kernel-metadata.json <<EOF
{"id": "$U/$KERNEL_SLUG", "title": "$KERNEL_SLUG", "code_file": "kernel_big.py", "language": "python", "kernel_type": "script", "is_private": true,
 "enable_gpu": true, "enable_tpu": false, "enable_internet": true, "machine_shape": "NvidiaTeslaT4",
 "dataset_sources": ["$U/$DATA_SLUG", "$U/$RUN_SLUG", "$U/$BASE_SLUG", "$U/$R3_SLUG"], "competition_sources": [], "kernel_sources": [], "model_sources": []}
EOF
  local tsec out v; tsec=$(awk -v b=$budget 'BEGIN{x=int((b+0.5)*3600); if(x>43200)x=43200; print x}')
  out=$($K kernels push -p $KD --accelerator NvidiaTeslaT4 -t $tsec 2>&1); echo "$(date -Is) seq $seq: $out" >> $W/push.log
  echo "$out" | grep -q 'successfully pushed' || die "kernel push failed: $(echo "$out" | tail -n 2 | tr '\n' ' ' | cut -c1-200)" 21
  v=$(echo "$out" | sed -n 's/.*Kernel version \([0-9]*\) successfully.*/\1/p')
  sset seq=$seq pushed_at=$(date +%s) kernel_version="${v:-?}" holder=kaggle budget_h=$budget
  status "-> Kaggle: seq $seq, step $step, kernel v${v:-?}, budget $budget h (quota left $q h)"; reg "Kaggle session $seq pushed (kernel $U/$KERNEL_SLUG v${v:-?}, budget $budget h)"
}

cmd_pull() {
  local seq=$(sget seq) out st DL fail
  while true; do
    out=$($K kernels status $U/$KERNEL_SLUG 2>&1); st=$(echo "$out" | sed -n 's/.*has status "\([^"]*\)".*/\1/p' | tr A-Z a-z)
    case "$st" in *complete*|*error*|*cancel*) break;; esac
    [ "${1:-}" = --once ] && { echo "running ($st)"; return 30; }
    sleep $POLL_S
  done
  fail=$(echo "$out" | sed -n 's/^Failure message: //p'); status "kernel seq $seq ended: $st${fail:+ ($fail)}"
  DL=$W/dl/seq$seq; rm -rf $DL; mkdir -p $DL
  $K kernels output $U/$KERNEL_SLUG -p $DL -o > $W/output_seq$seq.log 2>&1 || die "output download failed" 35
  cp $DL/*.log $BIG/logs/ 2>/dev/null
  ab=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('abort',''))" $DL/KAGGLE_RESULT.json 2>/dev/null)
  [ -z "$ab" ] || die "session $seq aborted on Kaggle: $ab" 34
  [ -f $DL/lineage.bin ] && (cd $DL && md5sum -c --quiet lineage.bin.md5) || die "lineage.bin missing or md5 mismatch" 32
  mkdir -p $RUNL; cp $DL/lineage.bin $DL/lineage.bin.md5 $RUNL/
  mkdir -p $RUNL/x && tar -xf $RUNL/lineage.bin -C $RUNL/x && (cd $RUNL/x && md5sum -c --quiet MD5SUMS) || die "lineage content md5 mismatch" 32
  cp -r $DL/best $BIG/ 2>/dev/null
  local step done; step=$(python3 -c "import json;print(json.load(open('$RUNL/x/status.json')).get('step',0))"); done=$(python3 -c "import json;d=json.load(open('$RUNL/x/status.json'));print(int(bool(d.get('done'))))")
  rm -rf $RUNL/x; sset step=$step lineage_ok=1 holder=laptop done=$done
  status "<- Kaggle: seq $seq pulled, step $step, done=$done (best adapters in $BIG/best, gate: gate/gate_big.sh <ckpt_best_NNNN>)"; reg "Kaggle session $seq pulled: step $step done=$done"
  [ "$done" = 1 ] && { echo DONE; return 0; }
  echo NEXT; return 0
}

cmd_auto() {
  while true; do
    [ "$(sget holder)" = kaggle ] || { cmd_push || return $?; }
    cmd_pull > /dev/null || return $?
    [ "$(sget done)" = 1 ] && { status "plan done"; return 0; }
    q=$(quota); awk -v l="$q" -v m=$MIN_H 'BEGIN{exit !(l >= m)}' || { status "quota left $q h < $MIN_H: waiting 1 h for the refresh"; sleep 3600; }
  done
}

cmd_cleanup() {
  [ "${1:-}" = --yes ] || die "cleanup needs --yes (deletes the private datasets + kernel)" 2
  for s in $DATA_SLUG $RUN_SLUG $BASE_SLUG; do $K datasets delete $U/$s -y 2>&1 | tail -n 1; done
  $K kernels delete $U/$KERNEL_SLUG -y 2>&1 | tail -n 1
  status "cleanup: private datasets rsn-big-* and kernel deleted from Kaggle"; reg "Kaggle rsn-big datasets + kernel deleted (owner rule)"
}

case "${1:-}" in
  check) cmd_check;; stage) cmd_stage;; push) cmd_push;; pull) shift; cmd_pull "$@";; auto) cmd_auto;; cleanup) shift; cmd_cleanup "$@";;
  status) cat $STATE 2>/dev/null; tail -n 5 $STATUS;;
  *) sed -n 2,11p "$0"; exit 2;;
esac
