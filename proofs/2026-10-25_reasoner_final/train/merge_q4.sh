#!/usr/bin/env bash
# owner order 2026-10-27: final checkpoint (612) -> merged Q4_0 GGUF -> Code/models_stage/${NAME}_q4_0.gguf + md5
set -e
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
free_mb() { timeout 30 $PS -NoProfile -Command "(Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes" < /dev/null 2>/dev/null | tr -dc 0-9; }  # 2026-10-31: available, not free (free never reaches 4 GB on this laptop)
until [ "$(free_mb)" -ge 1536 ]; do echo "$(date +%T) RAM $(free_mb) MB < 1.5 GB available, waiting"; sleep 60; done
NAME=${NAME:-rsn_v1}; CK=${CK:-~/smartcity_runs/reasoner_v1/run1/ckpt_step0612}
E=~/smartcity_runs/reasoner_v1/gguf/$NAME; mkdir -p $E; rm -rf $E/hf
LC=~/gpu_work/llama.cpp; export PYTHONPATH=$LC/gguf-py OMP_NUM_THREADS=4
H=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/train
nice -n 15 ~/venvs/rsn/bin/python $H/merge_lora.py $CK $E/hf
nice -n 15 ~/venvs/train/bin/python $LC/convert_hf_to_gguf.py $E/hf --outtype bf16 --outfile $E/bf16.gguf.part > $E/convert.log 2>&1
mv $E/bf16.gguf.part $E/bf16.gguf; rm -rf $E/hf
nice -n 15 $LC/build-host/bin/llama-quantize $E/bf16.gguf $E/${NAME}_q4_0.gguf.part Q4_0 4 > $E/quant.log 2>&1
mv $E/${NAME}_q4_0.gguf.part $E/${NAME}_q4_0.gguf; rm -f $E/bf16.gguf
D=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage; mkdir -p $D
cp $E/${NAME}_q4_0.gguf $D/${NAME}_q4_0.gguf.part && mv $D/${NAME}_q4_0.gguf.part $D/${NAME}_q4_0.gguf
(cd $D && md5sum ${NAME}_q4_0.gguf | tee ${NAME}_q4_0.gguf.md5); md5sum $E/${NAME}_q4_0.gguf; ls -la $D/${NAME}_q4_0.gguf
