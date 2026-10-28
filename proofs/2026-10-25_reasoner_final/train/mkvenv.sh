#!/usr/bin/env bash
# new venv for Qwen3.5 QLoRA (train venv's transformers 4.46 cannot load qwen3_5)
set -e
L=~/smartcity_runs/reasoner_v1/mkvenv.log; mkdir -p ~/smartcity_runs/reasoner_v1; exec > $L 2>&1
python3 -m venv ~/venvs/rsn; . ~/venvs/rsn/bin/activate
pip install -q --upgrade pip
nice -n 19 pip install -q torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124
nice -n 19 pip install -q "transformers>=5.0" peft accelerate bitsandbytes safetensors sentencepiece
nice -n 19 pip install -q flash-linear-attention || echo "FLA install failed"
python -c "import torch,transformers,peft,bitsandbytes;print('OK',torch.__version__,transformers.__version__,peft.__version__,bitsandbytes.__version__)"
python -c "import fla;print('fla',fla.__version__)" || true
echo VENV_DONE
