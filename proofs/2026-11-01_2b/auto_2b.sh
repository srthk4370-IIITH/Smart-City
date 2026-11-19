#!/usr/bin/env bash
# auto_2b.sh: wait for the 2B gate; on PASS run deploy26_2b.sh (lab -> promote, auto-rollback). On FAIL do nothing.
G=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/gate/g2b_r1/gate.json
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-01_2b
until [ -s "$G" ]; do sleep 120; done
if grep -q '"pass": *true' "$G"; then echo "$(date) gate PASS -> deploy26"; bash $D/deploy26_2b.sh
else echo "$(date) gate FAIL -> no deploy"; fi
