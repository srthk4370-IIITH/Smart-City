cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
~/venvs/rsn/bin/python we_neuron.py --mode profile --out ~/we_work/nsm --n-think-easy 2 --n-think-hard 2 --n-trust 3 > ~/we_work/nsm.log 2>&1
grep -v "Loading weights\|Triton" ~/we_work/nsm.log | tail -15
