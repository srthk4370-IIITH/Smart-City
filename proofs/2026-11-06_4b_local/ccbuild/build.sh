# causal-conv1d 1.5.2 build: CPU-only nvcc compile, sm_89 only, cxx11abi FALSE
cd ~/ccsrc/causal_conv1d-1.5.2
grep -q PATCHED_SM89 setup.py || python3 - <<'PY'
p='setup.py'; s=open(p).read()
s=s.replace('["--threads", "4"]','["--threads", "1"]')
s=s.replace('    ext_modules.append(\n        CUDAExtension(','    cc_flag = [f for f in cc_flag if f != "-gencode" and not f.startswith("arch=")] + ["-gencode", "arch=compute_89,code=sm_89"]  # PATCHED_SM89\n    ext_modules.append(\n        CUDAExtension(',1)
open(p,'w').write(s)
PY
grep -n "PATCHED_SM89\|--threads" setup.py
[ -e ~/ccsrc/cuda/lib64 ] || ln -s lib ~/ccsrc/cuda/lib64
export CUDA_HOME=~/ccsrc/cuda PATH=~/ccsrc/cuda/bin:~/venvs/ccbuild/bin:$PATH
export CAUSAL_CONV1D_FORCE_BUILD=TRUE CAUSAL_CONV1D_FORCE_CXX11_ABI=FALSE TORCH_CUDA_ARCH_LIST=8.9 MAX_JOBS=1 CUDA_VISIBLE_DEVICES=""
nvcc --version | tail -2
python -c "import torch;print(torch.__version__, torch.__file__, torch._C._GLIBCXX_USE_CXX11_ABI)"
# RAM watchdog: abort build if available < 800 MB; log peak used
( peak=0; while sleep 3; do a=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo); u=$(ps -o rss= -g $$ 2>/dev/null | awk '{s+=$1}END{print int(s/1024)}'); [ "$u" -gt "$peak" ] && peak=$u && echo $peak > ~/ccsrc/peak_mb; if [ "$a" -lt 800 ]; then echo "WATCHDOG: avail ${a}MB <800, aborting"; pkill -g $$ -f "nvcc|cicc|ptxas|cc1plus|pip wheel"; fi; done ) &
W=$!
mkdir -p ~/wheels/built
time pip wheel --no-deps --no-build-isolation -v -w ~/wheels/built . 2>&1 | grep -v "^  *copying\|^ *adding" | tail -60
kill $W
echo "peak build-group RSS MB: $(cat ~/ccsrc/peak_mb)"
ls -la ~/wheels/built
echo BUILD_DONE
