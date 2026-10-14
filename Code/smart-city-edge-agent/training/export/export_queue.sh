#!/usr/bin/env bash
# Serialized export queue. Runs each job to completion before starting the next, because two
# exports at once is what exhausted WSL memory and filled C: on 2026-10-14. Writes a one-line
# status per job to ~/qaihm_work/queue.status so progress can be checked without reading logs.
#
#   setsid nohup bash export_queue.sh > ~/qaihm_work/queue.log 2>&1 &
#   cat ~/qaihm_work/queue.status
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source ~/venvs/qaihm/bin/activate
export TZ=Asia/Kolkata
export PYTHONPATH="$HERE/pyhooks${PYTHONPATH:+:$PYTHONPATH}"
ST=~/qaihm_work/queue.status
: > "$ST"
note() { echo "$(date +%H:%M:%S) $*" | tee -a "$ST"; }

# RAM + swap together is the real OOM condition: this export is EXPECTED to spill into swap.
mem_free_mb() { awk '/MemAvailable/ {m=$2} /SwapFree/ {s=$2} END {print int((m+s)/1024)}' /proc/meminfo; }
guard() {
  while true; do
    a=$(mem_free_mb)
    if [ "$a" -lt 600 ]; then note "MEM GUARD: ${a} MB RAM+swap left, aborting current export"; pkill -f "qai-hub-models export"; fi
    sleep 20
  done
}
guard & GUARD=$!
trap 'kill $GUARD 2>/dev/null || true' EXIT
setsid nohup bash "$HERE/disk_guard.sh" 5 >/dev/null 2>&1 &

run_job() { # name, out_dir, then the export arguments
  local name=$1 out=$2; shift 2
  if find "$out" -name '*part*3*.bin' 2>/dev/null | grep -q .; then note "$name: already exported, skipping"; return 0; fi
  if pgrep -f "qai-hub-models export" >/dev/null; then note "$name: another export is running, refusing"; return 1; fi
  rm -rf "$out"; mkdir -p "$out"
  note "$name: START"
  local t0=$(date +%s)
  if qai-hub-models export "$@" --target-runtime genie --skip-profiling \
       --device "Samsung Galaxy S24 (Family)" --output-dir "$out" > ~/qaihm_work/"$name".log 2>&1; then
    local n=$(find "$out" -name '*.bin' | wc -l) sz=$(du -sh "$out" | cut -f1)
    note "$name: DONE in $(( ($(date +%s) - t0) / 60 )) min, $n bins, $sz"
  else
    note "$name: FAILED after $(( ($(date +%s) - t0) / 60 )) min - see ~/qaihm_work/$name.log"
  fi
}

# 1. Same fine-tuned 3B checkpoint, decode graph widened from ar1 to ar4 so several agents can
#    decode in ONE NPU pass (continuous batching in genied). Exactly 2 graphs per part: on this
#    device a third graph is refused by the DSP SMMU unless graph switching is on, and graph
#    switching was measured as a net loss (HANDBOOK 2.12).
run_job llama3b_ar4 ~/qaihm_work/ftgptq16_genie_ar4 \
  llama_v3_2_3b_instruct --checkpoint ~/qaihm_work/ftgptq16_ckpt \
  --sequence-lengths 128,4 --context-lengths 2048

# 2. Separate cross-domain reasoner: Qwen3-1.7B, stock weights for now (it will be fine-tuned and
#    later improved from operator feedback). Same 2-graph shape so it fits the same budget.
run_job qwen3_1_7b ~/qaihm_work/qwen3_1_7b_genie \
  qwen3_1_7b --sequence-lengths 128,1 --context-lengths 2048

note "QUEUE FINISHED"
