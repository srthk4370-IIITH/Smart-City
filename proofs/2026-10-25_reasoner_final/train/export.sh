#!/usr/bin/env bash
# export.sh <ckpt_dir> <tag>: merge -> BF16 GGUF -> imatrix-free Q4_0 + Q4_K_M (host eval); intermediates deleted.
set -e
CK=$1; TAG=$2; E=~/smartcity_runs/reasoner_v1/gguf/$TAG; mkdir -p $E
LC=~/gpu_work/llama.cpp; export PYTHONPATH=$LC/gguf-py OMP_NUM_THREADS=4
H=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/train
[ -f $E/$TAG-q4_0.gguf ] && { echo "exists $TAG"; exit 0; }
nice -n 15 ~/venvs/rsn/bin/python $H/merge_lora.py $CK $E/hf
nice -n 15 ~/venvs/train/bin/python $LC/convert_hf_to_gguf.py $E/hf --outtype bf16 --outfile $E/$TAG-bf16.gguf.part > $E/convert.log 2>&1
mv $E/$TAG-bf16.gguf.part $E/$TAG-bf16.gguf; rm -rf $E/hf
for q in Q4_0 Q4_K_M; do lq=$(echo $q | tr A-Z a-z)
  nice -n 15 $LC/build-host/bin/llama-quantize $E/$TAG-bf16.gguf $E/$TAG-$lq.gguf.part $q 4 > $E/quant_$lq.log 2>&1
  mv $E/$TAG-$lq.gguf.part $E/$TAG-$lq.gguf; done
rm -f $E/$TAG-bf16.gguf; ls -la $E | grep gguf
