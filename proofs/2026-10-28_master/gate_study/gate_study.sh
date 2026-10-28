#!/usr/bin/env bash
# Gate-length study GPU run (standalone; start with: bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh gate_study <this script>).
# Waits until ~/smartcity_runs/GPU_FREE_FOR_REASONER exists AND ~/smartcity_runs/reasoner_v1/import_round2.log says DONE,
# then the deployed B50 Q4_0 (CUDA, paced 2 s per request) answers the 2,640 truncated-event windows; resumable.
# Guards (20 s): GPU >= 80 C pause own llama-server, resume <= 72 C; Windows free RAM < 1.5 GB pause; PAUSE_GPU -> stop + exit.
G=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/gate_study; S=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts
H3E=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e; M=~/smartcity_runs/agents_v2_topup3f/post/gguf/ft_B50_q4_0.gguf
PAUSE=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final/PAUSE_GPU; PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
exec >> $G/gate_study.log 2>&1 < /dev/null; MAIN=$$
log() { echo "$(date -u +%FT%TZ) $*"; }
free_mb() { $PS -NoProfile -Command "[int](Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue" < /dev/null 2>/dev/null | tr -dc 0-9; }
log "waiting for GPU_FREE_FOR_REASONER + rsn_v2 eval DONE"
until [ -e ~/smartcity_runs/GPU_FREE_FOR_REASONER ] && grep -q DONE ~/smartcity_runs/reasoner_v1/import_round2.log 2>/dev/null && ! pgrep -f "llama-server|train_3e.py|train_rsn" >/dev/null; do
  [ -e $PAUSE ] && { sleep 60; continue; }; sleep 60; done  # owner pause: keep waiting (2026-10-28)
while [ -e $PAUSE ]; do sleep 60; done
log "start"
( hot=0
  while sleep 20; do kill -0 $MAIN 2>/dev/null || exit 0
    P=$(pgrep -f "llama-cuda-shim/build-host/bin/llama-server -m $M")
    if [ -e $PAUSE ]; then log "PAUSE_GPU -> stop"; for p in $P; do kill -CONT $p; kill $p; done; pkill -f "host_eval_paced.py run --out $G"; kill $MAIN; exit 0; fi
    t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | tr -dc 0-9); f=$(free_mb)
    want=0; { [ -n "$t" ] && [ "$t" -ge 80 ]; } && want=1; { [ -n "$f" ] && [ "$f" -lt 1536 ]; } && want=1
    if [ $hot = 0 ] && [ $want = 1 ]; then for p in $P; do kill -STOP $p; done; hot=1; log "pause gpu=${t}C free=${f}MB"; fi
    [ $hot = 1 ] && for p in $P; do kill -STOP $p 2>/dev/null; done  # re-stop: a server started during the pause (next eval config) escaped the one-shot STOP and ran at 87 C (2026-10-28)
    if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 72 ] && { [ -z "$f" ] || [ "$f" -ge 2560 ]; }; then for p in $P; do kill -CONT $p; done; hot=0; log "resume gpu=${t}C"; fi
  done ) &
WD=$!; trap "kill $WD 2>/dev/null" EXIT
source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1
N=$(wc -l < $G/eval3e.jsonl)
for k in 1 2 3 4; do
  [ -s $G/eval/B50/samples.jsonl ] && [ "$(wc -l < $G/eval/B50/samples.jsonl)" -ge $N ] && break
  (cd $H3E && nice -n 10 python $S/host_eval_paced.py run --out $G --model $M --tag B50 --cuda --threads 2 --np 4 >> $G/eval_B50.log 2>&1); sleep 2
done
log "eval rows $(wc -l < $G/eval/B50/samples.jsonl)/$N"
python $G/gate_analyze.py B50 | tee -a $G/gate_study.log
log "GATE_STUDY_DONE"
