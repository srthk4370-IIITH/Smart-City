#!/usr/bin/env bash
# Cross-compile genied (the persistent Genie dialog daemon) for arm64 Android.
#
# Unlike the backend, this binary CANNOT be CGO_ENABLED=0: it calls the Genie C API directly, which
# is the whole point (HANDBOOK 2.19). That means an NDK cross-compile and a dynamically linked PIE
# rather than the static binary we ship for edge-agent. The backend is unchanged and still static;
# if genied is absent or not listening, GenieRunner spawns the CLI exactly as before.
#
#   bash build.sh            # builds app/device/genied
#
# Requires:
#   ANDROID_NDK_ROOT  (or ~/ndk/android-ndk-r26d)
#   QAIRT_SDK         (default ~/qairt/qairt/2.50.0.260828)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SDK="${QAIRT_SDK:-$HOME/qairt/qairt/2.50.0.260828}"
NDK="${ANDROID_NDK_ROOT:-$HOME/ndk/android-ndk-r26d}"
[ -d "$SDK/include/Genie" ] || { echo "no Genie headers at $SDK/include/Genie"; exit 1; }
[ -d "$NDK" ] || { echo "no NDK at $NDK (set ANDROID_NDK_ROOT)"; exit 1; }

# cgo resolves -I/-L relative to the package dir, so stage the headers and the import library here.
# Both are gitignored: they belong to the SDK, not to this repo.
rm -rf "$HERE/include" "$HERE/lib"
mkdir -p "$HERE/include" "$HERE/lib"
cp "$SDK"/include/Genie/*.h "$HERE/include/"
cp "$SDK"/lib/aarch64-android/libGenie.so "$HERE/lib/"

CC="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android24-clang"
[ -x "$CC" ] || { echo "no clang at $CC"; exit 1; }

export PATH="$HOME/go-sdk/go/bin:$PATH"
cd "$HERE"
export CGO_ENABLED=1 GOOS=android GOARCH=arm64 CC="$CC"
# $ORIGIN so the binary finds libGenie.so next to itself on the device without LD_LIBRARY_PATH
# games for its direct dependency.
go build -buildmode=pie -ldflags "-extldflags '-Wl,-rpath,\$ORIGIN'" -o "$HERE/../device/genied" .

file "$HERE/../device/genied" 2>/dev/null || true
ls -la "$HERE/../device/genied"
echo
echo "Deploy: push genied next to libGenie.so in the runtime bundle, then"
echo "  LD_LIBRARY_PATH=<runtime>/qairt_2_50_libs ADSP_LIBRARY_PATH='<runtime>/dsp_2_50;/vendor/dsp/cdsp;...' \\"
echo "    ./genied -bundle /data/local/tmp/genie_bundle_ft -config smartcity_agent.json &"
