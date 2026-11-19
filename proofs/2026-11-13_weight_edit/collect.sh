cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1   # 2026-11-13: 8 idle compile workers wasted RAM
mkdir -p ~/we_work; D=/mnt/c/Users/hp/Desktop/qidk/proofs
echo "weight_edit collect $(date)" > $D/2026-10-29_rsn_v3/GPU_LOCK
P=~/venvs/rsn/bin/python
[ -s ~/we_work/test_r3.jsonl ] || $P we_think.py --mode collect --data $D/2026-11-06_4b_local/data/final/chat_test_r3.jsonl --n-easy 556 --n-hard 200 --out ~/we_work/test_r3 2>&1 | grep -v "Loading weights\|Triton"
[ -s ~/we_work/fit.jsonl ] || $P we_think.py --mode collect --data $D/2026-11-12_topup_r4/data/final/train_new.jsonl --n-easy 400 --n-hard 250 --seed 11 --out ~/we_work/fit 2>&1 | grep -v "Loading weights\|Triton"
cp ~/we_work/*.jsonl $D/2026-11-13_weight_edit/ 
rm -f $D/2026-10-29_rsn_v3/GPU_LOCK; echo COLLECT_DONE
