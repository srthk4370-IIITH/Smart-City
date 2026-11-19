#!/usr/bin/env bash
# rsn_p2_export.sh: the winner (p2 best) as Code/models_stage/rsn_v3_4b_p2_q4_0.gguf + .md5 (already made by the gate's export; this checks md5,
# C: >= 20 GB and records it). Not deployed.
SCRIPT=rsn_p2_export; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
G=$QIDK/Code/models_stage/rsn_v3_4b_p2_q4_0.gguf
[ "$(df -Pm /mnt/c | awk 'NR==2{print $4}')" -ge 20000 ] || die "C: free < 20 GB" 5
[ -s "$G" ] && [ -s "$G.md5" ] || die "no $G" 2
(cd $(dirname $G) && md5sum -c $(basename $G).md5) || die "md5 mismatch" 2
status "export: winner $G md5 $(cut -d' ' -f1 $G.md5) (not deployed)"
