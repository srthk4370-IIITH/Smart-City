#!/usr/bin/env bash
# lib.sh: shared code of the laptop <-> Kaggle baton (sourced by to_kaggle.sh, from_kaggle.sh, baton_auto.sh). See BATON.md.
# Every path can be overridden for the offline tests (test/run_tests.sh): BATON_RUN_DIR BATON_WORK BATON_FILE BATON_STATUS
# BATON_CTL BATON_CHAIN_DIR BATON_CURSOR_DATA KAGGLE BATON_PY BATON_KDIR POLL_S.
SCRIPT=baton
source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
set -o pipefail
B=$QIDK/proofs/2026-11-06_4b_local/baton
H=$QIDK/proofs/2026-11-06_4b_local
source "$B/baton.conf"
STATUS=${BATON_STATUS:-$STATUS}                                   # [baton] lines -> proofs/2026-10-29_rsn_v3/kaggle/STATUS.md
R=${BATON_RUN_DIR:-$HOME/smartcity_runs/rsn3_4b_r3}              # the laptop run dir = home of the lineage
WORK=${BATON_WORK:-$HOME/smartcity_runs/baton_r3}                # staging, downloads (WSL disk, not C:)
BATON=${BATON_FILE:-$B/BATON}
CTL=${BATON_CTL:-$H/ctl_4b.sh}
CHAIN_DIR=${BATON_CHAIN_DIR:-$H/chain}; CHAIN_PID=$CHAIN_DIR/chain.pid
KAGGLE=${KAGGLE:-$HOME/venvs/kaggle/bin/kaggle}
PY=${BATON_PY:-$HOME/venvs/rsn/bin/python}
KDIR=${BATON_KDIR:-$HOME/.kaggle}
TRAINER=$KG/train_rsn3.py
UTIL=$B/baton_util.py
D=$H/data/final
CURSOR_DATA=${BATON_CURSOR_DATA:-"$D/incidents_train.jsonl $D/chat_train_r3.jsonl"}   # ids the schedule may reference
POLL_S=${POLL_S:-$((POLL_MIN * 60))}
STOPF=${BATON_STOP:-$B/STOP}; PLOGS=${BATON_LOGS:-$B/logs}   # STOP file; Kaggle session logs kept as proof
mkdir -p "$WORK"

util() { CUDA_VISIBLE_DEVICES= nice -n 10 "$PY" "$UTIL" "$@"; }

# ---- token: existence + permissions only. The file is never read, printed or copied by these scripts; the kaggle CLI
# (2.2.4) reads it itself: ~/.kaggle/access_token (new token format, used first) or ~/.kaggle/kaggle.json (legacy).
token_ok() {
  local f
  for f in "$KDIR/access_token" "$KDIR/kaggle.json"; do
    [ -s "$f" ] || continue
    [ "$(stat -c %a "$f")" = 600 ] && return 0
    status "WARNING: $f is not chmod 600 (run: chmod 600 $f)"; return 1
  done
  return 1
}
kuser() {
  [ -n "$KAGGLE_USER" ] && { echo "$KAGGLE_USER"; return; }
  "$KAGGLE" config view 2>/dev/null | sed -n 's/^- username: *//p' | head -1
}

# ---- BATON file: key=value lines (holder, step, seq, md5, time, kernel_version, note)
bget() { [ -f "$BATON" ] && sed -n "s/^$1=//p" "$BATON" | tail -1; }
bset() {   # bset k=v k=v ...: rewrite BATON with the given keys replaced, append the change to baton/HISTORY.log
  local tmp=$BATON.part kv k
  [ -f "$BATON" ] && cp "$BATON" "$tmp" || : > "$tmp"
  for kv in "$@"; do k=${kv%%=*}; sed -i "/^$k=/d" "$tmp"; echo "$kv" >> "$tmp"; done
  sed -i '/^time=/d' "$tmp"; echo "time=$(date -Is)" >> "$tmp"
  mv "$tmp" "$BATON"
  echo "$(date -Is) $*" >> "$(dirname "$BATON")/HISTORY.log"
}

laptop_running() {
  local p; p=$(cat "$CHAIN_PID" 2>/dev/null)
  { [ -n "$p" ] && kill -0 "$p" 2>/dev/null; } || pgrep -f "train_rsn3.py.*$(basename "$R")( |$)" > /dev/null
}
run_step() { [ -s "$1/ckpt_latest/state.pt" ] && util step "$1/ckpt_latest/state.pt" || echo 0; }
train_finished() { [ -e "$CHAIN_DIR/train.done" ] || grep -qE '"stopped": "(after_epoch1|early_stop)"' "$R/status.json" 2>/dev/null; }

