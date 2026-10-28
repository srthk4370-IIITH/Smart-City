#!/usr/bin/env bash
# rest of step 2, one heavy WSL command per gate (Windows side): md5 repro of the deployed Q4_0, Q8_0 for v2 and 3d
S=/c/Users/hp/Desktop/qidk/proofs/2026-10-23_3d_quant_fix/scripts
FIXW='~/smartcity_runs/agents_v2_topup3d/post/gguf_fix'
B='~/gpu_work/llama.cpp/build-host/bin'
DC="wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'"
TYPES="--output-tensor-type q8_0 --token-embedding-type f16 --tensor-type ffn_down=q4_0"
$S/gate.sh wsl.exe -d Ubuntu -- bash -c "cd $FIXW/work && nice $B/llama-quantize --imatrix ../../gguf/imatrix_v2t3d.gguf $TYPES ft_v2t3d_f16.gguf repro_q4_0.gguf Q4_0 4 > repro_q4_0.log 2>&1; md5sum repro_q4_0.gguf ../../gguf/ft_v2t3d_q4_0.gguf | tee ../merge_verify/repro_md5.txt; rm -f repro_q4_0.gguf"; eval $DC
$S/gate.sh wsl.exe -d Ubuntu -- bash -c "cd $FIXW/work && nice $B/llama-quantize ft_v2t3d_f16.gguf ft_v2t3d_q8_0.gguf.tmp Q8_0 4 > q8_3d.log 2>&1 && mv ft_v2t3d_q8_0.gguf.tmp ft_v2t3d_q8_0.gguf"; eval $DC
$S/gate.sh wsl.exe -d Ubuntu -- bash -c "cd $FIXW/work && nice $B/llama-quantize ~/smartcity_runs/agents_v2/post/gguf/ft_v2_f16.gguf ft_v2_q8_0.gguf.tmp Q8_0 4 > q8_v2.log 2>&1 && mv ft_v2_q8_0.gguf.tmp ft_v2_q8_0.gguf"; eval $DC
wsl.exe -d Ubuntu -- bash -c "ls -la $FIXW/work; cat $FIXW/merge_verify/repro_md5.txt"
echo STEP2B DONE
