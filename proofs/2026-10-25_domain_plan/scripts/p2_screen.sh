#!/usr/bin/env bash
# P2 screen (GPU, only after main's "GPU free"): one host pass per candidate on E1 (184) + dev3f (2010), runtime LoRA on the
# deployed ft_mixA50_q4_0.gguf (CUDA llama-server b11815, -ngl 99, 2 CPU threads). Agent-owned bg shell; exits and kills its
# own jobs if $D/HEARTBEAT is older than 15 min. Resumable (host_eval3e skips done ids).
#   bash p2_screen.sh [TAG ...]     default: E1REF B20 B35 B50 T20 T30 (D90 dropped: rank-128 keeps 28% of its energy, so it collapses to ~B35)
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; R=~/smartcity_runs/agents_v2_topup3f; LG=$R/lora_gguf
M=$R/post/gguf/ft_mixA50_q4_0.gguf; H3E=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
declare -A SPEC=([E1REF]="" [B20]="$LG/v21_621.gguf:0.2,$LG/v2.gguf:-0.2" [B35]="$LG/v21_621.gguf:0.35,$LG/v2.gguf:-0.35"
  [B50]="$LG/v21_621.gguf:0.5,$LG/v2.gguf:-0.5" [T20]="$LG/p2_T20.gguf:1.0" [T30]="$LG/p2_T30.gguf:1.0" [D90]="$LG/p2_D90.gguf:1.0")
TAGS="${*:-E1REF B20 B35 B50 T20 T30}"
exec >> $D/p2_screen.log 2>&1 < /dev/null; touch $D/HEARTBEAT; MAIN=$$
( while sleep 20; do kill -0 $MAIN 2>/dev/null || exit 0; age=$(( $(date +%s) - $(stat -c %Y $D/HEARTBEAT) ))
  t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | tr -dc 0-9); P=$(pgrep -f "llama-cuda-shim/build-host/bin/llama-server -m $M")
  if [ -n "$t" ] && [ "$t" -ge 75 ] && [ "${hot:-0}" = 0 ]; then for p in $P; do kill -STOP $p; done; hot=1; echo "$(date +%T) GPU ${t}C pause"; fi
  if [ "${hot:-0}" = 1 ] && [ -n "$t" ] && [ "$t" -le 65 ]; then for p in $P; do kill -CONT $p; done; hot=0; echo "$(date +%T) GPU ${t}C resume"; fi
  if [ $age -gt 900 ]; then for p in $P; do kill -CONT $p; done; echo "$(date +%T) WATCHDOG ${age}s"; pkill -f "host_eval3e.py run --out .*(domain_plan/e1|eval_dev) --model $M"; pkill -f "llama-cuda-shim/build-host/bin/llama-server -m $M"; kill $MAIN; exit 0; fi; done ) &
trap "kill $! 2>/dev/null" EXIT
source ~/venvs/train/bin/activate; cd $H3E; export HF_HUB_OFFLINE=1
for t in $TAGS; do
  for E in ${SETS:-$D/e1 $R/eval_dev}; do
    [ $t = E1REF ] && [ $E != $D/e1 ] && continue
    tag=$t; [ $t = E1REF ] && tag=mixA50cuda
    echo "$(date +%T) $tag on $(basename $E)"
    LORA_SCALED="${SPEC[$t]}" nice -n 10 python /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts/host_eval_paced.py run --out $E --model $M --tag $tag --cuda --threads 2 --np 4 > $E/eval_p2_$tag.log 2>&1
    echo "$(date +%T) done $tag $(basename $E) rows $(wc -l < $E/eval/$tag/samples.jsonl)"
  done
done
echo P2_SCREEN_DONE
