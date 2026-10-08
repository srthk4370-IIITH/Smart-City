SHARD = "2/4"
BUDGET = 200
CALIB_SRC = '"""Activation-range calibration for the w4a16 NPU graph without AIMET\'s memory overhead.\n\nAIMET\'s Calibration step for this recipe is plain running min/max of every quantised activation tensor\nover the calibration data (quant_scheme min_max), turned into scale/offset by\naimet_onnx.common.quantsim.calculate_delta_offset. AIMET needs >30 GB to build its QuantSim for this 3B\ngraph (killed on Kaggle\'s 30 GiB box), so this script measures the same min/max directly:\n\n  * runs the EXACT exported graph (model_dynamic.onnx, the one compiled on AI Hub) in ONNX Runtime with\n    the fp32 weights read from model.data,\n  * adds ReduceMin/ReduceMax nodes on every tensor that has an activation encoding, so only scalars leave\n    the session (memory stays ~15-18 GB),\n  * feeds inputs exactly like on the device: 128-token prefill chunks, 4096 context, left-padded zero KV\n    cache, 4-D attention mask clipped to -50 and RoPE cos/sin from qai-hub-models\' LlamaPositionProcessor,\n  * uses OUR agent prompts + answers (train split) as calibration data.\n\nOutput: an encodings JSON = the published w4a16 encodings with every measured activation encoding\nrecomputed with AIMET\'s formula. Param (weight) encodings are taken from GPTQ later (merge_calibrated.py).\n\nUsage: python calib_ort.py --ckpt <dir with model_dynamic.onnx+model.data> --hf <merged hf dir>\n         --texts calib_texts.jsonl --encodings <published w4a16 model.encodings> --out out.encodings\n         [--budget-min 150] [--max-samples 200]\n"""\nimport argparse, json, math, os, time\nfrom pathlib import Path\n\nimport numpy as np\nimport onnx\nimport onnxruntime as ort\nimport torch\nfrom onnx import helper\nfrom transformers import AutoConfig, AutoTokenizer\n\nfrom qai_hub_models.models.templates.llama3.model import LlamaPositionProcessor\n\nSEQ, CTX = 128, 4096\nKEEP_PUBLISHED = {"attention_mask", "position_ids_cos", "position_ids_sin"}  # fixed, data-independent\n\n\ndef log(*a):\n    print(time.strftime("%H:%M:%S"), *a, flush=True)\n\n\ndef build_stat_graph(ck: Path, names: list[str]) -> Path:\n    m = onnx.load(str(ck / "model_dynamic.onnx"), load_external_data=False)\n    keep_outputs = [o for o in m.graph.output if o.name.startswith("past_")]\n    del m.graph.output[:]\n    m.graph.output.extend(keep_outputs)\n    for i, n in enumerate(names):\n        for op in ("ReduceMin", "ReduceMax"):\n            out = f"{n}::{op[-3:].lower()}"\n            m.graph.node.append(helper.make_node(op, [n], [out], keepdims=0, name=f"calib_{op}_{i}"))\n            m.graph.output.append(helper.make_empty_tensor_value_info(out))\n    path = ck / "_calib_stats.onnx"\n    onnx.save(m, str(path))  # initialisers keep their external refs into model.data\n    return path\n\n\ndef aimet_encoding(lo, hi, bw, sym):\n    """aimet_onnx.common.quantsim.calculate_delta_offset (+ gate_min_max), scalar case."""\n    lo, hi = min(float(lo), 0.0), max(float(hi), 0.0)\n    if hi - lo < 1e-5:\n        hi = lo + 1e-5\n    steps = 2 ** bw - 1\n    if sym and lo < 0:\n        pos = math.floor(steps / 2)\n        absmax = max(abs(lo), abs(hi))\n        return absmax / pos, int(-pos - 1)\n    delta = (hi - lo) / steps\n    return delta, int(round(lo / delta))\n\n\ndef main():\n    ap = argparse.ArgumentParser()\n    ap.add_argument("--ckpt", required=True)\n    ap.add_argument("--hf", required=True)\n    ap.add_argument("--texts", required=True)\n    ap.add_argument("--encodings", required=True)\n    ap.add_argument("--out", required=True)\n    ap.add_argument("--budget-min", type=float, default=150)\n    ap.add_argument("--max-samples", type=int, default=200)\n    ap.add_argument("--threads", type=int, default=os.cpu_count())\n    ap.add_argument("--shard", default="0/1", help="i/n: process texts[i::n] (parallel Kaggle sessions)")\n    ap.add_argument("--opt", choices=["basic", "all"], default="all")\n    a = ap.parse_args()\n    ck = Path(a.ckpt)\n    t_start = time.time()\n\n    pub = json.load(open(a.encodings))\n    acts = pub["activation_encodings"]\n    g = onnx.load(str(ck / "model_dynamic.onnx"), load_external_data=False)\n    produced = {o for nd in g.graph.node for o in nd.output} | {i.name for i in g.graph.input}\n    names = [e["name"] for e in acts if e["name"] in produced and e["name"] not in KEEP_PUBLISHED]\n    log(f"{len(acts)} activation encodings, measuring {len(names)}")\n    del g\n    stat_path = build_stat_graph(ck, names)\n\n    so = ort.SessionOptions()\n    so.intra_op_num_threads = a.threads\n    # ENABLE_ALL lets MLAS use its fast NCHWc kernels for the 1x1 Convs; tensors we measure keep a second\n    # consumer (the Reduce node) so fusions cannot remove them.\n    so.graph_optimization_level = (ort.GraphOptimizationLevel.ORT_ENABLE_ALL if a.opt == "all"\n                                   else ort.GraphOptimizationLevel.ORT_ENABLE_BASIC)\n    log("creating ORT session ...")\n    sess = ort.InferenceSession(str(stat_path), so, providers=["CPUExecutionProvider"])\n    log(f"session ready ({(time.time() - t_start) / 60:.1f} min)")\n    in_names = [i.name for i in sess.get_inputs()]\n    out_names = [o.name for o in sess.get_outputs()]\n    stat_out = [o for o in out_names if "::" in o]\n\n    cfg = AutoConfig.from_pretrained(a.hf)\n    tok = AutoTokenizer.from_pretrained(a.hf)\n    pos = LlamaPositionProcessor(context_length=CTX, config=cfg)\n    L = cfg.num_hidden_layers\n    kvh, hd = cfg.num_key_value_heads, cfg.hidden_size // cfg.num_attention_heads\n\n    lo = {n: math.inf for n in names}\n    hi = {n: -math.inf for n in names}\n    si_, sn_ = (int(x) for x in a.shard.split("/"))\n    texts = [json.loads(l)["text"] for l in open(a.texts, encoding="utf-8")][: a.max_samples][si_::sn_]\n    log(f"shard {a.shard}: {len(texts)} texts")\n    runs = toks = 0\n    for si, text in enumerate(texts):\n        ids = tok("<|begin_of_text|>" + text, add_special_tokens=False)["input_ids"][: CTX - SEQ]\n        kcache = [np.zeros((kvh, 1, hd, 0), np.float32) for _ in range(L)]\n        vcache = [np.zeros((kvh, 1, 0, hd), np.float32) for _ in range(L)]\n        for c0 in range(0, len(ids), SEQ):\n            chunk = ids[c0:c0 + SEQ]\n            n, cur = len(chunk), kcache[0].shape[-1]\n            pad = CTX - SEQ - cur\n            mask2d = torch.tensor([[0] * pad + [1] * cur + [0] * (SEQ - n) + [1] * n], dtype=torch.float32)\n            pids = (torch.cumsum(mask2d, dim=1, dtype=torch.int32) - 1).clip(0, CTX - 1)[:, -SEQ:]\n            m4, cos, sin = pos(mask2d, pids)\n            feed = {"input_ids": np.array([[0] * (SEQ - n) + chunk], np.int32),\n                    "attention_mask": m4.numpy().astype(np.float32),\n                    "position_ids_cos": cos.numpy().astype(np.float32),\n                    "position_ids_sin": sin.numpy().astype(np.float32)}\n            for l in range(L):\n                feed[f"past_key_{l}_in"] = np.concatenate([np.zeros((kvh, 1, hd, pad), np.float32), kcache[l]], axis=-1)\n                feed[f"past_value_{l}_in"] = np.concatenate([np.zeros((kvh, 1, pad, hd), np.float32), vcache[l]], axis=-2)\n            feed = {k: v for k, v in feed.items() if k in in_names}\n            res = dict(zip(out_names, sess.run(out_names, feed)))\n            for o in stat_out:\n                nm, kind = o.rsplit("::", 1)\n                v = float(res[o])\n                if kind == "min":\n                    lo[nm] = min(lo[nm], v)\n                else:\n                    hi[nm] = max(hi[nm], v)\n            for l in range(L):\n                kcache[l] = np.concatenate([kcache[l], res[f"past_key_{l}_out"][..., -n:]], axis=-1)\n                vcache[l] = np.concatenate([vcache[l], res[f"past_value_{l}_out"][..., -n:, :]], axis=-2)\n            runs += 1\n            toks += n\n        el = (time.time() - t_start) / 60\n        log(f"sample {si + 1}/{len(texts)}: {len(ids)} tok | total {toks} tok, {runs} runs, {el:.1f} min")\n        if el > a.budget_min:\n            log("time budget reached")\n            break\n        if (si + 1) % 3 == 0:\n            write(pub, acts, lo, hi, a.out, toks)  # checkpoint partial results\n\n    write(pub, acts, lo, hi, a.out, toks)\n    log(f"done: {toks} calibration tokens in {(time.time() - t_start) / 60:.1f} min -> {a.out}")\n\n\ndef write(pub, acts, lo, hi, out, toks):\n    # raw running min/max (merged across shards later: min of mins, max of maxes)\n    json.dump({"tokens": toks, "lo": {k: v for k, v in lo.items() if math.isfinite(v)},\n               "hi": {k: v for k, v in hi.items() if math.isfinite(v)}}, open(out + ".stats.json", "w"))\n    new, changed, ratios = [], 0, []\n    for e in acts:\n        e2 = dict(e)\n        n = e["name"]\n        if n in lo and math.isfinite(lo[n]) and math.isfinite(hi[n]) and e.get("dtype") == "INT":\n            s, off = aimet_encoding(lo[n], hi[n], e["bw"], e.get("is_sym", False))\n            old = e["scale"][0] if isinstance(e["scale"], list) else e["scale"]\n            if old:\n                ratios.append(s / old)\n            e2["scale"] = [s] if isinstance(e["scale"], list) else s\n            e2["offset"] = [off] if isinstance(e["offset"], list) else off\n            changed += 1\n        new.append(e2)\n    o = dict(pub)\n    o["activation_encodings"] = new\n    o["calibration"] = {"tokens": toks, "tensors_recomputed": changed, "method": "ORT min/max, AIMET delta/offset"}\n    json.dump(o, open(out, "w"))\n    r = np.array(ratios) if ratios else np.array([1.0])\n    log(f"  wrote {out}: {changed} encodings recomputed; new/published scale median {np.median(r):.3f} "\n        f"p5 {np.percentile(r, 5):.3f} p95 {np.percentile(r, 95):.3f}")\n\n\nif __name__ == "__main__":\n    main()\n'

