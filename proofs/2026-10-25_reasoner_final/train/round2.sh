#!/usr/bin/env bash
# Round 2, unattended (owner-approved 2026-10-27). Waits for ~/smartcity_runs/GPU_FREE_FOR_REASONER (written by the domain
# P2/P3 queue), then: chat paraphrases + replay answers (local base Q4, GPU) -> verify -> mix2 -> QLoRA continue from step 612
# (LR 5e-5, 1 pass over mix2 ~= 0.5 epoch, ckpt every 25) -> merge Q4_0 -> models_stage/rsn_v2_q4_0.gguf + md5 -> RWH + P0 score.
# Guards: heat 75/65 C (eval, generation, trainer), Windows RAM pause < 1.5 GB (run.sh), PAUSE_GPU file, heartbeat self-touch
# only until 08:00 IST (then the 15-min day rule applies). Log: ~/smartcity_runs/reasoner_v1/round2.log
R=~/smartcity_runs/reasoner_v1; T=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final; P=$T/pipeline; HB=$R/HEARTBEAT
PAUSEF=$T/PAUSE_GPU; FLAG=~/smartcity_runs/GPU_FREE_FOR_REASONER
export HEAT_HI=80 HEAT_LO=72
exec >> $R/round2.log 2>&1; echo "=== $(date) round2 waiter start"
( while true; do h=$(TZ=Asia/Kolkata date +%-H); d=$(TZ=Asia/Kolkata date +%F); if [ "$d" = "2026-10-27" ] || [ $h -ge 22 ] || [ $h -lt 8 ]; then touch $HB; fi; sleep 60; done ) &
TOUCHER=$!; trap "kill $TOUCHER 2>/dev/null; pkill -f 'llama-server .*--port 18097'" EXIT
step() { echo "$(date +%T) == $*"; }
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
free_mb() { $PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -dc 0-9; }
until [ -e $FLAG ]; do sleep 60; done; step "flag seen"
while [ -e $PAUSEF ]; do sleep 60; done
until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9)" -lt 800 ] && [ "$(free_mb)" -ge 3072 ]; do sleep 60; done
# 1) local-model generation (base Q4_0, 4 slots)
if [ ! -s $T/data/chat2_train.ok.jsonl ] || [ ! -s $T/data/replay_train.ok.jsonl ]; then
  step "generation server"; LC=~/llama-cuda-b11815
  LD_LIBRARY_PATH=$LC/bin nice -n 10 $LC/bin/llama-server -m ~/models/qwen3.5-4b-gguf/qwen3.5-4b-q4_0.gguf -ngl 99 -c 16384 -np 8 --jinja -t 2 -tb 2 \
    --host 127.0.0.1 --port 18097 --no-webui > $R/gen_server.log 2>&1 &
  for i in $(seq 1 90); do sleep 2; curl -s localhost:18097/health | grep -q ok && break; done
  cd $P && [ -s $T/data/chat2_train.jsonl ] || python3 paraphrase_chat.py --url http://127.0.0.1:18097/v1/chat/completions --seeds 1200 --k 5 --cap 5000 --out $T/data/chat2_train.jsonl
  [ -s $T/data/replay_train.jsonl ] || python3 replay_general.py --url http://127.0.0.1:18097/v1/chat/completions
  pkill -f "llama-server .*--port 18097"; sleep 5
  python3 verify.py $T/data/chat2_train.jsonl $T/data/replay_train.jsonl
fi
[ -s $T/data/incidents_border.ok.jsonl ] || { cd $P && python3 gen_border.py 600 && python3 verify.py $T/data/incidents_border.jsonl; }
if false; then :
fi
[ -e $PAUSEF ] && { step "PAUSE_GPU -> stop"; exit 0; }
cd $P && python3 build_mix2.py
# 2) training (run.sh: GPU/RAM gates, watchdog, PAUSE_GPU, heat 75/65 in the trainer)
step "train run2"
RUN=run2 bash $T/train/run.sh --data $T/data/train_mix2.jsonl --init-adapter $R/run1/ckpt_step0612 --lr 5e-5 --epochs 1 --max-len 3200 --hours 20 --thermal-pause-at 80 --thermal-resume-at 72
grep -q '"done": true' $R/run2/status.json || { step "training not done -> stop"; exit 1; }
# 3) merge -> stage
step "merge"; CK=$(ls -d $R/run2/ckpt_step* | sort | tail -1) NAME=rsn_v2 bash $T/train/merge_q4.sh
# 4) quick score on the merged Q4_0 (RWH + P0)
step "score"; G2=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v2_q4_0.gguf
bash $T/eval/eval_gguf.sh $G2 rsn_v2 rwh,p0; bash $T/eval/eval_gguf.sh $G2 rsn_v2b rwh
cd $T/eval && REPAIR=1 python3 score_v3.py rsn_v2 ft612 | tee $R/round2_result.txt; python3 p0_score.py rsn_v2 ft612 | tail -2 | tee -a $R/round2_result.txt
python3 sev_agree.py rsn_v2 rsn_v2b | tee -a $R/round2_result.txt
cp $R/round2_result.txt $T/eval/results/round2_result.txt; touch $R/ROUND2_DONE; step "ROUND2 DONE"
