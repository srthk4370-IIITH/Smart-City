#!/usr/bin/env bash
# build_server.sh: Android llama-server from C:/Users/hp/gpu_work/llama.cpp-new (upstream 338fce65, Snapdragon preset,
# OpenCL + Hexagon; same tree as the 2026-10-29 GPU bench and /data/local/tmp/llama.cpp-new on the board), incremental in
# build-snapdragon. Output: proofs/2026-11-04_split/gpu/llama-server (+ md5). Owner: 2B chat on the GPU (2026-11-04 night).
set -uo pipefail
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-04_split/gpu; L=$P/build_server.log
SRC=/mnt/c/Users/hp/gpu_work/llama.cpp-new; IMG=ghcr.io/snapdragon-toolchain/arm64-android:v0.8
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"; NAME=sce_build_server
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$L"; }
avail() { powershell.exe -NoProfile -Command "[int](Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue" | tr -d '\r'; }
log "=== build_server start (available $(avail) MB)"
if ! "$DOCKER" info >/dev/null 2>&1; then
  log "starting Docker Desktop"; "/mnt/c/Program Files/Docker/Docker/Docker Desktop.exe" >/dev/null 2>&1 & disown
  for i in $(seq 1 60); do "$DOCKER" info >/dev/null 2>&1 && break; sleep 10; done
fi
"$DOCKER" info >/dev/null 2>&1 || { log "ABORT: docker engine not up"; exit 2; }
W=$(wslpath -w "$SRC"); "$DOCKER" rm -f "$NAME" >/dev/null 2>&1
"$DOCKER" run --rm --name "$NAME" --platform linux/amd64 -v "$W:/workspace" -w /workspace "$IMG" \
  bash -c "cmake --preset arm64-android-snapdragon-release -B build-snapdragon -DLLAMA_BUILD_SERVER=ON > /dev/null && cmake --build build-snapdragon -j3 --target llama-server && cp build-snapdragon/bin/llama-server pkg-android/llama.cpp/bin/ && echo BUILD_RC=0" >> "$L" 2>&1
cp "$SRC/pkg-android/llama.cpp/bin/llama-server" "$P/llama-server" && md5sum "$P/llama-server" | tee "$P/llama-server.md5" | tee -a "$L"
grep -E "BUILD_RC|error:" "$L" | tail -8; log "=== build_server done"
