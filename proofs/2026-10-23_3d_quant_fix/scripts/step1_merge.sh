#!/usr/bin/env bash
# Step 1: re-merge 3d (step 50) with merge_lowmem.py (unchanged), verify ALL tensors vs PEFT; validate merge_lowmem
# itself against merge_v2.py's PEFT merge_and_unload output (merged_v2) on ALL tensors.
set -uo pipefail
R=~/smartcity_runs/agents_v2_topup3d; FIX=$R/post/gguf_fix; mkdir -p $FIX/merge_verify
S=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-23_3d_quant_fix/scripts
T=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup
PY=~/venvs/train/bin/python; export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 HF_HUB_OFFLINE=1
dc() { /mnt/c/Windows/System32/wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null; }
echo "[$(date)] merge 3d"; nice $PY $T/merge_lowmem.py --post $R/post --out $R/merged_v2t3d; dc
echo "[$(date)] verify 3d vs PEFT"; nice $PY $S/verify_merge.py peft $R/checkpoints/checkpoint-50 $R/merged_v2t3d $FIX/merge_verify/v2t3d_vs_peft.json; dc
mkdir -p $FIX/v2check; $PY - <<'P'
import json, os
p = os.path.expanduser("~/smartcity_runs/agents_v2_topup3d/post/gguf_fix/v2check/choice.json")
c = json.load(open(os.path.expanduser("~/smartcity_runs/agents_v2/post/choice.json"))); json.dump(c, open(p, "w"), indent=1)
P
echo "[$(date)] merge v2 lowmem"; nice $PY $T/merge_lowmem.py --post $FIX/v2check --out $FIX/v2check/merged_v2_lowmem; dc
echo "[$(date)] verify v2 lowmem vs merged_v2 (merge_v2.py / PEFT merge_and_unload)"
nice $PY $S/verify_merge.py ref $FIX/v2check/merged_v2_lowmem ~/smartcity_runs/agents_v2/merged_v2 $FIX/merge_verify/v2_lowmem_vs_merge_v2.json
rm -rf $FIX/v2check/merged_v2_lowmem; dc
echo "[$(date)] STEP1 DONE"
