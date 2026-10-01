#!/bin/bash
set -e

LLAMA_DIR="/mnt/c/Users/hp/Desktop/qidk/smart-city-edge-agent/llama.cpp-master"
BUILD_DIR="$LLAMA_DIR/build-android"
NDK_PATH="/mnt/c/Users/hp/Desktop/qidk/android-ndk/android-ndk-r26d"
QNN_SDK_PATH="/mnt/c/Users/hp/Desktop/qidk/qairt_temp_2_50/qairt/2.50.40.240728"

mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

cmake .. \
  -DCMAKE_TOOLCHAIN_FILE="$NDK_PATH/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-28 \
  -DCMAKE_C_FLAGS="-march=armv8.4a+dotprod" \
  -DCMAKE_CXX_FLAGS="-march=armv8.4a+dotprod" \
  -DGGML_QNN=ON \
  -DQNN_SDK_PATH="$QNN_SDK_PATH" \
  -DGGML_OPENMP=OFF \
  -DLLAMA_OPENMP=OFF

make -j4 llama-cli
