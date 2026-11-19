#!/usr/bin/env bash
# CPU dry run of post_chain.sh wait -> pick -> export on a tiny Qwen3.5 + fake finished run (make_tiny.py); the GPU gate step
# is pre-marked done. Every path/threshold is redirected into <outdir> (no real marker, STATUS.md, run dir or models_stage
# is touched). Then: a second launch must skip every step (idempotent), and the merge math is checked on one tensor.
# usage: bash t_export_tiny.sh <outdir>   (needs WSL MemAvailable >= 2.5 GB and Windows available >= 1.5 GB)
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post; O=${1:?outdir}
rm -rf $O; mkdir -p $O/state/markers $O/chain $O/stage
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
nice -n 15 ~/venvs/rsn/bin/python $P/test/make_tiny.py $O || exit 1
touch $O/chain/train.done; echo "holder=laptop" > $O/BATON; echo "skipped in the CPU dry run" > $O/state/markers/gate.done
export POST_STATUS=$O/status.md POST_OUT=$O/state POST_RUN=rsn3_tiny_post POST_RUNDIR=$O/run POST_NAME=tiny_post POST_BASE=$O/base \
  POST_CHAIN_DIR=$O/chain POST_BATON=$O/BATON POST_PICK_DIR=$O/pick STAGE_DIR=$O/stage WORK=/mnt/c/Users/hp/AppData/Local/Temp/post_4b_tiny_test \
  SCRIPT=post_4b_test RAM_WIN_MB=1500 RAM_WSL_MB=2000
nice -n 15 bash $P/post_chain.sh; echo "first run rc=$?"
nice -n 15 bash $P/post_chain.sh; echo "second run rc=$? (must skip every step)"
echo "--- status lines"; cat $O/status.md
echo "--- stage"; ls -la $O/stage; (cd $O/stage && md5sum -c tiny_post_q4_0.gguf.md5)
echo "--- work dir left: $(ls /mnt/c/Users/hp/AppData/Local/Temp/post_4b_tiny_test 2>&1 | head -2)"
echo "--- merge math + GGUF content"
mkdir -p $O/hfcheck
PYTHONPATH=~/gpu_work/llama.cpp/gguf-py nice -n 15 ~/venvs/rsn/bin/python - $O <<'EOF'
import json, os, sys, subprocess
import torch
from safetensors.torch import load_file
O = sys.argv[1]
q = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/merge_any.py"
a = os.path.join(O, "pick", "ckpt_best_0300")
print(subprocess.run([sys.executable, q, os.path.join(O, "base"), a, os.path.join(O, "hfcheck")], capture_output=True, text=True).stdout.strip())
base, merged = {}, {}
for d, t in ((os.path.join(O, "base"), base), (os.path.join(O, "hfcheck"), merged)):
    for f in os.listdir(d):
        if f.endswith(".safetensors"):
            t.update(load_file(os.path.join(d, f)))
lw = load_file(os.path.join(a, "adapter_model.safetensors"))
bad = 0
for k in [k for k in lw if k.endswith("lora_A.weight")]:
    mk = k.replace("base_model.model.", "").replace(".lora_A.weight", ".weight")
    exp = (base[mk].float() + 2.0 * (lw[k.replace("lora_A", "lora_B")].float() @ lw[k].float())).to(torch.bfloat16)
    bad += int(not torch.equal(exp, merged[mk]))
same = sum(int(torch.equal(base[k], merged[k])) for k in base if not any(k + "" == x.replace("base_model.model.", "").replace(".lora_A.weight", ".weight") for x in lw))
print("merge check: %d LoRA modules, %d mismatches vs W + (64/32)*B@A; untouched tensors identical: %d/%d" % (
    sum(1 for k in lw if k.endswith("lora_A.weight")), bad, same, len(base) - sum(1 for k in lw if k.endswith("lora_A.weight"))))
from gguf import GGUFReader
r = GGUFReader(os.path.join(O, "stage", "tiny_post_q4_0.gguf"))
ty = {}
for t in r.tensors:
    ty[t.tensor_type.name] = ty.get(t.tensor_type.name, 0) + 1
arch = bytes(r.fields["general.architecture"].parts[-1]).decode()
print("gguf: arch %s, %d tensors, types %s" % (arch, len(r.tensors), ty))
EOF
rm -rf $O/hfcheck
