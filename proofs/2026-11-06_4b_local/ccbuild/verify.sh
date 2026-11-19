cd ~/ccsrc; rm -rf vt; mkdir vt; cd vt
W=$(ls ~/wheels/built/causal_conv1d-*.whl | head -1); echo "$W"; sha256sum "$W"
python3 -m zipfile -e "$W" .
SO=$(ls causal_conv1d_cuda*.so); ls -la $SO
echo "cxx11 c10 syms: $(nm -D $SO | grep -c '__cxx11.*c10\|c10.*__cxx11')"
echo "total __cxx11 syms: $(nm -D $SO | grep -c __cxx11)"
nm -D $SO | grep -c '_ZN3c107WarningC1'; nm -D $SO | grep '_ZN3c107WarningC1' 
cd ~ && CUDA_VISIBLE_DEVICES="" PYTHONPATH=~/ccsrc/vt ~/venvs/ccbuild/bin/python -c "import torch, causal_conv1d_cuda, causal_conv1d; print('IMPORT_OK', torch.__version__, causal_conv1d_cuda.__file__, causal_conv1d.__version__)"
