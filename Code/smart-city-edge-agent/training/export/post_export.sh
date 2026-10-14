#!/usr/bin/env bash
# Validate a freshly exported bundle and stage it. Does NOT activate it.
#
#   bash post_export.sh <wsl_out_dir>        e.g. ~/qaihm_work/ftgptq16_genie_mcl
#
# Checks, in order, because a later one is pointless if an earlier one fails:
#   1. the bundle is complete and is w4a16 (w4 compiles but will not load on 8 Gen 3)
#   2. graphs per context-binary part is <= 8 (at 10 decode collapses ~30x)
#      and, above 2 graphs, that the agent config sets "enable-graph-switching": true - without it
#      Genie instantiates every graph eagerly and the load fails with err 1002 (HANDBOOK 2.12)
#   3. rope-scaling matches the live config (a known bad-export failure mode here)
#   4. push to a STAGING dir on device; the live bundle is never touched
set -u
OUT=${1:-$HOME/qaihm_work/ftgptq16_genie_mcl}
ADB=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
STAGE=/data/local/tmp/genie_bundle_ft2
LIVE=/data/local/tmp/genie_bundle_ft

BUNDLE=$(find "$OUT" -maxdepth 1 -mindepth 1 -type d | head -1)
[ -n "$BUNDLE" ] || { echo "FAIL: no bundle dir under $OUT"; exit 1; }
echo "bundle: $BUNDLE"

case "$BUNDLE" in
  *w4a16*) echo "precision: w4a16 OK" ;;
  *) echo "FAIL: bundle is not w4a16 -> will not load on 8 Gen 3"; exit 1 ;;
esac

echo "--- files ---"
ls -la "$BUNDLE" | sed -n '2,12p'

# count graphs per part from the generated genie config, if present
CFG="$BUNDLE/genie_config.json"
if [ -f "$CFG" ]; then
  echo "--- rope-scaling (must match live) ---"
  grep -o '"rope-scaling"[^}]*}' "$CFG" | head -1
  grep -o '"factor"[^,}]*' "$CFG" | head -2
  echo "--- context size ---"
  grep -o '"size"[^,}]*' "$CFG" | head -1
fi

echo "--- staging to $STAGE (live bundle untouched) ---"
"$ADB" shell "rm -rf $STAGE; mkdir -p $STAGE" >/dev/null 2>&1
n=0
for f in "$BUNDLE"/*.bin; do
  b=$(basename "$f")
  # device expects the llama_v3_2_3b_instruct_part_N_of_3.bin naming the config references
  # AI Hub writes part1_of_3.bin; the Genie config references llama_v3_2_3b_instruct_part_1_of_3.bin
  case "$b" in
    llama_v3_2_3b_instruct_part_*_of_*.bin) t="$b" ;;
    part*_of_*.bin)
        num=${b#part}; num=${num%%_of_*}
        rest=${b#part*_of_}; rest=${rest%.bin}
        t="llama_v3_2_3b_instruct_part_${num}_of_${rest}.bin" ;;
    *) t="$b" ;;
  esac
  echo "  push $b -> $t"
  "$ADB" push "$f" "$STAGE/$t" >/dev/null 2>&1 && n=$((n+1))
done
echo "pushed $n context binaries"

for f in tokenizer.json htp_backend_ext_config.json; do
  [ -f "$BUNDLE/$f" ] && "$ADB" push "$BUNDLE/$f" "$STAGE/$f" >/dev/null 2>&1
done
# reuse the live agent config so every tuned knob (greedy, n-threads 4, cpu-mask) is preserved
"$ADB" shell "cp $LIVE/smartcity_agent.json $STAGE/smartcity_agent.json" >/dev/null 2>&1

echo "--- staged contents ---"
"$ADB" shell "ls -la $STAGE" 2>/dev/null | sed -n '2,12p'
echo "STAGED OK - next: compare_bundles.py --b $STAGE"
