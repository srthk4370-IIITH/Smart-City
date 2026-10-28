#!/bin/bash
# serve.sh <gguf> [port]  -- one llama-server at a time, CPU, 4 threads, model's own template (--jinja), no mmap
# (-lm none: weights in anonymous memory, so the page-cache guard cannot evict them).
M=$1; PORT=${2:-18080}
pkill -f "llama-server -m .* --port $PORT" 2>/dev/null; sleep 1
LS=${LLAMA_SERVER:-$HOME/gpu_work/llama.cpp/build-host/bin/llama-server}
nohup nice -n 10 $LS -m "$M" -c 8192 -np 1 --jinja -t 4 -tb 4 --port $PORT --host 127.0.0.1 -lm none --no-webui ${EXTRA_ARGS} \
  > $HOME/bench_server_$PORT.log 2>&1 &
for i in $(seq 1 50); do
  sleep 2
  if curl -s localhost:$PORT/health | grep -q '"ok"'; then echo "ready after $((i*2)) s"; exit 0; fi
done
echo "server not ready"; tail -20 $HOME/bench_server_$PORT.log; exit 1
