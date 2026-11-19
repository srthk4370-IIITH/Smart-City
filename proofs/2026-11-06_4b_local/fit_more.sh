#!/usr/bin/env bash
# fit_more.sh: after fit_probe.sh found 6144: (a) fit probes at 5120 and 4096 with the same levers; (b) speed lever
# --mlp-chunk-min 4096 (MLP chunking only for forwards over 4096 tokens): fit at 6144 + 3 probe steps + 5 real-mode steps.
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local
mkdir -p $D/logs/run2_5120_4096 $D/logs/run3_chunk_min4096
LENS=5120 NOSPEED=1 bash $D/fit_probe.sh; LENS=4096 NOSPEED=1 bash $D/fit_probe.sh
mv $D/logs/summary.txt $D/logs/*probe_5120.log $D/logs/*probe_4096.log $D/logs/run2_5120_4096/
LEV="--head-cpu --ckpt-offload --mlp-chunk 1024 --mlp-chunk-min 4096 --lean-host" LENS=6144 bash $D/fit_probe.sh
mv $D/logs/summary.txt $D/logs/*_6144.log $D/logs/run3_chunk_min4096/
