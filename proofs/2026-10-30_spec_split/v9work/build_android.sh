# board build of htpd v9: exactly as v8x5 (build_htpd_wsl.sh, NDK r26d, llama.cpp 620d2225 build-snapdragon libs/headers)
H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/htpd
O=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split/v9
nice -n 15 bash $H/build_htpd_wsl.sh $H $O 2>&1 | grep -vE "^\s*$" | tail -5
cp $H/htpd.cpp $O/htpd_v9.cpp; md5sum $O/htpd_v9.cpp
R=~/ndk/android-ndk-r26d/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf
$R -d $O/htpd | grep NEEDED; $R -d /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/v8x5/htpd | grep NEEDED
