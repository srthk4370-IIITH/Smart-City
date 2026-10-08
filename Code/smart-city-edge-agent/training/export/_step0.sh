source ~/venvs/train/bin/activate
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
M=$(ls -d ~/smartcity_runs/agents_*/merged | tail -1)
cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/export
rm -f ../results/fakequant_step0.jsonl
[ -f ~/fq_int4/config.json ] && [ "$(ls ~/fq_int4/*.safetensors 2>/dev/null | wc -l)" -ge 2 ] || python fakequant_eval.py --merged "$M" --prep-int4 ~/fq_int4 > ~/step0_prep.log 2>&1
python fakequant_eval.py --merged ~/fq_int4 --mode int4 --per-role 10 > ~/step0_int4.log 2>&1
python fakequant_eval.py --merged "$M" --mode bf16 --per-role 10 > ~/step0_bf16.log 2>&1
echo ALLDONE >> ~/step0_bf16.log
