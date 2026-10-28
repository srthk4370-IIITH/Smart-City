#!/usr/bin/env bash
# bash eval_bg.sh TAG MODEL [threads np] : host Q4_0 eval of one model (waits until no other llama-server runs)
cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
source ~/venvs/train/bin/activate
E=~/smartcity_runs/agents_v2_topup3e/eval; mkdir -p $E/logs
while pgrep -f llama-server >/dev/null; do sleep 60; done
nice -n 5 python host_eval3e.py run --out $E --model "$2" --tag "$1" --threads ${3:-8} --np ${4:-4} > $E/logs/$1.log 2>&1
echo "EXIT $? $(date)" >> $E/logs/$1.log
/mnt/c/Windows/System32/wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || true
