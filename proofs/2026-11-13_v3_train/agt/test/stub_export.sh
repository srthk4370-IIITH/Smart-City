#!/usr/bin/env bash
# dry-run stand-in for export.sh: writes a fake GGUF (+ md5) where export.sh would
source "$(dirname "$(readlink -f "$0")")/../lib.sh"
P=$POST/$2; mkdir -p "$P"; echo "fake gguf of $1 ($3)" > "$P/agt3_$2_q4_0.gguf"; md5sum "$P/agt3_$2_q4_0.gguf" | cut -d' ' -f1 > "$P/agt3_$2_q4_0.gguf.md5"
echo '{"tensor_type_match_vs_B50": true, "stub": true}' > "$P/gguf_check.json"
