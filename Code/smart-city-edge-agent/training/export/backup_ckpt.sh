#!/usr/bin/env bash
# Copy the reconstructed w4a16 checkpoint out of the WSL image onto Windows.
#
# After the disk cleanup this is the only copy of the GPTQ-quantised fine-tuned weights; the
# checkpoints it was rebuilt from were deleted. The DEPLOYED bundle is safe (QIDK + qidk_backup),
# but without this we could not re-export with different graph shapes.
set -u
SRC="$HOME/qaihm_work/ftgptq16_ckpt"
DST="/mnt/c/Users/hp/Desktop/qidk/qidk_backup/ckpt_ftgptq16"

mkdir -p "$DST"
echo "source: $SRC"
echo "dest  : $DST"
df -h /mnt/c | tail -1

for f in model.data model_dynamic.onnx model.encodings args.json config.json \
         tokenizer.json tokenizer_config.json special_tokens_map.json; do
  if [ -f "$SRC/$f" ]; then
    if [ -f "$DST/$f" ] && [ "$(stat -c %s "$SRC/$f")" = "$(stat -c %s "$DST/$f")" ]; then
      echo "  skip (already identical size): $f"
    else
      echo "  copying $f ..."
      cp "$SRC/$f" "$DST/$f"
    fi
  fi
done

echo
echo "=== verification (size must match exactly) ==="
ok=1
for f in model.data model_dynamic.onnx model.encodings; do
  a=$(stat -c %s "$SRC/$f" 2>/dev/null)
  b=$(stat -c %s "$DST/$f" 2>/dev/null)
  if [ "$a" = "$b" ]; then
    printf '  OK   %-22s %s bytes\n' "$f" "$a"
  else
    printf '  FAIL %-22s src=%s dst=%s\n' "$f" "$a" "$b"
    ok=0
  fi
done
echo
df -h /mnt/c | tail -1
[ "$ok" = 1 ] && echo "BACKUP COMPLETE" || { echo "BACKUP INCOMPLETE"; exit 1; }
