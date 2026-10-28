#!/usr/bin/env bash
# Young-window top-up queue (standalone; start: bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh yw_queue <this>). Resumable.
# Waits for the gate study (GATE_STUDY_DONE) and an idle GPU, then:
#  1 B50 (merged Q4_0) answers 3,500 v2-train pool rows -> replay = rows it gets right (3x the 690 new young-window rows)
#  2 train YW from the exact B50 adapter (r 128), LR 3e-6, ckpt every 25, thermal 80/72
#  3 refs: B50 merged on E1 + dev3f; WiSE a 0.5/0.7/1.0 (runtime LoRA on ft_B50_q4_0: yw:a, b50ad:-a) on E1 -> best -> dev3f + gate study
#  4 accept only if gate2 vs B50 passes (dev3f + E1, no regression) AND young-window all-3 improves (yw_compare.py)
#  5 accepted -> merge (exact mix) -> Q4_0 -> Code/models_stage/ft_YW_q4_0.gguf + md5. NOT deployed. -> YW_DONE.json
# Guards (20 s): GPU >= 80 C pause own llama-server/trainer, resume <= 72 C; Windows free RAM < 1.5 GB pause; PAUSE_GPU -> stop + exit.
Y=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/young_window; G=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/gate_study
S=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts; E1=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/e1
R=~/smartcity_runs/agents_v2_topup3f; LG=$R/lora_gguf; W=~/smartcity_runs/agents_yw; O=$W/run1; M=$R/post/gguf/ft_B50_q4_0.gguf
H3E=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e; TF=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
STAGE=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage; PAUSE=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/PAUSE_GPU
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
exec >> $Y/yw_queue.log 2>&1 < /dev/null; MAIN=$$
log() { echo "$(date -u +%FT%TZ) $*"; }
free_mb() { $PS -NoProfile -Command "[int](Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue" < /dev/null 2>/dev/null | tr -dc 0-9; }
log "waiting for the gate study + idle GPU"
until grep -q GATE_STUDY_DONE $G/gate_study.log 2>/dev/null && ! pgrep -f "llama-server|train_3e.py|train_rsn" >/dev/null; do
  [ -e $PAUSE ] && { sleep 60; continue; }; sleep 60; done  # owner pause: keep waiting (2026-10-28)
log "start"
jobs_pids() { pgrep -f "llama-cuda-shim/build-host/bin/llama-server"; pgrep -f "train_3e.py --out $O"; }
( hot=0
  while sleep 20; do kill -0 $MAIN 2>/dev/null || exit 0
    if [ -e $PAUSE ]; then log "PAUSE_GPU -> stop"; for p in $(jobs_pids) $(pgrep -f "host_eval_paced.py run"); do kill -CONT $p; kill $p; done; kill $MAIN; exit 0; fi
    t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | tr -dc 0-9); f=$(free_mb)
    want=0; { [ -n "$t" ] && [ "$t" -ge 80 ]; } && want=1; { [ -n "$f" ] && [ "$f" -lt 1536 ]; } && want=1
    if [ $hot = 0 ] && [ $want = 1 ]; then for p in $(jobs_pids); do kill -STOP $p; done; hot=1; log "pause gpu=${t}C free=${f}MB"; fi
    [ $hot = 1 ] && for p in $(jobs_pids); do kill -STOP $p 2>/dev/null; done  # re-stop: a server started during the pause (next eval config) escaped the one-shot STOP and ran at 87 C (2026-10-28)
    if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 72 ] && { [ -z "$f" ] || [ "$f" -ge 2560 ]; }; then for p in $(jobs_pids); do kill -CONT $p; done; hot=0; log "resume gpu=${t}C"; fi
  done ) &
WD=$!; trap "kill $WD 2>/dev/null" EXIT
source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
ev() {  # tag lora_spec outdir [model]
  local n=$(wc -l < $3/eval3e.jsonl) mod=${4:-$M}
  for k in 1 2 3; do
    [ -s $3/eval/$1/samples.jsonl ] && [ "$(wc -l < $3/eval/$1/samples.jsonl)" -ge $n ] && break
    (cd $H3E && LORA_SCALED="$2" nice -n 10 python $S/host_eval_paced.py run --out $3 --model $mod --tag $1 --cuda --threads 2 --np 4 >> $3/eval_yw_$1.log 2>&1)
    sleep 2
  done
  log "eval $1 $(basename $3) $(wc -l < $3/eval/$1/samples.jsonl)/$n"; }
# 1 replay filter on a 3,500-row slice of the P3b pool (v2-train rows, no eval overlap)
P=$W/pool; mkdir -p $P; [ -s $P/eval3e.jsonl ] || head -n 3500 ~/smartcity_runs/agents_p3/pool/eval3e.jsonl > $P/eval3e.jsonl
ev B50Q "" $P
[ -s $W/data/train_yw.jsonl ] || python $Y/yw_data.py build --ratio 3 --pool $P
log "data: $(cat $W/data/train_yw.manifest.json | tr -d '\n ' | cut -c1-200)"
# 2 train
mkdir -p $O
for k in 1 2 3 4 5 6; do
  grep -q '"done": true' $O/session_status.json 2>/dev/null && break
  (cd $H3E && nice -n 10 python train_3e.py --out $O --data $W/data/train_yw.jsonl --init-adapter $W/b50_adapter --lr 3e-6 --warmup-ratio 0.05 \
     --save-every 25 --hours 6 --thermal-pause-at 80 --thermal-resume-at 72 >> $O/stdout.log 2>&1) || { log "train rc=$?"; sleep 60; }
