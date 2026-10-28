#!/usr/bin/env bash
# 3f/3g LoRA-scaling SCREEN (owner-approved): candidates = runtime LoRAs on the base Q4_0 (ft_base0_q4_0.gguf = merge_mix
# with weight 0 -> the v2 Q4_0 recipe, imatrix_v2), llama-server --lora-scaled, instead of merge->convert->quantize each.
#   bash pipe_lora.sh SET TAG ...      spec: $R/screen/TAG.lora = "v2:0.5,c49:0.5" (names -> $R/lora_gguf/NAME.gguf)
#   TAG without a .lora file but with post/gguf/ft_TAG_q4_0.gguf = a merged GGUF run on the same set (fidelity reference).
# SET: dev, test, rw5dev, rw5test, fid200 (eval_fid200/eval3e.jsonl prepared once). Strictly serial, same gates as pipe_3f.
SET=$1; shift; TAGS="$*"
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
E=$R/eval_$SET; mkdir -p $E/eval $E/logs; BASE=$R/post/gguf/ft_base0_q4_0.gguf
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
waitgpu() { while true; do if [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9)" -lt 800 ]; then  # GPU idle (CPU llama-servers of other agents are ignored)
  f=$($PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -dc 0-9); [ -n "$f" ] && [ "$f" -ge ${GATE_MB:-3072} ] && return; fi; sleep 3; done; }
cd $H/../topup3e; source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
exec >> $R/pipe_lora.log 2>&1
echo "=== $(date) pipe_lora $SET: $TAGS"
N=$(wc -l < $E/eval3e.jsonl)
clean() { pkill -f "llama-cuda-shim/build-host/bin/llama-server" 2>/dev/null; sleep 3; }
ev() {  # tag gguf [lora]
  for t in 1 2 3 4 5 6; do
    clean; waitgpu
    LORA_SCALED="$3" nice -n 19 ionice -c3 python host_eval3e.py run --out $E --model $2 --tag $1 --cuda --threads 4 --np 4 >> $E/logs/$1.log 2>&1
    clean
    [ "$(wc -l < $E/eval/$1/samples.jsonl)" -ge "$N" ] && { echo "$(date +%T) eval $SET $1 complete"; return 0; }
    sleep 90
  done; echo "$(date +%T) eval $SET $1 INCOMPLETE"; }
[ -s $E/eval/v2cuda/samples.jsonl ] && [ "$(wc -l < $E/eval/v2cuda/samples.jsonl)" -ge "$N" ] || ev v2cuda ~/smartcity_runs/agents_v2/post/gguf/ft_v2_q4_0.gguf
for t in $TAGS; do
  if [ -s $R/screen/$t.lora ]; then
    LS=$(tr -d ' \n' < $R/screen/$t.lora | sed "s#\([^,:]*\):#$R/lora_gguf/\1.gguf:#g")
    echo "$(date +%T) $t = $LS"; ev $t $BASE "$LS"
  else ev $t $R/post/gguf/ft_${t}_q4_0.gguf; fi
done
echo "=== $(date) PIPE_LORA_DONE $SET $TAGS"
