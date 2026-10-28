#!/system/bin/sh
# pruned lm_head A/B: v8r + base GGUF (ref) vs htpd_v8p (libllama_p) + keep GGUF; v8p + base GGUF checks that
# libllama_p changes nothing for the agents and for a full-vocab model.
cd /data/local/tmp/rfast; [ -d ab ] && mv ab ab_prev_$(date +%H%M%S)
K=/data/local/tmp/gpu/rsn_v1_q4_0_keep.gguf
REQS="0 0 1 2 3 4 5 6 7 8 9" sh ab_board.sh "base,htpd_v8r,-,X=0" "v8pbase,htpd_v8p,-,X=0" "keep,htpd_v8p,$K,X=0" "keeppoll,htpd_v8p,$K,GGML_HEXAGON_OPPOLL=1"
