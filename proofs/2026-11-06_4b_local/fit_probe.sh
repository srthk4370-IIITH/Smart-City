#!/usr/bin/env bash
# fit_probe.sh: Qwen3.5-4B QLoRA fit on the RTX 4050 with the 6 GB levers (FIT.md).
#  1) one optimizer step (2 synthetic rows of L tokens + 6 real r2 rows, accum 8) at L = 6144 5120 4096
#  2) speed: 3 probe steps at the largest L that fit + a 5-step real-mode run (accum 16, --micro-tokens 6144) as the real run would do
# GPU_LOCK (fit_4b line) must be held. Watchdog: SIGSTOP at GPU >= 87 C, resume at <= 82 C; WSL avail < 500 MB -> abort (a pause frees no RAM).
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local; KG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle
R2=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-02_2b_r2/data/final; PY=~/venvs/rsn/bin/python
grep -q "^fit_4b" $KG/../GPU_LOCK || { echo "no fit_4b lock"; exit 1; }
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True RSN3_SEG_TOKENIZE=1 TORCHINDUCTOR_COMPILE_THREADS=1 MALLOC_ARENA_MAX=2
LEV=${LEV:---head-cpu --ckpt-offload --mlp-chunk 1024 --lean-host}
COMMON="--base $HOME/models/qwen3.5-4b --model-dir $HOME/models/qwen3.5-4b-nf4 --tools $R2/tools_r2.json --inc $R2/incidents_train.jsonl --chat $R2/chat_train.jsonl --quant nf4 --dtype bf16 $LEV"
setup() { mkdir -p $1; [ $1 = ~/smartcity_runs/fit4b_probe ] || for f in ~/smartcity_runs/fit4b_probe/*_tok.pt; do ln -sf $f $1/; done; }
watch() {  # watch pid name
  local hot=0 np=0 ps=0 t f; while kill -0 $1 2>/dev/null; do sleep 5
    t=$(nvidia-smi --query-gpu=temperature.gpu,memory.used --format=csv,noheader,nounits | tr -d ' '); f=$(free -m | awk 'NR==2{print $7}')
    r=$(ps -o rss= -p $1 | tr -dc 0-9); echo "$(date +%T) $t avail=$f rss_mb=$(( ${r:-0} / 1024 ))" >> $D/logs/watch_$2.log
    if [ "$f" -lt 500 ]; then echo "RAM ABORT avail $f MB" >> $D/logs/watch_$2.log; kill -TERM $1; kill -CONT $1; sleep 5; continue; fi
    tc=${t%%[.,]*}
    if [ $hot = 0 ] && [ "$tc" -ge 87 ]; then kill -STOP $1; hot=1; np=$((np+1)); fi
    if [ $hot = 1 ]; then ps=$((ps+5)); [ "$tc" -le 82 ] && { kill -CONT $1; hot=0; }; fi
  done; echo "pauses $np, paused ${ps}s" >> $D/logs/watch_$2.log; }
run() {  # run name outdir args...
  local n=$1 o=$2; shift 2; setup $o; : > $o/train.log
  nice -n 10 $PY $KG/train_rsn3.py $COMMON --out $o "$@" > $D/logs/$n.log 2>&1 & local p=$!
  watch $p $n; wait $p; local rc=$?
  echo "$n rc=$rc $(grep -h -e PROBE_RESULT -e 'tok/s' -e OOM $o/train.log | tail -2 | cut -c1-400) | $(tail -1 $D/logs/watch_$n.log)" | tee -a $D/logs/summary.txt
}
FIT=""
for L in ${LENS:-6144 5120 4096}; do
  run probe_$L ~/smartcity_runs/fit4b_probe --accum 8 --probe-steps 1 --probe-len $L --max-len 8192
  grep -h PROBE_RESULT ~/smartcity_runs/fit4b_probe/train.log | tail -1 | grep -q '"oom_steps": 0' && { FIT=$L; break; }
done
echo "FIT=${FIT:-none}" | tee -a $D/logs/summary.txt
[ -n "$FIT" ] || exit 2
[ -n "${NOSPEED:-}" ] && exit 0
run speed_probe_$FIT ~/smartcity_runs/fit4b_probe --accum 8 --probe-steps 3 --probe-len $FIT --max-len 8192
rm -rf ~/smartcity_runs/fit4b_speed; run speed_real_$FIT ~/smartcity_runs/fit4b_speed --accum 16 --max-len $FIT --micro-tokens 6144 \
  --max-steps 5 --save-every 100000 --eval-every 100000 --gen-every 100000 --hours 2
