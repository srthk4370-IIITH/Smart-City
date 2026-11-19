#!/usr/bin/env bash
# native_build.sh (WSL): llama-server for the board GPU without the Docker image (its pull ran at ~10 MB/min, 2026-11-04).
# Same source as the board's llama.cpp-new (upstream 338fce6), NDK r29, Snapdragon preset flags minus -flto, OpenCL ON,
# Hexagon OFF (the GPU server never touches the NPU). It ships its own libs to /data/local/tmp/chatgpu/lib, so the NPU
# libs and the llama.cpp-new bench libs stay untouched. Output: gpu/srv/{llama-server,lib/*.so} + md5s. Log: native_build.log.
set -uo pipefail
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-04_split/gpu; L=$P/native_build.log; O=$P/srv
SRC=/mnt/c/Users/hp/gpu_work/llama.cpp-new; WS=$HOME/gpu_work/srv_src; B=$HOME/gpu_work/srv_build
NDK=$HOME/ndk/android-ndk-r29; CL=$HOME/gpu_work
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$L"; }
log "=== native_build start"
mkdir -p $WS && rsync -a --delete --exclude '.git' --exclude '/build*' --exclude '/pkg-android' --exclude '/models' --exclude '/media' $SRC/ $WS/ || { log "ABORT rsync"; exit 1; }
F="-march=armv8.7a+fp16+dotprod+i8mm -fvectorize -ffp-model=fast -fno-finite-math-only -D_GNU_SOURCE"
cmake -S $WS -B $B -G Ninja -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-34 -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_FLAGS="$F" -DCMAKE_CXX_FLAGS="$F" \
  -DBUILD_SHARED_LIBS=ON -DGGML_OPENMP=OFF -DGGML_LLAMAFILE=OFF -DGGML_OPENCL=ON -DGGML_HEXAGON=OFF -DLLAMA_OPENSSL=OFF \
  -DLLAMA_CURL=OFF -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
  -DOpenCL_INCLUDE_DIR=$CL/OpenCL-Headers -DOpenCL_LIBRARY=$CL/OpenCL-ICD-Loader/build_ndk/libOpenCL.so >> $L 2>&1 || { log "ABORT cmake"; log "=== native_build done"; exit 1; }
nice cmake --build $B -j6 --target llama-server >> $L 2>&1 || { log "ABORT build"; grep -E "error" $L | tail -5; log "=== native_build done"; exit 1; }
rm -rf $O; mkdir -p $O/lib; cp $B/bin/llama-server $O/; cp $B/bin/*.so $O/lib/ 2>/dev/null
cp $NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so $O/lib/
rm -f $O/lib/libOpenCL.so  # the board's /vendor/lib64/libOpenCL.so is the real driver
(cd $O && md5sum llama-server lib/*.so > MD5SUMS); ls -la $O $O/lib | tee -a $L
log "BUILD_RC=0"; log "=== native_build done"
