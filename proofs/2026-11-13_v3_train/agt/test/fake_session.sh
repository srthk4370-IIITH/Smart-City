#!/usr/bin/env bash
# fake_session.sh SHIMDIR: runs the pushed (seq/nonce-filled) agt3_kernel.py on CPU against the shim's datasets: no pip, the tiny
# base, fp32 + torch AdamW, at most SESSION_STEPS steps per session (exercises exit 3 + resume), launched by FAKE_LAUNCH.
S=$1; IN=$S/input; rm -rf "$IN"; mkdir -p "$IN"
for d in "$S"/ds/*; do ln -s "$d" "$IN/$(basename "$d")"; done
export PATH=$HOME/venvs/rsn/bin:$PATH CUDA_VISIBLE_DEVICES= AGT3_INPUT=$IN AGT3_WORK=$S/kernel/working AGT3_TMP=$S/ktmp AGT3_SKIP_PIP=1 \
  AGT3_BASE_DIR=$TINY AGT3_TRAIN_FLAGS="--dtype fp32 --optim adamw --gen-batch 2 --max-steps-session ${SESSION_STEPS:-3}"
[ -n "${FAKE_LAUNCH:-}" ] && export AGT3_LAUNCH="$FAKE_LAUNCH"
rm -rf "$S/ktmp"; mkdir -p "$S/ktmp"
python "$S/kernel/agt3_kernel.py"
