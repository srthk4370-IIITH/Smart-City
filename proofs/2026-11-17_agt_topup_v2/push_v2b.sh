#!/usr/bin/env bash
# push_v2.sh: push.sh of agt_v3 for the automated TOP-UP v2 (proofs/2026-11-17_agt_topup_v2). Differences, all of them:
#  1. AGT_CONF = agt_topup2.conf (separate slugs agt3-topup2-data / agt3-topup2-run / kernel agt3-topup2-train, separate run area
#     ~/smartcity_runs/agt_topup_k2, separate STATE): the original agt_v3 lineage, STATE and datasets are never read or written;
#  2. data check = check_data_v2.py (explicit, logged, md5-pinned owner exception for the REAL rows of THIS dataset);
#  3. first session starts from the snap_0300 (v1 top-up winner) adapter: run/ckpt_latest = adapter only (no state.pt = fresh optimizer) + status.json
#     step 0, packed as lineage.bin; the kernel loads it like a resumed lineage at step 0 (trainer: PeftModel.from_pretrained).
# Everything else (quota, holder, token never read, secret scan, live-version check, kernel push) is the original push.sh text.
# exit: 0 pushed | 10 no token / CLI | 11 holder is not laptop | 19 cap reached | 20 quota | 21 push error | 22 upload error
#       23 data / lineage check failed
TK=$(dirname "$(readlink -f "$0")")
export AGT_CONF=$TK/agt_topup2.conf
source "${AGT_DIR:-/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt}/lib.sh"
mkdir -p "$WORK" "$PLOGS" "$R/ckpt_latest"
if [ ! -s "$R/ckpt_latest/state.pt" ] && [ ! -s "$R/ckpt_latest/adapter_model.safetensors" ]; then   # seed from snap_0300 (v1 top-up winner) (copy, original untouched)
  [ -s "$SNAP0/adapter_model.safetensors" ] || die "snap_0300 (v1 top-up winner) adapter missing at $SNAP0" 23
  cp "$SNAP0/adapter_model.safetensors" "$SNAP0/adapter_config.json" "$R/ckpt_latest/"
  echo '{"step": 0, "n_steps": 0, "seeded_from": "snap_0300 (v1 top-up winner)"}' > "$R/status.json"
fi
token_ok || die "no ~/.kaggle/access_token (chmod 600): nothing uploaded" 10
[ -x "$KAGGLE" ] || die "kaggle CLI missing at $KAGGLE" 10
U=$(kuser); [ -n "$U" ] || die "Kaggle username unknown (set KAGGLE_USER)" 10
h=$(sget holder); [ -z "$h" ] || [ "$h" = laptop ] || die "holder is '$h', not laptop: run pull.sh first" 11
used=$(sget kaggle_h); used=${used:-0}
awk -v u="$used" -v c="$TOTAL_CAP_H" -v m="$MIN_KAGGLE_H" 'BEGIN{exit !(u + m > c)}' && { status "Kaggle hours used ${used} h: cap ${TOTAL_CAP_H} h reached, no new session"; exit 19; }

