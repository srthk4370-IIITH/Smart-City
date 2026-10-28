#!/usr/bin/env bash
# P2 CPU prep: TIES d0.2 / d0.3 + DARE p0.9 relative adapters -> GGUF LoRA (f16). Waits for >= 3 GB free RAM before each step.
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; S=$D/scripts; P=~/smartcity_runs/agents_v2_topup3f/p2; mkdir -p $P
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
free_mb() { $PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" < /dev/null 2>/dev/null | tr -dc 0-9; }
gate() { while f=$(free_mb); [ -z "$f" ] || [ "$f" -lt 3072 ]; do sleep 30; done; }
source ~/venvs/train/bin/activate; exec >> $D/p2_prep.log 2>&1 < /dev/null
for spec in "T20 --method ties --density 0.2" "T30 --method ties --density 0.3" "D90 --method dare --p 0.9"; do
  set -- $spec; n=$1; shift
  [ -s $P/$n/adapter_model.safetensors ] || { gate; nice -n 19 python $S/p2_merge.py "$@" --out $P/$n; }
  gate; bash /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f/conv_lora_3f.sh p2_$n $P/$n
done
echo P2_PREP_DONE
