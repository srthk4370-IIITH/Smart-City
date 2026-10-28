#!/usr/bin/env bash
# Step 2: merged_v2t3d -> f16 GGUF (same converter/shim as post_topup.sh), all-tensor GGUF check, reproduce the
# deployed Q4_0 bit-exactly (same imatrix + types), Q8_0 for host evals (v2 and 3d).
set -uo pipefail
R=~/smartcity_runs/agents_v2_topup3d; FIX=$R/post/gguf_fix; W=$FIX/work; mkdir -p $W $FIX/merge_verify
S=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-23_3d_quant_fix/scripts
L=~/gpu_work/llama.cpp; B=$L/build-host/bin; PY=~/venvs/train/bin/python; TH=4
V2G=~/smartcity_runs/agents_v2/post/gguf
dc() { /mnt/c/Windows/System32/wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null; }
TYPES="--output-tensor-type q8_0 --token-embedding-type f16 --tensor-type ffn_down=q4_0"
cd $W
if [ ! -s ft_v2t3d_f16.gguf ]; then
  echo "[$(date)] convert"; PYTHONPATH="$L/gguf-py:$R/post/pyshim" nice $PY $L/convert_hf_to_gguf.py $R/merged_v2t3d --outtype f16 --outfile ft_v2t3d_f16.gguf.tmp > convert.log 2>&1 && mv ft_v2t3d_f16.gguf.tmp ft_v2t3d_f16.gguf; tail -2 convert.log; dc
fi
echo "[$(date)] verify gguf f16 vs merged (+ 3d-vs-v2 weight change)"
nice $PY $S/verify_gguf.py ft_v2t3d_f16.gguf $R/merged_v2t3d $FIX/merge_verify/gguf_f16_vs_merged.json ~/smartcity_runs/agents_v2/merged_v2; dc
echo "[$(date)] reproduce deployed Q4_0"
nice $B/llama-quantize --imatrix $R/post/gguf/imatrix_v2t3d.gguf $TYPES ft_v2t3d_f16.gguf repro_q4_0.gguf Q4_0 $TH > repro_q4_0.log 2>&1
md5sum repro_q4_0.gguf $R/post/gguf/ft_v2t3d_q4_0.gguf | tee $FIX/merge_verify/repro_md5.txt; rm -f repro_q4_0.gguf; dc
for m in "ft_v2t3d_f16.gguf ft_v2t3d_q8_0.gguf" "$V2G/ft_v2_f16.gguf ft_v2_q8_0.gguf"; do set -- $m
  [ -s $2 ] || { echo "[$(date)] q8_0 $2"; nice $B/llama-quantize $1 $2.tmp Q8_0 $TH > $2.log 2>&1 && mv $2.tmp $2; dc; }
done
ls -la $W; echo "[$(date)] STEP2 DONE"