# ---- quota: `kaggle quota -v` (CSV: resource,used,remaining,total,refreshAt). Prints "<hours left> <refreshAt>" or nothing.
quota_left() {
  "$KAGGLE" quota -v 2>&1 | awk -F, '$1=="GPU"{gsub(/h/,"",$3); t=$5; if (t != "" && t !~ /(Z|[+-][0-9][0-9]:?[0-9][0-9])$/) t=t "Z"; print $3, t}' | head -1   # refreshAt is UTC
}
is_quota_msg() { grep -Eiq 'quota|exceeded|weekly (gpu|accelerator)|not enough .*(gpu|hours)|accelerator.*(unavailable|not available)|no (gpu|accelerator) (time|hours)'; }

# ---- lineage = what one uninterrupted run would have on disk (BATON.md "What travels")
LINEAGE_FILES="schedule.json best.json status.json plan.json maxlen.json train.log losses.jsonl dev.jsonl gen_eval.jsonl tokfp.json baton_scaler_kaggle.pt BATON_HISTORY.jsonl recipe.json"
lineage_list() {   # lineage_list RUNDIR -> relative file paths (laptop -> Kaggle: no ckpt_step* snapshots)
  local r=$1 d s
  (cd "$r" && find ckpt_latest -maxdepth 1 -type f | sort)
  for d in ckpt_epoch1 ckpt_final; do [ -d "$r/$d" ] && (cd "$r" && find "$d" -maxdepth 1 -type f | sort); done
  if [ "$SHIP_BEST" = 1 ] && [ -s "$r/best.json" ]; then
    for s in $(python3 -c "import json,sys;[print(t[1]) for t in json.load(open(sys.argv[1]))['top']]" "$r/best.json"); do
      d=$(printf 'ckpt_best_%04d' "$s"); [ -d "$r/$d" ] && (cd "$r" && find "$d" -maxdepth 1 -type f | sort)
    done
  fi
  for f in $LINEAGE_FILES; do [ -f "$r/$f" ] && echo "$f"; done
  return 0
}
pack_lineage() {   # pack_lineage RUNDIR OUTDIR -> OUTDIR/lineage.tar (+ MD5SUMS inside) and OUTDIR/lineage.tar.md5
  local r=$1 o=$2
  mkdir -p "$o"; lineage_list "$r" > "$o/files.txt"
  grep -q '^ckpt_latest/state.pt$' "$o/files.txt" || { echo "no ckpt_latest/state.pt in $r" >&2; return 1; }
  (cd "$r" && xargs -d '\n' md5sum < "$o/files.txt") > "$o/MD5SUMS" || return 1
  tar -cf "$o/lineage.tar.part" -C "$r" -T "$o/files.txt" -C "$o" MD5SUMS || return 1
  mv "$o/lineage.tar.part" "$o/lineage.tar"
  (cd "$o" && md5sum lineage.tar > lineage.tar.md5)
}
unpack_lineage() {  # unpack_lineage TAR DESTDIR: tar md5 (when the .md5 is next to it), extract, md5sum -c of every file
  local t=$1 d=$2
  if [ -f "$t.md5" ]; then (cd "$(dirname "$t")" && md5sum -c --quiet "$(basename "$t").md5") || return 1; fi
  rm -rf "$d"; mkdir -p "$d"
  tar -xf "$t" -C "$d" || return 1
  (cd "$d" && md5sum -c --quiet MD5SUMS) || return 1
}

