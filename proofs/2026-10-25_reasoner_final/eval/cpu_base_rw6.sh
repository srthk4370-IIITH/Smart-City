#!/usr/bin/env bash
# base Qwen3.5-4B Q4_0, CPU llama-server (GPU untouched), RW6 with the v3 prompt
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
f=$($PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" | tr -dc 0-9); echo "win free $f MB"
[ "$f" -lt 3072 ] && { echo "RAM gate"; exit 1; }
LS=~/gpu_work/llama.cpp/build-host/bin/llama-server
nice -n 19 $LS -m ~/models/qwen3.5-4b-gguf/qwen3.5-4b-q4_0.gguf -c 8192 -np 1 --jinja -t 4 -tb 4 --port 18095 --host 127.0.0.1 --no-webui > ~/smartcity_runs/reasoner_v1/cpu_server.log 2>&1 &
SP=$!; trap "kill $SP" EXIT
for i in $(seq 1 60); do sleep 3; curl -s localhost:18095/health | grep -q ok && break; done
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/eval && python3 run_v3.py --tag base_v3_cpu --port 18095 --suites rw6
