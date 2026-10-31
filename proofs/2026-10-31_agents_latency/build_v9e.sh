#!/bin/bash
H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/htpd
O=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_agents_latency/v9e
nice -n 15 bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split/v9work/build_host.sh $H ~/v9host/htpd_v9e 2>&1 | grep -E "error|warning: unused|md5|htpd_v9e" | tail -8
nice -n 15 bash $H/build_htpd_wsl.sh $H $O 2>&1 | grep -E "error|htpd" | tail -5
cp $H/htpd.cpp $O/htpd_v9e.cpp
echo BUILD_DONE
