#!/usr/bin/env bash
# 3f master queue (owner on the laptop): strictly serial, one GPU job at a time, every step waits for >= 3 GB Windows
# free RAM and runs at nice 19 / idle IO. Idempotent (markers in $R/done/). Log: $R/master.log
#  S0 REALWORLD section-5 data (gen_rw5.py) + 60-sample review page
#  S1 dev eval: soup3 (resume)        S2 rw5dev: v2, mixA50, soup3        S3 rw5test: v2 (scored first)
#  S4 mixA50 -> exact rank-64 LoRA     S5 SFT file (rw5 train + 1.5x gold replay)
#  S6 SFT from the mixA50 LoRA (<= 1.5 h, LR 1e-5)   S7 dev + rw5dev evals of its checkpoints
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
mkdir -p $R/done; exec >> $R/master.log 2>&1
cd $H; source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
waitfree() { while true; do f=$($PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -d '\r'); [ -n "$f" ] && [ "$f" -ge 3072 ] && return; sleep 30; done; }
step() { local name=$1; shift; [ -e $R/done/$name ] && return 0; waitfree; echo "$(date +%T) START $name"
  nice -n 19 ionice -c3 "$@"; local rc=$?; echo "$(date +%T) END $name rc=$rc"; [ $rc = 0 ] && touch $R/done/$name; return $rc; }
echo "=== $(date) master_3f start"
step S0_rw5 python gen_rw5.py --out $R/rw5 --train-scale 1 --eval-scale 1.5 || exit 1
step S0_review bash -c "mkdir -p $R/rw5/review && cp $R/rw5/rw5_train.jsonl $R/rw5/review/train.jsonl && python -c \"import json,hashlib;p='$R/rw5/review/train.jsonl';json.dump({'splits':{'train':{'sha256_16':hashlib.sha256(open(p,'rb').read()).hexdigest()[:16]}}},open('$R/rw5/review/manifest.json','w'))\" && python ../review_v2.py --data $R/rw5/review --n 60"
step S1_dev_soup3 bash pipe_3f.sh dev soup3
step S2_rw5dev bash pipe_3f.sh rw5dev mixA50 soup3
step S3_rw5test bash pipe_3f.sh rw5test
step S4_m50lora python mix_to_lora.py --choice $R/post/mixA50/choice.json --out $R/m50_adapter || exit 1
step S5_sft python build_rw5sft.py --rw5 $R/rw5/rw5_train.jsonl --out $R/data/train3f_rw5sft.jsonl --replay 1.5 || exit 1
mkdir -p $R/m50rw
step S6_train python ../topup3e/train_3e.py --out $R/m50rw --data $R/data/train3f_rw5sft.jsonl --init-adapter $R/m50_adapter --lr 1e-5 --save-every 25 --hours 1.5
L=$(ls -d $R/m50rw/checkpoints/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1)
[ -n "$L" ] || { echo "no m50rw checkpoint"; exit 1; }
mkdir -p $R/post/m50rwL; echo "{\"mix\": [[\"$L\", 1.0]], \"chosen\": \"m50rwL\"}" > $R/post/m50rwL/choice.json
step S7_rw5dev bash pipe_3f.sh rw5dev m50rwL
step S7_dev bash pipe_3f.sh dev m50rwL
echo "=== $(date) MASTER_DONE"
