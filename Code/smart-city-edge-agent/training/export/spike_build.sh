#!/usr/bin/env bash
# Spike: build the Qualcomm checkpoint from the UNMODIFIED base model (validates build_ft_ckpt.py; no upload).
source ~/venvs/qaihm/bin/activate
export TZ=Asia/Kolkata HF_HUB_OFFLINE=1
BASE=$(ls -d ~/.cache/huggingface/hub/models--meta-llama--Llama-3.2-3B-Instruct/snapshots/* | head -1)
OUT=~/qaihm_work/base_spike_ckpt_w4a16
mkdir -p ~/qaihm_work
echo "=== $(date) building $OUT from $BASE"; free -g | head -2
/usr/bin/time -v python /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/export/build_ft_ckpt.py "$BASE" "$OUT" 2>&1 | grep -v -E "^\s+(Voluntary|Involuntary|Socket|Signals|Swaps|File system|Average|Page size|Exit status|Minor|Major|Percent|System time|User time)"
ls -la "$OUT"
python - <<PY
import json
e=json.load(open("$OUT/model.encodings"))
import onnx
m=onnx.load("$OUT/model_dynamic.onnx", load_external_data=False)
names={t.name for t in m.graph.initializer}|{o for n in m.graph.node for o in n.output}
pe=[p["name"] for p in e["param_encodings"]]; ae=[a["name"] for a in e["activation_encodings"]]
print("param encodings matched:", sum(n in names for n in pe), "/", len(pe))
print("activation encodings matched:", sum(n in names for n in ae), "/", len(ae))
PY
echo "=== done $(date)"
