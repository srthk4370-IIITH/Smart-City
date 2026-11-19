#!/usr/bin/env bash
# make_bundle.sh: zip the rsn_v3 Kaggle bundle from make_data's output + the CURRENT chat3 sources (re-read now; their md5
# must equal what make_data verified) -> kaggle/build/$RUN_ID/rsn_v3_bundle.zip (+ .md5, UPLOAD_MANIFEST.md).
# Synthetic data only: every staged file must match the allowlist below and none may match the denylist (board data,
# real pool, eval suites, model weights); otherwise nothing is zipped.
# usage: RUN_ID=d1 bash .../local/make_bundle.sh        (DATA_RUN=<id> to bundle another make_data run's output)
SCRIPT=make_bundle; source "$(dirname "$0")/guard.sh"
set -o pipefail
check_run_id
DATA=$KG/build/${DATA_RUN:-$RUN_ID}/data
OUT=$KG/build/$RUN_ID
ST=$OUT/bundle_stage
[ -s "$DATA/manifest.json" ] || die "no make_data output at $DATA (run make_data.sh first)"
[ -e "$OUT/rsn_v3_bundle.zip" ] && die "$OUT/rsn_v3_bundle.zip exists: refusing to overwrite, use a new run id" 6
need_ram 1536
need_disk /mnt/c 1500
rm -rf "$ST"; mkdir -p "$ST"
status "start (data $DATA)"
(cd "$DATA" && md5sum -c --quiet MD5SUMS) || die "make_data output changed since its MD5SUMS"
(cd "$V3" && md5sum -c --quiet "$DATA/chat3_sources.md5") || die "chat3 sources changed since make_data verified them: rerun make_data with a new RUN_ID"
python3 "$KG/mknb.py" > "$OUT/mknb.log" 2>&1 || die "notebook build failed: $(cat "$OUT/mknb.log")"

P3=$ST/proofs/2026-10-29_rsn_v3; P1=$ST/proofs/2026-10-25_reasoner_final
mkdir -p "$P3/pipeline" "$P3/data" "$P3/data3" "$P3/kaggle" "$P1/eval/p0" "$ST/base"
cp "$V3"/pipeline/{verify_chat.py,tools_v3_impl.py,tools_v4.json} "$P3/pipeline/"
cp "$V3"/data/{chat3_train.jsonl,chat3_dev.jsonl,chat3_manifest.json} "$P3/data/"
cp "$DATA"/{incidents3_train.jsonl,incidents_dev60.jsonl,incidents3_report.json,manifest.json} "$P3/data3/"
cp "$KG"/{chatloop.py,distill.py,select_distill.py,build_mix3.py,train_rsn3.py,rsn3_kaggle.py,rsn3_kaggle.ipynb} "$P3/kaggle/"
cp "$R1"/eval/p0/{tools_impl.py,common.py} "$P1/eval/p0/"
cp "$R1/tools.json" "$P1/"                       # read by eval/p0/tools_impl.py at import
STORE_REL=$(cat "$DATA/store_path.txt")          # e.g. data/train_store_v3.sqlite (relative to the rsn_v3 dir)
STORE_DST=$P3/$STORE_REL; mkdir -p "$(dirname "$STORE_DST")"
cp ~/models/qwen3.5-4b/SHA256SUMS "$ST/base/SHA256SUMS" || die "no base SHA256SUMS"
# the store (WAL mode locally) as one self-contained file: consistent online backup, journal_mode DELETE, no -wal/-shm
python3 - "$V3/$STORE_REL" "$STORE_DST" <<'EOF' || die "store copy failed"
import sqlite3, sys
src = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.execute("PRAGMA journal_mode=DELETE")
n = dst.execute("SELECT count(*) FROM incident").fetchone()[0]
dst.close(); src.close()
print("store copy:", n, "incidents, journal_mode DELETE")
EOF
rm -f "$STORE_DST-wal" "$STORE_DST-shm"

# ---- allowlist / denylist (paths relative to the bundle root)
ALLOW='^(BUNDLE_OK_RSN3|base/SHA256SUMS|proofs/2026-10-29_rsn_v3/pipeline/(verify_chat\.py|tools_v3_impl\.py|tools_v4\.json)|proofs/2026-10-29_rsn_v3/data/chat3_(train|dev)\.jsonl|proofs/2026-10-29_rsn_v3/data/chat3_manifest\.json|proofs/2026-10-29_rsn_v3/data3/(incidents3_train\.jsonl|incidents_dev60\.jsonl|incidents3_report\.json|manifest\.json)|proofs/2026-10-29_rsn_v3/kaggle/(chatloop|distill|select_distill|build_mix3|train_rsn3|rsn3_kaggle)\.py|proofs/2026-10-29_rsn_v3/kaggle/rsn3_kaggle\.ipynb|proofs/2026-10-25_reasoner_final/eval/p0/(tools_impl|common)\.py|proofs/2026-10-25_reasoner_final/tools\.json|proofs/2026-10-25_reasoner_final/data/train_store\.sqlite|proofs/2026-10-29_rsn_v3/data/train_store_v3\.sqlite)$'
DENY='(^|/)(incidents\.jsonl|chats\.json|state[^/]*\.json|real_pool[^/]*|[^/]*rwh[^/]*|rw6[^/]*|[^/]*\.gguf|[^/]*-(wal|shm)|[^/]*\.safetensors|\.env)$'
printf 'rsn_v3 bundle %s %s\n' "$RUN_ID" "$(date -u +%FT%TZ)" > "$ST/BUNDLE_OK_RSN3"
(cd "$ST" && find . -type f | sed 's|^\./||' | sort) > "$OUT/bundle_files.txt"
bad=$(grep -Ev "$ALLOW" "$OUT/bundle_files.txt"; grep -E "$DENY" "$OUT/bundle_files.txt")
[ -z "$bad" ] || die "non-allowlisted / denied files staged: $(echo $bad)"
# no board snapshot content: the board's live files carry these keys; the synthetic sets never do
if grep -lE '"(board_serial|adb_serial)"' -r "$ST" >/dev/null 2>&1; then die "board identifiers found in the staged files"; fi
(cd "$ST" && md5sum $(cat "$OUT/bundle_files.txt" | grep -v BUNDLE_OK_RSN3)) >> "$ST/BUNDLE_OK_RSN3"

