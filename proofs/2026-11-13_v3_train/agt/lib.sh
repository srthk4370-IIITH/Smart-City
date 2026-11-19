#!/usr/bin/env bash
# lib.sh: shared code for push.sh / pull.sh / select.sh / gate.sh / runner.sh (agt_v3). Adapted from the 4B baton lib
# (proofs/2026-11-06_4b_local/baton/lib.sh): token check without reading it, quota, secret scan, dataset versions with a
# live-version check (seq + nonce), lineage tar with md5s.
set -u -o pipefail
source "${AGT_CONF:-$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/agt.conf}"
SCRIPT=${SCRIPT:-$(basename "$0" .sh)}
STATEF=${STATEF:-$A/STATE}            # key=value: holder (laptop|kaggle), seq, step, kernel_version, kaggle_h, note
mkdir -p "$WORK" "$PLOGS" "$R" "$POST"

status() {
  [ -s "$STATUS" ] || printf '# agt_v3 training status (append-only)\n\n' > "$STATUS"
  local l="- $(date '+%F %T') [$SCRIPT] $*"; echo "$l" >> "$STATUS"; echo "$l"
}
die() { status "FAIL: $1"; exit "${2:-1}"; }

sget() { [ -f "$STATEF" ] && sed -n "s/^$1=//p" "$STATEF" | tail -1; }
sset() {
  local t=$STATEF.part kv; [ -f "$STATEF" ] && cp "$STATEF" "$t" || : > "$t"
  for kv in "$@"; do sed -i "/^${kv%%=*}=/d" "$t"; echo "$kv" >> "$t"; done
  sed -i '/^time=/d' "$t"; echo "time=$(date -Is)" >> "$t"; mv "$t" "$STATEF"
  echo "$(date -Is) $*" >> "${STATEF%/*}/HISTORY.log"
}

token_ok() {
  local f
  for f in "$KDIR/access_token" "$KDIR/kaggle.json"; do
    [ -s "$f" ] || continue
    [ "$(stat -c %a "$f")" = 600 ] && return 0
    status "WARNING: $f is not chmod 600"; return 1
  done
  return 1
}
kuser() { [ -n "$KAGGLE_USER" ] && { echo "$KAGGLE_USER"; return; }; "$KAGGLE" config view 2>/dev/null | sed -n 's/^- username: *//p' | head -1; }
quota_left() {   # "<hours left> <refreshAt UTC>" or nothing
  "$KAGGLE" quota -v 2>&1 | awk -F, '$1=="GPU"{gsub(/h/,"",$3); t=$5; if (t != "" && t !~ /(Z|[+-][0-9][0-9]:?[0-9][0-9])$/) t=t "Z"; print $3, t}' | head -1
}
is_quota_msg() { grep -Eiq 'quota|exceeded|weekly (gpu|accelerator)|not enough .*(gpu|hours)|accelerator.*(unavailable|not available)'; }

free_c_mb() { df -Pm /mnt/c 2>/dev/null | awk 'NR==2{print $4}'; }
need_c() { local f; f=$(free_c_mb); [ -z "$f" ] || [ "$f" -ge "$MIN_C_FREE_MB" ] || die "C: has ${f} MB free < $MIN_C_FREE_MB MB (WSL vhdx is on C:)" 5; }
PS_EXE=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
win_free_mb() { [ -x "$PS_EXE" ] || { echo 99999; return; }; timeout 30 "$PS_EXE" -NoProfile -Command "(Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes" < /dev/null 2>/dev/null | tr -dc 0-9; }
need_ram() { local n=${1:-1536} t=0 f; while :; do f=$(win_free_mb); [ -n "$f" ] && [ "$f" -ge "$n" ] && return 0
  [ "$t" -ge 60 ] && die "Windows free RAM ${f:-?} MB < $n MB for 60 min" 4; sleep 60; t=$((t + 1)); done; }