"""Kaggle job: AIMET calibration-only (w4a16) of the GPTQ fine-tuned Llama 3.2 3B on OUR agent prompts.

Produces /kaggle/working/out/model.encodings whose ACTIVATION encodings are calibrated for the
fine-tuned model (the device bundle currently reuses the base model's). Weight encodings in the
result are ignored later - the exact GPTQ scales are kept locally.

Inputs (private dataset srthk4370/qidk-ft-gptq-calib):
  hf__*                 GPTQ fine-tuned HF checkpoint (flattened)
  model_dynamic.onnx    the exact graph we compile locally (so tensor names match)
  gateup_map.json, rebuild_model_data.py   rebuild the 14 GB fp32 model.data from the HF weights
  calib_texts.jsonl     240 train-split prompt+answer texts
  requirements.txt      exact pip freeze of the local qai-hub-models venv
"""
import glob, json, os, shutil, subprocess, sys, threading, time

T0 = time.time()
def log(*a):
    print(f"[{(time.time() - T0) / 60:6.1f} min]", *a, flush=True)

def sh(cmd, env=None):
    log("$", cmd)
    subprocess.run(cmd, shell=True, check=True, env=env)

def mem_watch():
    while True:
        try:
            m = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
            log(f"MEM avail {m['MemAvailable'] / 2**20:.1f} GiB of {m['MemTotal'] / 2**20:.1f}")
        except Exception:
            pass
        time.sleep(60)