python3 - "$ST" "$OUT/rsn_v3_bundle.zip.part" <<'EOF' || die "zip failed"
import os, sys, zipfile
st, out = sys.argv[1:3]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for root, _, files in os.walk(st):
        for f in sorted(files):
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, st))
print("zip ok")
EOF
mv "$OUT/rsn_v3_bundle.zip.part" "$OUT/rsn_v3_bundle.zip"
(cd "$OUT" && md5sum rsn_v3_bundle.zip > rsn_v3_bundle.zip.md5)
python3 - "$ST" "$OUT" "$DATA" <<'EOF' || die "manifest failed"
import hashlib, json, os, sys
st, out, data = sys.argv[1:4]
zp = os.path.join(out, "rsn_v3_bundle.zip")
md5 = open(os.path.join(out, "rsn_v3_bundle.zip.md5")).read().split()[0]
rep = json.load(open(os.path.join(data, "incidents3_report.json")))
DESC = {"chat3_train.jsonl": "synthetic chat questions + gold calls/results/reference answers (gen_chat_v3.py, training store)",
        "chat3_dev.jsonl": "synthetic chat dev (dev-loss slice only; also the gate's chat dev v3 suite, never trained on)",
        "incidents3_train.jsonl": "incident traces: round-1 generator seed %d (see FLAG for real_agent rows) + 600 synthetic borderline" % rep["seed"],
        "incidents_dev60.jsonl": "first 60 round-1 incident dev rows (dev-loss only, never trained on)",
        "train_store.sqlite": "round-1 training incident store (chat tools executed against it; see FLAG)",
        "train_store_v3.sqlite": "rsn_v3 chat tool store = round-1 training store + synthetic recent readings (make_store_v3.py; see FLAG)",
        "tools.json": "round-1 tool schema read by eval/p0/tools_impl.py at import",
        "SHA256SUMS": "hashes of the local Qwen3.5-4B, used to check the HF download"}
real = rep["composition_v3"].get("real_agent", 0)
L = ["# Upload manifest: rsn_v3_bundle.zip (%s bytes, md5 %s)" % (format(os.path.getsize(zp), ","), md5), "",
     "Built by kaggle/local/make_bundle.sh (allowlist + denylist enforced; nothing from the board: no incidents.jsonl, chats.json or",
     "state files; no real_pool.jsonl; no eval suites RW6/RWH/P0; no model weights). Precedent: round-2 UPLOAD_MANIFEST.md.",
     "- **FLAG (as round 2):** `incidents3_train.jsonl` holds %d `real_agent` rows: round-1 generator variants of the %d real_pool" % (real, rep["real_pool_rows_used_by_round1"]),
     "  train rows that round 1 already trained on (real domain-agent outputs + real E-lines from SCRC windows). No held-out (RWH) rows.",
     "- **FLAG (as round 2):** the chat tool store (`train_store*.sqlite`) is, or is built from, the round-1 training store (synthetic",
     "  readings; holds the 110 demo-injection app-test incidents that the tools exclude by default; operator names are synthetic).",
     "- Everything else is synthetic or template-generated code/data. Nothing identifies a person.", "",
     "| path in zip | bytes | md5 | content |", "|---|---|---|---|"]
for root, _, files in os.walk(st):
    for f in sorted(files):
        p = os.path.join(root, f)
        rel = os.path.relpath(p, st)
        L.append("| %s | %s | %s | %s |" % (rel, format(os.path.getsize(p), ","), hashlib.md5(open(p, "rb").read()).hexdigest()[:12],
                                           DESC.get(f, "script / config (unchanged copy)" if f.endswith((".py", ".json", ".ipynb")) else "")))
open(os.path.join(out, "UPLOAD_MANIFEST.md"), "w").write("\n".join(L) + "\n")
print("manifest ok")
EOF
rm -rf "$ST"
status "DONE bundle $OUT/rsn_v3_bundle.zip ($(du -h "$OUT/rsn_v3_bundle.zip" | cut -f1), md5 $(cut -d' ' -f1 "$OUT/rsn_v3_bundle.zip.md5"))"
