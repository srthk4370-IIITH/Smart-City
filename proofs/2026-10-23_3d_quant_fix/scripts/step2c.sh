#!/usr/bin/env bash
S=/c/Users/hp/Desktop/qidk/proofs/2026-10-23_3d_quant_fix/scripts
SW=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-23_3d_quant_fix/scripts
FIXW='~/smartcity_runs/agents_v2_topup3d/post/gguf_fix'
B='~/gpu_work/llama.cpp/build-host/bin'; PY='~/venvs/train/bin/python'
DC="wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'"
TYPES="--output-tensor-type q8_0 --token-embedding-type f16 --tensor-type ffn_down=q4_0"
$S/gate.sh wsl.exe -d Ubuntu -- bash -c "cd $FIXW/work && nice $PY $SW/verify_gguf.py ft_v2t3d_f16.gguf ~/smartcity_runs/agents_v2_topup3d/merged_v2t3d ../merge_verify/gguf_f16_vs_merged.json ~/smartcity_runs/agents_v2/merged_v2"; eval $DC
$S/gate.sh wsl.exe -d Ubuntu -- bash -c "cd $FIXW/work && nice $B/llama-quantize --imatrix ../../gguf/imatrix_v2t3d.gguf $TYPES ft_v2t3d_f16.gguf repro_q4_0.gguf Q4_0 4 > repro_q4_0.log 2>&1; nice $PY $SW/cmp_gguf.py repro_q4_0.gguf ../../gguf/ft_v2t3d_q4_0.gguf ../merge_verify/repro_vs_deployed_q4_0.json; rm -f repro_q4_0.gguf"; eval $DC
echo STEP2C DONE
