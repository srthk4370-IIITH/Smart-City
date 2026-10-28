#!/usr/bin/env bash
# Serialize with the benchmark agent: wait until Windows free RAM >= 2.5 GB AND no llama-server/llama-cli/run_bench/
# other llama tool/convert/verify python runs in WSL (poll 60 s), then run "$@". Never kills anything.
while true; do
  f=$(powershell.exe -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" | tr -d '\r')
  o=$(wsl.exe -d Ubuntu -- bash -c "pgrep -fa 'llama-server|llama-cli|run_bench|llama-quantize|llama-imatrix|llama-perplexity|convert_hf_to_gguf|verify_gguf|verify_merge|merge_lowmem' | grep -v pgrep | wc -l" | tr -d '\r')
  [ "${f:-0}" -ge 2560 ] && [ "${o:-1}" = 0 ] && break
  echo "[$(date +%T)] waiting: win free ${f} MB, model procs ${o}"; sleep 60
done
echo "[$(date +%T)] gate open (win free ${f} MB)"; "$@"
