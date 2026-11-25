#!/usr/bin/env bash
# run_topup.sh (2026-11-24): chat-focused 200-step top-up from rsn_full step 640 (copy of run_full.sh). Data topup/data/{train_new,replay}.jsonl from build/prep_topup.py.
# run_full.sh: laptop-GPU full-pool continuation of the reasoner big top-up. HOLD: refuses to start unless $D/GO exists (owner go after dataset review).
# Start detached: setsid nohup bash run_full.sh > logs/run_full.out 2>&1 &   | stop: touch $D/STOP (clean stop after the current step; re-run resumes)
# Requires $D/data/{train_new,replay,dev_*}.jsonl from prep_data.py (pool minus gate/tests, long rows trimmed, x2 weight on report rows, dev split) - built by prep_data.py (see data/MANIFEST.json, PLAN.md).
QP=/mnt/c/Users/hp/Desktop/qidk/proofs; D=$QP/2026-11-21_rsn_full/topup; P=$QP/2026-11-21_rsn_full; BIG=$QP/2026-11-20_rsn_big; FT=$QP/2026-11-13_v3_train/rsn_ft
source $QP/2026-10-29_rsn_v3/kaggle/local/guard.sh; STATUS=$D/STATUS.md; SCRIPT=rsn_topup; RUN_ID=topup
[ -e $D/GO ] || die "HOLD: no $D/GO (owner review pending)" 2
mkdir -p $D/logs; set -a; source $FT/run_ft.env; set +a; D=$QP/2026-11-21_rsn_full/topup  # run_ft.env sets D: restore the run dir
export MAX_LEN=6656 FIT_FLAGS="--max-drop 0.07 --micro-tokens 6656 --head-cpu --ckpt-offload --mlp-chunk 256 --lean-host --oom-stop"  # shared-prefix off: batch OOM + allocator assert (2026-11-21). rows > 6144 tokens skipped (OOM retries + allocator assert on the 6 GB GPU)
for f in train_new replay; do [ -s $D/data/$f.jsonl ] || die "missing $D/data/$f.jsonl (run prep_data.py)" 2; done
export RUN=rsn_topup BASE=$(cat $FT/chain/BASE) NEW=$D/data/train_new.jsonl REPLAY=$D/data/replay.jsonl TOOLS4=$P/data/tools_v5.json
export DEV4_INC=$P/data/dev_inc.jsonl DEV4_CHAT=$P/data/dev_chat.jsonl
export START_ADAPTER=$HOME/smartcity_runs/rsn_full/ckpt_0640 CHUNK_H=6 MAX_STEPS=${MAX_STEPS:-400}
# mix 0.65 new / 0.35 replay; epochs set by prep (rows/step 16); ~1200 steps
export TOPUP_FLAGS="--lr 1e-5 --warmup 0.05 --floor 0.1 --accum 16 --mix 0.75 --epochs 1 --save-every 25 --eval-every 100 --gen-every 100 --patience 2 --keep-best 3 --w-r4 0.6 --r3-tol 1.0 --mlp-chunk-min 3072 --offload-min 3072"  # 2026-11-24 chat top-up: fresh LR peak 1e-5, 400 steps (owner 2026-11-24: +200, reports too), 12 new + 4 replay per step, evals every 100 (24 rows)
export GEN_FLAGS="--gen-r4-n 24 --gen-n 12 --gen-r3 auto"
export RSN3_GEN_TOK_BUDGET=8000   # 2026-11-23: step-200 gen eval hit CUDA OOM (display shares the 6 GB GPU); smaller gen batches (default 24000)
# owner rules: NORMAL priority (no nice/ionice), CPU threads = nproc - 2, no memory cap. Windows free-RAM watchdog every 30 s (no pause at 2 GB):
#   < 1.5 GB: drop WSL page cache from the Windows side | < 1 GB: ALERT line (time, free MB, top-5 Windows processes by RAM) into $D/MEM_ALERT
#   < 500 MB: clean stop (STOP file in run dir + $D: trainer saves ckpt_latest and exits rc 3, re-run resumes)
# 2026-11-22 owner works on the laptop while it trains: 4 CPU threads, nice 10, GPU duty-cycle throttle (below)
NP=$(nproc); NT=4; [ "$NT" -gt "$NP" ] && NT=$NP
export OMP_NUM_THREADS=$NT MKL_NUM_THREADS=$NT OPENBLAS_NUM_THREADS=$NT NUMEXPR_NUM_THREADS=$NT TRAIN_NICE=10
status "nproc=$NP -> $NT CPU threads, nice 10, GPU throttle via $D/THROTTLE"
# GPU throttle (2026-11-24 v2): no signals. SIGSTOP/SIGCONT broke WSL dxg ioctls (dmesg Ioctl failed -512) and froze the display.
# The trainer itself pauses: rsn_ft_train.py decoder-layer hook, after ON ms of GPU work it syncs and sleeps OFF ms; $D/THROTTLE = "ON OFF" (ms), live.
[ -s $D/THROTTLE ] || echo "350 150" > $D/THROTTLE
# GPU_DUTY_FILE not set (owner 2026-11-24: no GPU-bridge throttling at all; slower but clean: mlp-chunk 256)
WSLX=/mnt/c/Windows/System32/wsl.exe; RUND=$HOME/smartcity_runs/$RUN; mkdir -p $RUND
( last_drop=0
  while sleep 30; do
    [ -e $D/DONE ] && exit 0
    f=$(free_mb); [ -z "$f" ] && continue
    if [ "$f" -lt 1500 ] && [ $(( $(date +%s) - last_drop )) -ge 60 ]; then
      timeout 60 $WSLX -u root sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' < /dev/null >/dev/null 2>&1; last_drop=$(date +%s); status "free RAM $f MB < 1500: page-cache drop requested"; fi
    if [ "$f" -lt 1000 ]; then
      echo "ALERT $(date '+%F %T') free ${f} MB" >> $D/MEM_ALERT; fi
    if [ "$f" -lt 250 ] && [ ! -e $D/STOP ]; then
      touch $D/STOP $RUND/STOP; status "Windows free RAM $f MB < 250: clean STOP requested (ckpt_latest saved, resumable: rm STOP files and re-run)"; fi
  done ) & GUARD=$!
