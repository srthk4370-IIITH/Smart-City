#!/usr/bin/env bash
# Unattended overnight GPU queue (2026-10-27/28), one agent-owned background shell, no detached processes.
#  1 P2: dev3f for the 2 best E1 candidates -> pick.py final (winner only if it BEATS mixA50+P1 on E2 dev3f AND E1)
#  2 P3 if HVAC/compound E1 gaps remain for the current best: train from mixA50 (p3 data), WiSE a 0.5/0.7 on E1, dev3f for the best
#  3 QUEUE_DONE.json (winner + numbers), touch ~/smartcity_runs/GPU_FREE_FOR_REASONER
# Guards (watchdog, every 20 s): GPU >= 75 C -> SIGSTOP own llama-server / training python, resume <= 65 C; Windows free RAM < 1.5 GB ->
# pause, resume >= 2.5 GB; proofs/2026-10-25_reasoner_final/PAUSE_GPU -> stop own jobs (training checkpoints every 50 steps), exit.
# Heartbeat: self-touched until 08:00 IST; after that the 15-min rule applies (stale HEARTBEAT -> stop cleanly, resumable).
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; S=$D/scripts; R=~/smartcity_runs/agents_v2_topup3f; LG=$R/lora_gguf
M=$R/post/gguf/ft_mixA50_q4_0.gguf; H3E=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
PAUSE=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/PAUSE_GPU; O=~/smartcity_runs/agents_p3/run1; DATA=~/smartcity_runs/agents_p3/data/train_p3.jsonl
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
exec >> $D/overnight.log 2>&1 < /dev/null; MAIN=$$; touch $D/HEARTBEAT
log() { echo "$(date -u +%FT%TZ) $*"; }
free_mb() { $PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" < /dev/null 2>/dev/null | tr -dc 0-9; }
jobs_pids() { pgrep -f "llama-cuda-shim/build-host/bin/llama-server -m $M"; pgrep -f "train_3e.py --out $O"; }
stop_all() { for p in $(jobs_pids) $(pgrep -f "host_eval_paced.py run"); do kill -CONT $p 2>/dev/null; kill $p 2>/dev/null; done; }
( hot=0; low=0
  while sleep 20; do kill -0 $MAIN 2>/dev/null || exit 0
    h=$(TZ=Asia/Kolkata date +%H%M); [ $h -lt 0800 ] && touch $D/HEARTBEAT
    age=$(( $(date +%s) - $(stat -c %Y $D/HEARTBEAT) ))
    if [ $age -gt 900 ] || [ -e $PAUSE ]; then log "STOP (heartbeat ${age}s or PAUSE_GPU)"; stop_all; kill $MAIN; exit 0; fi
    t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | tr -dc 0-9); f=$(free_mb)
    want=0; { [ -n "$t" ] && [ "$t" -ge 75 ]; } && want=1; { [ -n "$f" ] && [ "$f" -lt 1536 ]; } && want=1
    if [ $hot = 0 ] && [ $want = 1 ]; then for p in $(jobs_pids); do kill -STOP $p; done; hot=1; log "pause gpu=${t}C free=${f}MB"; fi
    if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 65 ] && { [ -z "$f" ] || [ "$f" -ge 2560 ]; }; then for p in $(jobs_pids); do kill -CONT $p; done; hot=0; log "resume gpu=${t}C free=${f}MB"; fi
  done ) &
WD=$!; trap "kill $WD 2>/dev/null" EXIT
source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
ev() {  # tag lora_spec outdir
  local n=$(wc -l < $3/eval3e.jsonl)
  for k in 1 2 3; do
    [ -s $3/eval/$1/samples.jsonl ] && [ "$(wc -l < $3/eval/$1/samples.jsonl)" -ge $n ] && break
    (cd $H3E && LORA_SCALED="$2" nice -n 10 python $S/host_eval_paced.py run --out $3 --model $M --tag $1 --cuda --threads 2 --np 4 >> $3/eval_q_$1.log 2>&1)
    sleep 2
  done
  log "eval $1 $(basename $3) $(wc -l < $3/eval/$1/samples.jsonl)/$n"; }
