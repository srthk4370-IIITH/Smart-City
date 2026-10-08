# Fine-tuned Llama 3.2 3B: export to a Genie bundle for SM8650 (8 Gen 3, HTP v75)

Researched 2026-10-06 against qai-hub-models **v0.63.0** (PyPI latest, 2026-09-23) and GitHub `qualcomm/ai-hub-models` main @ 8b4dfc7. The repo moved from `quic/` to `qualcomm/`, and the code now lives under `src/qai_hub_models/`. Source paths below are relative to that folder.

## TL;DR

* **Official path (needs local AIMET quantization):** `python -m qai_hub_models.models.llama_v3_2_3b_instruct.quantize --checkpoint <merged> -o <out>` and then `qai-hub-models export ... --checkpoint <out>`. The README marks quantization as "GPU required" and recommends "40 GB VRAM for 3B models". The default recipe is **SeqMSE (20 it) + Calibration (20 it)**, and SeqMSE hard-requires CUDA. `MIN_MEMORY_RECOMMENDED = 80` GB RAM+swap, but that limit is only a printed warning. **You can't do this on an RTX 4050 (6 GB) with 7–12 GB RAM.**
* **Recommended path (works on the laptop, no AIMET run):** use the code path that the published `DEFAULT_W4A16` export already uses. In v0.63 that path downloads **only `w4a16/model.encodings`** from the public asset store. It then exports `model_dynamic.onnx` and `model.data` **locally from FP torch weights** and ships both to AI Hub to compile. You run the same three library calls with your merged checkpoint as the FP model. That gives a checkpoint folder in the supported `AIMET_ONNX_EXPORT` format, and `qai-hub-models export --checkpoint <folder> --target-runtime genie` compiles it on AI Hub with **QAIRT 2.50** (the v0.63 default, which matches your device).
  * Trade-off: activation encodings and SeqMSE-tuned weight scales come from the **base** model. For a LoRA merge that only touches q/k/v/o/gate/up/down, this is usually fine. An optional script below widens any weight scale that would clip the new weights.
* **Fallback:** run the same thing on Kaggle (CPU or T4 session, about 30 GB RAM, fast uplink) to avoid laptop RAM and upload-bandwidth limits. For the best quality, run `quantize.py` there with a **Calibration-only recipe YAML** (no SeqMSE, so no CUDA needed).
* **LoRA adapters on Genie/QNN-HTP:** not available through AI Hub or qai-hub-models. Ruled out.

---

## 1. Facts verified in source

