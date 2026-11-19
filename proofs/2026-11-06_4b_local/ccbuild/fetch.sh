set -e
~/venvs/ccbuild/bin/pip uninstall -y -q nvidia-cuda-nvcc-cu12 nvidia-cuda-cccl-cu12 || true
mkdir -p ~/ccsrc/dl && cd ~/ccsrc/dl
B=https://developer.download.nvidia.com/compute/cuda/redist
for p in cuda_nvcc/linux-x86_64/cuda_nvcc-linux-x86_64-12.4.131-archive cuda_cudart/linux-x86_64/cuda_cudart-linux-x86_64-12.4.127-archive cuda_cccl/linux-x86_64/cuda_cccl-linux-x86_64-12.4.127-archive; do curl -sfLO $B/$p.tar.xz; done
ls -la
cd ..
U=$(curl -s https://pypi.org/pypi/causal-conv1d/1.5.2/json | python3 -c 'import sys,json;print([u["url"] for u in json.load(sys.stdin)["urls"] if u["packagetype"]=="sdist"][0])')
curl -sfLO "$U"; ls
