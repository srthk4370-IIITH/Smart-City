#!/usr/bin/env bash
# STANDALONE, run inside WSL via proofs/detach.sh: build the latest llama.cpp (C:/Users/hp/gpu_work/llama.cpp-new, upstream
# 338fce65, 2026-10-27) for the QIDK with its Snapdragon preset (Hexagon + OpenCL) in the official toolchain image,
# then build htpd (our app/htpd/htpd.cpp) against it. Nothing touches the board or the deployed build.
#   bash build_newhex.sh            -> C:/Users/hp/gpu_work/llama.cpp-new/pkg-android/ (libs, htp skels, llama-bench)
#                                      + proofs/2026-10-27_reasoner_fast/htpd_new/htpd (md5 in htpd.md5)
# RAM guard (owner): starts only at >= 5 GB available; the build container is paused while Windows "Available MBytes" < 2048 and resumed at > 2560.
# Log: proofs/2026-10-27_reasoner_fast/logs/build_newhex.log
set -uo pipefail
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast
L=$P/logs/build_${2:-newhex}.log
SRC=${1:-/mnt/c/Users/hp/gpu_work/llama.cpp-new}
ON=${2:-htpd_new}
HT=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/htpd
IMG=ghcr.io/snapdragon-toolchain/arm64-android:v0.8
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
NAME=sce_build_${2:-newhex}
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$L"; }
avail() { powershell.exe -NoProfile -Command "[int](Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue" | tr -d '\r'; }
winp() { wslpath -w "$1"; }

log "=== build_newhex start (available $(avail) MB)"
until [ "$(avail)" -ge 3072 ]; do log "waiting for RAM (available $(avail) MB < 3072, owner gate)"; sleep 60; done
if ! "$DOCKER" info >/dev/null 2>&1; then
  log "starting Docker Desktop"; "/mnt/c/Program Files/Docker/Docker/Docker Desktop.exe" >/dev/null 2>&1 & disown
  for i in $(seq 1 60); do "$DOCKER" info >/dev/null 2>&1 && break; sleep 10; done
fi
"$DOCKER" info >/dev/null 2>&1 || { log "ABORT: docker engine not up"; exit 2; }
log "pull $IMG (about 2.5 GB compressed)"
"$DOCKER" pull "$IMG" >> "$L" 2>&1 || { log "ABORT: pull failed"; exit 3; }

cp "$SRC/docs/backend/snapdragon/CMakeUserPresets.json" "$SRC/CMakeUserPresets.json"
mkdir -p "$P/$ON"
cp "$HT/htpd.cpp" "$HT/htpd_logic.h" "$HT/reason_logic.h" "$P/$ON/"
W=$(winp "$SRC"); O=$(winp "$P/$ON")
# htpd: same flags as the deployed build, against the new headers and libs (the C API may have moved: errors are logged)
HTPD_CMD='NDK=$ANDROID_NDK_ROOT; [ -d "$NDK" ] || NDK=$(ls -d /opt/android-ndk-* | tail -1);
  CXX="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/clang++ --target=aarch64-none-linux-android34 --sysroot=$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot";
  FL="-DANDROID -fdata-sections -ffunction-sections -funwind-tables -fstack-protector-strong -no-canonical-prefixes -D_FORTIFY_SOURCE=2 -march=armv8.7a+fp16+dotprod+i8mm -fvectorize -ffp-model=fast -fno-finite-math-only -D_GNU_SOURCE -O3 -DNDEBUG";
  B=/workspace/build-snapdragon/bin;
  $CXX -std=gnu++17 -DGGML_BACKEND_SHARED -DGGML_SHARED -DGGML_USE_CPU -DGGML_USE_HEXAGON -DGGML_USE_OPENCL -DLLAMA_SHARED -I/workspace/include -I/workspace/ggml/include $FL -fPIE -c /htpd/htpd.cpp -o /htpd/htpd.o &&
  $CXX $FL -static-libstdc++ -Wl,--gc-sections /htpd/htpd.o -o /htpd/htpd $B/libllama.so $B/libggml.so -pthread $B/libggml-cpu.so $B/libggml-opencl.so $B/libggml-hexagon.so $B/libggml-base.so -latomic -lm'
"$DOCKER" rm -f "$NAME" >/dev/null 2>&1
log "build (cmake preset arm64-android-snapdragon-release, -j2) + install + htpd"
"$DOCKER" run -d --name "$NAME" --platform linux/amd64 -v "$W:/workspace" -v "$O:/htpd" -w /workspace "$IMG" \
  bash -c "set -x; cmake --preset arm64-android-snapdragon-release -B build-snapdragon && cmake --build build-snapdragon -j2 --target llama llama-bench && mkdir -p pkg-android/llama.cpp/lib pkg-android/llama.cpp/bin && find build-snapdragon -name '*.so' -exec cp {} pkg-android/llama.cpp/lib/ \; && cp build-snapdragon/bin/llama-bench pkg-android/llama.cpp/bin/; $HTPD_CMD; echo BUILD_RC=\$?" >> "$L" 2>&1
paused=0
while [ "$("$DOCKER" inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = "true" ]; do
  a=$(avail)
  if [ "$paused" = 0 ] && [ "$a" -lt 2048 ]; then "$DOCKER" pause "$NAME" >/dev/null && paused=1 && log "PAUSED: available $a MB < 2048"; fi
  if [ "$paused" = 1 ] && [ "$a" -gt 2560 ]; then "$DOCKER" unpause "$NAME" >/dev/null && paused=0 && log "resumed: available $a MB"; fi
  sleep 15
done
"$DOCKER" logs "$NAME" >> "$L" 2>&1
"$DOCKER" rm "$NAME" >/dev/null 2>&1
ls -la "$SRC/pkg-android/llama.cpp/lib" >> "$L" 2>&1
md5sum "$P/$ON/htpd" 2>/dev/null | tee "$P/$ON/htpd.md5" | tee -a "$L"
grep -E "BUILD_RC|error:" "$L" | tail -15
log "=== build_newhex done"
