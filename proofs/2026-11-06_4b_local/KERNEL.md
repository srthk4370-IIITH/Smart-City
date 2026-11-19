# causal-conv1d 1.5.2 local build (cxx11abi FALSE, sm_89) - IN PROGRESS

Why: the prebuilt wheel in ~/wheels was built with cxx11 ABI and fails to import in ~/venvs/rsn (undefined symbol c10::Warning __cxx11).

Toolchain: pip nvidia-cuda-nvcc-cu12 ships only ptxas, no nvcc. So CUDA 12.4 redist tarballs were used instead
(cuda_nvcc 12.4.131, cuda_cudart 12.4.127, cuda_cccl 12.4.127 from developer.download.nvidia.com/compute/cuda/redist).
They are unpacked to ~/ccsrc/cuda (CUDA_HOME). lib64 points to lib. The cublas, cusparse, cusolver, curand, cufft and nvtx headers are symlinked from rsn's nvidia pip packages.
Build venv: ~/venvs/ccbuild (setuptools, wheel, ninja). Torch is read from rsn's site-packages through a .pth file, so nothing is installed into rsn.
setup.py patches: gencode list replaced by sm_89 only, nvcc --threads 1. Env: FORCE_BUILD=TRUE, FORCE_CXX11_ABI=FALSE, MAX_JOBS=1, CUDA_VISIBLE_DEVICES="". No GPU used.
The build runs detached with an 800 MB MemAvailable watchdog. Log: ~/detached/ccbuild.log. Output: ~/wheels/built/.
Verify: wsl bash proofs/2026-11-06_4b_local/ccbuild/verify.sh (sha256, nm -D __cxx11 count, import check with CUDA hidden).
Scripts: proofs/2026-11-06_4b_local/ccbuild/{fetch,prep,build,verify}.sh

## Result (2026-11-06 14:00 IST, applied to the live 4B r3 run)
- Wheel `~/wheels/built/causal_conv1d-1.5.2-cp312-cp312-linux_x86_64.whl`, sha256 958305eb4faab8291b02eb9e7f65f942d0059dd9c17d64884b53216f8fbd5076,
  sm_89, old C++ ABI (0 `__cxx11` symbols; c10::Warning resolves to the `Ss` string form), import OK.
- The official prebuilt 1.5.2 cu12torch2.6 cxx11abiFALSE wheel failed to import (undefined `c10::Warning` with `__cxx11` string): mislabelled ABI.
- GPU check vs the PyTorch reference (bf16, D 8192, T 7424, K 4, silu): forward rel 1.43e-3 (max abs 0.062), backward rel 1.50e-3 (x)
  / 1.67e-3 (w). Conv time 1.41 ms vs 6.86 ms (4.9x). transformers detects it.
- Installed with --no-deps into ~/venvs/rsn at the step-20 checkpoint; run restarted with it and with the heat guard 92/88.
- Rollback: `~/venvs/rsn/bin/pip uninstall -y causal-conv1d` at a clean stop.
