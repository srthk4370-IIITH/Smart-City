# Edit A attempt 3: rank-1 mean-key edits (solve_mean.py). Waits for the m2 eval, reuses its base rows (same points/seed/NLL rows).
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/data/final/train_new.jsonl; P=~/venvs/rsn/bin/python
LK=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK
until grep -q MEMIT_DONE ~/detached/we_memit.log; do sleep 60; done
[ -s ~/we_work/m3_eval.json ] || python3 -c "import json;d=json.load(open('/home/hp_srthk4370/we_work/m2_eval.json'));json.dump({'base':d['base']},open('/home/hp_srthk4370/we_work/m3_eval.json','w'))"
until [ ! -e $LK ]; do sleep 60; done; echo "weight_edit m3 $(date)" > $LK
DW=""; for t in mk_L16-20_b0.5 mk_L16-20_b1.0 mk_L16-20_b2.0; do DW="$DW${DW:+,}$HOME/we_work/m3_dw_$t.pt"; done
$P we_memit.py --mode eval --data $D --n-easy 80 --n-hard 50 --seed 12 --dw $DW --nll-rows 30 --out ~/we_work/m3_eval.json 2>&1 | grep --line-buffered -v "Loading weights\|Triton"
cp ~/we_work/m3_eval.json analysis/; rm -f $LK; echo M3_DONE
