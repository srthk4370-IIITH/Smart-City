#!/usr/bin/env bash
# pull_build.sh: docker pull of the Snapdragon toolchain image with a stall watchdog (first pull hung at 477 MB, 2026-11-04 ~00:58),
# then build_server.sh (image present -> straight to the compile). Progress: build_server.log + pull.log; heartbeat line every minute.
set -u
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-04_split/gpu; L=$P/build_server.log; PL=$P/pull.log
IMG=ghcr.io/snapdragon-toolchain/arm64-android:v0.8; DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$L"; }
for a in 1 2 3 4 5 6; do
  "$DOCKER" image inspect "$IMG" > /dev/null 2>&1 && break
  log "pull attempt $a"; : > "$PL"
  "$DOCKER" pull "$IMG" >> "$PL" 2>&1 & pp=$!
  last=-1; still=0
  while kill -0 $pp 2>/dev/null; do
    sleep 60; n=$(wc -l < "$PL"); sz=$("$DOCKER" system df --format '{{.Size}}' 2>/dev/null | head -1)
    log "pull hb: lines=$n store=$sz $(tail -1 "$PL" | tr -d '\r' | cut -c1-60)"
    if [ "$n:$sz" = "$last" ]; then still=$((still+1)); else still=0; last="$n:$sz"; fi
    [ $still -ge 12 ] && { log "pull STALL 12 min -> kill, retry"; kill $pp; sleep 5; break; }
  done
  wait $pp 2>/dev/null
done
"$DOCKER" image inspect "$IMG" > /dev/null 2>&1 || { log "ABORT: image not pulled after 6 tries"; log "=== build_server done"; exit 1; }
log "image ready"; exec bash "$P/build_server.sh"
