# attempt 2: closed-form conditional edit. keys/cov on seed 11 rows; eval on DIFFERENT rows (seed 12) + gold-answer NLL
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/data/final/train_new.jsonl; P=~/venvs/rsn/bin/python
LK=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK
until [ ! -e $LK ]; do sleep 60; done; echo "weight_edit memit $(date)" > $LK
[ -s ~/we_work/m2_keys.pt ] || $P we_memit.py --mode collect --data $D --n-easy 200 --n-hard 150 --seed 11 --cov-prompts 40 --layers 16,20 --out ~/we_work/m2 2>&1 | grep -v "Loading weights\|Triton"
$P we_memit.py --mode solve --dirs analysis/dirs.npz --grid analysis/grid2.json --out ~/we_work/m2 2>&1 | tail -20
DW=none; for t in $(python3 -c "import json;print(' '.join(g['tag'] for g in json.load(open('analysis/grid2.json'))))"); do DW="$DW,$HOME/we_work/m2_dw_$t.pt"; done
$P we_memit.py --mode eval --data $D --n-easy 80 --n-hard 50 --seed 12 --dw $DW --nll-rows 30 --out ~/we_work/m2_eval.json 2>&1 | grep -v "Loading weights\|Triton"
cp ~/we_work/m2_eval.json analysis/; rm -f $LK; echo MEMIT_DONE
