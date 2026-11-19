#!/usr/bin/env bash
# to_kaggle.sh [--fresh]: hand the baton laptop -> Kaggle (BATON.md). Order: token + quota check (laptop untouched if Kaggle
# cannot run), r3 data md5 verify + stage, clean laptop stop (ctl_4b.sh stop), lineage pack (md5 manifest), secret scan,
# private dataset versions (data only when its md5s changed; baton every time), kernel push, BATON -> holder=kaggle.
# --fresh: no laptop checkpoint yet -> the lineage starts on Kaggle at step 0.
# exit: 0 pushed | 10 no token / CLI | 11 wrong holder / no checkpoint | 12 laptop still running | 20 quota | 21 push error
#       22 upload error | 23 data / lineage verification failed
source "$(dirname "$(readlink -f "$0")")/lib.sh"
FRESH=0; [ "${1:-}" = --fresh ] && FRESH=1
token_ok || { status "waiting for token: no ~/.kaggle/access_token or kaggle.json (chmod 600) (owner step, BATON.md); nothing uploaded"; exit 10; }
[ -x "$KAGGLE" ] || die "kaggle CLI missing at $KAGGLE (BATON.md: python3 -m venv ~/venvs/kaggle && ~/venvs/kaggle/bin/pip install kaggle)" 10
U=$(kuser); [ -n "$U" ] || die "Kaggle username unknown: set KAGGLE_USER in baton/baton.conf" 10
h=$(bget holder)
[ -z "$h" ] || [ "$h" = laptop ] || die "baton holder is '$h', not laptop: run from_kaggle.sh first" 11
L=$WORK/logs; mkdir -p "$L"

