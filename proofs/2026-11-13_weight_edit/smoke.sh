cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
mkdir -p ~/we_work
~/venvs/rsn/bin/python we_think.py --mode collect --data /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/data/final/train_new.jsonl --n-easy 2 --n-hard 2 --out ~/we_work/smoke 2>&1 | grep -v Warning | tail -20
python3 -c "
import json; [print(l.strip()[:300]) for l in open('/home/hp_srthk4370/we_work/smoke.jsonl')]"