declare -A SPEC=([B20]="$LG/v21_621.gguf:0.2,$LG/v2.gguf:-0.2" [B35]="$LG/v21_621.gguf:0.35,$LG/v2.gguf:-0.35"
  [B50]="$LG/v21_621.gguf:0.5,$LG/v2.gguf:-0.5" [T20]="$LG/p2_T20.gguf:1.0" [T30]="$LG/p2_T30.gguf:1.0"
  [P3W05]="$LG/p3_last.gguf:0.5,$LG/m50.gguf:-0.5" [P3W07]="$LG/p3_last.gguf:0.7,$LG/m50.gguf:-0.7")
log "=== overnight start"
# ---- P2
for t in B20 B35 B50 T20 T30; do ev $t "${SPEC[$t]}" $D/e1; done
TOP=$(python $S/pick.py e1top 2 B20 B35 B50 T20 T30 | tr '\n' ' '); log "P2 E1 top: $TOP"
for t in $TOP; do ev $t "${SPEC[$t]}" $R/eval_dev; done
python $S/pick.py final $TOP > $D/p2_pick.json; P2W=$(python -c "import json;print(json.load(open('$D/p2_pick.json'))['winner'])"); log "P2 winner: $P2W"
CANDS="$TOP"
# ---- P3 if gaps remain (for the P2 winner, or mixA50 when none)
G=ref; [[ "$P2W" != mixA50* ]] && G=$P2W
if python $S/pick.py gaps $G; then
  log "P3: gaps open for $G -> train"
  python -c "
import json,sys; p=sys.argv[1]; rows=[json.loads(l) for l in open(p)]
if any('type' not in r for r in rows):
    open(p,'w').write(''.join(json.dumps(dict(r, type=r.get('type','sft')), ensure_ascii=False)+'\n' for r in rows))" $DATA
  mkdir -p $O
  for k in 1 2 3 4 5 6; do
    grep -q '"done": true' $O/session_status.json 2>/dev/null && break
    (cd $H3E && nice -n 10 python train_3e.py --out $O --data $DATA --init-adapter $R/m50_adapter --lr 4e-6 --warmup-ratio 0.05 \
       --save-every 50 --hours 7 --thermal-pause-at 75 --thermal-resume-at 65 >> $O/stdout.log 2>&1) || { log "train rc=$?"; sleep 60; }
  done
  C=$(ls -d $O/checkpoints/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1); log "P3 trained -> $C"
  if [ -n "$C" ]; then
    rm -f $LG/p3_last.gguf; bash /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f/conv_lora_3f.sh p3_last $C
    for t in P3W05 P3W07; do ev $t "${SPEC[$t]}" $D/e1; done
    B=$(python $S/pick.py e1top 1 P3W05 P3W07 | head -1)
    [ -n "$B" ] && { ev $B "${SPEC[$B]}" $R/eval_dev; CANDS="$CANDS $B"; } || log "P3 WiSE below ref on E1"
  fi
else log "no HVAC/compound gaps -> P3 skipped"; fi
# ---- final pick over everything that ran on dev3f
python $S/pick.py final $CANDS > $D/QUEUE_DONE.tmp && python - $D/QUEUE_DONE.tmp $D/QUEUE_DONE.json "${C:-}" <<'EOF'
import json, sys, datetime
r = json.load(open(sys.argv[1])); r["p3_checkpoint"] = sys.argv[3] or None
r["finished_utc"] = datetime.datetime.utcnow().isoformat(timespec="seconds")
r["lora_specs"] = "see scripts/overnight.sh SPEC (runtime LoRA on ft_mixA50_q4_0.gguf); a winner needs a merged Q4_0 build before the board"
json.dump(r, open(sys.argv[2], "w"), indent=1); print("winner", r["winner"])
EOF
log "QUEUE_DONE winner=$(python -c "import json;print(json.load(open('$D/QUEUE_DONE.json'))['winner'])")"
touch ~/smartcity_runs/GPU_FREE_FOR_REASONER; log "=== overnight done"