| Fact | Source | Confidence |
|---|---|---|
| Latest qai-hub-models is 0.63.0 (Python 3.10–3.13) | https://pypi.org/pypi/qai-hub-models/json | High |
| v0.63.0 default QAIRT is **2.50** (v0.62.2 used 2.45). It is auto-appended as `--qairt_version 2.50` to compile jobs unless you pass one | `common.py` L407 at tag v0.63.0; `utils/qai_hub_helpers.py` L527-530 | High |
| Install: `pip install qai-hub-models && qai-hub-models install llama_v3_2_3b_instruct`. The CLI auto-detects CUDA and installs the GPU AIMET wheel when present. Pins: torch 2.10.0, onnx 1.18.0, onnxruntime 1.22, aimet-onnx 2.28.0 (Linux), transformers (4.45.0 in the model reqs, 4.56.2 in the template reqs) | `models/llama_v3_2_3b_instruct/README.md`, `requirements.txt`, `models/templates/llama3/requirements.txt` | High |
| Quantize CLI: `--checkpoint` ("Input directory with custom weights"), `-o/--output-dir` (required), `--precision` (a name **or a recipe-YAML path**), `--context-length` (default 4096), `--calibration-sequence-length` (default 2048) | `models/templates/llm/quantize.py` `llm_quantize()` | High |
| Default w4a16 recipe = SeqMSE (Wikitext, 20 it) + Calibration (20 it). SeqMSE and AdaScale raise "requires a CUDA GPU" on CPU. Only `w4a16` has a recipe in the manifest, so `--precision w4` needs a YAML | `manifest.yaml` `lm_quantization_details`; `quantize.py` `quantize()` | High |
| `MIN_MEMORY_RECOMMENDED = 80` (GB RAM+swap). This is **only a printed warning** (`has_recommended_memory`) and links to increase_swap.md | `models/llama_v3_2_3b_instruct/model.py`; `utils/system_info.py` | High |
| Export accepts a local folder as `--checkpoint` if it holds `model*.onnx` + `model.encodings` (type `AIMET_ONNX_EXPORT`). Precision comes from `args.json` `{"precision": ...}`, otherwise defaults to w4a16. A plain HF folder (config.json + *.safetensors) is **not** accepted (INVALID) | `utils/checkpoint.py` `from_checkpoint()` and `precision()` | High |
| The export pipeline reads **`model_dynamic.onnx` + `model.data` + `model.encodings`** from the checkpoint. Without `model_dynamic.onnx` it falls back to a torch export, so your legacy v4 cache (`model_seqlen*_cl4096.onnx`) does **not** plug into v0.63 | `models/templates/llm/model.py` `get_full_onnx_bundle()` L741-776 | High |
| The published DEFAULT_W4A16 flow fetches only `w4a16/model.encodings` (asset v7), creates the FP model, and calls `create_onnx_models()` + `save_tokenizer_and_config()` on a checkpoint dir ("This may take around 30 minutes") | `models/templates/llama3/model.py` `LlamaDynamicQuantizablePreSplitMixin.resolve_default_checkpoint()` L533-605 | High |
| `https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/llama_v3_2_3b_instruct/v7/w4a16/model.encodings` is public (40.7 MB). `v7/w4/model.encodings` is also public | HTTP HEAD 200 | High |
| v7 encodings use AIMET format 1.0.0 (lists; `PER_CHANNEL`, `is_sym`, `scale[]`, `offset[]`). Names come from torch.export (`conv2d_1176`, `add_3408`, `model.model.layers.N.self_attn.q_proj_sha.H.weight`, ...). Embedding and RMSNorm weights carry 16-bit encodings in `activation_encodings`. The scales are numerically **identical** to your v4 cache (for example `lm_head` ch0 scale 0.0006574495570866142), so it is the same calibration renamed | downloaded file vs `~/.qaihm/.../v4/.../model.encodings` | High |
| Export CLI flags (built from the signatures): `--checkpoint`, `--device`/`--chipset`, `--target-runtime` (default **geniex_qairt**; `genie` is accepted but prints a deprecation warning), `--skip-profiling`, `--skip-downloading`, `--output-dir`, `--compile-options`, `--zip-assets`, `--components`. Default graphs are seq [128, 1] × ctx [4096] → `prompt_ar128_cl4096_{i}_of_3`, `token_ar1_cl4096_{i}_of_3` (same names as your on-device bundle) | `models/llama_v3_2_3b_instruct/export.py`; `utils/export/multi_graph_collection_pipeline.py`; `utils/args.py` L248-272; `llm/model.py` `get_qnn_context_graph_name()` | High |
| The bundle writer produces `genie_config.json` + `htp_backend_ext_config.json` + `tokenizer.json` + `sample_prompt.txt` + the .bin files. It takes tokenizer and config **from the checkpoint dir** when present | `llm/model.py` `DynamicSplitCollectionBase.write_supplementary_files()` | High |
| 8 Gen 3 is **no longer listed** in `supported_chipsets` and has no release assets in v0.63, but nothing in the export enforces that list. `Samsung Galaxy S24` → `qualcomm-snapdragon-8gen3` is still in `devices_and_chipsets.yaml` | `perf.yaml`, `release-assets.yaml`, `devices_and_chipsets.yaml` | High (no enforcement found); Medium that a v75 compile succeeds |
| ai-hub-apps tutorial: "The export command may take 2–3 hours and requires significant memory (RAM + swap)". Host memory guidance: "12GB memory or more for 3B+ models" | https://github.com/qualcomm/ai-hub-apps/blob/main/tutorials/llm_on_genie/export.md and README.md | High (quoted) |
| AI Hub `--qairt_version` accepts `major.minor`, `default` or `latest`. Supported versions are listed by `get_frameworks()` / `qai-hub list-frameworks` | https://workbench.aihub.qualcomm.com/docs/hub/api.html | High |

