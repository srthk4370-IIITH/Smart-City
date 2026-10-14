#!/usr/bin/env bash
# Builds SmartCityEdge.apk without Gradle: aapt2 -> javac -> d8 -> zip native libs -> zipalign -> apksigner.
# Native lib: the Go backend (app/device/edge-agent).
# (exactly the versions that run there today). NPU-side (Hexagon) libs go to assets/dsp because some
# share file names with ARM libs (libQnnSystem.so, libQnnHtpNetRunExtensions.so); EdgeService copies
# them to files/dsp and points ADSP_LIBRARY_PATH there.
# Needs ~/android-sdk (build-tools 34, platform 34) + JDK 17.
#   bash app/android/build_apk.sh            # -> app/android/out/SmartCityEdge.apk
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$(dirname "$HERE")"
SDK=~/android-sdk; BT=$SDK/build-tools/34.0.0; JAR=$SDK/platforms/android-34/android.jar
ADB=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
R=/data/local/tmp/genie_bundle
W=~/apk_build; rm -rf $W; mkdir -p $W/res/mipmap $W/res/values $W/gen $W/classes $W/pkg/lib/arm64-v8a $W/assets/app
OUT=$HERE/out; mkdir -p $OUT
# Only the Go backend is packaged. Genie + QAIRT run from the QIDK's existing runtime
# (/data/local/tmp/genie_bundle) inside the shell-user backend, the only user allowed to use the NPU.
cp $APP/device/edge-agent $W/pkg/lib/arm64-v8a/libedgeagent.so
# genied: the persistent Genie dialog daemon (app/genied). Packaged alongside the backend so a
# reinstall or a wiped /data/local/tmp cannot silently drop the fast path - EdgeService copies it
# out on every start, exactly like libedgeagent.so. Optional: the app works without it.
if [ -f $APP/device/genied ]; then
  cp $APP/device/genied $W/pkg/lib/arm64-v8a/libgenied.so
else
  echo "  note: app/device/genied not built (app/genied/build.sh); packaging without the daemon"
fi
ls -la $W/pkg/lib/arm64-v8a | awk 'NR>3{print "  ", $5, $9}'

# resources + assets
cp $APP/device/web/icon-192.png $W/res/mipmap/ic_launcher.png
echo '<resources><string name="app_name">Smart City Edge</string></resources>' > $W/res/values/strings.xml
mkdir -p $W/res/xml && cp $HERE/res/xml/*.xml $W/res/xml/
cp -r $APP/device/web $W/assets/app/web
mkdir -p $W/assets/app/data && cp $APP/device/data/sensors.json $W/assets/app/data/
$BT/aapt2 compile --dir $W/res -o $W/res.zip
$BT/aapt2 link -I $JAR --manifest $HERE/AndroidManifest.xml -A $W/assets --java $W/gen \
  --min-sdk-version 29 --target-sdk-version 34 -o $W/base.apk $W/res.zip

# code
javac -source 17 -target 17 -encoding UTF-8 -Xlint:-options -classpath $JAR -d $W/classes \
  $(find $HERE/src $W/gen -name '*.java')
$BT/d8 --lib $JAR --min-api 29 --output $W $(find $W/classes -name '*.class')

# package, align, sign
cp $W/base.apk $W/unsigned.apk
(cd $W && zip -q -j unsigned.apk classes.dex)
(cd $W/pkg && zip -q -r -0 ../unsigned.apk lib)
$BT/zipalign -f -p 4 $W/unsigned.apk $W/aligned.apk
KS=~/.android-debug.keystore
[ -f $KS ] || keytool -genkeypair -keystore $KS -storepass android -keypass android -alias debug \
  -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=SmartCityEdge Debug" >/dev/null 2>&1
$BT/apksigner sign --ks $KS --ks-pass pass:android --key-pass pass:android --out $OUT/SmartCityEdge.apk $W/aligned.apk
$BT/apksigner verify $OUT/SmartCityEdge.apk && ls -la $OUT/SmartCityEdge.apk
