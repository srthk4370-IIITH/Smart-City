#!/usr/bin/env bash
# P3 (GPU, only after "GPU free"): SFT from the mixA50 adapter (m50_adapter, r 64) on train_p3.jsonl, LR 4e-6, 1 epoch
# (~300 steps at grad-accum 16), checkpoint every 50 steps; then the last checkpoint -> GGUF LoRA and the WiSE screen
# (runtime LoRA on ft_mixA50_q4_0: p3:a, m50:-a for a in 0.5 0.7) on E1 + dev3f. Agent-owned shell, HEARTBEAT watchdog (15 min).
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; R=~/smartcity_runs/agents_v2_topup3f; O=~/smartcity_runs/agents_p3/run1
DATA=~/smartcity_runs/agents_p3/data/train_p3.jsonl; H3E=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
mkdir -p $O; exec >> $D/p3_train.log 2>&1 < /dev/null; touch $D/HEARTBEAT; MAIN=$$
( while sleep 60; do kill -0 $MAIN 2>/dev/null || exit 0; age=$(( $(date +%s) - $(stat -c %Y $D/HEARTBEAT) ))
  if [ $age -gt 900 ]; then echo "$(date +%T) WATCHDOG ${age}s"; pkill -f "train_3e.py --out $O"; pkill -f "host_eval3e.py run"; kill $MAIN; exit 0; fi; done ) &
trap "kill $! 2>/dev/null" EXIT
source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false; cd $H3E
python -c "
import json,sys; p=sys.argv[1]; rows=[json.loads(l) for l in open(p)]
if any('type' not in r for r in rows):
    open(p,'w').write(''.join(json.dumps(dict(r, type=r.get('type','sft')), ensure_ascii=False)+'\n' for r in rows))" $DATA
until grep -q '"done": true' $O/session_status.json 2>/dev/null; do
  nice -n 10 python train_3e.py --out $O --data $DATA --init-adapter $R/m50_adapter --lr ${LR:-4e-6} --warmup-ratio 0.05 \
     --save-every 50 --hours 8 >> $O/stdout.log 2>&1 || { echo "$(date +%T) train rc=$?"; sleep 60; }
  [ -e $O/STOP ] && exit 0
done
C=$(ls -d $O/checkpoints/checkpoint-* | sort -t- -k2 -n | tail -1); echo "$(date +%T) trained -> $C"
bash /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f/conv_lora_3f.sh p3_last $C
LG=$R/lora_gguf; M=$R/post/gguf/ft_mixA50_q4_0.gguf
for al in 0.5 0.7; do t=P3W$(echo $al | tr -d .)
  for E in $D/e1 $R/eval_dev; do
    LORA_SCALED="$LG/p3_last.gguf:$al,$LG/m50.gguf:-$al" nice -n 10 python host_eval3e.py run --out $E --model $M --tag $t --cuda --threads 2 --np 4 > $E/eval_p3_$t.log 2>&1
    echo "$(date +%T) done $t $(basename $E) rows $(wc -l < $E/eval/$t/samples.jsonl)"
  done
done
echo P3_DONE