Observed on this machine (read-only): WSL `free -g` reports **7 GB RAM + 48 GB swap**, not 12 + 32. Check `.wslconfig`. About 920 GB is free on the WSL ext4 disk. **No venv currently has qai-hub-models, torch or onnx installed** (`~/venvs/train` is empty of them), so expect a 20–30 min install. Your v4 cache's `model.data` is dated 30 min after its `model.encodings`, so you already ran this local FP-to-ONNX export successfully on this machine.

---

## 2. Recommended path: base encodings + fine-tuned weights, compiled on AI Hub

Expected total time is **about 3.5–5 h**. The big unknown is your **upload bandwidth**: export uploads about 14.4 GB of fp32 ONNX. At 50 Mbit/s that takes about 40 min; at 10 Mbit/s it takes about 3+ h. **Measure your upload speed before Wednesday.** If it is under 25 Mbit/s, use the Kaggle variant in §3A.

### Step 0: environment (about 25 min, WSL, keep everything on ext4, not /mnt/c)
```bash
python3.11 -m venv ~/venvs/qaihm && source ~/venvs/qaihm/bin/activate
pip install -U pip "qai-hub-models==0.63.0"
qai-hub-models install llama_v3_2_3b_instruct      # pulls the pinned torch/onnx/transformers/aimet-onnx
python -c "import qai_hub_models,torch,transformers,onnx;print(qai_hub_models.__version__,torch.__version__,transformers.__version__)"
qai-hub list-frameworks | grep -i qairt             # confirm 2.50 is still offered
```
Make sure swap is at least 40 GB (`free -g`). The 80 GB warning can be ignored.

### Step 1: sanity-check the merged checkpoint (5 min)
Your `training/merge_adapter.py` writes to `<run>/merged`. Check these four things:
- `config.json` still has `"tie_word_embeddings": true`, 28 layers, hidden 3072, 24/8 heads. `_verify_ckpt` rejects anything else.
- There is **no** separate trained `lm_head.weight`. If LoRA targeted `lm_head` or `embed_tokens`, the base encodings for those are wrong, and with tied weights HF silently re-ties and drops the change.
- `tokenizer.json` and `tokenizer_config.json` (with `chat_template`) are present.
- Check what the adapter touched: `python -c "import json;print(json.load(open('<run>/adapter/adapter_config.json'))['target_modules'])"`. The path is safest when only `q,k,v,o,gate,up,down` were trained.

### Step 2: build the AIMET-style checkpoint folder (30–60 min, CPU, swap-heavy)
Save as `build_ft_ckpt.py`. It uses only APIs from `templates/llama3/model.py` and `templates/llm/model.py` in v0.63.0.
```python
import json, shutil, sys, torch
from pathlib import Path
from qai_hub_models.models.llama_v3_2_3b_instruct.model import (
    Llama3_2_3B_PreSplit as FP, Llama3_2_3B_QuantizablePreSplit as Q)
from qai_hub_models.utils.asset_loaders import CachedWebModelAsset

merged, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
cpu = torch.device("cpu")
# 1) the published w4a16 encodings (asset v7) -- same file DEFAULT_W4A16 uses
enc = CachedWebModelAsset.from_asset_store(Q.model_id, Q.model_asset_version, "w4a16/model.encodings").fetch()
shutil.copy(enc, out / "model.encodings")
# 2) FP model from YOUR merged weights (loads as fp32, ~13 GB)
fp = FP.from_pretrained(checkpoint=str(merged), host_device=cpu)
# 3) torch.export -> out/model_dynamic.onnx + out/model.data (~14.4 GB)
Q.create_onnx_models(checkpoint=str(out), fp_model=fp, context_length=fp.context_length,
                     host_device=cpu, llm_io_type=fp.llm_io_type)
Q.save_tokenizer_and_config(checkpoint=str(out), fp_model=fp)
json.dump({"precision": "w4a16"}, open(out / "args.json", "w"))
print("done:", sorted(p.name for p in out.iterdir()))
```
```bash
python build_ft_ckpt.py ~/runs/<run>/merged ~/ft_ckpt_w4a16
# expect: args.json config.json model.data model.encodings model_dynamic.onnx tokenizer*.json ...
```
**Why the names match:** the published encodings were produced against exactly this torch.export graph. Use the pinned torch and transformers from Step 0, because a different version can rename nodes such as `conv2d_1176`. This is also why the old v4 cache can't be reused with v0.63.

