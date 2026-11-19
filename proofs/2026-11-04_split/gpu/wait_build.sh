#!/usr/bin/env bash
# wait_build.sh [pull_pid]: replaces pull_build.sh's watchdog. A non-TTY docker pull prints nothing while a layer downloads,
# so the progress signal here is the laptop's received network bytes. A stall is < 2 MB/min for 15 min: kill that pull and
# start a new one (5 tries; partial layers resume from the content store). Once the image is present -> build_server.sh.
set -u
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-04_split/gpu; L=$P/build_server.log; PL=$P/pull.log
IMG=ghcr.io/snapdragon-toolchain/arm64-android:v0.8; DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$L"; }
rx() { powershell.exe -NoProfile -Command "(Get-NetAdapterStatistics | Measure-Object ReceivedBytes -Sum).Sum" | tr -d '\r'; }
pp=${1:-}; tries=0
while ! "$DOCKER" image inspect "$IMG" > /dev/null 2>&1; do
  if [ -z "$pp" ] || ! kill -0 "$pp" 2>/dev/null; then
    tries=$((tries+1)); [ $tries -gt 5 ] && { log "ABORT: image not pulled after 5 new pulls"; log "=== build_server done"; exit 1; }
    log "pull start $tries"; "$DOCKER" pull "$IMG" >> "$PL" 2>&1 & pp=$!
  fi
  r0=$(rx); slow=0; tot=0
  while kill -0 "$pp" 2>/dev/null; do
    sleep 60; r1=$(rx); mb=$(( (r1 - r0) / 1048576 )); r0=$r1; tot=$((tot+mb))
    log "pull hb: ${mb} MB/min, ${tot} MB this pull | $(tail -1 "$PL" | tr -d '\r' | cut -c1-50)"
    if [ $mb -lt 2 ]; then slow=$((slow+1)); else slow=0; fi
    [ $slow -ge 15 ] && { log "pull STALL 15 min -> kill, retry"; kill "$pp"; sleep 5; break; }
  done
  pp=""
done
log "image ready"; exec bash "$P/build_server.sh"
