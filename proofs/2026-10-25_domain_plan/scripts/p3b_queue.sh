#!/usr/bin/env bash
# P3b queue (2026-10-28), run in MAIN's shell (survives agent rate limits). Resumable: every step skips what is done.
#  1 replay filter: mixA50 (merged Q4_0, CUDA) answers 7,000 v2-train pool rows -> keep 3,600 it gets right (+1,200 new rows)
#  2 train P3b from m50_adapter (LR 4e-6, ~300 steps, ckpt every 25, thermal 80/72)
#  3 WiSE alpha 0.5 / 0.7 / 1.0: E1 then dev3f (runtime LoRA on ft_mixA50_q4_0)
#  4 sound gate (gate2.py) over P3b alphas + T30 + B50 -> winner
#  5 merge winner -> Q4_0 (post_3f.sh), runtime-LoRA vs Q4_0 parity on fid200, stage in Code/models_stage with md5
#  6 QUEUE_DONE_P3B.json, touch ~/smartcity_runs/GPU_FREE_FOR_REASONER
# Guards (20 s): GPU >= 80 C pause own llama-server/trainer, resume <= 72 C; Windows free RAM < 1.5 GB pause (resume >= 2.5 GB);
# proofs/2026-10-25_reasoner_final/PAUSE_GPU -> stop (checkpointed) + exit. HEARTBEAT self-touched until 23:59 IST, then 15-min rule.
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; S=$D/scripts; R=~/smartcity_runs/agents_v2_topup3f; LG=$R/lora_gguf
M=$R/post/gguf/ft_mixA50_q4_0.gguf; H3E=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
TF=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f; STAGE=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage
PAUSE=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/PAUSE_GPU; O=~/smartcity_runs/agents_p3/run_b
POOL=~/smartcity_runs/agents_p3/pool; DATA=~/smartcity_runs/agents_p3/data/train_p3b.jsonl
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
exec >> $D/p3b_queue.log 2>&1 < /dev/null; MAIN=$$; touch $D/HEARTBEAT
log() { echo "$(date -u +%FT%TZ) $*"; }
free_mb() { $PS -NoProfile -Command "[int](Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue" < /dev/null 2>/dev/null | tr -dc 0-9; }  # Available (free + standby), not FreePhysicalMemory: compressed/standby pages after a game made Free read ~0.3 GB with 2.6 GB available
jobs_pids() { pgrep -f "llama-cuda-shim/build-host/bin/llama-server"; pgrep -f "train_3e.py --out $O"; }
stop_all() { for p in $(jobs_pids) $(pgrep -f "host_eval_paced.py run"); do kill -CONT $p 2>/dev/null; kill $p 2>/dev/null; done; }
( hot=0
  while sleep 20; do kill -0 $MAIN 2>/dev/null || exit 0
    h=$(TZ=Asia/Kolkata date +%H%M); [ $h -lt 2359 ] && touch $D/HEARTBEAT
    age=$(( $(date +%s) - $(stat -c %Y $D/HEARTBEAT) ))
    if [ $age -gt 900 ] || [ -e $PAUSE ]; then log "STOP (heartbeat ${age}s or PAUSE_GPU)"; stop_all; kill $MAIN; exit 0; fi
    t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | tr -dc 0-9); f=$(free_mb)
    want=0; { [ -n "$t" ] && [ "$t" -ge 80 ]; } && want=1; { [ -n "$f" ] && [ "$f" -lt 1536 ]; } && want=1
    if [ $hot = 0 ] && [ $want = 1 ]; then for p in $(jobs_pids); do kill -STOP $p; done; hot=1; log "pause gpu=${t}C free=${f}MB"; fi
    [ $hot = 1 ] && for p in $(jobs_pids); do kill -STOP $p 2>/dev/null; done  # re-stop: a server started during the pause (next eval config) escaped the one-shot STOP and ran at 87 C (2026-10-28)
    if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 72 ] && { [ -z "$f" ] || [ "$f" -ge 2560 ]; }; then for p in $(jobs_pids); do kill -CONT $p; done; hot=0; log "resume gpu=${t}C free=${f}MB"; fi
  done ) &