need_ram 1536 1440
for i in 1 2 3 4 5 6 7 8; do   # chunks of 6 h; rc 3 = chunk/STOP -> resume (STOP file ends the loop)
  [ -e $D/STOP ] && break
  bash $FT/ft_chunk.sh; rc=$?; status "chunk $i rc=$rc"
  case $rc in 0|6) touch $D/DONE; break;; 3) ;; 7) status "OOM stop"; break;; *) sleep 600;; esac
done
kill $GUARD 2>/dev/null
if [ -e $D/DONE ]; then
  S=$(python3 -c "import json;t=json.load(open('$HOME/smartcity_runs/$RUN/best.json'))['top'];print(t[0][1] if t else -1)")  # empty top (no eval beat the start) -> ckpt_latest
  A=$(printf "%s/smartcity_runs/%s/ckpt_best_%04d" $HOME $RUN $S); [ "$S" -lt 0 ] && A=$HOME/smartcity_runs/$RUN/ckpt_latest
  # the gate skips export when the GGUF name exists and reuses res/new when complete: move step-640 outputs aside first
  G=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v3_4b_full_q4_0.gguf; T=$(date +%s)
  [ -e $G ] && mv $G ${G%.gguf}_s640_$T.gguf && mv $G.md5 ${G%.gguf}_s640_$T.gguf.md5 2>/dev/null
  [ -d $P/gate_full/res/new ] && mv $P/gate_full/res/new $P/gate_full/res/new_prev_$T
  status "after-run gate on $A (gate only, no deploy)"; bash $P/gate_full/gate_full.sh $A >> $D/logs/gate.out 2>&1; status "gate rc=$? (see $P/gate_full/GATE.md; step 640 = GATE_0640.md)"
fi
