#!/usr/bin/env bash
# fit_r3.sh <max_len>: r3 data (tools_r3, chat_train_r3 + incidents_train), fit levers. 1) one optimizer step (accum 8) whose
# first 2 rows are the 2 LONGEST REAL rows (--probe-len 0) at --max-len <max_len>; 2) 3 probe steps (speed); 3) 5 real-mode steps
# (accum 16, --micro-tokens <max_len>) in a throwaway dir. Needs the fit_4b GPU_LOCK line; Windows available >= 1.5 GB to start.
# Watchdog: GPU >= 87 C SIGSTOP / <= 82 C CONT; WSL avail < 500 MB or Windows avail < 700 MB -> abort.
M=${1:?max_len}; D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local; KG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle
F=$D/data/final; PY=~/venvs/rsn/bin/python; PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe; L=$D/logs/r3_$M; mkdir -p $L
winfree() { timeout 30 $PS -NoProfile -Command "(Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes" < /dev/null 2>/dev/null | tr -dc 0-9; }
grep -q "^fit_4b" $KG/../GPU_LOCK || { echo "no fit_4b lock"; exit 1; }
w=$(winfree); [ "${w:-0}" -ge 1500 ] || { echo "WAIT: Windows available ${w} MB < 1500" | tee -a $L/summary.txt; exit 7; }
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True RSN3_SEG_TOKENIZE=1 TORCHINDUCTOR_COMPILE_THREADS=1 MALLOC_ARENA_MAX=2
LEV=${LEV:---head-cpu --ckpt-offload --mlp-chunk 1024 --lean-host}
COMMON="--base $HOME/models/qwen3.5-4b --model-dir $HOME/models/qwen3.5-4b-nf4 --tools $F/tools_r3.json --inc $F/incidents_train.jsonl --chat $F/chat_train_r3.jsonl --quant nf4 --dtype bf16 --max-len $M $LEV"
setup() { mkdir -p $1; [ $1 = ~/smartcity_runs/fit4b_r3 ] || for f in ~/smartcity_runs/fit4b_r3/*_tok.pt; do ln -sf $f $1/; done; }
watch() {
  local hot=0 np=0 ps=0 k=0 t f w r; while kill -0 $1 2>/dev/null; do sleep 5; k=$((k+1))
    t=$(nvidia-smi --query-gpu=temperature.gpu,memory.used --format=csv,noheader,nounits | tr -d ' '); f=$(free -m | awk 'NR==2{print $7}')
    [ $((k % 6)) = 1 ] && w=$(winfree)
    r=$(ps -o rss= -p $1 | tr -dc 0-9); echo "$(date +%T) $t avail=$f win=$w rss_mb=$(( ${r:-0} / 1024 ))" >> $L/watch_$2.log
    if [ "$f" -lt 500 ] || [ "${w:-9999}" -lt 700 ]; then echo "RAM ABORT wsl $f win $w" >> $L/watch_$2.log; kill -TERM $1; kill -CONT $1; sleep 5; continue; fi
    tc=${t%%[.,]*}
    if [ $hot = 0 ] && [ "$tc" -ge 87 ]; then kill -STOP $1; hot=1; np=$((np+1)); fi
    if [ $hot = 1 ]; then ps=$((ps+5)); [ "$tc" -le 82 ] && { kill -CONT $1; hot=0; }; fi
  done; echo "pauses $np, paused ${ps}s" >> $L/watch_$2.log; }
run() {
  local n=$1 o=$2; shift 2; setup $o; : > $o/train.log
  nice -n 10 $PY $KG/train_rsn3.py $COMMON --out $o "$@" > $L/$n.log 2>&1 & local p=$!
  watch $p $n; wait $p; local rc=$?
  cp $o/train.log $L/${n}_train.log
  echo "$n rc=$rc $(grep -h -e PROBE_RESULT -e 'tok/s' -e OOM -e 'host RSS' $o/train.log | tail -3 | cut -c1-500) | $(tail -1 $L/watch_$n.log)" | tee -a $L/summary.txt
}
run fit ~/smartcity_runs/fit4b_r3 --accum 8 --probe-steps 1 --probe-len 0
grep -h PROBE_RESULT ~/smartcity_runs/fit4b_r3/train.log | tail -1 | grep -q '"oom_steps": 0' || { echo "FIT FAIL at $M" | tee -a $L/summary.txt; exit 2; }
[ -n "${NOSPEED:-}" ] && exit 0
run speed_probe ~/smartcity_runs/fit4b_r3 --accum 8 --probe-steps 3 --probe-len 0
rm -rf ~/smartcity_runs/fit4b_r3_speed; run speed_real ~/smartcity_runs/fit4b_r3_speed --accum 16 --micro-tokens $M \
  --max-steps 5 --save-every 100000 --eval-every 100000 --gen-every 100000 --hours 2
rm -rf ~/smartcity_runs/fit4b_r3_speed
