#!/bin/bash
# htpd v9h board build (WSL, NDK r26d, same flags/libs as v9f: build_htpd_wsl.sh). ggml-hexagon untouched: htpd links the
# deployed libs in gpu_work/llama.cpp/build-snapdragon/bin. Output: this dir/htpd + htpd.md5 + htpd_v9h.cpp + v9h.patch
H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/htpd
O=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_htpd_v9h
nice -n 15 bash $H/build_htpd_wsl.sh $H $O 2>&1 | grep -E "error|warning|htpd" | tail -8
cp $H/htpd.cpp $O/htpd_v9h.cpp
diff -u /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_night/v9f/htpd_v9f.cpp $O/htpd_v9h.cpp | sed '1,2s#/mnt/c/Users/hp/Desktop/qidk/##' > $O/v9h.patch
md5sum $O/htpd_v9h.cpp
echo BUILD_DONE