# ---- 1. quota
q=$(quota_left); left=${q%% *}; refresh=${q#* }
budget=$(awk -v u="$used" -v c="$TOTAL_CAP_H" -v b="$BUDGET_H" 'BEGIN{x=c-u; if(x>b)x=b; printf "%.2f", x}')
if [ -n "$q" ]; then
  if awk -v l="$left" -v m="$MIN_KAGGLE_H" 'BEGIN{exit !(l < m)}'; then
    echo "$refresh" > "$WORK/quota_refresh"; status "Kaggle GPU quota left ${left} h < ${MIN_KAGGLE_H} h (refresh ${refresh:-?})"; exit 20
  fi
  budget=$(awk -v l="$left" -v m="$QUOTA_MARGIN_H" -v b="$budget" 'BEGIN{x=l-m; if(x>b)x=b; printf "%.2f", x}')
fi

# ---- 2. data stage (synthetic rows + aggregate calib + base tensor hashes + laptop tokenizer files)
SD=$WORK/data_stage; rm -rf "$SD"; mkdir -p "$SD/data/base"
REAL_APPROVED="$TK/b_pf/REAL_APPROVED.json" NEW_FULL="$TOPUP_K/gen/new_full.jsonl" CHECKS_OUT="$TK/data_b" "$PY" -I "$TK/check_data_v2.py" "$AGT_TRAIN" "$AGT_GENDEV" "$CALIB_STATS" 0 "$SD/data" > "$WORK/check_data.log" 2>&1 \
  || die "data check: $(tail -n 1 "$WORK/check_data.log")" 23
key=$(stat -L -c '%n %s %Y' "$BASE_LOCAL"/*.safetensors | md5sum | cut -c1-32)
if [ ! -s "$WORK/tensor_sha_$key.json" ]; then
  CUDA_VISIBLE_DEVICES= nice "$PY" -I - "$BASE_LOCAL" > "$WORK/tensor_sha_$key.json.part" <<'P' || die "base tensor hashes failed" 23
import glob, hashlib, json, sys, torch
from safetensors import safe_open
out = {}
for f in sorted(glob.glob(sys.argv[1] + "/*.safetensors")):
    with safe_open(f, "pt") as s:
        for k in s.keys():
            t = s.get_tensor(k)
            out[k] = [str(t.dtype), list(t.shape), hashlib.sha256(t.contiguous().view(-1).view(torch.uint8).numpy().tobytes()).hexdigest()]
print(json.dumps(out))
P
  mv "$WORK/tensor_sha_$key.json.part" "$WORK/tensor_sha_$key.json"
fi
cp "$WORK/tensor_sha_$key.json" "$SD/data/base/TENSOR_SHA.json"
for f in config.json generation_config.json tokenizer.json tokenizer_config.json special_tokens_map.json; do
  [ -f "$BASE_LOCAL/$f" ] && cp "$BASE_LOCAL/$f" "$SD/data/base/"; done
TMD5=$(md5sum < "$SD/data/train.jsonl" | cut -c1-32)
if [ ! -s "$WORK/tokfp_$TMD5.json" ]; then     # laptop tokenizer = Kaggle pins; also refuses rows > MAX_LEN (nothing truncated)
  CUDA_VISIBLE_DEVICES= PYTHONPATH="$A/kaggle" nice "$PY" "$TK/train_agt3b.py" --tokfp-only --base "$BASE_LOCAL" --train "$SD/data/train.jsonl" \
    --dev "$SD/data/gendev.jsonl" --out "$WORK/tokfp_tmp" --max-len "$MAX_LEN" > "$WORK/tokfp_$TMD5.json.part" 2> "$WORK/tokfp.err" \
    || die "token check: $(tail -c 300 "$WORK/tokfp_$TMD5.json.part" "$WORK/tokfp.err" | tr '\n' ' ')" 23
  mv "$WORK/tokfp_$TMD5.json.part" "$WORK/tokfp_$TMD5.json"
fi
if [ -s "$R/tokfp.json" ]; then
  python3 - "$R/tokfp.json" "$WORK/tokfp_$TMD5.json" <<'P' || die "train data / tokenizer changed under a running lineage" 23
import json, sys
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
sys.exit(0 if all(a[k] == b[k] for k in ("n", "tokens", "md5_first512")) else 1)
P
fi
(cd "$SD/data" && find . -type f ! -name DATA_OK | sed 's|^\./||' | sort | xargs -d '\n' md5sum) > "$SD/data/DATA_OK"
DID=$(md5sum < "$SD/data/DATA_OK" | cut -c1-32)
DU=$WORK/data_upload; rm -rf "$DU"; mkdir -p "$DU"
tar -cf "$DU/agt3_data.tar" -C "$SD" data && cp "$SD/data/DATA_OK" "$DU/"
m=$(secret_scan "$SD/data") || die "data stage: $m" 23

# ---- 3. lineage (ckpt_latest + bookkeeping; snapshots stay home)
seq=$(( $(sget seq || true) + 0 + 1 ))
S=$WORK/out/seq$seq; UP=$S/upload; rm -rf "$S"; mkdir -p "$UP"
step=0; fresh=true; tmd5=""
if [ -s "$R/ckpt_latest/state.pt" ] || [ -s "$R/ckpt_latest/adapter_model.safetensors" ]; then
  train_stopped && die "the run already stopped ($(python3 -c "import json;print(json.load(open('$R/status.json')).get('stopped'))")): nothing to push" 11
  step=$(run_step); fresh=false
  (cd "$R" && { find ckpt_latest -maxdepth 1 -type f | sort; for f in schedule.json recipe.json tokfp.json status.json best.json train.log \
     losses.jsonl gen_dev.jsonl HISTORY.jsonl; do [ -f "$f" ] && echo "$f"; done; }) > "$S/files.txt"
  (cd "$R" && xargs -d '\n' md5sum < "$S/files.txt") > "$S/MD5SUMS" || die "lineage md5" 23
  tar -cf "$UP/lineage.bin" -C "$R" -T "$S/files.txt" -C "$S" MD5SUMS || die "lineage tar" 23
  tmd5=$(md5sum < "$UP/lineage.bin" | cut -c1-32)   # .bin: Kaggle auto-extracts .tar in datasets (2026-11-13 seq 2-4 aborts)
fi
cp "$TK/train_agt3b.py" "$UP/train_agt3.py"; cp "$A/kaggle/rows.py" "$UP/"  # kernel runs train_agt3.py (patched b version uploaded under that name)
nonce=$(od -An -N8 -tx1 /dev/urandom | tr -dc '0-9a-f')
python3 - "$UP/agt3_cfg.json" <<P || die "cfg" 23
import json
json.dump({"seq": $seq, "nonce": "$nonce", "step": $step, "fresh": "$fresh" == "true", "budget_h": $budget, "data_id": "$DID",
  "trainer_md5": "$(md5sum < "$TK/train_agt3b.py" | cut -c1-32)", "rows_md5": "$(md5sum < "$A/kaggle/rows.py" | cut -c1-32)",
  "lineage_tar_md5": "$tmd5", "train_file": "train.jsonl", "dev_file": "gendev.jsonl", "base_hf": "$BASE_HF",
  "save_every": $SAVE_EVERY, "snap_every": $SNAP_EVERY, "gen_n": $GEN_N, "max_new": $MAX_NEW, "patience": $PATIENCE,
  "recipe": {"rank": $LORA_R, "alpha": $LORA_ALPHA, "dropout": $DROPOUT, "lr": $LR, "warmup": $WARMUP, "min_lr_ratio": $MIN_LR_RATIO,
             "rows_per_step": $ROWS_PER_STEP, "micro": $MICRO, "max_len": $MAX_LEN, "epochs": $EPOCHS, "seed": $SEED, "quant": "$QUANT",
             "train_md5": "$TMD5"}}, open("$UP/agt3_cfg.json", "w"), indent=1)
P
m=$(secret_scan "$UP" ${tmd5:+"$UP/lineage.bin"}) || die "run upload: $m" 23

# ---- 4. private datasets
if [ "$(cat "$WORK/data_uploaded" 2>/dev/null)" != "$DID" ]; then
  dsmeta "$DU" "$DATA_SLUG"; status "uploading data dataset $DATA_SLUG (private, REAL rows, id $DID, $(du -m "$DU/agt3_data.tar" | cut -f1) MB)"
  kds "$DU" "$DATA_SLUG" "agt3 data $DID" || die "data dataset upload failed (see $WORK/upload.log)" 22
  echo "$DID" > "$WORK/data_uploaded"
fi
SRCS="\"$U/$DATA_SLUG\", \"$U/$RUN_SLUG\""
if [ "$BASE_SRC" = dataset ] || [ -e "$WORK/base_src_dataset" ]; then
  if [ "$(cat "$WORK/base_uploaded" 2>/dev/null)" != "$key" ]; then
    BU=$WORK/base_upload; rm -rf "$BU"; mkdir -p "$BU"
    for f in "$BASE_LOCAL"/*.safetensors "$BASE_LOCAL"/*.json; do ln -s "$f" "$BU/"; done; echo "$key" > "$BU/BASE_OK"; dsmeta "$BU" "$BASE_SLUG"
    m=$(secret_scan "$BU") || die "base upload: $m" 23
    status "uploading base weights to $BASE_SLUG (private, once, ~6.4 GB)"
    kds "$BU" "$BASE_SLUG" "llama-3.2-3b-instruct laptop copy" || die "base dataset upload failed" 22
    echo "$key" > "$WORK/base_uploaded"
  fi
  SRCS="$SRCS, \"$U/$BASE_SLUG\""
fi
dsmeta "$UP" "$RUN_SLUG"
status "uploading run seq $seq (step $step, $(du -m "$UP" | tail -1 | cut -f1) MB) to $RUN_SLUG"
kds "$UP" "$RUN_SLUG" "agt3 seq $seq step $step" || die "run dataset upload failed" 22
live() { local d=$WORK/live f; rm -rf "$d"; mkdir -p "$d"
  "$KAGGLE" datasets download "$U/$RUN_SLUG" -f agt3_cfg.json -p "$d" -o -q > /dev/null 2>&1 || return 0
  f=$(ls "$d"/agt3_cfg.json* 2>/dev/null | head -1); [ -n "$f" ] || return 0
  python3 -c "import json,sys,zipfile;p=sys.argv[1];d=json.loads(zipfile.ZipFile(p).read('agt3_cfg.json')) if p.endswith('.zip') else json.load(open(p));print('%s:%s'%(d['seq'],d.get('nonce')))" "$f" 2>/dev/null; }
for i in $(seq 1 "${LIVE_TRIES:-60}"); do lv=$(live); [ "$lv" = "$seq:$nonce" ] && break; sleep "${LIVE_POLL_S:-30}"; done
[ "$lv" = "$seq:$nonce" ] || die "run dataset live version is '${lv:-?}', not $seq:$nonce: not pushing" 22

# ---- 5. kernel (private, GPU T4 x2, Internet on for pip + HF base)
KD=$WORK/kernel; rm -rf "$KD"; mkdir -p "$KD"
sed "s/@@SEQ@@/$seq/; s/@@NONCE@@/$nonce/" "$A/kaggle/agt3_kernel.py" > "$KD/agt3_kernel.py"
cat > "$KD/kernel-metadata.json" <<EOF
{"id": "$U/$KERNEL_SLUG", "title": "$KERNEL_SLUG", "code_file": "agt3_kernel.py", "language": "python", "kernel_type": "script",
 "is_private": true, "enable_gpu": true, "enable_tpu": false, "enable_internet": true, "machine_shape": "$ACCEL",
 "dataset_sources": [$SRCS], "competition_sources": [], "kernel_sources": [], "model_sources": []}
EOF
tsec=$(awk -v b="$budget" 'BEGIN{x=int((b+0.4)*3600); if(x>43200)x=43200; print x}')
out=$("$KAGGLE" kernels push -p "$KD" --accelerator "$ACCEL" -t "$tsec" 2>&1); echo "$(date -Is) seq $seq: $out" >> "$WORK/push.log"
if echo "$out" | grep -q 'successfully pushed'; then
  v=$(echo "$out" | sed -n 's/.*Kernel version \([0-9]*\) successfully.*/\1/p')
  sset holder=kaggle seq="$seq" step="$step" kernel_version="${v:-?}" budget_h="$budget" pushed_at="$(date +%s)" note="pushed seq $seq"
  status "-> Kaggle: seq $seq, step $step, kernel v${v:-?}, budget $budget h (used so far ${used} h of ${TOTAL_CAP_H})"; exit 0
fi
echo "$out" | is_quota_msg && { status "push refused (quota): $(echo "$out" | tail -n 1 | cut -c1-200)"; exit 20; }
status "push failed: $(echo "$out" | tail -n 2 | tr '\n' ' ' | cut -c1-240)"; exit 21
