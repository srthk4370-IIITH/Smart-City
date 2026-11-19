#!/usr/bin/env bash
# export stub: ADAPTER_DIR TAG [shared|own] -> placeholder GGUF + md5 (no merge, no llama, no GPU)
P=$POST/$2; mkdir -p "$P"; echo "fake gguf for $2 from $1" > "$P/agt3_$2_q4_0.gguf"; md5sum < "$P/agt3_$2_q4_0.gguf" | cut -c1-32 > "$P/agt3_$2_q4_0.gguf.md5"; echo "stub export $2 imatrix=$3" >> "$P/export.log"
