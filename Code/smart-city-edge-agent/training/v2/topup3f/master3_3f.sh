#!/usr/bin/env bash
# 3f queue 3 (run as the agent's own background task; watchdog.sh stops it if HEARTBEAT is > 15 min old)
#  U1 SFT file B: rw5 train + 1.5x replay, half of it stage-placed event/status rows v2 answers right (vs the drift to stable)
#  U2 train m50rwB from the mixA50 LoRA: LR 2e-5, 1.5 epochs, save every 10 steps (sessions of <= 1.5 h, resumed until done)
#  U3 last checkpoint -> rw5dev + dev
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
mkdir -p $R/done $R/m50rwB; exec >> $R/master.log 2>&1; cd $H; source $H/watchdog.sh
source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
waitgpu() { while true; do if ! pgrep -x llama-server | xargs -r ps -o args= -p | grep -q llama-server; then
  f=$($PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -dc 0-9); [ -n "$f" ] && [ "$f" -ge 3072 ] && return; fi; sleep 3; done; }
step() { local name=$1; shift; [ -e $R/done/$name ] && return 0; echo "$(date +%T) START $name"
  nice -n 19 ionice -c3 "$@"; local rc=$?; echo "$(date +%T) END $name rc=$rc"; [ $rc = 0 ] && touch $R/done/$name; return $rc; }
echo "=== $(date) master3_3f start"
step U1_sftB python build_rw5sft.py --rw5 $R/rw5/rw5_train.jsonl --out $R/data/train3f_rw5sftB.jsonl --replay 1.5 --event-share 0.5 || exit 1
until grep -q '"done": true' $R/m50rwB/session_status.json 2>/dev/null; do
  waitgpu; echo "$(date +%T) train session m50rwB"
  nice -n 19 ionice -c3 python ../topup3e/train_3e.py --out $R/m50rwB --data $R/data/train3f_rw5sftB.jsonl --init-adapter $R/m50_adapter \
     --lr 2e-5 --epochs 1.5 --save-every 10 --hours 1.4 >> $R/m50rwB/stdout.log 2>&1 || { echo "train rc=$?"; exit 1; }
done
L=$(ls -d $R/m50rwB/checkpoints/checkpoint-* | sort -t- -k2 -n | tail -1)
mkdir -p $R/post/m50rwB; echo "{\"mix\": [[\"$L\", 1.0]], \"chosen\": \"m50rwB\"}" > $R/post/m50rwB/choice.json
step U3_rw5dev bash pipe_3f.sh rw5dev m50rwB
step U3_dev bash pipe_3f.sh dev m50rwB
echo "=== $(date) MASTER3_DONE"
