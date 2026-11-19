#!/usr/bin/env bash
# from_kaggle.sh [--once]: take the baton back Kaggle -> laptop (BATON.md). Polls `kaggle kernels status` until the session
# ends (--once: one check, exit 30 while it runs), downloads the output, verifies lineage.tar md5 + every file md5 + step >
# baton step, checks the laptop did not train meanwhile, installs into the laptop run dir (the replaced lineage files are kept
# in <run>.prev_step<N> until the next successful install), BATON -> holder=laptop. Never starts the laptop trainer.
# exit: 0 installed | 10 no token | 30 still running | 31 holder is not kaggle | 32 no usable lineage (nothing installed,
#       holder -> laptop) | 33 conflict (laptop trained meanwhile; holder=conflict) | 34 kernel aborted before training (holder
#       -> laptop) | 35 download failed (holder stays kaggle, retry)
source "$(dirname "$(readlink -f "$0")")/lib.sh"
ONCE=0; [ "${1:-}" = --once ] && ONCE=1
h=$(bget holder); [ "$h" = kaggle ] || { echo "baton holder is '${h:-none}', not kaggle"; exit 31; }
token_ok || { status "waiting for token: cannot poll Kaggle"; exit 10; }
U=$(kuser); K=$U/$KERNEL_SLUG; seq=$(bget seq); prev=$(bget step)
L=$WORK/logs; mkdir -p "$L" "$PLOGS"
back() { rm -f "$R/BATON_AT_KAGGLE"; bset holder=laptop note="$1"; status "baton -> laptop (nothing installed): $1"; exit "$2"; }

while true; do
  out=$("$KAGGLE" kernels status "$K" 2>&1)
  st=$(echo "$out" | sed -n 's/.*has status "\([^"]*\)".*/\1/p' | tr A-Z a-z)
  case "$st" in
    *complete*|*error*|*cancel*) break ;;
    *running*|*queued*|*new_script*) ;;
    *) status "kernel status unreadable: $(echo "$out" | tr '\n' ' ' | cut -c1-200)" ;;
  esac
  [ $ONCE = 1 ] && exit 30
  [ -e "$STOPF" ] && exit 30
  sleep "$POLL_S"
done
fail=$(echo "$out" | sed -n 's/^Failure message: //p')
status "kernel seq $seq ended: $st${fail:+ ($fail)}"

