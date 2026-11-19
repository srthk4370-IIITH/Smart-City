# r3_edit_C1 (merged bf16 + neuron edits) -> bf16 GGUF -> Q4_0 (same steps/flags as export_4b.sh), staged with md5
set -o pipefail
LC=$HOME/gpu_work/llama.cpp; PYC=$HOME/venvs/train/bin/python
SRC=/mnt/c/Users/hp/qidk_models/r3_edit_C1; W=/mnt/c/Users/hp/AppData/Local/Temp/export_r3c1; mkdir -p $W
ST=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage; G=$ST/rsn_v3_4b_r3c1_q4_0.gguf
[ -s "$G" ] && { echo exists; exit 0; }
export PYTHONPATH=$LC/gguf-py OMP_NUM_THREADS=4
nice -n 15 $PYC $LC/convert_hf_to_gguf.py $SRC --outtype bf16 --outfile $W/bf16.gguf.part 2>&1 | tr '\r' '\n' | grep -v '^Writing:' | tail -3 || exit 1
mv $W/bf16.gguf.part $W/bf16.gguf
nice -n 15 $LC/build-host/bin/llama-quantize $W/bf16.gguf $G.part Q4_0 4 > $W/quant.log 2>&1 || { tail -2 $W/quant.log; exit 1; }
M=$(md5sum < $G.part | cut -d' ' -f1); echo "$M  rsn_v3_4b_r3c1_q4_0.gguf" > $G.md5; mv $G.part $G; rm -f $W/bf16.gguf
echo "EXPORT_DONE $G $M"
