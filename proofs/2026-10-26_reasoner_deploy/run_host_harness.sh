#!/usr/bin/env bash
# Host harness for the v3 reasoner backend path (run in WSL, ONLY when the GPU training is finished and the
# laptop has >= 3 GB free; CPU llama-server, ~3 GB RAM for the Q4_0 4B at -c 4096).
#   bash run_host_harness.sh <gguf> [n_items] [data.jsonl]
set -euo pipefail
GGUF=${1:?gguf}; N=${2:-20}
HERE=$(cd "$(dirname "$0")" && pwd)
DATA=${3:-$HERE/../2026-10-25_reasoner_final/data/incidents_dev.ok.jsonl}
BACK=$HERE/../../Code/smart-city-edge-agent/app/backend
SRV=${LLAMA_SERVER:-$HOME/llama-cuda-b11815/llama-server}
OUT=$HERE/host_harness_$(date +%Y%m%d_%H%M).jsonl
free_kb=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
[ "$free_kb" -ge 3000000 ] || { echo "less than 3 GB free in WSL; not starting"; exit 1; }
"$SRV" -m "$GGUF" -c 4096 -ngl 0 --threads 4 --port 8092 --host 127.0.0.1 > "$OUT.server.log" 2>&1 &
PID=$!; trap 'kill $PID 2>/dev/null; wait $PID 2>/dev/null' EXIT
for i in $(seq 120); do curl -sf http://127.0.0.1:8092/health >/dev/null && break; sleep 2; done
cd "$BACK"
SCE_REASONER_HOST_URL=http://127.0.0.1:8092 SCE_REASONER_HOST_DATA="$DATA" SCE_REASONER_HOST_OUT="$OUT" \
SCE_REASONER_HOST_N="$N" GOMAXPROCS=2 PATH=$HOME/go-sdk/go/bin:$PATH go test -run TestReasonerV3Host -count=1 -timeout 0 -v . | tail -3
echo "results: $OUT"
