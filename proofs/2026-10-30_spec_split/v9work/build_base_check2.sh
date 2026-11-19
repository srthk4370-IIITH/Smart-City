W=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split/v9work
H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/htpd
bash $H/build_htpd_wsl.sh $H /tmp/base_android2 > /dev/null 2>&1; cat /tmp/base_android2/htpd.md5
for N in 26d 29; do
 NDK=~/ndk/android-ndk-r$N bash $H/build_htpd_wsl.sh $H /tmp/b_$N >/dev/null 2>&1; echo r$N $(cat /tmp/b_$N/htpd.md5)
done
S=~/ndk/android-ndk-r29/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip
V=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/v8x5/htpd
for f in $V /tmp/b_26d/htpd /tmp/b_29/htpd; do $S -o /tmp/s.bin $f; echo "$f stripped $(md5sum < /tmp/s.bin) $(stat -c %s $f)"; done
~/ndk/android-ndk-r29/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf -p .comment $V | head
