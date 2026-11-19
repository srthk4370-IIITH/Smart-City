#!/usr/bin/env bash
# export_gguf.sh <base_dir> <adapter_dir> <name>: streaming merge -> GGUF bf16 -> Q4_0 -> Code/models_stage/<name>_q4_0.gguf (+ md5).
# Same flow as round-1 merge_q4.sh (.part files, md5, mv) but with the base as an argument (used for the 2B). CPU only;
# waits for >= 4 GB free Windows RAM; refuses to overwrite a staged GGUF.
SCRIPT=export_gguf; source "$(dirname "$0")/guard.sh"
B=${1:?base dir}; A=${2:?adapter dir}; NAME=${3:?name}
D=$QIDK/Code/models_stage; G=$D/${NAME}_q4_0.gguf
[ -e "$G" ] && die "$G exists: refusing to overwrite (use another name)" 6
E=~/smartcity_runs/reasoner_v1/gguf/$NAME; LC=~/gpu_work/llama.cpp
need_ram ${EXPORT_RAM_MB:-4096} 120   # 2B export streams; EXPORT_RAM_MB=2000 used 2026-11-01
need_disk ~ 15000
mkdir -p "$E"; rm -rf "$E/hf"
export PYTHONPATH=$LC/gguf-py OMP_NUM_THREADS=4
nice -n 15 ~/venvs/rsn/bin/python "$KG/local/merge_any.py" "$B" "$A" "$E/hf" > "$E/merge.log" 2>&1 || die "merge failed ($E/merge.log)"
status "$(tail -n 1 "$E/merge.log")"
nice -n 15 ~/venvs/train/bin/python $LC/convert_hf_to_gguf.py "$E/hf" --outtype bf16 --outfile "$E/bf16.gguf.part" > "$E/convert.log" 2>&1 \
  || die "convert failed ($E/convert.log)"
mv "$E/bf16.gguf.part" "$E/bf16.gguf"; rm -rf "$E/hf"
nice -n 15 $LC/build-host/bin/llama-quantize "$E/bf16.gguf" "$E/${NAME}_q4_0.gguf.part" Q4_0 4 > "$E/quant.log" 2>&1 || die "quantize failed"
mv "$E/${NAME}_q4_0.gguf.part" "$E/${NAME}_q4_0.gguf"; rm -f "$E/bf16.gguf"
mkdir -p "$D"; cp "$E/${NAME}_q4_0.gguf" "$G.part" && mv "$G.part" "$G"
(cd "$D" && md5sum "${NAME}_q4_0.gguf" > "${NAME}_q4_0.gguf.md5")
[ "$(cut -d' ' -f1 "$G.md5")" = "$(md5sum < "$E/${NAME}_q4_0.gguf" | cut -d' ' -f1)" ] || die "md5 mismatch after copy"
status "DONE $G ($(du -h "$G" | cut -f1), md5 $(cut -d' ' -f1 "$G.md5"))"
