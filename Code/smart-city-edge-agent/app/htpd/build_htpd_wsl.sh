#!/usr/bin/env bash
# Build htpd for the QIDK (Android arm64) in WSL with the NDK there (no Docker): the compile and link flags of
# build_htpd.sh (CMake's commands for tools/htpd in llama.cpp 620d2225 build-snapdragon), against the headers of
# that tree and the deployed libraries in build-snapdragon/bin. Used for htpd v8 (2026-10-26): Docker Desktop was
# not running and the laptop had to stay light. Only the toolchain differs from build_htpd.sh (NDK r26d here,
# r29 in the docker image); htpd talks to libllama through the C API and links libc++ statically.
#
# usage (inside WSL): build_htpd_wsl.sh <src dir with htpd.cpp> <out dir>   -> <out>/htpd + <out>/htpd.md5
set -euo pipefail
SRC=$(cd "$1" && pwd)
OUT=$2
mkdir -p "$OUT/obj"
LLAMA=${LLAMA_DIR:-/mnt/c/Users/hp/gpu_work/llama.cpp}
BIN=$LLAMA/build-snapdragon/bin
NDK=${NDK:-$HOME/ndk/android-ndk-r26d}/toolchains/llvm/prebuilt/linux-x86_64
CXX="$NDK/bin/clang++ --target=aarch64-none-linux-android34 --sysroot=$NDK/sysroot"
FLAGS="-g -DANDROID -fdata-sections -ffunction-sections -funwind-tables -fstack-protector-strong -no-canonical-prefixes -D_FORTIFY_SOURCE=2 -Wformat -Werror=format-security -march=armv8.7a+fp16+dotprod+i8mm -fvectorize -ffp-model=fast -fno-finite-math-only -flto -D_GNU_SOURCE -O3 -DNDEBUG"
$CXX -std=gnu++17 -DGGML_BACKEND_SHARED -DGGML_SHARED -DGGML_USE_CPU -DGGML_USE_HEXAGON -DGGML_USE_OPENCL -DLLAMA_SHARED \
  -I"$LLAMA/include" -I"$LLAMA/ggml/include" $FLAGS -fPIE -Wall -Wextra -Wno-unused-function \
  -o "$OUT/obj/htpd.cpp.o" -c "$SRC/htpd.cpp"
$CXX $FLAGS -static-libstdc++ -Wl,--build-id=sha1 -Wl,--no-undefined -Wl,--gc-sections "$OUT/obj/htpd.cpp.o" -o "$OUT/htpd" \
  "$BIN/libllama.so" "$BIN/libggml.so" -pthread "$BIN/libggml-cpu.so" "$BIN/libggml-opencl.so" "$BIN/libggml-hexagon.so" \
  "$BIN/libggml-base.so" -latomic -lm
rm -rf "$OUT/obj"
(cd "$OUT" && md5sum htpd | tee htpd.md5)