### Step 2b (optional, recommended): widen weight scales that would clip (about 10 min)
The base per-channel 4-bit and 8-bit scales were SeqMSE-tuned on base weights. LoRA can push some channels past them. This script keeps each old scale unless the new weights need a larger one. That choice is mine, not a Qualcomm tool. Confidence is Medium that AI Hub's converter honours the provided param encodings, and High that the script is harmless.
```python
# refresh_param_scales.py <ckpt_dir>
import json, sys, numpy as np, onnx
from pathlib import Path
ck = Path(sys.argv[1]); m = onnx.load(str(ck/"model_dynamic.onnx"), load_external_data=False)
consumer = {i: n.op_type for n in m.graph.node for i in n.input}
inits = {t.name: t for t in m.graph.initializer if t.data_location == onnx.TensorProto.EXTERNAL}
enc = json.load(open(ck/"model.encodings")); widened = skipped = 0
for p in enc["param_encodings"]:
    t = inits.get(p["name"])
    if p.get("enc_type") != "PER_CHANNEL" or t is None or t.data_type != onnx.TensorProto.FLOAT:
        skipped += 1; continue
    info = {e.key: e.value for e in t.external_data}; dims = tuple(t.dims)
    w = np.memmap(ck/info["location"], np.float32, "r", int(info.get("offset", 0)), (int(info["length"])//4,)).reshape(dims)
    ax = len(dims)-1 if consumer.get(p["name"]) in ("MatMul", "Gemm") else 0
    if dims[ax] != len(p["scale"]): skipped += 1; continue
    red = tuple(i for i in range(len(dims)) if i != ax); q = 2**(p["bw"]-1)
    need = np.maximum(w.max(axis=red)/(q-1), -w.min(axis=red)/q)
    old = np.asarray(p["scale"]); new = np.maximum(old, need)
    widened += int((new > old*1.0001).sum()); p["scale"] = new.tolist()
json.dump(enc, open(ck/"model.encodings", "w"))
print("channels widened:", widened, "| entries skipped:", skipped)
```
A large "widened" count (thousands) means the fine-tune drifted far, and the §3B quantize route is worth the extra effort.

### Step 3: compile on AI Hub and download the Genie bundle (about 2–3 h; most of it is upload plus cloud compile)
```bash
qai-hub-models export llama_v3_2_3b_instruct \
  --checkpoint ~/ft_ckpt_w4a16 \
  --device "Samsung Galaxy S24 (Family)" \
  --target-runtime genie \
  --skip-profiling \
  --output-dir ~/genie_ft
# (equivalently --chipset qualcomm-snapdragon-8gen3; check the exact device string with `qai-hub list-devices | grep -i s24`)
```
What happens: the checkpoint is split into 3 parts locally (about 30 GB of temporary disk), each part is uploaded once (dynamic shapes), and AI Hub runs 6 compile jobs (ar128 and ar1 for each part) plus 3 link jobs with weight sharing. The bundle is then downloaded and written.