done
C=$(ls -d $O/checkpoints/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1); log "YW trained -> $C"; [ -n "$C" ] || exit 1
[ "$(cat $LG/yw_last.src 2>/dev/null)" = "$C" ] || { rm -f $LG/yw_last.gguf; echo $C > $LG/yw_last.src; }
bash $TF/conv_lora_3f.sh yw_last $C b50ad $W/b50_adapter
# 3 refs + WiSE
ev B50Q "" $E1 $M; ev B50Q "" $R/eval_dev $M; [ -s $G/eval/B50/samples.jsonl ] || ev B50 "" $G $M
declare -A SPEC=([YW05]="$LG/yw_last.gguf:0.5,$LG/b50ad.gguf:-0.5" [YW07]="$LG/yw_last.gguf:0.7,$LG/b50ad.gguf:-0.7" [YW10]="$LG/yw_last.gguf:1.0,$LG/b50ad.gguf:-1.0")
for t in YW05 YW07 YW10; do ev $t "${SPEC[$t]}" $E1; done
B=$(cd $S && python - <<'EOF'
import pick
ref = pick.e1("B50Q"); sc = [(t, pick.e1(t)) for t in ("YW05", "YW07", "YW10")]
sc = [(t, s) for t, s in sc if s and s["safety"] >= ref["safety"]]
sc.sort(key=lambda x: -x[1]["all3"]); print(sc[0][0] if sc else "")
EOF
)
log "best on E1: ${B:-none}"
VERDICT="rejected"
if [ -n "$B" ]; then
  ev $B "${SPEC[$B]}" $R/eval_dev; ev $B "${SPEC[$B]}" $G
  (cd $S && python gate2.py $Y/gate2_yw.json --ref-dev B50Q --ref-e1 B50Q $B) | tee -a $Y/yw_queue.log
  python $Y/yw_compare.py B50 $B $Y/young_$B.json | tee -a $Y/yw_queue.log
  if python -c "import json,sys;g=json.load(open('$Y/gate2_yw.json'));y=json.load(open('$Y/young_$B.json'));sys.exit(0 if g.get('winner')=='$B' and y['improves'] else 1)"; then
    VERDICT="accepted"; a=$(python -c "print(int('${B#YW}')/10)")
    mkdir -p $R/post/YW; echo "{\"mix\": [[\"$W/b50_adapter\", $(python -c "print(round(1-$a,4))")], [\"$C\", $a]], \"chosen\": \"$B\"}" > $R/post/YW/choice.json
    [ -s $R/post/gguf/ft_YW_q4_0.gguf ] || bash $TF/post_3f.sh none YW
    Q=$R/post/gguf/ft_YW_q4_0.gguf
    if [ -s $Q ]; then cp $Q $STAGE/ft_YW_q4_0.gguf.part && md5sum $STAGE/ft_YW_q4_0.gguf.part | cut -d" " -f1 > $STAGE/ft_YW_q4_0.gguf.md5 && mv -f $STAGE/ft_YW_q4_0.gguf.part $STAGE/ft_YW_q4_0.gguf
      log "staged $STAGE/ft_YW_q4_0.gguf md5 $(cat $STAGE/ft_YW_q4_0.gguf.md5)"; else log "merge failed"; VERDICT="accepted_merge_failed"; fi
  fi
fi
python - $Y "$B" "$VERDICT" "$C" <<'EOF'
import json, sys, os, datetime
Y, b, v, c = sys.argv[1:5]
g = json.load(open(f"{Y}/gate2_yw.json")) if os.path.exists(f"{Y}/gate2_yw.json") else None
y = json.load(open(f"{Y}/young_{b}.json")) if b and os.path.exists(f"{Y}/young_{b}.json") else None
st = "/mnt/c/Users/hp/Desktop/qidk/Code/models_stage/ft_YW_q4_0.gguf"
out = {"verdict": v, "candidate": b or None, "checkpoint": c, "young_window": y,
       "gate2": {k: (val.get("pass"), val["dev"]["total_net"], val["dev"]["sev_net"][0], val["e1"]["total_net"][0]) for k, val in (g or {}).items() if isinstance(val, dict) and "dev" in val},
       "staged": st if v == "accepted" and os.path.exists(st) else None,
       "md5": open(st + ".md5").read().strip() if v == "accepted" and os.path.exists(st + ".md5") else None,
       "finished_utc": datetime.datetime.utcnow().isoformat(timespec="seconds")}
json.dump(out, open(f"{Y}/YW_DONE.json", "w"), indent=1); print(json.dumps(out)[:300])
EOF
log "=== YW done: $VERDICT"