WD=$!; trap "kill $WD 2>/dev/null" EXIT
source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
ev() {  # tag lora_spec outdir [model]
  local n=$(wc -l < $3/eval3e.jsonl) mod=${4:-$M}
  for k in 1 2 3; do
    [ -s $3/eval/$1/samples.jsonl ] && [ "$(wc -l < $3/eval/$1/samples.jsonl)" -ge $n ] && break
    (cd $H3E && LORA_SCALED="$2" nice -n 10 python $S/host_eval_paced.py run --out $3 --model $mod --tag $1 --cuda --threads 2 --np 4 >> $3/eval_q_$1.log 2>&1)
    sleep 2
  done
  log "eval $1 $(basename $3) $(wc -l < $3/eval/$1/samples.jsonl)/$n"; }
log "=== p3b start"
# 1 replay filter
[ -s $POOL/eval3e.jsonl ] || python $S/p3b_data.py pool
ev mixA50cuda "" $POOL
[ -s $DATA ] || python $S/p3b_data.py build
log "data: $(python -c "import json;m=json.load(open('${DATA%.jsonl}.manifest.json'));print(m['rows'],'rows, replay correct',m['replay_correct'],'of',m['pool_answered'])")"
# 2 train
mkdir -p $O
for k in 1 2 3 4 5 6; do
  grep -q '"done": true' $O/session_status.json 2>/dev/null && break
  (cd $H3E && nice -n 10 python train_3e.py --out $O --data $DATA --init-adapter $R/m50_adapter --lr 4e-6 --warmup-ratio 0.05 \
     --save-every 25 --hours 7 --thermal-pause-at 80 --thermal-resume-at 72 >> $O/stdout.log 2>&1) || { log "train rc=$?"; sleep 60; }
done
C=$(ls -d $O/checkpoints/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1); log "P3b trained -> $C"
[ -n "$C" ] || { log "no checkpoint"; exit 1; }
[ "$(cat $LG/p3b_last.src 2>/dev/null)" = "$C" ] || { rm -f $LG/p3b_last.gguf; echo $C > $LG/p3b_last.src; }
bash $TF/conv_lora_3f.sh p3b_last $C
# 3 WiSE sweep
declare -A SPEC=([P3B05]="$LG/p3b_last.gguf:0.5,$LG/m50.gguf:-0.5" [P3B07]="$LG/p3b_last.gguf:0.7,$LG/m50.gguf:-0.7"
  [P3B10]="$LG/p3b_last.gguf:1.0,$LG/m50.gguf:-1.0" [T30]="$LG/p2_T30.gguf:1.0" [B50]="$LG/v21_621.gguf:0.5,$LG/v2.gguf:-0.5")
