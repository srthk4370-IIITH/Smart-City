#!/usr/bin/env bash
# import_adapter.sh <rsn_v3_adapter.zip>: Kaggle adapter -> low-RAM streaming merge -> GGUF bf16 -> Q4_0 (round-1 merge_q4.sh,
# which writes .part files, md5 and mv) -> Code/models_stage/${NAME}_q4_0.gguf (NAME=rsn_v3 by default).
# Refuses a PARTIAL adapter (ALLOW_PARTIAL=1 to import it anyway, e.g. for a mid-run look) and refuses to overwrite an
# existing staged GGUF or import dir (use a new RUN_ID / NAME). CPU only (merge_q4.sh waits for >= 4 GB free Windows RAM).
# usage: RUN_ID=t1 [NAME=rsn_v3] bash detach.sh imp_t1 .../local/import_adapter.sh /mnt/c/Users/hp/Downloads/rsn_v3_adapter.zip
SCRIPT=import_adapter; source "$(dirname "$0")/guard.sh"
set -o pipefail
check_run_id
Z=${1:-}; [ -s "$Z" ] || die "usage: RUN_ID=.. bash import_adapter.sh <rsn_v3_adapter.zip>" 2
NAME=${NAME:-rsn_v3}
STAGE=$QIDK/Code/models_stage/${NAME}_q4_0.gguf
IMP=~/smartcity_runs/reasoner_v1/rsn_v3_$RUN_ID
[ -e "$STAGE" ] && die "$STAGE exists: refusing to overwrite (NAME=rsn_v3_$RUN_ID for a second import)" 6
[ -e ~/smartcity_runs/reasoner_v1/gguf/$NAME ] && die "~/smartcity_runs/reasoner_v1/gguf/$NAME exists (old export dir): use another NAME" 6
need_ram 1536
need_disk ~ 25000
need_disk /mnt/c 20000   # 2026-10-31: merge+convert grow the WSL vhd on C: by ~16 GB; C: full crashed WSL
new_dir "$IMP"
status "start: $Z (md5 $(md5sum < "$Z" | cut -c1-32)) -> $STAGE"
md5sum "$Z" > "$IMP/adapter_zip.md5"
CK=$IMP/ckpt; mkdir -p "$CK"
python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$Z" "$CK" || die "unzip failed"
[ -s "$CK/adapter_model.safetensors" ] && [ -s "$CK/adapter_config.json" ] || die "zip has no adapter (distillation-only session?)"
cat "$CK/KAGGLE_MANIFEST.json" > "$IMP/KAGGLE_MANIFEST.json"
if ! grep -qE '"done": true|"adapter": "rsn_v3_adapter_(epoch1|best|final)"' "$CK/KAGGLE_MANIFEST.json"; then
  [ "${ALLOW_PARTIAL:-0}" = 1 ] || die "PARTIAL adapter (training not finished); ALLOW_PARTIAL=1 to import anyway"
  status "WARNING: importing a PARTIAL adapter"
fi
python3 - "$CK/adapter_config.json" <<'EOF' || die "adapter config is not r32/a64"
import json, sys
c = json.load(open(sys.argv[1]))
print("adapter r=%s alpha=%s targets=%d" % (c["r"], c["lora_alpha"], len(c["target_modules"])))
assert c["r"] == 32 and c["lora_alpha"] == 64
EOF
(cd "$CK" && md5sum adapter_model.safetensors adapter_config.json > "$IMP/adapter.md5")
need_ram 1536
CK=$CK NAME=$NAME bash "$R1/train/merge_q4.sh" > "$IMP/merge_q4.log" 2>&1 || die "merge_q4.sh failed (see $IMP/merge_q4.log)"
grep -q "merged" "$IMP/merge_q4.log" && grep "merged" "$IMP/merge_q4.log" | tail -1 | while read -r l; do status "$l"; done
[ -s "$STAGE" ] && [ -s "$STAGE.md5" ] || die "no staged GGUF after merge_q4.sh"
(cd "$(dirname "$STAGE")" && md5sum -c --quiet "$(basename "$STAGE").md5") || die "staged GGUF md5 mismatch"
status "DONE $STAGE ($(du -h "$STAGE" | cut -f1), md5 $(cut -d' ' -f1 "$STAGE.md5"))"
