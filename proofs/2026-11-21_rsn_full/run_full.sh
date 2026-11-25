#!/usr/bin/env bash
# run_full.sh: laptop-GPU full-pool continuation of the reasoner big top-up. HOLD: refuses to start unless $D/GO exists (owner go after dataset review).
# Start detached: setsid nohup bash run_full.sh > logs/run_full.out 2>&1 &   | stop: touch $D/STOP (clean stop after the current step; re-run resumes)
# Requires $D/data/{train_new,replay,dev_*}.jsonl from prep_data.py (pool minus gate/tests, long rows trimmed, x2 weight on report rows, dev split) - built by prep_data.py (see data/MANIFEST.json, PLAN.md).
QP=/mnt/c/Users/hp/Desktop/qidk/proofs; D=$QP/2026-11-21_rsn_full; BIG=$QP/2026-11-20_rsn_big; FT=$QP/2026-11-13_v3_train/rsn_ft
source $QP/2026-10-29_rsn_v3/kaggle/local/guard.sh; STATUS=$D/STATUS.md; SCRIPT=rsn_full; RUN_ID=full
[ -e $D/GO ] || die "HOLD: no $D/GO (owner review pending)" 2
mkdir -p $D/logs; set -a; source $FT/run_ft.env; set +a; D=$QP/2026-11-21_rsn_full  # run_ft.env sets D: restore the run dir
export MAX_LEN=6656 FIT_FLAGS="--max-drop 0.07 --micro-tokens 6656 --head-cpu --ckpt-offload --mlp-chunk 512 --lean-host --oom-stop"  # shared-prefix off: batch OOM + allocator assert (2026-11-21). rows > 6144 tokens skipped (OOM retries + allocator assert on the 6 GB GPU)
for f in train_new replay dev_inc dev_chat; do [ -s $D/data/$f.jsonl ] || die "missing $D/data/$f.jsonl (run prep_data.py)" 2; done
export RUN=rsn_full BASE=$(cat $FT/chain/BASE) NEW=$D/data/train_new.jsonl REPLAY=$D/data/replay.jsonl TOOLS4=$([ -s $D/data/tools_v5.json ] && echo $D/data/tools_v5.json || echo $BIG/data/final_big/tools_v4.json)
export DEV4_INC=$D/data/dev_inc.jsonl DEV4_CHAT=$D/data/dev_chat.jsonl
export START_ADAPTER=$BIG/best/ckpt_best_0242 CHUNK_H=6 MAX_STEPS=${MAX_STEPS:-1200}
# mix 0.65 new / 0.35 replay; epochs set by prep (rows/step 16); ~1200 steps
export TOPUP_FLAGS="--lr 2e-5 --warmup 0.03 --floor 0.1 --accum 16 --mix 0.65 --epochs 0.375 --save-every 50 --eval-every 100 --gen-every 100 --patience 2 --keep-best 3 --w-r4 0.6 --r3-tol 1.0 --mlp-chunk-min 3072 --offload-min 3072"
export GEN_FLAGS="--gen-r4-n 12 --gen-n 12 --gen-r3 auto"
export RSN3_GEN_TOK_BUDGET=8000   # 2026-11-23: step-200 gen eval hit CUDA OOM (display shares the 6 GB GPU); smaller gen batches (default 24000)
# owner rules: NORMAL priority (no nice/ionice), CPU threads = nproc - 2, no memory cap. Windows free-RAM watchdog every 30 s (no pause at 2 GB):
#   < 1.5 GB: drop WSL page cache from the Windows side | < 1 GB: ALERT line (time, free MB, top-5 Windows processes by RAM) into $D/MEM_ALERT
#   < 500 MB: clean stop (STOP file in run dir + $D: trainer saves ckpt_latest and exits rc 3, re-run resumes)
# 2026-11-22 owner works on the laptop while it trains: 4 CPU threads, nice 10, GPU duty-cycle throttle (below)
NP=$(nproc); NT=4; [ "$NT" -gt "$NP" ] && NT=$NP
export OMP_NUM_THREADS=$NT MKL_NUM_THREADS=$NT OPENBLAS_NUM_THREADS=$NT NUMEXPR_NUM_THREADS=$NT TRAIN_NICE=10
status "nproc=$NP -> $NT CPU threads, nice 10, GPU throttle via $D/THROTTLE"
# GPU throttle: the RTX 4050 also drives the display; a 100% busy GPU lags the desktop/Chrome. Every cycle the trainer is
# SIGSTOPped for OFF ms and runs ON ms, leaving idle GPU slices for the compositor. $D/THROTTLE = "ON OFF" (ms), re-read each
# cycle (edit live; "1000 0" = off). Default 350 on / 150 off (~70 % duty).
[ -s $D/THROTTLE ] || echo "350 150" > $D/THROTTLE
( while sleep 1; do
    [ -e $D/DONE ] && exit 0
    for p in $(pgrep -f "rsn_ft_train.py"); do
      read on off < $D/THROTTLE 2>/dev/null; on=${on:-1000}; off=${off:-0}
      while kill -0 $p 2>/dev/null; do
        read on off < $D/THROTTLE 2>/dev/null; on=${on:-1000}; off=${off:-0}
        if [ "$off" -gt 0 ]; then kill -STOP $p 2>/dev/null; sleep 0.$(printf %03d $off); kill -CONT $p 2>/dev/null; fi
        sleep $(awk "BEGIN{print $on/1000}")
      done
    done
  done ) & THR=$!
trap 'kill $THR 2>/dev/null; for p in $(pgrep -f rsn_ft_train.py); do kill -CONT $p 2>/dev/null; done' EXIT
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
  cp -r $BIG/gate $D/gate_step242_backup 2>/dev/null
  status "after-run gate on $A (gate only, no deploy)"; bash $D/gate_full/gate_full.sh $A >> $D/logs/gate.out 2>&1; status "gate rc=$? (see $D/gate_full/GATE.md)"
fi