# ---- no secrets / board files in anything uploaded (file names + text content)
DENY_NAMES='(^|/)(kaggle\.json|access_token|\.env[^/]*|htpd_profile[^/]*|website_final\.sh|id_rsa[^/]*|[^/]*\.pem|[^/]*\.key|[^/]*\.gguf|[^/]*-(wal|shm))$'
DENY_TEXT='BEGIN [A-Z ]*PRIVATE KEY|KAGGLE_KEY|"key" *: *"[0-9a-f]{32}"|ghp_[A-Za-z0-9]{30}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{32}|"(board_serial|adb_serial)"|htpd_profile|website_final'
secret_scan() {    # secret_scan DIR [TAR...]: non-zero + message on a hit
  local d=$1 hit; shift
  hit=$( (cd "$d" && find . -type f | sed 's|^\./||'; for t in "$@"; do tar -tf "$t"; done) | grep -E "$DENY_NAMES")
  [ -z "$hit" ] || { echo "denied file names: $hit"; return 1; }
  hit=$(grep -rIlE "$DENY_TEXT" "$d" --exclude='*.tar' 2>/dev/null)
  [ -z "$hit" ] || { echo "secret-like text in: $hit"; return 1; }
  for t in "$@"; do
    hit=$(tar -xOf "$t" --wildcards '*.json' '*.jsonl' '*.log' 'MD5SUMS' 2>/dev/null | grep -aEc "$DENY_TEXT")
    [ "${hit:-0}" = 0 ] || { echo "secret-like text inside $t"; return 1; }
  done
  return 0
}

# ---- the private data dataset: r3 rows + the gen-eval tool tree, in the repo layout the trainer expects
DATA_FILES="incidents_train.jsonl chat_train_r3.jsonl dev_r3.jsonl gen_chat_r3.jsonl gen_train_chat_r3.jsonl incidents_dev60.jsonl tools_r3.json"
stage_data() {     # stage_data STAGEDIR -> prints the data id (md5 of the staged MD5 list); refuses on any md5 mismatch
  local s=$1 P=$1/tree/proofs f
  (cd "$D" && md5sum -c --quiet MD5SUMS) >&2 || { echo "r3 data/final does not match its MD5SUMS" >&2; return 1; }
  echo "$GEN_INC_MD5  $QIDK/proofs/2026-11-02_2b_r2/data/final/gen_inc_r2.jsonl" | md5sum -c --quiet >&2 || { echo "gen_inc_r2.jsonl md5 changed" >&2; return 1; }
  rm -rf "$s"; mkdir -p "$P/2026-11-06_4b_local/data/final" "$P/2026-11-06_4b_local/data/store" "$P/2026-11-06_4b_local/tools" \
    "$P/2026-11-02_2b_r2/data/final" "$P/2026-10-29_rsn_v3/pipeline" "$P/2026-10-29_rsn_v3/kaggle" "$P/2026-10-25_reasoner_final/eval/p0" "$1/tree/base"
  for f in $DATA_FILES; do cp "$D/$f" "$P/2026-11-06_4b_local/data/final/"; done
  cp "$D/MD5SUMS" "$P/2026-11-06_4b_local/data/final/MD5SUMS.full"
  cp "$QIDK/proofs/2026-11-02_2b_r2/data/final/gen_inc_r2.jsonl" "$P/2026-11-02_2b_r2/data/final/"
  cp "$H/tools/tools_r3_impl.py" "$H/tools/knowledge_r3.json" "$P/2026-11-06_4b_local/tools/"
  cp "$H/data/store/store_r3_manifest.json" "$P/2026-11-06_4b_local/data/store/"
  for f in fog_store_r3.sqlite device_store_r3.sqlite; do   # consistent single-file copies (no -wal/-shm)
    python3 -c "import sqlite3,sys;a=sqlite3.connect('file:%s?mode=ro'%sys.argv[1],uri=True);b=sqlite3.connect(sys.argv[2]);a.backup(b);b.execute('PRAGMA journal_mode=DELETE');b.close()" \
      "$H/data/store/$f" "$P/2026-11-06_4b_local/data/store/$f" || return 1
  done
  cp "$V3/pipeline/verify_chat.py" "$V3/pipeline/tools_v3_impl.py" "$V3/pipeline/tools_v4.json" "$P/2026-10-29_rsn_v3/pipeline/"
  cp "$KG/chatloop.py" "$P/2026-10-29_rsn_v3/kaggle/"
  cp "$R1/eval/p0/tools_impl.py" "$R1/eval/p0/common.py" "$P/2026-10-25_reasoner_final/eval/p0/"
  cp "$R1/tools.json" "$P/2026-10-25_reasoner_final/"
  cp "$HOME/models/qwen3.5-4b/SHA256SUMS" "$1/tree/base/SHA256SUMS" || return 1
  (cd "$s/tree" && find . -type f ! -name R3_DATA_OK | sed 's|^\./||' | sort | xargs -d '\n' md5sum) > "$s/tree/R3_DATA_OK"
  md5sum < "$s/tree/R3_DATA_OK" | cut -c1-32
}
