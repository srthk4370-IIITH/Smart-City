#!/usr/bin/env bash
# make_bundle_b.sh <chat3_distilled.jsonl> [replay_train.jsonl]: bundle B for Kaggle (second private dataset "rsn-v3-chat")
# -> kaggle/build/$RUN_ID/rsn_v3_chat_bundle.zip (+ .md5, UPLOAD_MANIFEST_B.md). Checks: every chat row is tools=chat with
# messages and comes from a chat3 TRAIN question (no chat3 dev id, no RWH/board data); replay rows are tools=none, 2 messages.
# usage: RUN_ID=r1 bash make_bundle_b.sh .../distill_laptop/chat3_distilled.jsonl .../build/r1/replay/replay_train.jsonl
SCRIPT=make_bundle_b; source "$(dirname "$0")/guard.sh"
check_run_id
C=${1:?chat3_distilled.jsonl}; P=${2:-}
OUT=$KG/build/$RUN_ID; ST=$OUT/bundle_b_stage
[ -s "$C" ] || die "no distilled chat file $C"
[ -e "$OUT/rsn_v3_chat_bundle.zip" ] && die "$OUT/rsn_v3_chat_bundle.zip exists: refusing to overwrite, use a new run id" 6
need_ram 1536; need_disk /mnt/c 1000
rm -rf "$ST"; mkdir -p "$ST"
cp "$C" "$ST/chat3_distilled.jsonl"
[ -n "$P" ] && [ -s "$P" ] && cp "$P" "$ST/replay_train.jsonl"
python3 - "$ST" "$V3/data/chat3_train.jsonl" "$V3/data/chat3_dev.jsonl" <<'EOF' || die "bundle B content check failed"
import json, os, sys, collections
st, tr, dv = sys.argv[1:4]
train_ids = {json.loads(l)["id"] for l in open(tr, encoding="utf-8")}
dev_ids = {json.loads(l)["id"] for l in open(dv, encoding="utf-8")}
rows = [json.loads(l) for l in open(os.path.join(st, "chat3_distilled.jsonl"), encoding="utf-8")]
bad = [r.get("id") for r in rows if r.get("tools") != "chat" or not r.get("messages")]
q = lambda r: r.get("question_id") or r["id"].rsplit("-", 1)[0]
leak = [r["id"] for r in rows if q(r) in dev_ids]
unknown = [r["id"] for r in rows if q(r) not in train_ids]
assert not bad and not leak and not unknown, ("bad", bad[:3], "dev leak", leak[:3], "not a chat3 train question", unknown[:3])
rp = os.path.join(st, "replay_train.jsonl")
rep = [json.loads(l) for l in open(rp, encoding="utf-8")] if os.path.exists(rp) else []
assert all(r.get("tools") == "none" and len(r["messages"]) == 2 for r in rep), "replay rows malformed"
print("bundle B: %d chat rows (%s; %d questions, hard %d), %d replay rows" % (len(rows), dict(collections.Counter(r.get("source") for r in rows)),
      len({q(r) for r in rows}), sum(1 for r in rows if r.get("hard")), len(rep)))
EOF
printf 'rsn_v3 chat bundle %s %s\n' "$RUN_ID" "$(date -u +%FT%TZ)" > "$ST/BUNDLE_OK_RSN3_CHAT"
(cd "$ST" && md5sum chat3_distilled.jsonl $( [ -e replay_train.jsonl ] && echo replay_train.jsonl )) >> "$ST/BUNDLE_OK_RSN3_CHAT"
python3 -c "
import os, sys, zipfile
st, out = sys.argv[1:3]
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for f in sorted(os.listdir(st)):
        z.write(os.path.join(st, f), f)
" "$ST" "$OUT/rsn_v3_chat_bundle.zip.part" || die "zip failed"
mv "$OUT/rsn_v3_chat_bundle.zip.part" "$OUT/rsn_v3_chat_bundle.zip"
(cd "$OUT" && md5sum rsn_v3_chat_bundle.zip > rsn_v3_chat_bundle.zip.md5)
{ echo "# Upload manifest: rsn_v3_chat_bundle.zip ($(stat -c %s "$OUT/rsn_v3_chat_bundle.zip") bytes, md5 $(cut -d' ' -f1 "$OUT/rsn_v3_chat_bundle.zip.md5"))"
  echo; echo "Synthetic only: verified distilled answers to chat3 TRAIN questions (base Qwen3.5-4B teacher on the laptop, tools on the"
  echo "synthetic training store) and base-model answers to template general prompts. No dev/RWH/board data (checked)."; echo
  echo "| file | bytes | md5 |"; echo "|---|---|---|"
  for f in $(ls "$ST"); do echo "| $f | $(stat -c %s "$ST/$f") | $(md5sum < "$ST/$f" | cut -c1-12) |"; done; } > "$OUT/UPLOAD_MANIFEST_B.md"
rm -rf "$ST"
status "DONE bundle B $OUT/rsn_v3_chat_bundle.zip ($(du -h "$OUT/rsn_v3_chat_bundle.zip" | cut -f1), md5 $(cut -d' ' -f1 "$OUT/rsn_v3_chat_bundle.zip.md5"))"
