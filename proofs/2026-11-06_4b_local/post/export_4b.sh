#!/usr/bin/env bash
# export_4b.sh <base_dir> <adapter_dir> <name>: LoRA merge (kaggle/local/merge_any.py: streaming, one shard at a time,
# W' = W + (alpha/r) * B@A, the export_gguf.sh convention) -> GGUF bf16 -> Q4_0 -> $STAGE_DIR/<name>_q4_0.gguf + .md5.
# CPU only. Called by post_chain.sh (or by test/t_export_tiny.sh with a tiny model).
# Why the work dir is on NTFS (/mnt/c/.../Temp), not in WSL: on 2026-10-31 a 4B merge + bf16 convert inside WSL grew the
# ext4.vhdx on C: by ~16 GB, C: filled and WSL crashed (HANDBOOK "Laptop disk"); vhdx space never comes back without a
# compact. Files on /mnt/c are freed for real when deleted. Guards: C: free >= C_MIN_MB (20 GB) + what the next step writes;
# Windows available >= RAM_WIN_MB and WSL MemAvailable >= RAM_WSL_MB before merge/convert/quantize (waits, does not die,
# up to WAIT_H hours); nice -n 15; the big file goes .part -> md5 -> mv. Refuses to overwrite a staged GGUF it did not make.
SCRIPT=${SCRIPT:-post_4b}; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
STATUS=${POST_STATUS:-$STATUS}   # tests write their status lines elsewhere
set -o pipefail
B=${1:?base dir}; A=${2:?adapter dir}; NAME=${3:?name}
STAGE_DIR=${STAGE_DIR:-$QIDK/Code/models_stage}; G=$STAGE_DIR/${NAME}_q4_0.gguf
W=${WORK:-/mnt/c/Users/hp/AppData/Local/Temp/post_4b_$NAME}
LOGD=${LOGD:-$QIDK/proofs/2026-11-06_4b_local/post/export_r3}
LC=${LC:-$HOME/gpu_work/llama.cpp}; PYM=${PYM:-$HOME/venvs/rsn/bin/python}; PYC=${PYC:-$HOME/venvs/train/bin/python}
C_MIN_MB=${C_MIN_MB:-20000}; RAM_WIN_MB=${RAM_WIN_MB:-1000}; RAM_WSL_MB=${RAM_WSL_MB:-2500}; WAIT_H=${WAIT_H:-24}
EXPECT_R=${EXPECT_R:-32}; EXPECT_ALPHA=${EXPECT_ALPHA:-64}
mkdir -p "$LOGD" "$STAGE_DIR"

if [ -s "$G" ] && [ -s "$G.md5" ] && [ -s "$LOGD/export.json" ] && grep -q "\"$(cut -d' ' -f1 "$G.md5")\"" "$LOGD/export.json"; then
  status "export: $G already made by this chain (md5 $(cut -d' ' -f1 "$G.md5")): skip"; exit 0
fi
[ -e "$G" ] && die "export: $G exists and was not made by this chain: refusing to overwrite" 6
[ -s "$A/adapter_model.safetensors" ] && [ -s "$A/adapter_config.json" ] || die "export: no adapter in $A" 2
[ -s "$B/model.safetensors.index.json" ] || die "export: base $B has no model.safetensors.index.json" 2
python3 - "$A/adapter_config.json" "$EXPECT_R" "$EXPECT_ALPHA" > "$LOGD/adapter_check.txt" <<'EOF' || die "export: adapter config is not the trainer's LoRA (see $LOGD/adapter_check.txt)"
import json, sys
c = json.load(open(sys.argv[1]))
print("adapter r=%s alpha=%s rslora=%s dora=%s targets=%s" % (c["r"], c["lora_alpha"], c.get("use_rslora"), c.get("use_dora"), c.get("target_modules")))
assert c["r"] == int(sys.argv[2]) and c["lora_alpha"] == int(sys.argv[3]), "r/alpha"
assert not c.get("use_rslora") and not c.get("use_dora"), "merge_any.py scale alpha/r assumes plain LoRA"
EOF

