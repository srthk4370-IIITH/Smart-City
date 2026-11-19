#!/usr/bin/env bash
L=$HOME/smartcity_runs/rsn3_4b_r3; S=$HOME/smartcity_runs/ab_base44
$HOME/venvs/rsn/bin/python -c "import torch;print(torch.load(\"$L/ckpt_latest/state.pt\",map_location=\"cpu\",weights_only=False)[\"step\"])"
mkdir -p $S && cp -a $L/ckpt_latest $L/schedule.json $L/maxlen.json $L/caches.json $S/ && [ -e $L/best.json ] && cp $L/best.json $S/; ls -la $S $S/ckpt_latest; $HOME/venvs/rsn/bin/python -c "import torch;print(torch.load(\"$S/ckpt_latest/state.pt\",map_location=\"cpu\",weights_only=False)[\"step\"])"
