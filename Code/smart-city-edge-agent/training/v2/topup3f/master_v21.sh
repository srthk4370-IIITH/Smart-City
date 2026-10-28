#!/usr/bin/env bash
# v2.1 (track A) queue: continued SFT from the v2 adapter on train_v21.jsonl (1 epoch, LR $LR, ckpt every 100 steps),
# then each checkpoint -> GGUF LoRA -> LoRA-scaling screen on dev3f + rw5dev (pipe_lora.sh, tags V21_<step>).
# Own background shell + watchdog (HEARTBEAT); waits for the master8 screen to finish (one model on the GPU).
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
O=~/smartcity_runs/agents_v21/run1; DATA=~/smartcity_runs/agents_v21/data/train_v21.jsonl; LR=${LR:-8e-6}
mkdir -p $O $R/done; exec >> $R/master.log 2>&1; cd $H; source $H/watchdog.sh
source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
free_mb() { $PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -dc 0-9; }
waitgpu() { while true; do if [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9)" -lt 800 ] && ! pgrep -f "[m]aster8_3f.sh" >/dev/null; then
  f=$(free_mb); [ -n "$f" ] && [ "$f" -ge 3072 ] && return; fi; sleep 20; done; }
echo "=== $(date) master_v21 start (LR $LR)"
until grep -q '"done": true' $O/session_status.json 2>/dev/null; do
  waitgpu; nice -n 19 ionice -c3 python ../topup3e/train_3e.py --out $O --data $DATA --init-adapter ~/smartcity_runs/agents_v2/adapter \
     --lr $LR --warmup-ratio 0.05 --save-every 100 --hours 14 >> $O/stdout.log 2>&1 || { echo "v21 train rc=$?"; sleep 120; }
  [ -e $O/STOP_QUEUE ] && exit 0
done
echo "$(date +%T) v21 training done"
# screen checkpoints: last first, then every 200 steps
CK=$(ls -d $O/checkpoints/checkpoint-* | sort -t- -k2 -n -r)
for c in $CK; do s=${c##*-}; t=V21_$s
  bash $H/conv_lora_3f.sh v21_$s $c
  echo "v21_$s:1.0" > $R/screen/$t.lora
done
TAGS=$(for c in $CK; do s=${c##*-}; echo V21_$s; done | tr '\n' ' ')
for t in $TAGS; do
  bash $H/pipe_lora.sh rw5dev $t; bash $H/pipe_lora.sh dev $t
done
echo "=== $(date) MASTER_V21_DONE"
