#!/usr/bin/env bash
# fake_session.sh SHIM: what rsn3_r3_baton.py does on Kaggle, minus pip/GPU: real baton_util.py kunpack (seq, tar md5, file md5,
# scaler inject, step) -> fake training (step += $SHIM/steps, fp16 scaler state, a new best-K checkpoint, logs) -> real kpack.
# $SHIM/session: ok | killed (no pack: raw run/ left in the output) | stale (kernel expects another seq).
set -u
S=$1; W=$S/kernel/working; OUT=$W/run; U=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/baton/baton_util.py
PY=${BATON_PY:-$HOME/venvs/rsn/bin/python}
seq=$(sed -n 's/^EXPECT_SEQ = int("\([0-9]*\)").*/\1/p' "$S/kernel/rsn3_r3_baton.py")
nonce=$(sed -n 's/^EXPECT_NONCE = "\([0-9a-f]*\)".*/\1/p' "$S/kernel/rsn3_r3_baton.py")
mode=$(cat "$S/session" 2>/dev/null || echo ok); [ "$mode" = stale ] && seq=$((seq + 1))
BD=$S/ds/rsn3-r3-baton
[ -f "$S/ds/rsn3-r3-data/R3_DATA_OK" ] || { echo '{"abort": "data dataset not attached"}' > "$W/KAGGLE_RESULT.json"; exit 0; }
if ! msg=$($PY "$U" kunpack "$BD" "$OUT" "$seq" "$nonce"); then
  python3 -c "import json,sys;json.dump({'seq':int(sys.argv[1]),'ok':False,'abort':sys.argv[2]},open(sys.argv[3],'w'))" "$seq" "$(echo "$msg" | tail -1)" "$W/KAGGLE_RESULT.json"
  rm -rf "$OUT"; echo "ABORT: $msg"; exit 0
fi
echo "$msg"
s0=$($PY "$U" step "$OUT/ckpt_latest/state.pt")
$PY - "$OUT" "$(cat "$S/steps" 2>/dev/null || echo 50)" <<'PY'
import json, os, shutil, sys, time
os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch
out, n = sys.argv[1], int(sys.argv[2])
p = os.path.join(out, "ckpt_latest", "state.pt")
st = torch.load(p, weights_only=False, map_location="cpu")
st["step"] += n; st["sched"]["last_epoch"] += n; st["sched"]["_step_count"] = st["sched"].get("_step_count", 0) + n
st["scaler"] = st.get("scaler") or {"scale": 8192.0, "growth_factor": 2.0, "backoff_factor": 0.5, "growth_interval": 2000, "_growth_tracker": 0}
st["scaler"]["_growth_tracker"] += n
st.update(dtype="torch.float16", world=2, host="kaggle-fake")
torch.save(st, p)
s = st["step"]
json.dump({"step": s, "schedule": "mixed", "t": time.time()}, open(os.path.join(out, "status.json"), "w"))
open(os.path.join(out, "train.log"), "a").write("[fake] step %d/9999 (e1) loss 0.5 kaggle fake session\n" % s)
bp = os.path.join(out, "best.json")
b = json.load(open(bp)) if os.path.exists(bp) else {"top": [], "best": None, "since_best": 0, "evals": 0}
d = os.path.join(out, "ckpt_best_%04d" % s)
os.makedirs(d, exist_ok=True)
for f in ("adapter_model.safetensors", "adapter_config.json"):
    shutil.copy(os.path.join(out, "ckpt_latest", f), d)
sc = (b["best"] or 0.5) + 0.01
top = sorted(b["top"] + [[sc, s]], key=lambda x: (-x[0], -x[1]))
for _, s_ in top[3:]:
    shutil.rmtree(os.path.join(out, "ckpt_best_%04d" % s_), ignore_errors=True)
b.update(top=top[:3], best=sc, evals=b["evals"] + 1)
json.dump(b, open(bp, "w"), indent=1)
print("fake trained to step", s)
PY
mkdir -p "$W/wheels"; echo fakewheel > "$W/wheels/torch2.6.0124-py313__causal_conv1d-1.5.2-cp313-cp313-linux_x86_64.whl"
mkdir -p /tmp/fake_triton && echo k > /tmp/fake_triton/kernel.json && tar -cf "$W/triton_cache.tar" -C /tmp/fake_triton . && rm -rf /tmp/fake_triton
ls "$BD" > "$S/kernel/baton_inputs.txt"
[ "$mode" = killed ] && { echo "session killed before packing"; exit 0; }
r=$($PY "$U" kpack "$OUT" "$W" "$seq" "$s0" 3 2 "Tesla T4+Tesla T4" 11.1) || { echo "kpack failed: $r"; exit 0; }
python3 -c "import json,sys;json.dump({'seq':int(sys.argv[1]),'ok':True,'rc':3,'step_to':json.loads(sys.argv[2])['step_to']},open(sys.argv[3],'w'))" "$seq" "$(echo "$r" | tail -1)" "$W/KAGGLE_RESULT.json"
echo "packed: $r"
