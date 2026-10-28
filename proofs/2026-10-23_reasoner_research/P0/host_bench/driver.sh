#!/bin/bash
# Unattended P0 host-bench driver (WSL). One model at a time on the RTX 4050 (llama.cpp b11815 CUDA 12.8, official
# ggml-org release), models from ~/models. Domain-agent training / other llama-servers have priority: we wait for them
# and stop (resumably) if they start. a model starts only with Windows free RAM >= 3 GB; < 2.5 GB pauses our processes (owner rules 2026-10-23); GPU only, -t 2, nice 19. Logs: results/driver.log
HB=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-23_reasoner_research/P0/host_bench
LC=$HOME/llama-cuda-b11815
PORT=18090
LOG=$HB/results/driver.log
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
mkdir -p $HB/results
log() { echo "$(date '+%F %T') $*" >> $LOG; }
drop() { sudo -n true 2>/dev/null && { sync; echo 3 | sudo -n tee /proc/sys/vm/drop_caches >/dev/null; } || \
         $PS -NoProfile -Command "wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'" >/dev/null 2>&1; }
winfree_mb() { $PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -d '\r'; }
others_busy() {   # training or someone else's llama-server
  pgrep -f "train_topup|python.*topup" >/dev/null && return 0
  ps -eo args | grep -E "llama-server" | grep -v -- "--port $PORT" | grep -v grep >/dev/null && return 0
  return 1
}

# ---------------------------------------------------------------- engine
if [ ! -x $LC/bin/llama-server ]; then
  log "waiting for the CUDA build download"
  while [ ! -f $LC/dl/llama.tgz ] || [ ! -f $LC/dl/cudart.tgz ]; do sleep 30; done
  cd $LC/dl
  echo "3bfc8e971fca7caa56036e131914317a62943473306cac987d650c621fd11516  llama.tgz" > SHA256SUMS
  echo "b26946028fda3195d858f2e0cdb6763cc6572dfad860ff5741b2e95f0eba5384  cudart.tgz" >> SHA256SUMS
  if ! sha256sum -c SHA256SUMS >> $LOG 2>&1; then log "SHA256 MISMATCH - abort"; exit 1; fi
  mkdir -p $LC/x && tar -xzf llama.tgz -C $LC/x && tar -xzf cudart.tgz -C $LC/x
  mkdir -p $LC/bin
  find $LC/x -type f \( -name "llama-server" -o -name "*.so*" -o -name "llama-cli" \) -exec cp -a {} $LC/bin/ \;
  find $LC/x -type l -name "*.so*" -exec cp -a {} $LC/bin/ \;
  log "engine extracted: $(ls $LC/bin | tr '\n' ' ')"
fi
export LD_LIBRARY_PATH=$LC/bin:/usr/lib/wsl/lib
$LC/bin/llama-server --version >> $LOG 2>&1

# ---------------------------------------------------------------- RAM watcher (pauses our processes)
(
  paused=0
  while true; do
    f=$(winfree_mb); f=${f:-9999}
    pids=$(pgrep -f "run_bench.py|llama-server .*--port $PORT" | tr '\n' ' ')
    if [ "$f" -lt 2500 ] && [ $paused -eq 0 ] && [ -n "$pids" ]; then kill -STOP $pids 2>/dev/null; paused=1; log "PAUSE: Windows free ${f} MB"; drop; fi
    if [ "$f" -ge 3000 ] && [ $paused -eq 1 ]; then kill -CONT $(pgrep -f "run_bench.py|llama-server .*--port $PORT") 2>/dev/null; paused=0; log "RESUME: Windows free ${f} MB"; fi
    sleep 30
  done
) &
WATCH=$!
trap "kill $WATCH 2>/dev/null; stop_ours" EXIT TERM

stop_ours() { for p in $(pgrep -f "llama-server .*--port $PORT|run_bench.py"); do kill -CONT $p 2>/dev/null; kill $p 2>/dev/null; done; sleep 3
  for p in $(pgrep -f "llama-server .*--port $PORT|run_bench.py"); do kill -9 $p 2>/dev/null; done; }
start_server() {  # $1 gguf
  pkill -f "llama-server .*--port $PORT"; sleep 2
  nohup nice -n 19 $LC/bin/llama-server -m "$1" -ngl 99 -c 8192 -np 1 --jinja -t 2 -tb 2 --host 127.0.0.1 --port $PORT --no-webui \
    > $HB/results/server_$2.log 2>&1 &
  for i in $(seq 1 120); do
    sleep 3
    curl -s localhost:$PORT/health | grep -q '"ok"' && { drop; log "server ready ($2) after $((i*3)) s"; return 0; }
  done
  log "server failed ($2)"; tail -20 $HB/results/server_$2.log >> $LOG; return 1
}

run_model() {  # name gguf
  local name=$1 gguf=$2
  while true; do
    while others_busy; do log "GPU busy (training or other llama-server); waiting 10 min before $name"; sleep 600; done
    f=$(winfree_mb); f=${f:-0}
    if [ "$f" -lt 3000 ]; then log "Windows free ${f} MB < 3 GB; waiting 5 min before $name"; sleep 300; continue; fi
    start_server "$gguf" "$name" || return 1
    cd $HB
    nice -n 19 python3 run_bench.py --model "$name" --port $PORT >> $HB/results/run_$name.log 2>&1 &
    RB=$!
    while kill -0 $RB 2>/dev/null; do
      sleep 60
      if others_busy; then log "priority work started: stopping $name (resumable)"; stop_ours; drop; continue 2; fi
    done
    wait $RB
    stop_ours; drop
    log "finished $name: $(wc -l < $HB/results/$name/reasoning.jsonl 2>/dev/null) reasoning, $(wc -l < $HB/results/$name/chat.jsonl 2>/dev/null) chat"
    return 0
  done
}

log "driver start"
run_model v2_3b_q4_0 $HOME/smartcity_runs/agents_v2/post/gguf/ft_v2_q4_0.gguf
run_model llama32_3b_base_q4_0 $HOME/models/llama-3.2-3b-instruct-gguf/llama-3.2-3b-instruct-q4_0.gguf
run_model qwen35_4b_q4_0 $HOME/models/qwen3.5-4b-gguf/qwen3.5-4b-q4_0.gguf
run_model qwen35_2b_q4_0 $HOME/models/qwen3.5-2b-gguf/qwen3.5-2b-q4_0.gguf
run_model qwen35_4b_q4_k_m $HOME/models/qwen3.5-4b-gguf/qwen3.5-4b-q4_k_m.gguf
cd $HB && nice -n 19 python3 score.py >> $HB/results/score.log 2>&1 && nice -n 19 python3 make_tables.py >> $HB/results/score.log 2>&1
log "ALL DONE"
