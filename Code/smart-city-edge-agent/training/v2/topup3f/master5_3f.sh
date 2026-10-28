#!/usr/bin/env bash
# 3f queue 5 (agent's own background task + watchdog): status-preserving anchor repair of c49 (likelihood displacement)
#  X1 anchors (ref = c49; selection as anchor_3f.py)  X2 rep data: anchors + 1:1 gold replay  X3 train rep from c49
#  (LR 5e-6, save every 10)  X4 dev: repL and mixRep50 = v2 + 0.5 x (rep - v2)
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
C49=~/smartcity_runs/agents_v2_topup3e/run2/checkpoints/checkpoint-49; V2=~/smartcity_runs/agents_v2/adapter
mkdir -p $R/done $R/data $R/rep; exec >> $R/master.log 2>&1; cd $H; source $H/watchdog.sh
source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
waitgpu() { while true; do if ! pgrep -x llama-server >/dev/null; then
  f=$($PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -dc 0-9); [ -n "$f" ] && [ "$f" -ge 3072 ] && return; fi; sleep 3; done; }
step() { local name=$1; shift; [ -e $R/done/$name ] && return 0; echo "$(date +%T) START $name"
  nice -n 19 ionice -c3 "$@"; local rc=$?; echo "$(date +%T) END $name rc=$rc"; [ $rc = 0 ] && touch $R/done/$name; return $rc; }
echo "=== $(date) master5_3f start"
waitgpu; step X1_anchors python anchor_3f.py --out $R/data/anchors_c49.jsonl --adapter $C49 || exit 1
step X2_rep python build_3f.py --kind rep --anchors $R/data/anchors_c49.jsonl --out $R/data/train3f_rep.jsonl || exit 1
until grep -q '"done": true' $R/rep/session_status.json 2>/dev/null; do
  waitgpu; nice -n 19 ionice -c3 python ../topup3e/train_3e.py --out $R/rep --data $R/data/train3f_rep.jsonl --init-adapter $C49 \
     --lr 5e-6 --beta 0.1 --rpo-alpha 1.0 --save-every 10 --hours 1.4 >> $R/rep/stdout.log 2>&1 || { echo "rep train rc=$?"; exit 1; }
done
L=$(ls -d $R/rep/checkpoints/checkpoint-* | sort -t- -k2 -n | tail -1)
mkdir -p $R/post/repL $R/post/mixRep50
echo "{\"mix\": [[\"$L\", 1.0]], \"chosen\": \"repL\"}" > $R/post/repL/choice.json
echo "{\"mix\": [[\"$V2\", 0.5], [\"$L\", 0.5]], \"chosen\": \"mixRep50\"}" > $R/post/mixRep50/choice.json
step X4_dev bash pipe_3f.sh dev mixRep50 repL
step W2b_rw5dev bash pipe_3f.sh rw5dev m50rw50
step W2b_dev bash pipe_3f.sh dev m50rw50
echo "=== $(date) MASTER5_DONE"
