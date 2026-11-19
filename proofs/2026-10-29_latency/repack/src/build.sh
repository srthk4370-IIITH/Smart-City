#!/usr/bin/env bash
# build libggml-hexagon.so from a given ggml-hexagon.cpp copy: build-snapdragon flags minus -flto, NDK r26d, Hexagon SDK 6.7.0.1 headers
set -euo pipefail
SRCCPP=$1; OUT=$2
L=/mnt/c/Users/hp/gpu_work/llama.cpp; G=$L/ggml/src/ggml-hexagon; B=$L/build-snapdragon
SDK=/mnt/c/Qualcomm/Hexagon_SDK/6.7.0.1
NDK=$HOME/ndk/android-ndk-r26d/toolchains/llvm/prebuilt/linux-x86_64
CXX="$NDK/bin/clang++ --target=aarch64-none-linux-android34 --sysroot=$NDK/sysroot"
FL="-g0 -DANDROID -fdata-sections -ffunction-sections -funwind-tables -fstack-protector-strong -no-canonical-prefixes -D_FORTIFY_SOURCE=2 -march=armv8.7a+fp16+dotprod+i8mm -fvectorize -ffp-model=fast -fno-finite-math-only -D_GNU_SOURCE -O3 -DNDEBUG -fPIC"
DEF="-DGGML_BACKEND_BUILD -DGGML_BACKEND_SHARED -DGGML_SCHED_MAX_COPIES=4 -DGGML_SHARED -D_GNU_SOURCE -D_XOPEN_SOURCE=600 -Dggml_hexagon_EXPORTS"
INC="-I$G -I$G/.. -I$G/htp -I$B/ggml/src/ggml-hexagon -I$L/ggml/include -I$SDK/incs -I$SDK/incs/stddef -I$SDK/utils/examples"
W=$(mktemp -d); trap "rm -rf $W" EXIT
$CXX -std=gnu++17 $DEF $INC $FL -c $SRCCPP -o $W/a.o &
$CXX -std=gnu++17 $DEF $INC $FL -c $G/htp-drv.cpp -o $W/b.o &
$NDK/bin/clang --target=aarch64-none-linux-android34 --sysroot=$NDK/sysroot -std=gnu11 -DGGML_SCHED_MAX_COPIES=4 -D_GNU_SOURCE -D_XOPEN_SOURCE=600 $INC $FL -c $B/ggml/src/ggml-hexagon/htp_iface_stub.c -o $W/s.o
wait
$CXX $FL -shared -static-libstdc++ -Wl,-soname,libggml-hexagon.so -Wl,--build-id=sha1 -Wl,--no-undefined -Wl,--gc-sections \
  $W/s.o $W/a.o $W/b.o -o $OUT $B/bin/libggml-base.so -llog -ldl -latomic -lm
md5sum $OUT; ls -la $OUT