cfree() { df -Pm /mnt/c | awk 'NR==2{print $4}'; }
wslavail() { awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo; }
wait_res() {   # wait_res <MB to be written on C:> <step>: C: free >= C_MIN_MB + need, Windows + WSL RAM
  local need=$1 step=$2 t=0 c f w
  while true; do
    [ -e "${STOPF:-/nonexistent}" ] && { status "export: STOP file before $step"; exit 0; }
    c=$(cfree); f=$(free_mb); w=$(wslavail)
    if [ "${c:-0}" -ge $((C_MIN_MB + need)) ] && [ "${f:-0}" -ge "$RAM_WIN_MB" ] && [ "${w:-0}" -ge "$RAM_WSL_MB" ]; then return 0; fi
    [ $((t % 60)) = 0 ] && status "export: waiting before $step: C: free ${c:-?} MB (need $((C_MIN_MB + need))), Windows avail ${f:-?} MB (need $RAM_WIN_MB), WSL avail ${w:-?} MB (need $RAM_WSL_MB)"
    [ "$t" -ge $((WAIT_H * 60)) ] && die "export: resources not available for $WAIT_H h before $step" 4
    sleep 60; t=$((t + 1))
  done
}

BMB=$(du -smL "$B"/*.safetensors | awk '{s+=$1} END {print s+0}')
t0=$(date +%s)
mkdir -p "$W"; rm -rf "$W/hf" "$W"/*.part
# ---- merge: hf (~base size) is written; the bf16 GGUF (~base) and Q4_0 (~base/3) follow while hf still exists
wait_res $((BMB * 2 + BMB / 3 + 500)) merge
status "export: merge $A into $B -> $W/hf (C: free $(cfree) MB)"
export PYTHONPATH=$LC/gguf-py OMP_NUM_THREADS=4 MALLOC_ARENA_MAX=2
nice -n 15 "$PYM" "$QIDK/proofs/2026-10-29_rsn_v3/kaggle/local/merge_any.py" "$B" "$A" "$W/hf" > "$LOGD/merge.log" 2>&1 \
  || die "export: merge failed ($LOGD/merge.log: $(tail -n 1 "$LOGD/merge.log"))"
grep -q "^merged" "$LOGD/merge.log" || die "export: merge log has no 'merged' line"
status "export: $(grep '^merged' "$LOGD/merge.log" | tail -1)"
# ---- convert
wait_res $((BMB + BMB / 3 + 500)) convert
nice -n 15 "$PYC" "$LC/convert_hf_to_gguf.py" "$W/hf" --outtype bf16 --outfile "$W/bf16.gguf.part" 2>&1 | tr '\r' '\n' | grep -v '^Writing:' > "$LOGD/convert.log" \
  || die "export: convert failed ($LOGD/convert.log: $(tail -n 1 "$LOGD/convert.log"))"
mv "$W/bf16.gguf.part" "$W/bf16.gguf"; rm -rf "$W/hf"
status "export: bf16 GGUF $(du -h "$W/bf16.gguf" | cut -f1)"
# ---- quantize straight into the stage dir as .part, md5, mv
wait_res $((BMB / 3 + 500)) quantize
nice -n 15 "$LC/build-host/bin/llama-quantize" "$W/bf16.gguf" "$G.part" Q4_0 4 > "$LOGD/quant.log" 2>&1 \
  || die "export: quantize failed ($LOGD/quant.log: $(tail -n 1 "$LOGD/quant.log"))"
M=$(md5sum < "$G.part" | cut -d' ' -f1)
echo "$M  ${NAME}_q4_0.gguf" > "$G.md5"
mv "$G.part" "$G"
(cd "$STAGE_DIR" && md5sum -c --quiet "${NAME}_q4_0.gguf.md5") || die "export: md5 mismatch after mv"
rm -rf "$W"
python3 - "$LOGD/export.json" "$B" "$A" "$G" "$M" "$(stat -c %s "$G")" "$(( $(date +%s) - t0 ))" "$(grep '^merged' "$LOGD/merge.log" | tail -1)" <<'EOF'
import json, sys, time, hashlib, os
o, b, a, g, m, size, sec, merged = sys.argv[1:9]
h = hashlib.md5()
with open(os.path.join(a, "adapter_model.safetensors"), "rb") as f:
    for c in iter(lambda: f.read(1 << 22), b""):
        h.update(c)
am = h.hexdigest()
json.dump({"base": b, "adapter": a, "adapter_md5": am, "gguf": g, "gguf_md5": m, "bytes": int(size), "seconds": int(sec),
           "merge": merged, "quant": "Q4_0 (llama-quantize, 4 threads; as rsn_v1)", "time": time.strftime("%Y-%m-%d %H:%M:%S")},
          open(o, "w"), indent=1)
EOF
status "export: DONE $G ($(du -h "$G" | cut -f1), md5 $M, $(( ($(date +%s) - t0) / 60 )) min)"
