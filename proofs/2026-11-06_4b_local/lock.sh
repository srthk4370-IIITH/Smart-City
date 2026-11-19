#!/usr/bin/env bash
# lock.sh take|release : the fit_4b line in GPU_LOCK (take refuses when another holder exists)
L=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK
case $1 in
take) if [ -e $L ] && ! grep -q "^fit_4b" $L; then echo "HELD: $(cat $L)"; exit 1; fi
      [ -e $L ] || echo "fit_4b $(date -Is) pid=$$ (fit/probe agent 2026-11-06)" > $L; cat $L
      nvidia-smi --query-gpu=memory.used --format=csv,noheader;;
release) grep -q "^fit_4b" $L 2>/dev/null && rm -f $L; ls $L 2>&1;;
esac
