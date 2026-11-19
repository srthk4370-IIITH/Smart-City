cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
D=/mnt/c/Users/hp/Desktop/qidk/proofs
until [ ! -e $D/2026-10-29_rsn_v3/GPU_LOCK ]; do sleep 60; done
echo "weight_edit sweep $(date)" > $D/2026-10-29_rsn_v3/GPU_LOCK
~/venvs/rsn/bin/python we_think.py --mode sweep --data $D/2026-11-12_topup_r4/data/final/train_new.jsonl --n-easy 120 --n-hard 80 --seed 11 \
  --dirs analysis/dirs.npz --configs analysis/configs.json --out ~/we_work/sweep1.json 2>&1 | grep -v "Loading weights\|Triton"
cp ~/we_work/sweep1.json analysis/; rm -f $D/2026-10-29_rsn_v3/GPU_LOCK; echo SWEEP_DONE