# ---- GPU lock (same protocol as proofs/2026-11-12_agents_holes/scripts/run_A.sh): wait for lock + idle GPU, take, release
gpu_free() { [ -n "${GPU_ASSUME_FREE:-}" ] && [ ! -e "$GPU_LOCK" ] && return 0; [ ! -e "$GPU_LOCK" ] && [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -dc 0-9)" -lt 800 ] \
  && ! pgrep -f "[l]lama-server|[t]rain_" > /dev/null; }
gpu_take() { local said=0; until gpu_free; do [ -n "${GPU_NOWAIT:-}" ] && return 1; [ $said = 0 ] && status "waiting for the laptop GPU (lock / busy)"; said=1
  [ -e "$STOPF" ] && return 1; sleep 120; done; echo "agt_v3 $SCRIPT $(date -Is) pid $$" > "$GPU_LOCK"; }
gpu_release() { grep -q "^agt_v3 " "$GPU_LOCK" 2>/dev/null && rm -f "$GPU_LOCK"; return 0; }

# ---- secret scan of everything that leaves the laptop (file names + text)
DENY_NAMES='(^|/)(kaggle\.json|access_token|\.env[^/]*|htpd_profile[^/]*|website_final\.sh|id_rsa[^/]*|[^/]*\.pem|[^/]*\.key|[^/]*\.gguf|[^/]*\.sqlite|[^/]*-(wal|shm))$'
DENY_TEXT='BEGIN [A-Z ]*PRIVATE KEY|KAGGLE_KEY|KGAT_[A-Za-z0-9]{16}|"key" *: *"[0-9a-f]{32}"|ghp_[A-Za-z0-9]{30}|hf_[A-Za-z0-9]{30}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{32}|"(board_serial|adb_serial)"|htpd_profile|website_final'
secret_scan() {   # secret_scan DIR [TAR...]
  local d=$1 hit t; shift
  hit=$( (cd "$d" && find . -type f | sed 's|^\./||'; for t in "$@"; do tar -tf "$t"; done) | grep -E "$DENY_NAMES")
  [ -z "$hit" ] || { echo "denied file names: $hit"; return 1; }
  hit=$(grep -rIlE "$DENY_TEXT" "$d" --exclude='*.tar' --exclude='*.safetensors' 2>/dev/null)
  [ -z "$hit" ] || { echo "secret-like text in: $hit"; return 1; }
  for t in "$@"; do
    hit=$(tar -xOf "$t" --wildcards '*.json' '*.jsonl' '*.log' '*.py' 'MD5SUMS' 2>/dev/null | grep -aEc "$DENY_TEXT")
    [ "${hit:-0}" = 0 ] || { echo "secret-like text inside $t"; return 1; }
  done
}

# ---- private dataset create/version, then wait until Kaggle has processed it
kds() {   # kds DIR SLUG MSG
  local out i
  if "$KAGGLE" datasets status "$U/$2" > /dev/null 2>&1; then out=$("$KAGGLE" datasets version -p "$1" -m "$3" -t -r skip -q 2>&1)
  else out=$("$KAGGLE" datasets create -p "$1" -t -r skip -q 2>&1); fi           # private by default (no -u)
  echo "$(date -Is) $2: $out" >> "$WORK/upload.log"
  echo "$out" | grep -Eqi 'error|denied|forbidden|exception|failed' && { echo "$out" | tail -n 3; return 1; }
  for i in $(seq 1 120); do case "$("$KAGGLE" datasets status "$U/$2" 2>&1 | tr A-Z a-z)" in *ready*) return 0;; esac; sleep "${KDS_POLL_S:-30}"; done
  return 1
}
dsmeta() { printf '{"title": "%s", "id": "%s/%s", "licenses": [{"name": "other"}]}\n' "$2" "$U" "$2" > "$1/dataset-metadata.json"; }

run_step() { python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['step'])" "$R/status.json" 2>/dev/null || echo 0; }
train_stopped() { python3 -c "import json,sys;sys.exit(0 if json.load(open(sys.argv[1])).get('stopped') else 1)" "$R/status.json" 2>/dev/null; }