for t in P3B05 P3B07 P3B10; do ev $t "${SPEC[$t]}" $D/e1; done
for t in P3B05 P3B07 P3B10; do ev $t "${SPEC[$t]}" $R/eval_dev; done
# 4 sound gate
python $S/gate2.py $D/diag/gate2_final.json P3B05 P3B07 P3B10 T30 B50 | tee -a $D/p3b_gate.txt
W=$(python -c "import json;print(json.load(open('$D/diag/gate2_final.json'))['winner'] or '')"); log "winner: ${W:-none (keep mixA50)}"
# 5 merge, parity, stage
if [ -n "$W" ]; then
  V2A=~/smartcity_runs/agents_v2/adapter; C49=~/smartcity_runs/agents_v2_topup3e/run2/checkpoints/checkpoint-49; V21=~/smartcity_runs/agents_v21/run1/checkpoints/checkpoint-621
  case $W in
    P3B*) a=$(python -c "print(int('${W#P3B}')/10)"); MIX="[[\"$V2A\", $(python -c "print(0.5*(1-$a))")], [\"$C49\", $(python -c "print(0.5*(1-$a))")], [\"$C\", $a]]";;
    T30) MIX="[[\"$V2A\", 0.5], [\"$C49\", 0.5], [\"$R/p2/T30\", 1.0]]";;
    B50) MIX="[[\"$C49\", 0.5], [\"$V21\", 0.5]]";;
  esac
  mkdir -p $R/post/$W; echo "{\"mix\": $MIX, \"chosen\": \"$W\"}" > $R/post/$W/choice.json; log "merge $W: $MIX"
  bash $TF/post_3f.sh none $W; Q=$R/post/gguf/ft_${W}_q4_0.gguf
  if [ -s $Q ]; then
    FD=$R/eval_fid200; ev ${W}_LR "${SPEC[$W]}" $FD; ev ${W}_Q4 "" $FD $Q
    python - $FD/eval/${W}_LR/samples.jsonl $FD/eval/${W}_Q4/samples.jsonl $D/diag/parity_$W.json <<'EOF'
import json, sys
a = {json.loads(l)["id"]: json.loads(l) for l in open(sys.argv[1])}; b = {json.loads(l)["id"]: json.loads(l) for l in open(sys.argv[2])}
ids = [i for i in a if i in b]; k = ("pattern", "status", "likely_cause")
same = sum(all((a[i].get("pred") or {}).get(x) == (b[i].get("pred") or {}).get(x) for x in k) for i in ids)
acc = lambda s: sum(bool(s[i]["pattern"] and s[i]["status"] and s[i]["cause"]) for i in ids)
r = {"n": len(ids), "same_answer": same, "lora_all3": acc(a), "q4_all3": acc(b)}
json.dump(r, open(sys.argv[3], "w")); print("parity", r)
EOF
    mkdir -p $STAGE; cp $Q $STAGE/ft_${W}_q4_0.gguf.part && md5sum $STAGE/ft_${W}_q4_0.gguf.part | cut -d" " -f1 > $STAGE/ft_${W}_q4_0.gguf.md5 && mv $STAGE/ft_${W}_q4_0.gguf.part $STAGE/ft_${W}_q4_0.gguf
    log "staged $STAGE/ft_${W}_q4_0.gguf md5 $(cat $STAGE/ft_${W}_q4_0.gguf.md5)"
  else log "merge/quantize failed for $W (see $R/post/$W/post.log)"; fi
fi
python - $D/diag/gate2_final.json $D/QUEUE_DONE_P3B.json "${W:-}" "${C:-}" <<'EOF'
import json, sys, datetime, os
g = json.load(open(sys.argv[1])); w = sys.argv[3] or None
out = {"winner": w or "mixA50 (none passed the sound gate)", "p3b_checkpoint": sys.argv[4] or None,
       "finished_utc": datetime.datetime.utcnow().isoformat(timespec="seconds"),
       "candidates": {t: {"pass": v.get("pass"), "dev_net": v["dev"]["total_net"], "dev_sev": v["dev"]["sev_net"][0], "e1_net": v["e1"]["total_net"][0],
                          "holm_worse": v["dev"]["holm_worse_slices"] + v["e1"]["holm_worse_slices"]} for t, v in g.items() if isinstance(v, dict) and "dev" in v}}
if w:
    st = f"/mnt/c/Users/hp/Desktop/qidk/Code/models_stage/ft_{w}_q4_0.gguf"
    out["staged"] = st if os.path.exists(st) else None
    out["md5"] = open(st + ".md5").read().strip() if os.path.exists(st + ".md5") else None
    p = f"/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/diag/parity_{w}.json"
    out["parity_fid200"] = json.load(open(p)) if os.path.exists(p) else None
json.dump(out, open(sys.argv[2], "w"), indent=1); print(json.dumps(out)[:400])
EOF
touch ~/smartcity_runs/GPU_FREE_FOR_REASONER; log "=== p3b done"