Expected output in `~/genie_ft/llama_v3_2_3b_instruct-genie-w4a16-qualcomm_snapdragon_8gen3/`: three `*_part_{1,2,3}_of_3.bin` files, plus `genie_config.json`, `htp_backend_ext_config.json`, `tokenizer.json`, `sample_prompt.txt` and `tool-versions.yaml`. Check that `tool-versions.yaml` says qairt 2.50.x.

QAIRT pinning: v0.63.0 adds `--qairt_version 2.50` automatically. If AI Hub has retired 2.50, the export stops with a clear message. In that case pass `--compile-options "--qairt_version 2.50"` if 2.50 is still listed, or upgrade the device runtime. Don't use `latest` unless the device libs are updated to match.

**Deploy:** push the 3 .bin files to the device. The graph names match your existing official bundle, so you can keep the device's current `genie_config.json` and `htp_backend_ext_config.json` if the new .bin filenames are the same or you edit `ctx-bins`. Diff the two `genie_config.json` files first.

Confidence for the whole of §2: **Medium-High.** Every call is the library's own DEFAULT path with a different FP model. The open risks are (a) S24/v75 is no longer in Qualcomm's CI matrix, though you already run a v75 bundle of this model, and (b) quality drift from reusing base activation ranges. Test with 10–20 of your agent prompts on device before relying on it.

---

## 3. Fallback paths

### 3A. The same recipe on Kaggle (about the same time; avoids the slow uplink and 7 GB RAM)
Kaggle CPU or GPU sessions have about 30 GB RAM and a fast network. Export needs no GPU. Steps:
1. Upload the merged checkpoint as a private Kaggle Dataset (6.4 GB bf16).
2. Store the AI Hub token as a Kaggle Secret, then run `qai-hub configure --api_token $TOKEN`.
3. Run Steps 0, 2, 2b and 3 in the notebook. Put the checkpoint and temporary files under `/tmp` or `/kaggle/temp`, because `/kaggle/working` is capped at about 20 GB. Run `df -h` first, since you need about 50 GB in total. The disk figures are low confidence.
4. Download only the zipped bundle (`--zip-assets`, about 2 GB).

Session limit is 12 h. Confidence: Medium.

### 3B. True re-quantization for your weights on Kaggle (better quality, more risk)
SeqMSE needs CUDA and Qualcomm recommends 40 GB VRAM, so a T4 (16 GB) will probably run out of memory. Instead, drop SeqMSE with a recipe file that `--precision` accepts as a path (`resolve_quantize_recipe()`). That recomputes param **and** activation encodings for the fine-tuned model and runs on CPU or GPU:
```yaml
# calib_only_w4a16.yaml
precision:
  activations: int16
  blocks: {granularity: PCQ, qtype: int4}
  embedding: int16
  kv_cache: int8
  lm_head: {granularity: PCQ, qtype: int8}
recipe:
- name: Calibration
  dataset: {name: Wikitext, split: train}
  num_iterations: 20
```
```bash
python -m qai_hub_models.models.llama_v3_2_3b_instruct.quantize \
  --checkpoint /kaggle/input/<merged> --precision calib_only_w4a16.yaml \
  --calibration-sequence-length 512 -o /tmp/ft_quant      # 512 lowers memory use; the default is 2048
cp /kaggle/input/<merged>/config.json /tmp/ft_quant/       # the script's own advice
qai-hub-models export llama_v3_2_3b_instruct --checkpoint /tmp/ft_quant --device "Samsung Galaxy S24 (Family)" --target-runtime genie --skip-profiling --output-dir /tmp/genie_ft --zip-assets
```
Risks: AIMET QuantSim of a 3B fp32 graph in about 30 GB of RAM is tight (Qualcomm says 80 GB). On CPU, calibration could take several hours. Plain min-max weights without SeqMSE score somewhat worse than the official numbers. Confidence: **Low-Medium**, so only try this if §2 output quality is bad. Colab free (12.7 GB RAM) is not viable.

