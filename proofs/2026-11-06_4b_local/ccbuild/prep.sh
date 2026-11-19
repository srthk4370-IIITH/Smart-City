set -e
C=~/ccsrc/cuda; mkdir -p $C; cd $C
for f in ~/ccsrc/dl/*.tar.xz; do tar xf $f --strip-components=1; done
NV=~/venvs/rsn/lib/python3.12/site-packages/nvidia
for d in cublas cusparse cusolver curand cufft nvtx cuda_runtime; do [ -d $NV/$d/include ] && for h in $NV/$d/include/*; do [ -e include/$(basename $h) ] || ln -s $h include/; done; done
ls lib64 | head; ls bin
cd ~/ccsrc && tar xzf causal_conv1d-1.5.2.tar.gz
grep -n "environ\|getenv" causal_conv1d-1.5.2/setup.py
gcc --version | head -1; which g++ c++
