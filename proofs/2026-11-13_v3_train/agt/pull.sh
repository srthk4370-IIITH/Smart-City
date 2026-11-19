#!/usr/bin/env bash
# pull.sh [--once]: poll the Kaggle session until it ends (--once: one check, exit 30 while it runs), download the output, verify
# lineage.tar md5 + every file md5 + step progress, install ckpt_latest + bookkeeping into the run dir (previous copy kept in
# run/prev/), move the new snap_* dirs in, add the session hours, holder -> laptop. Session logs are kept in agt/logs/.
# exit: 0 installed | 10 no token | 30 running | 31 holder not kaggle | 32 no usable lineage (holder -> laptop)
#       34 kernel aborted before training (holder -> laptop; abort text in STATE note) | 35 download failed (retry)
source "$(dirname "$(readlink -f "$0")")/lib.sh"
ONCE=0; [ "${1:-}" = --once ] && ONCE=1
[ "$(sget holder)" = kaggle ] || { echo "holder is '$(sget holder)', not kaggle"; exit 31; }
token_ok || die "no token: cannot poll" 10
U=$(kuser); K=$U/$KERNEL_SLUG; seq=$(sget seq); prev=$(sget step)
addh() { local h; h=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('session_h',0))" "$1" 2>/dev/null || echo "$2")
  sset kaggle_h="$(awk -v a="$(sget kaggle_h)" -v b="${h:-0}" 'BEGIN{printf "%.2f", a+b}')"; }
back() { sset holder=laptop note="$1"; status "-> laptop (nothing installed): $1"; exit "$2"; }

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
need_c
DL=$WORK/dl/seq$seq; rm -rf "$DL"; mkdir -p "$DL"
"$KAGGLE" kernels output "$K" -p "$DL" -o > "$WORK/output_seq$seq.log" 2>&1 || { status "output download failed: $(tail -n 1 "$WORK/output_seq$seq.log")"; exit 35; }
for f in "$DL"/*.log; do [ -f "$f" ] && cp "$f" "$PLOGS/kaggle_seq${seq}_$(basename "$f")"; done
[ -f "$DL/KAGGLE_RESULT.json" ] && cp "$DL/KAGGLE_RESULT.json" "$PLOGS/kaggle_seq${seq}_result.json"
pushed=$(sget pushed_at); est=$(awk -v p="${pushed:-0}" -v n="$(date +%s)" 'BEGIN{printf "%.2f", (p>0)?(n-p)/3600:0}')
addh "$DL/KAGGLE_RESULT.json" "$est"
ab=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('abort',''))" "$DL/KAGGLE_RESULT.json" 2>/dev/null)
if [ -n "$ab" ]; then
  case "$ab" in *"base mismatch"*) touch "$WORK/base_src_dataset"; status "HF base differs from the laptop base: next push uploads the base dataset";; esac
  back "seq $seq aborted on Kaggle: $ab" 34
fi
[ -f "$DL/lineage.tar" ] || back "seq $seq: no lineage.tar in the output" 32
(cd "$DL" && md5sum -c --quiet lineage.tar.md5) || back "seq $seq: lineage.tar md5 check failed" 32
NEW=$WORK/new_seq$seq; rm -rf "$NEW"; mkdir -p "$NEW"
tar -xf "$DL/lineage.tar" -C "$NEW" && (cd "$NEW" && md5sum -c --quiet MD5SUMS) || back "seq $seq: lineage file md5 check failed" 32
rm -f "$NEW/MD5SUMS"
new=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['step'])" "$NEW/status.json" 2>/dev/null || echo -1)
[ "$new" -gt "${prev:-0}" ] || [ -n "$(ls -d "$NEW"/snap_* 2>/dev/null)" ] || back "seq $seq: no progress (step $new, handover step $prev)" 32
# install: previous bookkeeping -> run/prev, new files in, snapshots added
rm -rf "$R/prev"; mkdir -p "$R/prev"
for f in "$NEW"/*; do b=$(basename "$f"); [ -e "$R/$b" ] && mv "$R/$b" "$R/prev/"; mv "$f" "$R/"; done
rc=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('rc'))" "$DL/KAGGLE_RESULT.json" 2>/dev/null)
sset holder=laptop step="$new" note="pulled seq $seq (kaggle rc ${rc:-?})"
rm -rf "$DL/lineage.tar" "$NEW"
status "<- Kaggle: seq $seq installed, step $prev -> $new, rc ${rc:-?}, snaps: $(ls -d "$R"/snap_* 2>/dev/null | xargs -n1 basename | tr '\n' ' '); Kaggle hours used $(sget kaggle_h)"
exit 0
