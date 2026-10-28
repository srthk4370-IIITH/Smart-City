#!/usr/bin/env bash
# Build candidate Q4_0-family GGUFs from the f16 GGUF.  bash step3_quant.sh <3d|v2> <name> <imatrix> <tensor-type args...>
set -uo pipefail
TAG=$1; NAME=$2; IMX=$3; shift 3
FIX=~/smartcity_runs/agents_v2_topup3d/post/gguf_fix; B=~/gpu_work/llama.cpp/build-host/bin
F16=$FIX/work/ft_v2t3d_f16.gguf; [ "$TAG" = v2 ] && F16=~/smartcity_runs/agents_v2/post/gguf/ft_v2_f16.gguf
O=$FIX/ft_${TAG/3d/v2t3d}_${NAME}.gguf
[ -s $O ] && { echo "exists $O"; exit 0; }
ARGS=(--output-tensor-type q8_0 --token-embedding-type f16)
for t in "$@"; do ARGS+=(--tensor-type "$t"); done
nice $B/llama-quantize --imatrix $IMX "${ARGS[@]}" $F16 $O.tmp Q4_0 4 > $O.log 2>&1 && mv $O.tmp $O
grep -E "model size|quant size" $O.log; md5sum $O | tee $O.md5
/mnt/c/Windows/System32/wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null
