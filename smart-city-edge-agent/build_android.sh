#!/bin/bash
set -e

export NDK_PATH="/mnt/c/Users/hp/Desktop/qidk/android-ndk/android-ndk-r26d"
export QNN_SDK_ROOT="/mnt/c/Users/hp/Desktop/qidk/qairt_temp_2_50/qairt/2.50.40.260831"

cd /mnt/c/Users/hp/Desktop/qidk/smart-city-edge-agent/llama.cpp
mkdir -p build-android
cd build-android

cmake .. \
    -DCMAKE_TOOLCHAIN_FILE="$NDK_PATH/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI=arm64-v8a \
    -DANDROID_PLATFORM=android-28 \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_QNN=ON \
    -DQNN_SDK_PATH="$QNN_SDK_ROOT"

make -j4 llama-cli
