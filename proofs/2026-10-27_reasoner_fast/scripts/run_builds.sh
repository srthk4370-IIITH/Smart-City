#!/usr/bin/env bash
# STANDALONE (detach.sh): build upstream (llama.cpp-new -> htpd_new) then the 32x4-kernel variant (llama.cpp-k4 ->
# htpd_k4). Runs a private copy of build_newhex.sh so later edits never change a running job.
S=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/scripts
cp "$S/build_newhex.sh" /tmp/bnh_$$.sh
bash /tmp/bnh_$$.sh /mnt/c/Users/hp/gpu_work/llama.cpp-new htpd_new
cp /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/logs/build_htpd_new.log /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/logs/build_newhex.log  # chain.sh step 2 waits on this name
bash /tmp/bnh_$$.sh /mnt/c/Users/hp/gpu_work/llama.cpp-k4 htpd_k4
echo ALL_BUILDS_DONE
