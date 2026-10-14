#!/usr/bin/env bash
# !! The bundle this produces is NOT shippable. Kept to reproduce the experiment. !!
# LADE was measured on 2026-10-14: 14% faster end to end, and it CHANGES THE ANSWERS - "spike"
# decoded as "sp.peak", a flatline sensor_fault reported as normal. See HANDBOOK 2.14. The
# bundle itself is fine (byte-identical to live in basic mode); Genie's lookahead is what is lossy.
#
# Tier 3: export an AR-N token graph so Genie's lookahead decoding (LADE) can be used.
#
# Why: every speculative mode in Genie (lade / ssd-q1 / spd / eaglet) needs a token graph with
# AR-N > 1, and the stock AI Hub export only emits ar128 (prefill) + ar1 (decode). The CLI does
# expose --sequence-lengths, so the AR-N graph is reachable without a local QAIRT host.
#
# LADE's documented constraint:   (window + gcap) * (ngram - 1) <= AR-N
# With window=gcap=8, ngram=5  ->  (8+8)*4 = 64, so AR-N must be >= 64.
#
# Graph budget: graphs-per-part = len(seq) x len(ctx). This export is 3 (seq [128,64,1] x ctx
# [4096]). Any bundle with more than 2 graphs per part needs "enable-graph-switching": true in
# the Genie config or it fails to load with err 1002 - see HANDBOOK 2.12. Qualcomm ship a working
# 8-graph config for llama3-3b, so 8 is the real budget, not 3.
# ctx 1024 is dropped on purpose: our prompts are ~800 tokens and generation reaches ~1120 total,
# so the 1024 graph would be abandoned almost immediately anyway.
#
# Same checkpoint and encodings as the live bundle -> identical weights. Output must still be
# proven byte-identical with compare_bundles.py before anything ships.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source ~/venvs/qaihm/bin/activate
export TZ=Asia/Kolkata
export PYTHONPATH="$HERE/pyhooks${PYTHONPATH:+:$PYTHONPATH}"
CKPT=~/qaihm_work/ftgptq16_ckpt
OUT=~/qaihm_work/ftgptq16_genie_lade
[ -f "$CKPT/.ready" ] || { echo "checkpoint not ready"; exit 1; }
mkdir -p "$OUT"
echo "=== $(date) AR-N export for LADE"
echo "    ckpt=$CKPT  out=$OUT  seq=[128,64,1]  ctx=[4096]  (3 graphs/part)"
qai-hub-models export llama_v3_2_3b_instruct \
  --checkpoint "$CKPT" \
  --sequence-lengths 128,64,1 \
  --context-lengths 4096 \
  --device "Samsung Galaxy S24 (Family)" \
  --target-runtime genie --skip-profiling \
  --output-dir "$OUT"
echo "=== $(date) DONE"
find "$OUT" -name '*.bin' -o -name '*.json' | head -30
du -sh "$OUT"
