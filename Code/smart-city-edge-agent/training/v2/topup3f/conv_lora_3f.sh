#!/usr/bin/env bash
# 3f/3g: convert PEFT LoRA adapters to GGUF LoRA (f16) once, for runtime --lora-scaled screening on the base Q4_0.
#   bash conv_lora_3f.sh NAME ADAPTER_DIR [NAME ADAPTER_DIR ...]   -> $R/lora_gguf/NAME.gguf
R=~/smartcity_runs/agents_v2_topup3f; L=~/gpu_work/llama.cpp; PY=~/venvs/train/bin/python; O=$R/lora_gguf; mkdir -p $O
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
while [ $# -ge 2 ]; do n=$1; d=$2; shift 2
  [ -s $O/$n.gguf ] && { echo "have $n"; continue; }
  PYTHONPATH=$L/gguf-py nice -n 19 $PY $L/convert_lora_to_gguf.py $d --base ~/models/llama-3.2-3b-instruct --outtype f16 \
     --outfile $O/$n.gguf.tmp > $O/$n.log 2>&1 && mv $O/$n.gguf.tmp $O/$n.gguf && echo "ok $n $(du -h $O/$n.gguf | cut -f1)" || { echo "FAIL $n"; tail -3 $O/$n.log; }
done
