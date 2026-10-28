#!/usr/bin/env bash
# STANDALONE (detach.sh): build the HTP skel (DSP side, ExternalProject htp-v75) in the existing build-snapdragon of
# each tree and copy libggml-htp-v75.so into its pkg-android lib. The first build only targeted llama/llama-bench,
# so the board failed to open an HTP session (0x80000406: no skel). RAM gate: start at >= 3 GB available, pause the
# container below 2 GB, resume above 2.5 GB. usage: build_skels.sh <tree> [<tree> ...]; log logs/build_skels.log
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; L=$P/logs/build_skels.log
IMG=ghcr.io/snapdragon-toolchain/arm64-android:v0.8
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$L"; }
avail() { powershell.exe -NoProfile -Command "[int](Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue" | tr -d '\r'; }
for T in "$@"; do
  n=sce_skel_$(basename "$T")
  log "=== skel $T"
  until [ "$(avail)" -ge 3072 ]; do log "waiting for RAM ($(avail) MB < 3072)"; sleep 60; done
  "$DOCKER" info >/dev/null 2>&1 || { "/mnt/c/Program Files/Docker/Docker/Docker Desktop.exe" >/dev/null 2>&1 & disown; for i in $(seq 1 60); do "$DOCKER" info >/dev/null 2>&1 && break; sleep 10; done; }
  "$DOCKER" rm -f "$n" >/dev/null 2>&1
  "$DOCKER" run -d --name "$n" --platform linux/amd64 -v "$(wslpath -w "$T"):/workspace" -w /workspace "$IMG" \
    bash -c "set -x; cmake --build build-snapdragon -j2 --target htp-v75 && cp build-snapdragon/ggml/src/ggml-hexagon/libggml-htp-v75.so pkg-android/llama.cpp/lib/ && echo SKEL_RC=0" >/dev/null
  paused=0
  while [ "$("$DOCKER" inspect -f '{{.State.Running}}' "$n" 2>/dev/null)" = "true" ]; do
    a=$(avail)
    if [ "$paused" = 0 ] && [ "$a" -lt 2048 ]; then "$DOCKER" pause "$n" >/dev/null && paused=1 && log "PAUSED ($a MB)"; fi
    if [ "$paused" = 1 ] && [ "$a" -gt 2560 ]; then "$DOCKER" unpause "$n" >/dev/null && paused=0 && log "resumed ($a MB)"; fi
    sleep 15
  done
  "$DOCKER" logs "$n" 2>&1 | tail -30 >> "$L"; "$DOCKER" rm "$n" >/dev/null 2>&1
  ls -la "$T/pkg-android/llama.cpp/lib/libggml-htp-v75.so" >> "$L" 2>&1 && md5sum "$T/pkg-android/llama.cpp/lib/libggml-htp-v75.so" | tee -a "$L"
done
log "=== SKELS_DONE"
