#!/usr/bin/env bash
# 3f training queue (GPU, one model at a time): waits for the running dev pipeline, then
#  1) status-preserving anchors with reference v2 and with reference c49 (anchor_3f.py, same row selection)
#  2) rep: from c49, anchors + 1:1 gold replay (~30 steps)      3) r3: from v2, run2 data + anchors (~64 steps)
#  4) dev pipeline on rep c20/c30 and r3 c40/c64.   Log: $R/queue.log
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
C49=~/smartcity_runs/agents_v2_topup3e/run2/checkpoints/checkpoint-49; V2=~/smartcity_runs/agents_v2/adapter
mkdir -p $R/data; exec >> $R/queue.log 2>&1
echo "=== $(date) queue start"
until grep -q "PIPE_DONE dev mixA50" $R/pipe.log; do sleep 60; done
cd $H; source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
[ -s $R/data/anchors_v2.jsonl ] || python anchor_3f.py --out $R/data/anchors_v2.jsonl --adapter $V2 || exit 1
[ -s $R/data/anchors_c49.jsonl ] || python anchor_3f.py --out $R/data/anchors_c49.jsonl --adapter $C49 --ids-from $R/data/anchors_v2.jsonl || exit 1
python build_3f.py --kind rep --anchors $R/data/anchors_c49.jsonl --out $R/data/train3f_rep.jsonl
python build_3f.py --kind r3 --anchors $R/data/anchors_v2.jsonl --out $R/data/train3f_r3.jsonl
T=$H/../topup3e/train_3e.py
for run in rep r3; do
  mkdir -p $R/$run
  [ -s $R/$run/session_status.json ] && grep -q '"done": true' $R/$run/session_status.json && continue
  if [ $run = rep ]; then INIT=$C49; SE=10; else INIT=$V2; SE=20; fi
  echo "$(date +%T) train $run from $INIT"
  python $T --out $R/$run --data $R/data/train3f_$run.jsonl --init-adapter $INIT --save-every $SE --lr 5e-6 --beta 0.1 --rpo-alpha 1.0 --hours 1.5 >> $R/$run/stdout.log 2>&1
  echo "$(date +%T) ${run^^}_EXIT $?"
done
mk(){ mkdir -p $R/post/$1; echo "{\"mix\": [[\"$2\", 1.0]], \"chosen\": \"$1\"}" > $R/post/$1/choice.json; }
L3=$(ls -d $R/r3/checkpoints/checkpoint-* | sort -t- -k2 -n | tail -1)
mk rep20 $R/rep/checkpoints/checkpoint-20; mk rep30 $(ls -d $R/rep/checkpoints/checkpoint-* | sort -t- -k2 -n | tail -1)
mk r3c40 $R/r3/checkpoints/checkpoint-40; mk r3cL $L3
echo "$(date +%T) eval queue: rep20 rep30 r3c40 r3cL ($L3)"
bash $H/pipe_3f.sh dev rep20 rep30 r3c40 r3cL
echo "=== $(date) QUEUE_DONE"