DL=$WORK/dl/seq$seq; rm -rf "$DL"; mkdir -p "$DL"
"$KAGGLE" kernels output "$K" -p "$DL" -o > "$L/output_seq$seq.log" 2>&1 || { status "output download failed: $(tail -n 1 "$L/output_seq$seq.log")"; exit 35; }
for f in "$DL"/*.log "$DL/baton_kaggle.log"; do [ -f "$f" ] && cp "$f" "$PLOGS/kaggle_seq${seq}_$(basename "$f")"; done
[ -f "$DL/KAGGLE_RESULT.json" ] && cp "$DL/KAGGLE_RESULT.json" "$PLOGS/kaggle_seq${seq}_result.json"
ls "$DL"/wheels/*causal_conv1d-*.whl > /dev/null 2>&1 && { mkdir -p "$WORK/wheels"; cp "$DL"/wheels/*causal_conv1d-*.whl "$WORK/wheels/"; }
[ -s "$DL/triton_cache.tar" ] && { mkdir -p "$WORK/kcache"; mv "$DL/triton_cache.tar" "$WORK/kcache/triton_cache.tar"; }
[ -f "$DL/causal_conv1d_build.log" ] && cp "$DL/causal_conv1d_build.log" "$PLOGS/kaggle_seq${seq}_causal_conv1d_build.log"   # next session skips the 12 min build
if echo "$fail" | is_quota_msg; then echo "$(date -Is) $fail" > "$WORK/quota_hit"; fi
ab=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('abort',''))" "$DL/KAGGLE_RESULT.json" 2>/dev/null)

# ---- the lineage: packed tar (normal) or the raw run dir (session killed before packing)
NEW=$WORK/new_seq$seq; kind=tar
if [ -f "$DL/lineage.tar" ]; then
  unpack_lineage "$DL/lineage.tar" "$NEW" || back "seq $seq: lineage.tar md5 check failed" 32
  rm -f "$NEW/MD5SUMS"
elif [ -s "$DL/run/ckpt_latest/state.pt" ]; then
  kind=raw; rm -rf "$NEW"; mv "$DL/run" "$NEW"; rm -f "$NEW"/*_tok.pt "$NEW/caches.json"
  status "seq $seq: no lineage.tar (session cut before packing): using the raw run dir"
else
  [ -n "$ab" ] && back "seq $seq aborted on Kaggle: $ab" 34
  back "seq $seq: no lineage in the output (session ended before training)" 32
fi
util info "$NEW/ckpt_latest" > "$L/info_seq$seq.json" || back "seq $seq: checkpoint does not load" 32
new=$(run_step "$NEW")
[ "$new" -gt "$prev" ] || back "seq $seq: no progress (step $new, baton step $prev)" 32

# ---- never two lineages: the laptop must still be exactly where it handed over
lap=$(run_step "$R")
if [ "$lap" != "$prev" ] || laptop_running; then
  bset holder=conflict note="laptop at step $lap (running: $(laptop_running && echo yes || echo no)), Kaggle returned $new from $prev"
  die "CONFLICT: the laptop trained while Kaggle held the baton (laptop $lap, sent $prev, Kaggle $new). Nothing installed; Kaggle lineage kept in $NEW. BATON.md 'Conflict'" 33
fi

# ---- install: move the replaced lineage files aside, then move the new ones in
BK=$R.prev_step$prev; rm -rf "$BK"; mkdir -p "$BK"
for f in "$R"/ckpt_latest "$R"/ckpt_epoch1 "$R"/ckpt_final "$R"/ckpt_best_*; do [ -e "$f" ] && mv "$f" "$BK/"; done
for f in $LINEAGE_FILES; do [ -e "$R/$f" ] && mv "$R/$f" "$BK/"; done
rollback() { for f in "$R"/ckpt_latest "$R"/ckpt_epoch1 "$R"/ckpt_final "$R"/ckpt_best_*; do [ -e "$f" ] && rm -rf "$f"; done
  for f in $LINEAGE_FILES; do rm -f "$R/$f"; done; mv "$BK"/* "$R/"; rmdir "$BK"; }
(cd "$NEW" && find . -mindepth 1 -maxdepth 1) | while read -r f; do rm -rf "$R/${f#./}"; mv "$NEW/${f#./}" "$R/"; done
# best-K checkpoints that stayed home (SHIP_BEST=0, or made before the hop) come back from the backup
if [ -s "$R/best.json" ]; then
  for s in $(python3 -c "import json,sys;[print(t[1]) for t in json.load(open(sys.argv[1]))['top']]" "$R/best.json"); do
    d=$(printf 'ckpt_best_%04d' "$s"); [ ! -d "$R/$d" ] && [ -d "$BK/$d" ] && cp -al "$BK/$d" "$R/$d"
  done
fi
if ! util cursor "$R" $CURSOR_DATA > "$L/cursor_pull_seq$seq.json" || grep -q '"best_dirs_missing": \[[0-9]' "$L/cursor_pull_seq$seq.json"; then
  rollback; bset holder=laptop note="seq $seq install failed cursor/best check: rolled back"
  die "installed lineage failed the cursor/best check ($(cat "$L/cursor_pull_seq$seq.json")): rolled back to step $prev" 32
fi
if ls "$R"/*_tok.pt > /dev/null 2>&1 && [ -s "$R/tokfp.json" ]; then
  util tokfp-check "$R" "$R/tokfp.json" > "$L/tokfp_pull_seq$seq.json" || status "WARNING: laptop token caches differ from Kaggle's ($(cat "$L/tokfp_pull_seq$seq.json")): check before training on"
fi
for d in "$R".prev_step*; do [ "$d" != "$BK" ] && [ -d "$d" ] && rm -rf "$d"; done     # one backup: the lineage just replaced
rm -rf "$NEW" "$DL/lineage.tar" "$DL/run"
rm -f "$R/BATON_AT_KAGGLE"
rc=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('rc'))" "$DL/KAGGLE_RESULT.json" 2>/dev/null)
bset holder=laptop step="$new" md5="$(md5sum < "$R/ckpt_latest/state.pt" | cut -c1-32)" note="pulled seq $seq ($kind, kaggle rc ${rc:-?})"
util skipped "$R" > "$PLOGS/skipped_after_seq$seq.json" 2>/dev/null
nsk=$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print('%d steps / %d rows' % (d['n_steps'], d['n_rows']))" "$PLOGS/skipped_after_seq$seq.json" 2>/dev/null)
status "baton -> laptop: seq $seq installed, step $prev -> $new ($kind, kaggle rc ${rc:-?}); backup $BK; OOM-skipped in the lineage so far: ${nsk:-?}"
exit 0
