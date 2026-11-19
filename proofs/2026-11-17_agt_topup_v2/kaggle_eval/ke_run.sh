#!/usr/bin/env bash
# ke_run.sh ROUND TAG=ADAPTERDIR [TAG=ADAPTERDIR ...]   one Kaggle eval round: pack -> private run dataset -> private kernel agt3-topup2-eval -> poll -> pull
# Results: $PF/data/kaggle_eval[_rN]/<tag>/{val,hard,t1,t2}.jsonl. Real VAL rows go ONLY into the existing private dataset agt3-topup2-run (owner exception,
# logged in REAL_EXCEPTION.log + AGENT_REGISTRY.md). Never reads the Kaggle token. exit 0 ok | 1 failure
KE=$(dirname "$(readlink -f "$0")"); PF=$(dirname "$KE")
export AGT_CONF=${AGT_CONF:-$PF/agt_topup2.conf}
source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt/lib.sh
ROUND=$1; shift
OUTD=$PF/data/kaggle_eval${ROUND:+_$ROUND}; [ "$ROUND" = r1 ] && OUTD=$PF/data/kaggle_eval
EV_SLUG=${EV_SLUG:-agt3-topup2-eval}; BUDGET_MIN=${EVAL_BUDGET_MIN:-45}
token_ok || die "no kaggle token" 10
U=$(kuser); K="$U/$EV_SLUG"
PACK=$WORK/eval_pack_$ROUND; nonce=${REUSE_NONCE:-$(od -An -N8 -tx1 /dev/urandom | tr -dc "0-9a-f")}
[ -n "${REUSE_NONCE:-}" ] || python3 "$KE/ke_pack.py" "$PACK" "$nonce" "$BUDGET_MIN" "$@" > "$WORK/ke_pack_$ROUND.log" 2>&1 || die "ke_pack: $(tail -n 2 $WORK/ke_pack_$ROUND.log | tr '\n' ' ')" 1
m=$(secret_scan "$PACK") || die "eval pack: $m" 1
echo "- $(date -u +%FT%H:%MZ) [kaggle_eval $ROUND] OWNER EXCEPTION USED (as v1/v2): eval sets with REAL val rows go into the existing PRIVATE dataset $RUN_SLUG ($(cat $PACK/eval_cfg.json | tr -d '\n ' | cut -c1-120))" | tee -a "$PF/REAL_EXCEPTION.log" >> /mnt/c/Users/hp/Desktop/qidk/proofs/AGENT_REGISTRY.md
dsmeta "$PACK" "$RUN_SLUG"
status "STAGE K ($ROUND): uploading eval pack to private $RUN_SLUG ($(du -m -s $PACK | cut -f1) MB, nonce $nonce)"
[ -n "${REUSE_NONCE:-}" ] || "$KAGGLE" datasets version -p "$PACK" -m "eval $ROUND $nonce" -t -r zip -q > /dev/null 2>&1 || die "eval pack upload failed (dir-mode zip: sets/ and adapters/ were skipped with -r skip)" 1
live() { local d=$WORK/live_e f; rm -rf "$d"; mkdir -p "$d"
  "$KAGGLE" datasets download "$U/$RUN_SLUG" -f eval_cfg.json -p "$d" -o -q > /dev/null 2>&1 || return 0
  f=$(ls "$d"/eval_cfg.json* 2>/dev/null | head -1); [ -n "$f" ] || return 0
  python3 -c "import json,sys,zipfile;p=sys.argv[1];d=json.loads(zipfile.ZipFile(p).read('eval_cfg.json')) if p.endswith('.zip') else json.load(open(p));print(d['nonce'])" "$f" 2>/dev/null; }
for i in $(seq 1 60); do [ "$(live)" = "$nonce" ] && break; sleep 30; done
[ "$(live)" = "$nonce" ] || die "eval dataset live version is not $nonce" 1
KD=$WORK/kernel_eval; rm -rf "$KD"; mkdir -p "$KD"
sed "s/@@NONCE@@/$nonce/" "$KE/eval_kernel.py" > "$KD/eval_kernel.py"
cat > "$KD/kernel-metadata.json" <<EOF
{"id": "$K", "title": "$EV_SLUG", "code_file": "eval_kernel.py", "language": "python", "kernel_type": "script",
 "is_private": true, "enable_gpu": true, "enable_tpu": false, "enable_internet": true, "machine_shape": "$ACCEL",
 "dataset_sources": ["$U/$RUN_SLUG"], "competition_sources": [], "kernel_sources": [], "model_sources": []}
EOF
out=$("$KAGGLE" kernels push -p "$KD" --accelerator "$ACCEL" -t 10800 2>&1); echo "$(date -Is) eval $ROUND: $out" >> "$WORK/push.log"
echo "$out" | grep -q 'successfully pushed' || die "eval kernel push failed: $(echo "$out" | tail -n 1 | cut -c1-200)" 1
status "STAGE K ($ROUND): eval kernel $K pushed (private, T4x2, budget ${BUDGET_MIN} min of eval after ~8 min setup)"
t0=$(date +%s)
while true; do
  o=$("$KAGGLE" kernels status "$K" 2>&1); st=$(echo "$o" | sed -n 's/.*has status "\([^"]*\)".*/\1/p' | tr A-Z a-z)
  case "$st" in *complete*|*error*|*cancel*) break;; esac
  [ -e "$STOPF" ] && exit 1
  [ $(( $(date +%s) - t0 )) -gt 14400 ] && die "eval kernel timeout 4 h" 1
  sleep 120
done
status "STAGE K ($ROUND): eval kernel ended: $st"
DL=$WORK/dl_eval_$ROUND; rm -rf "$DL"; mkdir -p "$DL"
"$KAGGLE" kernels output "$K" -p "$DL" -o > "$WORK/eval_output_$ROUND.log" 2>&1 || die "eval output download failed" 1
[ -s "$DL/EVAL_RESULT.json" ] || die "no EVAL_RESULT.json ($st): $(tail -n 3 $DL/worker0.log 2>/dev/null | tr '\n' ' ' | cut -c1-300)" 1
mkdir -p "$OUTD"; cp -r "$DL"/eval_out/* "$OUTD"/ 2>/dev/null; cp "$DL"/*.log "$DL/EVAL_RESULT.json" "$OUTD"/ 2>/dev/null
status "STAGE K ($ROUND): eval pulled to $OUTD: $(tr -d '\n ' < $DL/EVAL_RESULT.json | cut -c1-250)"
exit 0
