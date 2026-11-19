#!/usr/bin/env bash
# wd_chunk.sh <trainer pid>: one-chunk replacement for laptop_train.sh's watchdog with the 2026-11-09 thresholds
# (owner keeps Chrome + VS Code open; WSL capped at 6 GB): pause at GPU >= 92 C or Windows available < 400 MB,
# resume at <= 88 C and >= 500 MB. Exits when the trainer exits. Status lines -> kaggle/STATUS.md.
SCRIPT=laptop_train; RUN_ID=; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
TP=$1; hot=0; np=0
kill -CONT $TP
while sleep 10; do kill -0 $TP 2>/dev/null || exit 0
  t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | head -1 | cut -d. -f1 | tr -dc 0-9); f=$(free_mb)
  if [ $hot = 0 ] && { { [ -n "$t" ] && [ "$t" -ge 92 ]; } || { [ -n "$f" ] && [ "$f" -lt 400 ]; }; }; then kill -STOP $TP; hot=1; np=$((np+1)); status "rsn3_4b_r3 paused (wd_chunk) #$np (gpu ${t}C, ram ${f} MB)"; fi
  if [ $hot = 1 ] && [ -n "$t" ] && [ "$t" -le 88 ] && { [ -z "$f" ] || [ "$f" -ge 500 ]; }; then kill -CONT $TP; hot=0; fi
done
