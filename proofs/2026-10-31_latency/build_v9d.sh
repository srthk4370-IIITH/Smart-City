#!/bin/bash
# v9d builds: host (WSL CPU, for host tests) + board (as v9c: build_htpd_wsl.sh, NDK r26d)
H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/htpd
O=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_latency/v9d
mkdir -p ~/v9host
nice -n 15 bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split/v9work/build_host.sh $H ~/v9host/htpd_v9d 2>&1 | grep -vE "^\s*$" | tail -5
nice -n 15 bash $H/build_htpd_wsl.sh $H $O 2>&1 | grep -vE "^\s*$" | tail -5
cp $H/htpd.cpp $O/htpd_v9d.cpp
echo BUILD_DONE
