cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/data/final/train_new.jsonl; P=~/venvs/rsn/bin/python
$P we_memit.py --mode collect --data $D --n-easy 3 --n-hard 2 --cov-prompts 2 --out ~/we_work/sm 2>&1 | grep -v "Loading weights\|Triton" | tail -4
$P we_memit.py --mode solve --dirs analysis/dirs.npz --grid analysis/grid_smoke.json --out ~/we_work/sm 2>&1 | tail -3
$P we_memit.py --mode eval --data $D --n-easy 3 --n-hard 2 --dw none,$HOME/we_work/sm_dw_t1.pt --nll-rows 2 --out ~/we_work/sm_eval.json 2>&1 | grep -v "Loading weights\|Triton" | tail -4