### 3C. w4 precision (fp16 activations)
`v7/w4/model.encodings` is public and only needs weight encodings, so it is insensitive to activation drift. Use the same script with `"w4/model.encodings"` and `args.json` `{"precision":"w4"}`. HTP v75 supports fp16, but w4 is slower on device and Qualcomm never shipped w4 for 8 Gen 3. Confidence: Low-Medium.

### 3D. LoRA adapters (keep base .bins and apply the adapter)
Genie does have LoRA plumbing (`genie-t2t-run -l/--lora ADAPTER,ALPHA,...`; QAIRT release notes mention `GenieDialog_applyLora`). However, the base context binaries must be **built LoRA-enabled**, and the adapter binaries must come from the **local QAIRT SDK + AIMET LoRA flow**. Neither AI Hub Workbench nor qai-hub-models exposes this; I found no LoRA option anywhere in the v0.63 llm/llama3 templates. The official bundle on your device is not LoRA-enabled, so this is **not feasible** under your constraints. Sources: https://docs.qualcomm.com/bundle/publicresource/80-63442-100/topics/genie-t2t-run.md and https://docs.qualcomm.com/bundle/publicresource/80-63442-100/topics/revision_history.md. Confidence: Medium.

---

## 4. Pitfalls

1. **Default runtime is `geniex_qairt`.** Pass `--target-runtime genie` to get a `genie_config.json` bundle for genie-t2t-run. You will see a deprecation warning, which is expected.
2. **Version pinning matters twice.** Pinned torch and transformers keep torch.export node names in line with the published encodings. qai-hub-models 0.63.0 gives QAIRT 2.50 for the device. Don't upgrade either mid-flow.
3. **tie_word_embeddings:** Llama 3.2 3B ties `lm_head` to `embed_tokens`. Don't fine-tune either of them for this path. Keep `tie_word_embeddings: true`.
4. **Chat template:** genie-t2t-run sends the raw prompt string, so your app must wrap prompts in the Llama-3 header format used in training (`<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n...<|eot_id|>...assistant<|end_header_id|>\n\n`). The bundle's `tokenizer.json` comes from the checkpoint dir (your merged tokenizer). EOS ids are [128001, 128008, 128009].
5. **Context and sequence length:** keep the defaults (AR128 + AR1, CL4096) so the graph names and KV sizes match your working config. Lower `--context-lengths` only if you hit device memory errors.
6. **Disk:** about 6.4 GB merged + 14.4 GB checkpoint + about 30 GB of export temp, so keep 60 GB free on the WSL ext4 filesystem. Never work under `/mnt/c`, because it is very slow.
7. **RAM:** WSL currently shows 7 GB, not 12. The FP load (fp32, about 13 GB) plus the torch.export step will lean on swap for 30–60 min. Close other apps and don't run training at the same time.
8. **Custom checkpoint + caching:** the legacy `export.py` requires `--model-cache-mode disable` for custom checkpoints. The v0.63 multi-graph pipeline has no such flag, so add it only if the CLI asks for it.
9. **HF gating:** some code paths fall back to `meta-llama/Llama-3.2-3B-Instruct` for config or tokenizer when the checkpoint folder lacks them. The Step 2 script saves both. Keep `HF_TOKEN` set anyway, since you already have access.
10. **AI Hub free tier:** compile and link jobs are free. Use `--skip-profiling` to save device time and about 30 min. If a job fails, the CLI prints the job URL. Check the job log on workbench.aihub.qualcomm.com.

## 5. Wednesday timeline (laptop, §2)
| Step | Wall time |
|---|---|
| Env install + checks | 0:25 |
| Merge (if not done) + sanity checks | 0:15 |
| build_ft_ckpt.py (FP load + torch.export) | 0:30–1:00 |
| refresh_param_scales.py | 0:10 |
| export: split + upload 14 GB | 0:40 at 50 Mbit/s (over 3 h at 10 Mbit/s, so use §3A) |
| AI Hub compile ×6 + link ×3 (parallel) | about 1:00–1:30 (Qualcomm says 2–3 h for the whole export) |
| Download bundle + push + smoke test | 0:20 |
| **Total** | **about 3.5–5 h** |
