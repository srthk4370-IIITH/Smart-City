source ~/venvs/train/bin/activate
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
M=$(ls -d ~/smartcity_runs/agents_*/merged | tail -1)
cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/export
while pgrep -f "bash .*s0.sh" >/dev/null; do sleep 30; done
FQ_MINMAX=1 python fakequant_eval.py --merged "$M" --prep-int4 ~/fq_minmax > ~/step0b_prep.log 2>&1
python fakequant_eval.py --merged ~/fq_minmax --mode int4 --per-role 10 > ~/step0b_int4.log 2>&1
echo ALLDONE >> ~/step0b_int4.log
