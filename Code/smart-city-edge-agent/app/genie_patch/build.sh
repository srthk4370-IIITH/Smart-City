#!/bin/bash
# Rebuilds libGenie.so (aarch64-android) from the QAIRT 2.50 Genie sample source.
#
# Produces two libraries so on-device A/B can separate "rebuilt from source" effects
# from "patch" effects:
#   libGenie_rebuilt_stock.so  stock source + build_fix.patch only
#   libGenie.so                stock source + build_fix.patch + genie_cb_fixes.patch
#
# Flags: the SDK's make/Application.mk (-std=c++2a -O3 -frtti -fexceptions
# -fvisibility=hidden, GenieSymbols.default version script, --strip-all, android-21,
# max-page-size=16384) with APP_STL=c++_static, because the stock QAIRT libGenie.so
# links libc++ statically (NEEDED = libc, libm, libdl, liblog only).
#
# Run inside WSL:  bash build.sh
# Needs: QAIRT SDK, Android NDK r26d, rustup/cargo with target aarch64-linux-android.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SDK="${SDK:-$HOME/qairt/qairt/2.50.0.260828}"
NDK="${ANDROID_NDK_ROOT:-$HOME/ndk/android-ndk-r26d}"
W="${WORK:-$HOME/genie_patch_build}"
CARGO="${CARGO:-$HOME/.cargo/bin/cargo}"
JOBS="${JOBS:-$(nproc)}"
TC="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"
echo "SDK=$SDK  NDK=$NDK  WORK=$W"

# fresh copy of the Genie example laid out so Android.mk's ../../../../include resolves
prepare() { # $1 = tree root
  rm -rf "$1"
  mkdir -p "$1/examples/Genie"
  ln -s "$SDK/include" "$1/include"
  cp -r "$SDK/examples/Genie/Genie" "$1/examples/Genie/Genie"
}
prepare "$W/stock_rebuild"
prepare "$W/sdk"
rm -rf "$W/orig" && cp -r "$SDK/examples/Genie/Genie" "$W/orig"   # pristine, for diffs/tests

( cd "$W/stock_rebuild" && patch -p1 --forward < "$HERE/build_fix.patch" )
( cd "$W/sdk" && patch -p1 --forward < "$HERE/build_fix.patch" \
               && patch -p1 --forward < "$HERE/genie_cb_fixes.patch" )

# Rust tokenizer static lib (same source in both trees: build once, copy)
export CC_aarch64_linux_android="$TC/aarch64-linux-android21-clang"
export CXX_aarch64_linux_android="$TC/aarch64-linux-android21-clang++"
export AR_aarch64_linux_android="$TC/llvm-ar"
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$TC/aarch64-linux-android21-clang"
RUST_DIR="src/qualla/tokenizers/rust"
RUST_A="target/aarch64-linux-android/release/libtokenizers_capi.a"
G="$W/sdk/examples/Genie/Genie"
GS="$W/stock_rebuild/examples/Genie/Genie"
"$CARGO" build --release --locked --manifest-path "$G/$RUST_DIR/Cargo.toml" --target aarch64-linux-android
mkdir -p "$(dirname "$GS/$RUST_DIR/$RUST_A")"
cp "$G/$RUST_DIR/$RUST_A" "$GS/$RUST_DIR/$RUST_A"

ndk() { # $1 = Genie dir
  ( cd "$1" && ANDROID_NDK_ROOT="$NDK" "$NDK/ndk-build" -j"$JOBS" APP_STL=c++_static \
      APP_ALLOW_MISSING_DEPS=true APP_ABI="arm64-v8a" NDK_PROJECT_PATH=./ \
      NDK_APPLICATION_MK=make/Application.mk APP_BUILD_SCRIPT=make/Android.mk )
}
ndk "$GS"
ndk "$G"

STOCK="$SDK/lib/aarch64-android/libGenie.so"
compare() { # $1 = built .so
  local so="$1"
  echo "---- $so"
  "$TC/llvm-nm" -D --defined-only "$STOCK" | awk '{print $NF}' | sort > /tmp/syms_a
  "$TC/llvm-nm" -D --defined-only "$so"    | awk '{print $NF}' | sort > /tmp/syms_b
  if diff -u /tmp/syms_a /tmp/syms_b; then
    echo "exported symbols: IDENTICAL to stock ($(wc -l < /tmp/syms_a))"
  fi
  "$TC/llvm-nm" -D --undefined-only "$STOCK" | awk '{print $NF}' | sort > /tmp/und_a
  "$TC/llvm-nm" -D --undefined-only "$so"    | awk '{print $NF}' | sort > /tmp/und_b
  echo "imports only in rebuilt: $(comm -13 /tmp/und_a /tmp/und_b | tr '\n' ' ')"
  echo "imports only in stock:   $(comm -23 /tmp/und_a /tmp/und_b | tr '\n' ' ')"
  "$TC/llvm-readelf" -d "$so" | grep -E "NEEDED|SONAME"
  ls -la "$so"
}
ls -la "$STOCK"
compare "$GS/libs/arm64-v8a/libGenie.so"
compare "$G/libs/arm64-v8a/libGenie.so"

cp "$GS/libs/arm64-v8a/libGenie.so" "$HERE/libGenie_rebuilt_stock.so"
cp "$G/libs/arm64-v8a/libGenie.so"  "$HERE/libGenie.so"
sha256sum "$STOCK" "$HERE/libGenie_rebuilt_stock.so" "$HERE/libGenie.so"
