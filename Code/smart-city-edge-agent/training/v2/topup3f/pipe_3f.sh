#!/usr/bin/env bash
# 3f unattended pipeline, STRICTLY SERIAL (a CPU GGUF build next to a GPU eval pushed Windows free RAM < 1.5 GB and the
# RAM guard kept stopping the eval): v2 eval if missing, then per tag: build Q4_0 (post_3f.sh) -> host greedy eval.
# SET = dev (dev3f, selection) or test (the 1,148-row 3e eval, final decision only).
#   bash pipe_3f.sh SET TAG1 TAG2 ...     ($R/post/TAG/choice.json must exist: {"mix": [[adapter, w], ...]})
# Owner on the laptop: every eval try / build waits for >= GATE_MB (3072) MB Windows free RAM and runs at nice 19,
# idle IO; llama-server -ngl 99 -t 2 -tb 2 (host_eval3e use_cuda). Sets: dev, test, rw5dev, rw5test.
# Log: $R/pipe.log, tables: $R/eval_SET/tables*.md
SET=$1; shift; TAGS="$*"
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
E=$R/eval_$SET; mkdir -p $E/eval $E/logs
if [ ! -s $E/eval3e.jsonl ]; then
  case $SET in
    dev) ln -sf $R/dev/dev3f.jsonl $E/eval3e.jsonl ;;
    rw5dev) ln -sf $R/rw5/rw5_dev.jsonl $E/eval3e.jsonl ;;
    rw5test) ln -sf $R/rw5/rw5_test.jsonl $E/eval3e.jsonl ;;
    test) ln -sf ~/smartcity_runs/agents_v2_topup3e/eval/eval3e.jsonl $E/eval3e.jsonl
          [ -e $E/eval/v2cuda ] || cp -r ~/smartcity_runs/agents_v2_topup3e/eval/eval/v2cuda $E/eval/v2cuda ;;
  esac
fi
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
# GPU shared with the reasoner benchmark (driver yields to python *topup* jobs at its model boundary): wait until no
# foreign llama-server runs AND Windows has >= GATE_MB free, then launch at once (the launch is the driver's signal).
waitgpu() { while true; do if ! pgrep -x llama-server | xargs -r ps -o args= -p | grep -v llama-cuda-shim | grep -q llama-server; then
  f=$($PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -dc 0-9); [ -n "$f" ] && [ "$f" -ge ${GATE_MB:-3072} ] && return; fi; sleep 3; done; }
waitfree() { while true; do f=$($PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -dc 0-9); [ -n "$f" ] && [ "$f" -ge ${GATE_MB:-3072} ] && return; sleep 30; done; }
cd $H/../topup3e; source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
exec >> $R/pipe.log 2>&1
echo "=== $(date) pipe_3f(serial) $SET: $TAGS"
N=$(wc -l < $E/eval3e.jsonl)
clean() { pkill -f "llama-cuda-shim/build-host/bin/llama-server" 2>/dev/null; sleep 3; }   # only this pipeline uses the shim
ev() {  # tag gguf
  for t in 1 2 3 4 5 6; do
    clean; waitgpu
    nice -n 19 ionice -c3 python host_eval3e.py run --out $E --model $2 --tag $1 --cuda --threads 4 --np 4 >> $E/logs/$1.log 2>&1
    clean
    [ "$(wc -l < $E/eval/$1/samples.jsonl)" -ge "$N" ] && { echo "$(date +%T) eval $SET $1 complete"; return 0; }
    sleep 90
  done; echo "$(date +%T) eval $SET $1 INCOMPLETE"; }
ev v2cuda ~/smartcity_runs/agents_v2/post/gguf/ft_v2_q4_0.gguf
for t in $TAGS; do
  g=$R/post/gguf/ft_${t}_q4_0.gguf
  [ -s $g.md5 ] || { waitfree; nice -n 19 ionice -c3 bash $H/post_3f.sh NONE $t v2; echo "$(date +%T) post $t rc=$?"; }
  [ -s $g.md5 ] && ev $t $g
done
python host_eval3e.py table --out $E --ref v2cuda --cand $TAGS > /dev/null
cp $E/tables.md $E/tables_$(echo $TAGS | tr ' ' '_' | cut -c1-80).md; cp $E/tables.json $E/tables_$(echo $TAGS | tr ' ' '_' | cut -c1-80).json
echo "=== $(date) PIPE_DONE $SET $TAGS"