# ---- 1. quota (before touching the laptop)
q=$(quota_left); left=${q%% *}; refresh=${q#* }
if [ -n "$q" ]; then
  if awk -v l="$left" -v m="$MIN_KAGGLE_H" 'BEGIN{exit !(l < m)}'; then
    echo "$refresh" > "$WORK/quota_refresh"
    status "Kaggle GPU quota left ${left} h < ${MIN_KAGGLE_H} h (refresh ${refresh:-?}): laptop keeps the baton"; exit 20
  fi
  budget=$(awk -v l="$left" -v m="$QUOTA_MARGIN_H" -v b="$BUDGET_H" 'BEGIN{x=l-m; if(x>b)x=b; printf "%.2f", x}')
else
  budget=$BUDGET_H; status "kaggle quota unreadable: session budget $budget h, push decides"
fi

# ---- 2. data: md5-verified r3 rows + tool tree (CPU only, laptop still training)
SD=$WORK/data_stage
DID=$(stage_data "$SD") || die "r3 data verification failed: nothing uploaded" 23
if [ ! -e "$WORK/data_selftest_$DID.ok" ]; then
  CUDA_VISIBLE_DEVICES= nice -n 10 "$PY" -I "$B/test/selftest_tree.py" "$QIDK" "$SD/tree" > "$L/data_selftest.log" 2>&1 \
    || die "gen-eval tool tree incomplete in the data stage: $(tail -n 2 "$L/data_selftest.log" | tr '\n' ' ')" 23
  touch "$WORK/data_selftest_$DID.ok"
fi

# ---- 3. clean laptop stop
if laptop_running; then status "handover: stopping the laptop run (ctl_4b.sh stop)"; bash "$CTL" stop; fi
for i in $(seq 1 30); do laptop_running || break; sleep 60; done
laptop_running && die "laptop trainer still running after ctl_4b.sh stop: no handover" 12

# ---- 4. lineage
seq=$(( $(bget seq || true) + 0 + 1 ))
S=$WORK/out/seq$seq; UP=$S/upload; rm -rf "$S"; mkdir -p "$UP"
[ -s "$H/run.env" ] && { set -a; . "$H/run.env"; set +a; }
ML=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['max_len'])" "$R/maxlen.json" 2>/dev/null || echo "${MAX_LEN:-6144}")
util recipe "${FIT_FLAGS:-} ${GEN_FLAGS:-}" "$ML" > "$S/recipe.json" || die "recipe: $(cat "$S/recipe.json")" 23
if [ -s "$R/ckpt_latest/state.pt" ]; then
  step=$(run_step "$R")
  util cursor "$R" $CURSOR_DATA > "$L/cursor_seq$seq.json" || die "data cursor check failed: $(cat "$L/cursor_seq$seq.json")" 23
  if ls "$R"/*_tok.pt > /dev/null 2>&1; then
    if [ -s "$R/tokfp.json" ]; then util tokfp-check "$R" "$R/tokfp.json" > "$L/tokfp_seq$seq.json" || die "laptop token caches differ from the lineage's tokfp.json" 23
    else util tokfp "$R" > "$R/tokfp.json.part" && mv "$R/tokfp.json.part" "$R/tokfp.json"; fi
  fi
  cp "$S/recipe.json" "$R/recipe.json"
  echo "{\"side\": \"laptop\", \"seq\": $seq, \"step_to\": $step, \"t\": $(date +%s)}" >> "$R/BATON_HISTORY.jsonl"
  pack_lineage "$R" "$S" || die "lineage pack failed" 23
  ln "$S/lineage.tar" "$UP/lineage.tar"
  tmd5=$(cut -c1-32 "$S/lineage.tar.md5"); smd5=$(md5sum < "$R/ckpt_latest/state.pt" | cut -c1-32); fresh=false
else
  [ $FRESH = 1 ] || die "no checkpoint in $R (start the laptop run first, or --fresh to start the lineage on Kaggle)" 11
  step=0; tmd5=""; smd5=""; fresh=true
fi
cp "$TRAINER" "$UTIL" "$UP/"
ls "$WORK"/wheels/*__causal_conv1d-1.5.2*.whl > /dev/null 2>&1 && cp "$WORK"/wheels/*__causal_conv1d-1.5.2*.whl "$UP/"   # tagged by torch/python
[ -s "$WORK/kcache/triton_cache.tar" ] && ln "$WORK/kcache/triton_cache.tar" "$UP/triton_cache.tar"                   # Kaggle's own Triton cache
nonce=$(od -An -N8 -tx1 /dev/urandom | tr -dc '0-9a-f')    # unique per upload: a re-upload of the same seq (after a failed push) is told apart
KAGGLE_PIN_TORCH=$KAGGLE_PIN_TORCH SP_RANK_BALANCE=$SP_RANK_BALANCE LEVER_MIN_TOKENS=$LEVER_MIN_TOKENS python3 - "$UP/baton_cfg.json" "$seq" "$step" "$fresh" "$budget" "$DID" "$(md5sum < "$TRAINER" | cut -c1-32)" "$tmd5" "$S/recipe.json" "$nonce" <<'EOF'
import json, os, sys, time
o, seq, step, fresh, budget, did, tm, lm, rp, nonce = sys.argv[1:]
json.dump({"seq": int(seq), "step": int(step), "fresh": fresh == "true", "budget_h": float(budget), "data_id": did, "trainer_md5": tm,
           "lineage_tar_md5": lm, "recipe": json.load(open(rp)), "nonce": nonce, "pin_torch": os.environ.get("KAGGLE_PIN_TORCH") == "1",
           "sp_rank_balance": os.environ.get("SP_RANK_BALANCE", "1") == "1", "lever_min_tokens": int(os.environ.get("LEVER_MIN_TOKENS", "4096")),
           "made": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, open(o, "w"), indent=1)
EOF
printf '{"title": "%s", "id": "%s/%s", "licenses": [{"name": "other"}]}\n' "$BATON_SLUG" "$U" "$BATON_SLUG" > "$UP/dataset-metadata.json"

# ---- 5. secret scan of everything that leaves the laptop
DU=$WORK/data_upload; rm -rf "$DU"; mkdir -p "$DU"
tar -cf "$DU/r3_data.tar" -C "$SD" tree && cp "$SD/tree/R3_DATA_OK" "$DU/"
printf '{"title": "%s", "id": "%s/%s", "licenses": [{"name": "other"}]}\n' "$DATA_SLUG" "$U" "$DATA_SLUG" > "$DU/dataset-metadata.json"
m=$(secret_scan "$SD/tree") || die "data stage: $m" 23
m=$(secret_scan "$UP" ${tmd5:+"$UP/lineage.tar"}) || die "baton upload: $m" 23

# ---- 6. private datasets: create once, then new versions; wait until Kaggle has processed them
kds() {  # kds DIR SLUG MSG
  local out
  if "$KAGGLE" datasets status "$U/$2" > /dev/null 2>&1; then
    out=$("$KAGGLE" datasets version -p "$1" -m "$3" -t -r skip -q 2>&1)
  else
    out=$("$KAGGLE" datasets create -p "$1" -t -r skip -q 2>&1)          # private by default (no -u)
  fi
  echo "$out" >> "$L/upload.log"
  echo "$out" | grep -Eqi 'error|denied|forbidden|exception|failed' && { echo "$out" | tail -n 3; return 1; }
  for i in $(seq 1 120); do
    case "$("$KAGGLE" datasets status "$U/$2" 2>&1 | tr A-Z a-z)" in *ready*) return 0;; esac   # an error right after create/version = not indexed yet: keep polling (2026-11-07 fix)
    sleep 30
  done
  return 1
}
if [ "$(cat "$WORK/data_uploaded" 2>/dev/null)" != "$DID" ]; then
  status "uploading r3 data dataset $DATA_SLUG (private, data id $DID, $(du -m "$DU/r3_data.tar" | cut -f1) MB)"
  kds "$DU" "$DATA_SLUG" "r3 data $DID" || die "data dataset upload failed (see $L/upload.log)" 22
  echo "$DID" > "$WORK/data_uploaded"
fi
# token caches (once; again only when they change): Kaggle uses them only if they match the lineage's tokfp.json
CS=""
if [ "$CACHE_TOK" = 1 ] && [ -s "$R/tokfp.json" ] && ls "$R"/*_seg_tok.pt > /dev/null 2>&1; then
  key=$(stat -L -c '%n %s %Y' "$R"/*_seg_tok.pt | md5sum | cut -c1-32)
  if [ "$(cat "$WORK/tokcache_uploaded" 2>/dev/null)" != "$key" ]; then
    CU=$WORK/tokcache_upload; rm -rf "$CU"; mkdir -p "$CU"
    for f in "$R"/*_seg_tok.pt; do ln -L "$f" "$CU/$(basename "$f")" 2>/dev/null || cp -L "$f" "$CU/"; done
    (cd "$CU" && md5sum *_seg_tok.pt > TOKCACHE_OK)
    printf '{"title": "%s", "id": "%s/%s", "licenses": [{"name": "other"}]}\n' "$CACHE_SLUG" "$U" "$CACHE_SLUG" > "$CU/dataset-metadata.json"
    m=$(secret_scan "$CU") || die "token cache upload: $m" 23
    status "uploading token caches to $CACHE_SLUG (private, $(du -mL "$CU" | tail -1 | cut -f1) MB; once)"
    if kds "$CU" "$CACHE_SLUG" "token caches $key"; then echo "$key" > "$WORK/tokcache_uploaded"; else status "token cache upload failed: Kaggle tokenizes itself (~16 min)"; fi
    rm -rf "$CU"
  fi
fi
[ -s "$WORK/tokcache_uploaded" ] && CS=", \"$U/$CACHE_SLUG\""
status "uploading baton seq $seq (step $step, $(du -m "$UP" | tail -1 | cut -f1) MB) to $BATON_SLUG"
kds "$UP" "$BATON_SLUG" "baton seq $seq step $step" || die "baton dataset upload failed (see $L/upload.log)" 22
# 'ready' is already true for the PREVIOUS version (seq 2 aborted as stale on 2026-11-07): push only once the live version's
# baton_cfg.json carries this seq (download just that file; poll up to LIVE_TRIES x LIVE_POLL_S, default 60 x 30 s)
live_seq() {
  local d=$WORK/live f; rm -rf "$d"; mkdir -p "$d"
  "$KAGGLE" datasets download "$U/$BATON_SLUG" -f baton_cfg.json -p "$d" -o -q > /dev/null 2>&1 || return 0
  f=$(ls "$d"/baton_cfg.json* 2>/dev/null | head -1); [ -n "$f" ] || return 0
  python3 -c "import json,sys,zipfile;p=sys.argv[1];d=json.loads(zipfile.ZipFile(p).read('baton_cfg.json')) if p.endswith('.zip') else json.load(open(p));print('%s:%s' % (d['seq'], d.get('nonce')))" "$f" 2>/dev/null
}
for i in $(seq 1 "${LIVE_TRIES:-60}"); do lv=$(live_seq); [ "$lv" = "$seq:$nonce" ] && break; sleep "${LIVE_POLL_S:-30}"; done
[ "$lv" = "$seq:$nonce" ] || die "baton dataset: live version is '${lv:-?}', not $seq:$nonce, after $((${LIVE_TRIES:-60} * ${LIVE_POLL_S:-30})) s: not pushing (laptop keeps the baton)" 22
status "baton dataset seq $seq is live (checked $i x)"

# ---- 7. kernel push (private script, GPU T4 x2, Internet on)
KD=$WORK/kernel; rm -rf "$KD"; mkdir -p "$KD"
sed "s/@@SEQ@@/$seq/; s/@@NONCE@@/$nonce/" "$B/kaggle/rsn3_r3_baton.py" > "$KD/rsn3_r3_baton.py"
cat > "$KD/kernel-metadata.json" <<EOF
{"id": "$U/$KERNEL_SLUG", "title": "$KERNEL_SLUG", "code_file": "rsn3_r3_baton.py", "language": "python", "kernel_type": "script",
 "is_private": true, "enable_gpu": true, "enable_tpu": false, "enable_internet": true, "machine_shape": "$ACCEL",
 "dataset_sources": ["$U/$DATA_SLUG", "$U/$BATON_SLUG"$CS], "competition_sources": [], "kernel_sources": [], "model_sources": []}
EOF
tsec=$(awk -v b="$budget" 'BEGIN{x=int((b+0.5)*3600); if(x>43200)x=43200; print x}')
out=$("$KAGGLE" kernels push -p "$KD" --accelerator "$ACCEL" -t "$tsec" 2>&1); echo "$(date -Is) seq $seq: $out" >> "$L/push.log"
if echo "$out" | grep -q 'successfully pushed'; then
  v=$(echo "$out" | sed -n 's/.*Kernel version \([0-9]*\) successfully.*/\1/p')
  bset holder=kaggle step="$step" seq="$seq" md5="$smd5" kernel_version="${v:-?}" budget_h="$budget" note="pushed seq $seq"
  echo "seq $seq step $step $(date -Is)" > "$R/BATON_AT_KAGGLE" 2>/dev/null
  status "baton -> Kaggle: seq $seq, step $step, kernel version ${v:-?}, budget $budget h; laptop GPU free"
  exit 0
fi
if echo "$out" | is_quota_msg; then status "push refused (quota): $(echo "$out" | tail -n 1 | cut -c1-200); laptop keeps the baton"; exit 20; fi
status "push failed: $(echo "$out" | tail -n 2 | tr '\n' ' ' | cut -c1-240); laptop keeps the baton"; exit 21
