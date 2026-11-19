#!/usr/bin/env bash
# Shared guards for the rsn_v3 local scripts (source it). Run under WSL, normally via proofs/detach.sh.
#  status MSG            append "- <time> [script run] MSG" to kaggle/STATUS.md and echo it
#  need_ram MB [WAIT_MIN] wait until Windows free RAM >= MB (default 1536), give up after WAIT_MIN minutes (default 30)
#  need_disk PATH MB     refuse when PATH's filesystem has < MB free
#  new_dir DIR           refuse to reuse an existing output dir (a new run id is required)
#  md5_manifest DIR      write DIR/MD5SUMS for every file below DIR (except MD5SUMS)
set -u
QIDK=/mnt/c/Users/hp/Desktop/qidk
V3=$QIDK/proofs/2026-10-29_rsn_v3
KG=$V3/kaggle
R1=$QIDK/proofs/2026-10-25_reasoner_final
STATUS=$KG/STATUS.md
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
SCRIPT=${SCRIPT:-$(basename "$0" .sh)}
RUN_ID=${RUN_ID:-}

status() {
  [ -s "$STATUS" ] || printf '# rsn_v3 local pipeline status (append-only)\n\n' > "$STATUS"
  local l="- $(date '+%F %T') [$SCRIPT${RUN_ID:+ $RUN_ID}] $*"
  echo "$l" >> "$STATUS"; echo "$l"
}
die() { status "FAIL: $*"; exit "${2:-1}"; }

free_mb() { timeout 30 "$PS" -NoProfile -Command "(Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes" < /dev/null 2>/dev/null | tr -dc 0-9; }

need_ram() {
  local need=${1:-1536} wait=${2:-30} t=0 f
  while true; do
    f=$(free_mb)
    [ -n "$f" ] && [ "$f" -ge "$need" ] && return 0
    [ "$t" -ge "$wait" ] && die "Windows free RAM ${f:-?} MB < $need MB for $wait min" 4
    [ "$t" = 0 ] && status "waiting: Windows free RAM ${f:-?} MB < $need MB"
    sleep 60; t=$((t + 1))
  done
}

need_disk() {
  local p=$1 need=$2 f
  f=$(df -Pm "$p" | awk 'NR==2{print $4}')
  [ -n "$f" ] && [ "$f" -ge "$need" ] || die "disk: $p has ${f:-?} MB free < $need MB" 5
}

new_dir() {
  [ -e "$1" ] && die "output $1 already exists: refusing to overwrite, use a new run id" 6
  mkdir -p "$1"
}

md5_manifest() { (cd "$1" && find . -type f ! -name MD5SUMS ! -name '*.part' -print0 | sort -z | xargs -0 md5sum > MD5SUMS); }

check_run_id() {
  [ -n "$RUN_ID" ] || die "RUN_ID missing (usage: RUN_ID=r1 bash $0 ...)" 2
  case "$RUN_ID" in *[!A-Za-z0-9_.-]*) die "bad RUN_ID '$RUN_ID'" 2;; esac
}