threading.Thread(target=mem_watch, daemon=True).start()

IN = os.path.dirname(glob.glob("/kaggle/input/**/model_dynamic.onnx", recursive=True)[0])
log("input:", IN, os.listdir(IN))
W = "/root/work"
OUT = "/kaggle/working/out"
os.makedirs(f"{W}/merged", exist_ok=True)
os.makedirs(f"{W}/ck", exist_ok=True)
os.makedirs(OUT, exist_ok=True)
for f in glob.glob(f"{IN}/hf__*"):
    dst = f"{W}/merged/{os.path.basename(f)[4:]}"
    if not os.path.exists(dst):
        os.symlink(f, dst)

# 1. exact local toolchain in a Python 3.11 venv
sh("pip install -q uv")
sh("uv venv -q -p 3.11 /root/venv")
reqs = [l.strip() for l in open(f"{IN}/requirements.txt") if l.strip() and not l.startswith("#")]
open(f"{W}/req.txt", "w").write("\n".join(r for r in reqs if not r.lower().startswith(("nvidia-", "triton"))))
sh(f"uv pip install -q -p /root/venv/bin/python --index-strategy unsafe-best-match "
   f"--extra-index-url https://download.pytorch.org/whl/cpu -r {W}/req.txt")
PY = "/root/venv/bin/python"
sh(f"{PY} -c \"import importlib.metadata as m; print([(p, m.version(p)) for p in ('torch','transformers','aimet-onnx','qai_hub_models','onnx')])\"")

