#!/usr/bin/env bash
# Build libllama_p.so (llama.cpp 620d2225 + patch_llama_keep.py) for the QIDK in WSL: the compile flags of
# build-snapdragon (minus -flto), NDK r26d, SONAME libllama_p.so so it never shadows the deployed libllama.so.
set -euo pipefail
S=~/llama_p; O=~/llama_p/obj; mkdir -p $O
BIN=/mnt/c/Users/hp/gpu_work/llama.cpp/build-snapdragon/bin
NDK=$HOME/ndk/android-ndk-r26d/toolchains/llvm/prebuilt/linux-x86_64
CXX="$NDK/bin/clang++ --target=aarch64-none-linux-android34 --sysroot=$NDK/sysroot"
FL="-g0 -DANDROID -fdata-sections -ffunction-sections -funwind-tables -fstack-protector-strong -no-canonical-prefixes -D_FORTIFY_SOURCE=2 -march=armv8.7a+fp16+dotprod+i8mm -fvectorize -ffp-model=fast -fno-finite-math-only -D_GNU_SOURCE -O3 -DNDEBUG -fPIC"
DEF="-DGGML_BACKEND_SHARED -DGGML_SHARED -DGGML_USE_CPU -DGGML_USE_HEXAGON -DGGML_USE_OPENCL -DLLAMA_BUILD -DLLAMA_SHARED -Dllama_EXPORTS"
INC="-I$S/src -I$S/build-src -I$S/include -I$S/ggml/include"
srcs=$(cd $S/src && ls *.cpp models/*.cpp)
echo "$srcs" | xargs -P 2 -I{} sh -c "o=$O/\$(echo {} | tr / _).o; [ $S/src/{} -ot \$o ] || $CXX -std=gnu++17 $DEF $INC $FL -c $S/src/{} -o \$o"
$CXX $FL -shared -static-libstdc++ -Wl,-soname,libllama_p.so -Wl,--build-id=sha1 -Wl,--no-undefined -Wl,--gc-sections $O/*.o -o $S/libllama_p.so \
  $BIN/libggml.so $BIN/libggml-cpu.so $BIN/libggml-opencl.so $BIN/libggml-hexagon.so $BIN/libggml-base.so -latomic -lm
md5sum $S/libllama_p.so
