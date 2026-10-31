#!/bin/bash
# rebuild the unmodified (v8x5) htpd.cpp with build_htpd_wsl.sh (NDK r26d) and the host CPU build; compare md5 with v8x5
set -x
W=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split/v9work
H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/htpd
bash $H/build_htpd_wsl.sh $W/base_src $W/base_android > $W/base_android.log 2>&1
cat $W/base_android/htpd.md5; cat /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/v8x5/htpd.md5