# 2. checkpoint dir: exact graph + rebuilt fp32 weights
shutil.copy(f"{IN}/model_dynamic.onnx", f"{W}/ck/model_dynamic.onnx")
if not os.path.exists(f"{W}/ck/model.data"):
    sh(f"{PY} {IN}/rebuild_model_data.py {W}/ck/model_dynamic.onnx {W}/merged {IN}/gateup_map.json {W}/ck/model.data")

# 3. lean ORT calibration (AIMET's QuantSim needs >30 GB for this graph; see calib_ort.py docstring)
open(f"{W}/calib_ort.py", "w").write(CALIB_SRC)
ENC = f"{W}/w4a16_published.encodings"
URL = "https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/llama_v3_2_3b_instruct/v7/w4a16/model.encodings"
sh(f"curl -sL -o {ENC} {URL} && ls -la {ENC}")
env = dict(os.environ, PYTHONUNBUFFERED="1", CUDA_VISIBLE_DEVICES="")
try:
    sh(f"{PY} {W}/calib_ort.py --ckpt {W}/ck --hf {W}/merged --texts {IN}/calib_texts.jsonl --encodings {ENC} "
       f"--out {OUT}/model.encodings --budget-min {BUDGET} --max-samples 240 --shard {SHARD} --opt all", env=env)
finally:
    log("out:", os.listdir(OUT))
log("DONE")
