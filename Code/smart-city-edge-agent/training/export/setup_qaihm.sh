#!/usr/bin/env bash
# Environment for exporting the fine-tuned model to a Genie bundle (qai-hub-models 0.63.0, QAIRT 2.50).
# CPU torch/torchvision from the PyTorch mirror (PyPI's CDN is slow here and the newest torchvision would pull a
# 2.5 GB CUDA torch). Never touches the training GPU.
set -euo pipefail
PY=$HOME/.pyenv/versions/3.11.9/bin/python3.11
[ -d ~/venvs/qaihm ] || $PY -m venv ~/venvs/qaihm
source ~/venvs/qaihm/bin/activate
pip install -q --upgrade pip
pip install --progress-bar off "torch==2.10.0" "torchvision==0.25.0" --index-url https://download.pytorch.org/whl/cpu
printf 'torch==2.10.0+cpu\ntorchvision==0.25.0+cpu\n' > /tmp/qaihm_constraints.txt
PIP_CONSTRAINT=/tmp/qaihm_constraints.txt pip install --progress-bar off "qai-hub-models==0.63.0" \
  --extra-index-url https://download.pytorch.org/whl/cpu
P=$(python -c "import qai_hub_models,os;print(os.path.dirname(qai_hub_models.__file__))")
# generic template requirements first, the model-specific pins LAST so they win (torch.export node names must
# match the published encodings)
for f in "$P/models/templates/llm/requirements.txt" "$P/models/templates/llama3/requirements.txt" "$P/models/llama_v3_2_3b_instruct/requirements.txt"; do
  if [ -f "$f" ]; then echo "== requirements: $f"; cat "$f"; PIP_CONSTRAINT=/tmp/qaihm_constraints.txt pip install --progress-bar off -r "$f" --extra-index-url https://download.pytorch.org/whl/cpu || true; fi
done
python -c "import qai_hub_models, torch, transformers, onnx; print('qaihm', qai_hub_models.__version__, 'torch', torch.__version__, 'tf', transformers.__version__, 'onnx', onnx.__version__)"
python -c "from qai_hub_models.models.llama_v3_2_3b_instruct.model import Llama3_2_3B_PreSplit, Llama3_2_3B_QuantizablePreSplit; print('llama export classes import OK')"
qai-hub list-devices 2>&1 | grep -i -E "s24|8 gen 3" | head -3 || echo "AI Hub token: run 'qai-hub configure --api_token <token>' if no devices are listed"
