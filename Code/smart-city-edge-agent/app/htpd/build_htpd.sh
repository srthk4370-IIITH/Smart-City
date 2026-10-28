#!/usr/bin/env bash
# Rebuild ONLY htpd for the QIDK (Android arm64) with exactly the toolchain and flags of the deployed build
# (llama.cpp 620d2225 build-snapdragon, docker image ghcr.io/snapdragon-toolchain/arm64-android:v0.7, NDK r29),
# without touching build-snapdragon: the compile/link commands are the ones CMake generated for tools/htpd
# (build-snapdragon/compile_commands.json, build.ninja), run in the same paths, but the source directory and
# the object/binary directories are bind-mounted over the tree from OUT, and the libraries it links are copies.
#
# usage (Git Bash on the laptop, Docker Desktop running):
#   app/htpd/build_htpd.sh <src dir with htpd.cpp> <out dir>
#   e.g. build_htpd.sh Code/smart-city-edge-agent/app/htpd /c/Users/hp/gpu_work/htpd_v7
# result: <out>/bin/htpd (+ md5 in <out>/htpd.md5)
set -euo pipefail
winpath() { (cd "$1" && { pwd -W 2>/dev/null || pwd; }); }
SRC=$(winpath "$1")
OUT_ARG=$2
mkdir -p "$OUT_ARG/bin" "$OUT_ARG/obj"
OUT=$(winpath "$OUT_ARG")
LLAMA=${LLAMA_DIR:-C:/Users/hp/gpu_work/llama.cpp}
BIN_SRC=${LLAMA_BIN_UNIX:-/c/Users/hp/gpu_work/llama.cpp/build-snapdragon/bin}
for l in libllama.so libggml.so libggml-cpu.so libggml-opencl.so libggml-hexagon.so libggml-base.so; do
  cp -p "$BIN_SRC/$l" "$OUT_ARG/bin/$l"
done
DOCKER=${DOCKER:-"/c/Program Files/Docker/Docker/resources/bin/docker.exe"}
NDK=/opt/android-ndk-r29/toolchains/llvm/prebuilt/linux-x86_64
CXX="$NDK/bin/clang++ --target=aarch64-none-linux-android34 --sysroot=$NDK/sysroot"
FLAGS="-g -DANDROID -fdata-sections -ffunction-sections -funwind-tables -fstack-protector-strong -no-canonical-prefixes -D_FORTIFY_SOURCE=2 -Wformat -Werror=format-security  -march=armv8.7a+fp16+dotprod+i8mm -fvectorize -ffp-model=fast -fno-finite-math-only -flto -D_GNU_SOURCE -O3 -DNDEBUG -O3 -DNDEBUG"
COMPILE="$CXX -DGGML_BACKEND_SHARED -DGGML_SHARED -DGGML_USE_CPU -DGGML_USE_HEXAGON -DGGML_USE_OPENCL -DLLAMA_SHARED -I/workspace/src/../include -I/workspace/ggml/src/../include $FLAGS -fPIE -Xclang -fno-pch-timestamp -Wmissing-declarations -Wmissing-noreturn -Wall -Wextra -Wpedantic -Wcast-qual -Wno-unused-function -Wunreachable-code-break -Wunreachable-code-return -Wmissing-prototypes -Wextra-semi -o tools/htpd/CMakeFiles/htpd.dir/htpd.cpp.o -c /workspace/tools/htpd/htpd.cpp"
LINK="$CXX $FLAGS -static-libstdc++ -Wl,--build-id=sha1 -Wl,--no-undefined-version -Wl,--fatal-warnings -Wl,--no-undefined -Qunused-arguments   -Wl,--gc-sections tools/htpd/CMakeFiles/htpd.dir/htpd.cpp.o -o bin/htpd  bin/libllama.so  bin/libggml.so  -pthread  bin/libggml-cpu.so  bin/libggml-opencl.so  bin/libggml-hexagon.so  bin/libggml-base.so  -latomic -lm"
MSYS_NO_PATHCONV=1 "$DOCKER" run --rm \
  -v "$LLAMA:/workspace:ro" \
  -v "$SRC:/workspace/tools/htpd:ro" \
  -v "$OUT/obj:/workspace/build-snapdragon/tools/htpd/CMakeFiles/htpd.dir" \
  -v "$OUT/bin:/workspace/build-snapdragon/bin" \
  -w /workspace/build-snapdragon \
  ghcr.io/snapdragon-toolchain/arm64-android:v0.7 \
  bash -c "set -e; $COMPILE; $LINK"
md5sum "$OUT_ARG/bin/htpd" | tee "$OUT_ARG/htpd.md5"
