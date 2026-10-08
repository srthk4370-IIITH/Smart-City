# Closing the w4a16 quantisation gap on a QLoRA-merged Llama 3.2 3B (Snapdragon 8 Gen 3)

Research report. Date: 2026-10-07. Target: `qai-hub-models==0.63.0`, QAIRT/Genie 2.50, SM8650 / HTP v75.

All statements marked with a confidence level. Source links inline. Facts marked **[local]** were
verified by reading the installed package at
`~/venvs/qaihm/lib/python3.11/site-packages/qai_hub_models/` (read-only); facts marked **[web]** come
from Qualcomm docs / GitHub / papers.

---

## 0. Executive summary

Three findings change the plan:

1. **The "base model is unaffected" control is worthless.** The base model scores ~20% on a 12-class
   task both on host and on device. That is at/near chance. A model at chance cannot degrade. It
   therefore gives *zero* evidence that the reused activation encodings are sound. **Confidence: very
   high** (logic, not citation).

2. **`Precision.w4` in `qai-hub-models` uses fp16 activations — i.e. no activation encodings at
   all.** **[local]** `LLM_AIMETOnnx._apply_precision_activations()` sets *every* activation
   quantizer to `float16` when `precision == Precision.w4`
   (`models/templates/llm/model.py:2997-3010`, called from `_configure_quant_sim` at line 3037-3039).
   `w4` is a *supported, published* precision for this model (`SUPPORTED_PRECISIONS = [w4a16, w4]`,
   `DEFAULT_CHECKPOINT[Precision.w4] = "w4"` in
   `models/llama_v3_2_3b_instruct/model.py:57-61`), Genie-compatible, and on Qualcomm's own Grace2
   benchmark it costs almost nothing versus w4a16 (**[local]** `numerics.yaml`: Snapdragon X Elite,
   genie runtime — `w4a16: 79.6`, `w4: 78.3`; torch reference 84.2).
   **This lets you delete the entire stale-activation-encoding variable with one export round trip
   and no calibration data, no CUDA and no 40 GB machine.** This is the single highest
   value/time option.

3. **The official AIMET re-quantisation path needs 40 GB VRAM / ~80 GB RAM on the default recipe,
   but the default recipe's expensive half (SeqMSE) is skippable, and a Calibration-only recipe runs
   on CPU.** **[local]** `models/templates/llm/quantize.py:250-256` raises
   *"This quantization technique requires a CUDA GPU (V100/A100)"* **only** if the recipe contains
   `SeqMSE` or `AdaScale`. A `Calibration`-only recipe has no CUDA guard. **[web]** the 40/80 GB
   figure is from the model README and the tutorial.

Recommended plan is in §8.

---

## 1. Root cause

### 1.1 What the evidence actually supports

| Hypothesis | Verdict |
|---|---|
| Stale **activation** encodings (int16/int8 ranges computed on the base model) clip or saturate on the fine-tuned model | **Most likely primary cause. ~60%** |
| **Weight** 4-bit error (per-channel int4) drowning a small LoRA delta | **Strong secondary / possibly co-primary. ~30%** |
| LoRA merging being intrinsically PTQ-hostile | **Unlikely as the dominant cause. ~10%** |

### 1.2 Why activation ranges are the prime suspect

**Qualcomm "a16" is INT16 with a static per-tensor calibration-derived scale, not IEEE fp16.** An
int16 tensor whose per-tensor max is *too small* does not degrade gracefully — it **saturates**. This
is categorically different from fp16, whose ±65504 range makes activation range a non-issue. Every
"16-bit activations are near-lossless" result in the literature assumes the scale was calibrated *on
that model*. Confidence: high.

Published cost of *correct* w4a16 on exactly your model: ≈ **+1% perplexity** on Llama-3.2-3B
("Is Your NPU Ready for LLMs?", https://arxiv.org/abs/2607.05475 — *flagged: verify this arXiv id, it
came from an automated search*). Corroborating: Atom (https://arxiv.org/abs/2310.19102) and COMET
(https://arxiv.org/abs/2410.12168) both report that with 16-bit activations LLaMA models are
"nearly identical" to FP16, while 8-bit activations degrade significantly. GPTQ Llama-2-7B
WikiText-2 goes 5.47 → 5.87 for int4-g128 weight-only. So the whole *weight-side* budget at correct
calibration is ~1-6%. You are seeing ~50 points. Confidence: high.

**The most on-point paper for your exact failure mode** is **Quaff** (https://arxiv.org/abs/2505.14742),
whose *Outlier Spatial Stability Hypothesis* states that during fine-tuning outlier channel
**positions stay stable but their magnitudes change significantly**, and that *"static scaling
predefined on calibration data can amplify quantization errors as distributions evolve."* That is
precisely "base-model encodings + fine-tuned weights". Confidence: high.

Supporting background on why a handful of activations dominate the range:
- **Massive Activations in LLMs**, Sun et al., ICLR'24 — https://arxiv.org/abs/2402.17762. A handful
  of activations are ~10^5× the median, at *fixed* dimensions and at *specific tokens* (BOS /
  delimiter / attention-sink tokens), nearly input-invariant, acting as implicit bias.
- **LLM.int8()** — https://arxiv.org/abs/2208.07339 (emergent outlier features).
- **CushionCache / Prefixing Attention Sinks** — https://arxiv.org/abs/2406.12016: changing the
  *prefix* changes the outlier structure. **Your agent prompt is a ~650-token fixed system prompt
  totally unlike wikitext** — the sink/prefix structure the base encodings were calibrated on is not
  the structure your deployment sees. This is a second, independent reason the base encodings are
  wrong for you, *even before* the fine-tune.
- Counterpoint: https://arxiv.org/abs/2405.20835 finds modern Llamas fairly robust to *calibration
  corpus choice*. But that paper swaps corpora for the **same** model; it does not study reusing
  **another model's** encodings. Do not let it talk you out of recalibrating. Confidence: high.

### 1.3 Which tensors are 8-bit, exactly

**[local]** For `Precision.w4a16`, `_configure_quant_sim` calls
`_apply_int8_kv_cache_tying_and_lm_head(sim, kv_io_map, use_16x8_matmuls=True)`
(`models/templates/llm/model.py:3032-3036`). Reading
`models/templates/llm/_utils.py:397-422`, that function:

1. ties Concat (or ScatterElements, native-KV) quantizers and rebuilds the session;
2. `_set_tensors_to_output_8b_sym(sim, kv_io_list)` — **every KV-cache input and output tensor
   becomes int8 symmetric** (28 layers × {key,value} × {in,out} = 112 tensors);
3. `_set_lm_head_to_8b(sim)` — lm_head weights to int8;
4. `_tie_quantizers_for_kv_cache(...)` — write path tied to read path;
5. `_set_matmul_second_input_to_8b(sim)` — **the second input of every MatMul is forced to int8**, and
   `_propagate_8b_upstream()` pushes that 8-bit requirement upstream through intervening ops
   (`_utils.py:~370-395`).

So your ~1456 8-bit activation tensors are, in order of risk:

| Tensor class | Count (approx) | Risk from stale encodings |
|---|---|---|
| **KV-cache K/V read+write tensors** | 112 | **Highest.** K carries the attention-sink / massive-activation outliers; the magnitude of those moves under fine-tuning (Quaff). An int8 symmetric per-tensor scale that is too small clips the sink and destroys attention routing. |
| **MatMul 2nd input + upstream-propagated tensors** | ~1200+ | High for the QKᵀ path (K is the 2nd input → inherits K's outliers). |
| **Softmax output / attention probs** (PV MatMul 2nd input) | ~28×n | **Lowest.** Bounded in [0,1]; the range is structural, not calibration-dependent. Mostly safe. |
| lm_head weights (int8 param) | 1 | Low; param encoding, you can recompute it. |

**Conclusion: it is almost certainly the KV / K-path int8 tensors, not softmax.** Confidence: medium-high.

### 1.4 Weight scales vs activation ranges — and the quantitative weight argument

Your own measurements (`refresh_param_scales.py` docstring) give relative RMS weight quantisation
error on the merged weights:

```
published base scales      0.1331  (worst 0.2368)
max(published, min-max)    0.1732  (worst 0.2718)   <- what the shipped export used
exact min-max              0.1731  (worst 0.2718)
tighter of both            0.1330  (worst 0.2355)
MSE-optimal clipping       0.1201  (worst 0.1715)
```

Two observations, both important:

- **You shipped the worst of the five options (0.173).** Min-max is dragged out by LoRA-induced
  outlier channels, coarsening every other weight in the channel. Switching to MSE-optimal clipping
  is a **31% reduction in weight error** for essentially zero cost (you already wrote the script).
- **13-17% relative RMS weight error is 2-3× what your host baseline has.** bitsandbytes NF4 uses
  **block size 64** with a non-uniform, Gaussian-matched codebook; Qualcomm w4 is **per-output-channel
  (PCQ)** symmetric uniform — one scale per 3072-element row. That is ~48× coarser grouping. Expect
  NF4 rel-RMS ≈ 0.05, device PCQ-int4 ≈ 0.12-0.17. **So the host 94% number was obtained under a
  materially finer 4-bit scheme than the device uses.** Comparing "host 4-bit 94%" to "device 4-bit
  45%" and concluding "4-bit is fine" is not valid. Confidence: high.

**The decisive quantitative argument you should run yourselves (§1.6):** a merged LoRA delta at
r=16, α=32 typically has ‖ΔW‖_F / ‖W‖_F of **0.5-3%** after a short fine-tune. If your per-channel
int4 weight noise is 12-17% of ‖W‖, the quantisation noise is **4-30× larger than the entire
fine-tuning signal**. The base model's generic behaviour is high-margin and survives; your fine-tune's
narrow, low-entropy JSON behaviour is a low-margin signal and does not. NF4-bs64 at ~5% error leaves
a much better signal-to-noise ratio — which is exactly the 94% vs 45% split you observe.
Confidence: medium-high. **Measure ‖ΔW‖/‖W‖ — it takes 10 minutes and it settles the weighting between
hypotheses A and B.**

### 1.5 Is LoRA-merging intrinsically PTQ-fragile? (literature)

There *is* a documented effect, but it is weight-side and far smaller than 49 points.

- *Don't Merge Your LoRA Adapter Into a 4-bit LLM* — https://kaitchup.substack.com/p/dont-merge-your-lora-adapter-into
  and https://kaitchup.substack.com/p/training-loading-and-merging-qdora. Two mechanisms: the adapter
  was trained against NF4 weights but merged into bf16; and the merged delta gets "virtually
  quantised". Prescribed safe recipe: quantise base → dequantise → merge → requantise. **NF4-specific;
  your host 94% already clears it.**
- The adapter delta injects **new outlier channels** that naive min-max crushes. This is real — you
  measured it (min-max 0.173 > published 0.133). Mitigated by per-channel scales + MSE clipping.
- The whole QA-LoRA / LoftQ / L4Q / ApiQ / RoLoRA research line exists *because* high-precision LoRA
  params and low-precision quantised weights "cannot be merged into low-precision values" losslessly
  (L4Q): https://arxiv.org/abs/2309.14717, https://arxiv.org/abs/2310.08659,
  https://arxiv.org/abs/2402.04902, https://arxiv.org/abs/2402.05147, https://arxiv.org/abs/2407.08044.
- PEFT refuses `merge_and_unload()` on AWQ/GPTQ bases (https://github.com/huggingface/peft/pull/1532);
  the *recommended* workaround is exactly your pipeline (train on NF4 → merge into bf16 → requantise),
  which is itself evidence that merge-then-quantise is normally fine.

**No paper or issue reports a merged LoRA being catastrophically more PTQ-fragile than its base under
weight-only per-channel int4.** Confidence that merging per se is your primary cause: **low (~10-15%)**.

### 1.6 The three diagnostics to run first (cheap, decisive)

**D1 — Host fake-quant replay (best single experiment, ~1 h, fits on the 4050 or Kaggle T4).**
Simulate the *device's* weight scheme on the host and re-run your eval:
per-output-channel symmetric int4 fake-quant of every q,k,v,o,gate,up,down weight, using **the exact
scales from `model.encodings`**, with bf16/fp16 activations and no activation quantisation.
- If accuracy stays ~85-94% → weights are fine, **activation encodings are the cause**.
- If accuracy falls to ~45-60% → **weight quantisation alone explains it**; activations are secondary.
This separates hypothesis A from B with **zero AI Hub round trips**. Do this before anything else.
Also sweep: published scales vs widened vs MSE-optimal, to confirm the scale-choice win offline.

**D2 — ‖ΔW‖/‖W‖ per module** (10 min). Load base + merged safetensors, print
`‖W_merged − W_base‖_F / ‖W_base‖_F` per layer/module. Compare against 0.12-0.17.

**D3 — Activation range audit** (~2 h). Hook the merged bf16 model on *your real prompts*, record
per-tensor min/max for every tensor that appears in `model.encodings`' `activation_encodings`, and
rank by `merged_max / published_max`. Anything > 1.0 is being clipped on device. Expect a short list
concentrated in later-layer K / residual tensors. You already have `pyhooks/` and `compare_scales.py`
infrastructure for this.

---

## 2. Official fix: AIMET quantisation of a custom checkpoint

### 2.1 Exact CLI (verified by running `--help`) **[local]**

```
python -m qai_hub_models.models.llama_v3_2_3b_instruct.quantize \
    --checkpoint <merged_hf_dir_or_DEFAULT> \
    --output-dir <out> \
    [--precision <name|path/to/recipe.yaml>] \
    [--context-length 4096] \
    [--calibration-sequence-length 2048]
```

That is the **complete** option set in 0.63.0. There is **no** `--use-seq-mse` flag any more (the
tutorial at https://github.com/qualcomm/ai-hub-models/blob/main/tutorials/llm/quantize_llama3.md is
out of date relative to the installed version); SeqMSE is now a *recipe step*. There is no
`--num-splits`, no `--calibration-dataset`, no `--device`. Defaults **[local]**
(`models/templates/llm/model.py:167-173`): `DEFAULT_SEQUENCE_LENGTH = 128`,
`DEFAULT_CONTEXT_LENGTH = 4096`, `DEFAULT_CALIBRATION_SEQ_LEN = 2048`.

`--precision` accepts either a precision **name** present in the model's manifest
`lm_quantization_details`, or a **path to a recipe YAML**. **[local]**
`quantize.py:resolve_quantize_recipe()`.

### 2.2 What the default w4a16 recipe actually does **[local]**

From `models/llama_v3_2_3b_instruct/manifest.yaml`:

```yaml
lm_quantization_details:
  w4a16:
    precision:
      activations: int16
      blocks:   {granularity: PCQ, qtype: int4}
      embedding: int16
      kv_cache: int8
      lm_head:  {granularity: PCQ, qtype: int8}
    recipe:
    - {name: SeqMSE,      num_iterations: 20, dataset: {name: Wikitext, split: train}}
    - {name: Calibration, num_iterations: 20, dataset: {name: Wikitext, split: train}}
```

So: **SeqMSE with 20 calibration blocks, then QuantSim `compute_encodings` with 20 blocks of
WikiText-2-raw train. No AdaRound. No AdaScale. No SpinQuant for this model.**
`num_iterations` is the *number of context-length blocks prefetched*, not optimiser steps
(`utils/quantization_aimet_onnx.py:449-510`). With `num_iterations: 0` or unset, the default pool is
`ceil(80000 / context_length)` ≈ 20 blocks at cl=4096 (`models/templates/llm/model.py:4018+`).

Phase order in `quantize()` **[local]** (`models/templates/llm/quantize.py:200-330`):
1. load FP model on CPU;
2. **skip export if `_has_onnx_on_disk()` is already true in `-o` or in `--checkpoint`** (see §4.3 —
   this is your shortcut);
3. export ONNX (`model_dynamic.onnx` + `model.data`);
4. `apply_pre_sim_transforms()` (SpinQuant) — no-op for this recipe;
5. build QuantSim on `cuda` if available else `cpu`;
6. `quantize_from_steps(on_sim_steps)`;
7. `save_calibrated_checkpoint()` → `model.onnx` + `model.data` + `model.encodings` + config + `args.json`.

### 2.3 What needs CUDA — and what doesn't **[local], high confidence**

`models/templates/llm/quantize.py:250-256`:

```python
device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
if device.type != "cuda" and (use_seq_mse or use_ada_scale):
    raise ValueError("This quantization technique requires a CUDA GPU (V100/A100). ...")
```

`use_seq_mse` / `use_ada_scale` are set purely from the recipe step names. **A recipe containing only
`Calibration` has no CUDA requirement at all.** That is your documented "min-max / calibration-only"
escape hatch. There is no flag for it — you express it as a recipe YAML.

### 2.4 Hardware requirements **[web] + [local]**

- Model README **[local]**: *"🔴 Quantizing the model (GPU required) ... a dedicated CUDA enabled GPU
  (40 GB VRAM for 3B models to 80 GB VRAM for 8B models) is recommended."*
- `models/llama_v3_2_3b_instruct/model.py:52` **[local]**: `MIN_MEMORY_RECOMMENDED = 80` (GB host RAM).
  Grepped: **this constant is never enforced anywhere in the package** — it is documentation only.
- Tutorial **[web]** https://github.com/qualcomm/ai-hub-models/blob/main/tutorials/llm/quantize_llama3.md:
  40 GB VRAM for 3B, 80 GB for 8B; SeqMSE "5+ hours".
- `manifest.yaml` `post_pip_install_commands` **[local]**: on a GPU machine it uninstalls
  `onnxruntime` and force-installs `onnxruntime-gpu==1.23.2`.

Realistic memory for a **Calibration-only, CPU** run of a 3B:
fp32 torch FP model (~12.8 GB) + ORT CPU session over `model.data` (~12.8 GB, partly mmapped) +
QuantSim quantiser state + prefill buffers (memory-mapped to disk — `_prefill_dataset()` writes to
`np.memmap` files precisely to avoid RAM blow-up **[local]**). **Estimate 25-40 GB RSS.**
Confidence: medium.

### 2.5 The recipe YAML you want (calibration-only, no CUDA)

File `calib_only_w4a16.yaml`. Top-level schema is `{precision:, recipe:}` — validated by
`LMQuantizationDetails` (`configs/manifest_yaml.py:250-271`) **[local]**:

```yaml
# calib_only_w4a16.yaml  --  w4a16, no SeqMSE, no CUDA required.
precision:
  activations: int16
  kv_cache:    int8
  embedding:   int16
  lm_head:
    qtype:       int8
    granularity: PCQ
  blocks:
    default:
      qtype:       int4
      granularity: PCQ
recipe:
  - name: Calibration
    num_iterations: 8           # 8 blocks of --context-length tokens. 20 = Qualcomm default.
    dataset:
      name:  Wikitext           # see section 3 -- this name is overridden by a monkeypatch
      split: train
```

Used as:

```bash
python -m qai_hub_models.models.llama_v3_2_3b_instruct.quantize \
    --checkpoint /path/to/merged_bf16_hf \
    --output-dir /path/to/ft_w4a16_calibrated \
    --precision ./calib_only_w4a16.yaml \
    --context-length 2048 \
    --calibration-sequence-length 1024
```

Schema rules you must respect **[local]** (`models/templates/lm_schema/recipe.py`,
`.../precision.py`, `models/templates/llm/quantize.py`):

- Technique vocabulary: `SpinQuant` (pre-sim), `RemoveQuantization`, `Skip`, `Clip`, `Calibration`,
  `SeqMSE`, `AdaScale`. **Only `SeqMSE`, `AdaScale`, `Calibration` are actually implemented** in
  `quantize_from_steps`; anything else raises `TypeError`.
- Every data-consuming step **must** name its own `dataset:`. There is no class-level default.
- A chain with no *terminal* step (`Calibration` / `Skip` / `RemoveQuantization`) gets a
  `Calibration` on Wikitext auto-appended.
- Pre-sim steps must form a contiguous prefix; `SpinQuant` requires at least one of
  `enable_r1/enable_r2/enable_r3`.
- `assert_realizable_precision()` **rejects** any precision block that does not resolve to exactly
  `w4a16` (int4 PCQ weights / int16 acts / int8 lm_head / int8 kv) or `w4` (int4 weights / float acts /
  int8 lm_head). **Anything else fails loud.**
- **Trap:** you *can* write `granularity: LPBQ, block_size: 64` in the YAML and it will validate, but
  **it will be silently ignored for Llama.** Only the Phi template calls `_set_4bit_weights_to_lpbq()`
  (`models/templates/phi/model.py:314-326`); `LLM_AIMETOnnx._configure_quant_sim` does not read the
  schema's granularity. Confidence: high. (A monkeypatch adding `_set_4bit_weights_to_lpbq(quant_sim)`
  to the Llama `_configure_quant_sim` would give blockwise-64 4-bit weights, which should cut weight
  error roughly to NF4 levels — but it is unvalidated for this model and could break the Genie export.
  Treat as a research option, not a plan.)

A **SeqMSE** variant (needs CUDA ≥ ~40 GB, do not attempt on a T4):

```yaml
recipe:
  - {name: SeqMSE,      num_iterations: 20, dataset: {name: Wikitext, split: train}}
  - {name: Calibration, num_iterations: 20, dataset: {name: Wikitext, split: train}}
```

### 2.6 Is there a cloud/free alternative to the 40 GB box?

- `qai_hub.submit_quantize_job()` (https://workbench.aihub.qualcomm.com/docs/hub/quantize_examples.html)
  does support `w4a16` and runs AIMET in the cloud — but it takes a **single unquantised ONNX plus
  calibration data**, and this model is `requires_aot_prepare: true`, `only_allow_orchestrator_runtimes:
  true`, with a 3-way split and a native-KV graph **[local]**. The LLM path in `qai-hub-models` does
  **not** route through hub quantize jobs; it quantises locally and only *compiles* on Hub.
  **Not a usable escape hatch for the LLM flow.** Confidence: medium-high.
- Qualcomm **GenAI Lab** (the desktop app) wraps the same AIMET recipes and has the same hardware
  requirement. Not a free-tier workaround.

---

## 3. Custom calibration data (your own agent prompts)

**There is no CLI flag for custom calibration data.** **[local]** `--precision` recipe YAML can only
name a dataset from a fixed vocabulary (`Wikitext`, `TinyMMLU`, `MMLU`, `MMLUPro`, `MMMLU`, `MMMU`,
`C4`, `AOKVQA`, `Imagenette`, `GeneratedDataset`, `Interleaved` —
`models/templates/lm_schema/dataset.py`), **and of those only `Wikitext` plus the AOKVQA×Wikitext
interleave are actually loadable**:

```python
# models/templates/llm/quantize.py :: resolve_dataset_cls
common_datasets: dict[str, type[BaseDataset]] = {"Wikitext": WikiText}
```

Everything else raises *"AI Hub Models cannot load calibration dataset X today"*. Confidence: high.

### 3.1 The supported-ish hook: override `WikiText.load_raw_dataset`

**[local]** `datasets/wikitext/wikitext.py` is trivially overridable: `load_raw_dataset()` returns a
🤗 `Dataset` with a `"text"` column, and `__init__` joins those texts with `tokenizer.bos_token`
(train split) then chunks the token stream into `context_length`-sized blocks. So:

`pyhooks/custom_calib.py`:

```python
# Import this module BEFORE calling quantize. Replaces wikitext with our agent prompts.
import json
from datasets import Dataset
from qai_hub_models.datasets.wikitext.wikitext import WikiText

PROMPTS = "/path/to/calib_prompts.jsonl"   # one JSON object per line: {"text": "<full prompt+response>"}

def _load_raw_dataset(self):
    texts = [json.loads(l)["text"] for l in open(PROMPTS, encoding="utf-8")]
    return Dataset.from_dict({"text": texts})

WikiText.load_raw_dataset = _load_raw_dataset
```

Then either `PYTHONPATH=pyhooks python -c "import custom_calib; ..."` driving `quantize()` directly,
or reuse your existing `pyhooks/sitecustomize.py` pattern so the module loads before
`python -m qai_hub_models...quantize`.

Cleaner but equivalent alternative: patch the resolver itself —

```python
import qai_hub_models.models.templates.llm.quantize as Q
_orig = Q.resolve_dataset_cls
Q.resolve_dataset_cls = lambda spec, extra=None: MyPromptDataset if spec.name == "Wikitext" else _orig(spec, extra)
```

`models/templates/llm/model.py :: prefill_dataset` imports `resolve_dataset_cls` *locally at call
time*, so patching the module attribute works. **[local]**

Your `MyPromptDataset` must be a `BaseDataset` whose `collate_fn` yields
`(input_ids, attention_mask, label)` and whose `__getitem__` returns `{"input_ids", "attention_mask"}`
of up to `context_length` tokens — copy `WikiText` and swap the loader. Confidence: high that this
works; medium that you hit no version-specific papercut.

### 3.2 How to build the calibration set, and how much

- **Use the *exact deployed prompt*** — same system prompt, same schema instructions, same few-shot
  block, same sensor-window formatting — with ~100-400 *different* windows, and **include a
  representative assistant JSON response** after each prompt. Calibration must cover both the prefill
  distribution (long, highly structured, fixed prefix) and the decode distribution (your short JSON).
  This matters a lot for you: attention-sink/outlier structure is prefix-dependent
  (https://arxiv.org/abs/2406.12016).
- **Volume:** Qualcomm's default is 20 blocks × 4096 tokens ≈ **80k tokens**. The code's own fallback
  is literally `ceil(80000 / context_length)`. At ~650 tokens/prompt + ~90 tokens response, **~110
  prompt/response pairs ≈ 80k tokens** reproduces Qualcomm's volume. 8-20 blocks is the practical
  range; min-max activation calibration converges fast. Going much above 20 blocks buys little and
  costs linear time. Confidence: medium-high.
- **Set `--context-length 2048`** (your prompts are ~650 tokens + ~84 output). This packs ~3 pairs per
  block, halves prefill cost and halves device KV RAM. **You must then export with
  `--context-lengths 2048`.** (Keep 4096 only if you need long multi-turn context.)
- Keep a small *held-out* set; `evaluate --task wikitext` is useless to you — evaluate with your own
  12-class metric via `demo`/`evaluate --checkpoint <out>` on host before spending an export.

---

## 4. Feasibility on your hardware

### 4.1 Summary table

| Route | Machine | Fits? | Wall clock | Confidence |
|---|---|---|---|---|
| Default w4a16 recipe (SeqMSE + Calibration) | needs 40 GB VRAM CUDA | **No** on any machine you have | 5-10 h on an A100 | high |
| SeqMSE on Kaggle T4 16 GB | T4 | **No — will OOM** | — | high |
| **Calibration-only, CPU** (`CUDA_VISIBLE_DEVICES=""`) | Kaggle CPU session, 30 GB RAM, 60 GB disk, 12 h | **Borderline (25-40 GB est.)** | 3-7 h | medium |
| **Calibration-only, CPU, Kaggle TPU VM** (~330 GB RAM, use CPU only) | TPU v3-8 VM | **Yes, comfortably** | 4-8 h | medium |
| Calibration-only on WSL2 (9 GB RAM + 64 GB swap) | laptop | technically yes, swap-thrashing | 20-60 h | medium-high it is too slow |
| **No re-quantisation at all — export at `w4` (fp16 acts)** | laptop CPU, no calibration | **Yes** | ~1 h local + 1.5-4 h AI Hub | high |

### 4.2 The CUDA trap on Kaggle

`torch.cuda.is_available()` → `True` on a T4, so `quantize()` picks `device=cuda` and builds QuantSim
+ the ORT session on a 16 GB card with a ~13 GB fp32 graph. **It will OOM.** If you run on a Kaggle
GPU session, force CPU explicitly:

```bash
CUDA_VISIBLE_DEVICES="" python -m qai_hub_models.models.llama_v3_2_3b_instruct.quantize ...
```

Also skip the GPU post-install (`onnxruntime-gpu`) — keep plain `onnxruntime` for the CPU path.
Confidence: high.

### 4.3 The big shortcut you already have

**[local]** `quantize()` skips the ONNX export phase entirely if a complete export already exists:

```python
def _has_onnx(p): return quantized_model_cls._has_onnx_on_disk(p, seq_len, context_length)
onnx_dir = output_path
if _has_onnx(output_path):        pass
elif checkpoint and _has_onnx(Path(checkpoint)): onnx_dir = Path(checkpoint)
else:                              export + pre-sim transforms
```

and `_has_onnx_on_disk` just checks for `model_dynamic.onnx` **and** (`model.data` or
`model.onnx.data`) (`models/templates/llm/model.py:2753-2773`).

**Your `build_ft_ckpt.py` already produces exactly those two files on CPU.** So:

```bash
mkdir -p ft_w4a16_calibrated
cp ft_ckpt/model_dynamic.onnx ft_ckpt/model.data ft_w4a16_calibrated/
CUDA_VISIBLE_DEVICES="" python -m qai_hub_models.models.llama_v3_2_3b_instruct.quantize \
  --checkpoint /path/to/merged_bf16_hf \
  --output-dir ft_w4a16_calibrated \
  --precision ./calib_only_w4a16.yaml \
  --context-length 2048 --calibration-sequence-length 1024
```

This skips the slowest phase and goes straight to QuantSim + calibration. (Keep `--checkpoint`
pointing at the **merged HF dir**: the FP torch model is still needed for prefill and for
`save_calibrated_checkpoint(fp_model=...)`.) Confidence: medium-high — the code path is clear, but
the sequence_length/context_length you pass must be consistent with how the ONNX was exported.

### 4.4 Sharding / blockwise

There is **no** `--num-splits` or per-part quantisation flag. `NUM_SPLITS = 3` is an architectural
constant used at *export/compile* time only (3 context binaries). Calibration deliberately runs on
the monolithic `PreSplit` QuantSim — `quantize()` even warns if given a split-forward wrapper because
stacking one ORT session per part "can OOM the GPU". **[local]** So there is no supported way to
quantise part-by-part to reduce peak memory. The levers you have are: CPU instead of GPU, lower
`--context-length`, lower `--calibration-sequence-length`, fewer `num_iterations`. Confidence: high.

### 4.5 Time estimates (3B, calibration-only)

| Phase | CPU (4-8 vCPU) |
|---|---|
| ONNX export (skippable — you have it) | 20-45 min |
| QuantSim build + session | 10-25 min |
| Prefill 8 blocks × 2048 tok | 30-90 min |
| `compute_encodings` over 8 blocks | 45-120 min |
| `save_calibrated_checkpoint` | 15-30 min |
| **Total (export skipped)** | **~2-4.5 h** |
| Same with 20 blocks × 4096 | ~6-10 h |

Then AI Hub export/compile (3 context binaries + bundle): **1.5-4 h**. Confidence: medium.

---

## 5. Keeping LoRA un-merged and applying it at runtime

**Verdict: the runtime LoRA feature is real, but it is NOT reachable from an AI Hub / qai-hub-models
bundle. Do not attempt this within 20 hours. Confidence: high.**

### 5.1 What exists (so you know it isn't imaginary)

**`genie-t2t-run -l/--lora` is real and documented.** Verbatim from the QAIRT 2.50 tools docs
(bundle 80-63442-10, `genie-t2t-run`):

```
-l or --lora   <VAL>   ADAPTER_NAME,ALPHA_NAME_1,ALPHA_VALUE_1,ALPHA_NAME_2,ALPHA_VALUE_2,..
                       Apply a LoRA adapter to a dialog.
```
```
./genie-t2t-run -c llama2-7b-htp-lora.json -p "..." -l lora1,alpha,0.5
```
Sample configs ship at `${QNN_SDK_ROOT}/examples/Genie/configs/llama2-7b-htp-lora.json` and
`.../llama3-3b/llama3-3b-eaglet-htp.json`. Eaglet dialogs add `--allow_engine_switch`.

**Genie C API in 2.50:** `GenieDialog_applyLora` (2.28.0), `GenieDialog_setLoraStrength` (2.28.0),
`GenieDialog_releaseLoraMemory` (2.46.0), plus `GenieNode_applyLora/setLoraStrength/saveLora`.
**There is no `GenieLoraAdapter_*` family** — adapters are declared in the dialog JSON, not via a
separate handle. LoRA V3 dialog JSON (Qualcomm's own worked example is **Llama-3.2-3B**):

```json
"lora": {
  "version": 1,
  "alpha-tensor-name": "lora_alpha",
  "adapters": [
    {"version":1,"name":"ar73_cl4096_2_of_3_default_adapter",
     "bin-sections":["ar73_cl4096_2_of_3_default_adapter.bin"]},
    {"version":1,"name":"ar73_cl4096_2_of_3_elementary","alphas":["alpha-elem"],
     "bin-sections":["ar73_cl4096_2_of_3_elementary.bin"]}
  ],
  "groups": [ ... ]
}
```

**`libQnnLoraAdapterBinUpdater.so` is undocumented** — zero hits across docs.qualcomm.com. Its
presence on your device proves nothing about your bundle; it is a runtime library shipped with the
BSP, not evidence that your context binaries carry updatable tensors.

### 5.2 Why it is unreachable for you — three independent blockers

1. **The base context binary must be built LoRA-aware. This is the hard blocker.**
   - `qairt-converter --lora_weight_list <tensor_names.txt>` is what marks the adapter weight tensors
     as **"updatable tensors" in the graph**. Without it they do not exist.
   - The raw QNN API docs state outright: *"Tensors must be of `UPDATEABLE` type, **created during
     graph composition**."*
   - `qnn-context-binary-generator --adapter_weight_config <adapters.yaml>` then emits the base
     binary **plus one binary-section `.bin` per adapter**. `QnnContext_applyBinarySection` patches
     those updatable tensors — with nothing to patch, there is no mechanism.
   - LoRAv2 *"requires full offline preparation of both Base Model & Adapters, with quantization done
     by AIMET"*, and *"both base model context binary and adapter binary files MUST be prepared using
     the same QAIRT SDK version."*
   - LoRAv3 additionally needs N+1 ONNX graphs with identical op/tensor names and `Conv->Mul->Conv`
     attach points. **None of this is retrofittable to an existing `.bin`.**

   **Your `llama_v3_2_3b_instruct_part_{1,2,3}_of_3.bin` were not built this way, so
   `genie-t2t-run -l` against them will fail (missing adapter/alpha tensors), not degrade
   gracefully.** Confidence: very high.
   Note the flag is `--lora_weight_list`; **`--lora_alpha_list` does not exist** — alpha is a graph
   *input tensor* (`lora_alpha`) set at runtime.

2. **`qai-hub-models` has zero LoRA support, and AI Hub explicitly disclaims the compiler path.**
   **[local]** A case-insensitive grep for `lora` across the entire installed `qai_hub_models`
   package returns matches in exactly four files, all the `ddcolor` *colorization* model (substring
   false positives). Same result on `quic/ai-hub-apps` and `qualcomm/ai-hub-models` main
   (`colorAccent`, `colorama`, `ddcolor` only); `llm_on_genie` never mentions LoRA. Decisively, the
   ai-hub-models repo's own triage FAQ carries an entry keyed on `--adapter_weight_config` /
   "QAIRT … LoRA w4 weights" whose answer is that the tool is *"outside AI Hub's expertise — the AI
   Hub team works on AI Hub Workbench, not the lower-level QAIRT compiler binaries."*
   No `submit_compile_job` compile-option for LoRA is documented. **Not reachable on any tier.**
   Confidence: very high.

3. **You would have to replace the whole toolchain**: `qairt-lora-mapper` →
   `qairt-lora-model-creator` → `qairt-converter --lora_weight_list` → `qairt-quantizer` →
   `qairt-lora-importer` → `qnn-context-binary-generator --adapter_weight_config`, locally, with the
   full QAIRT SDK + AIMET on an x86 Linux/Windows host, reproducing the 3-way split, native KV cache,
   AR-128/AR-1 graph pair and Genie bundle layout by hand. Qualcomm's only end-to-end material is a
   3-notebook series **inside the SDK** (not on GitHub); there is **no public GitHub sample, blog post
   or ai-hub-apps demo** of runtime LoRA on a Genie *LLM* bundle. Multi-week, not 20 hours.

**LoRA version timeline (for the record):** 2.28 `GenieDialog_applyLora`/`setLoraStrength`, LoRA V1+V2 ·
2.34 all three LoRA generations · 2.36 `skip-lora-validation` · 2.37 LoRA weight sharing across
graphs · 2.43 weight-shared adapters via JSON · 2.46 `GenieDialog_releaseLoraMemory` · 2.49 LoRA
buffer groups · 2.50 LoRA checksum fix for 2/4-bit context binary generation.

### 5.3 Also worth knowing

Even if it worked, it would **not** solve your problem. The accuracy loss is in how the *base* weights
and activations are quantised; an un-merged LoRA applied at runtime would be applied *on top of* the
same quantised base, through the same stale activation encodings. It changes where the delta lives,
not the quantisation of the path it flows through.

**Recommendation: close this line of enquiry.**

---

## 6. Alternative precisions

### 6.1 w8a16 — **not supported**. Confidence: very high **[local]**

- `SUPPORTED_PRECISIONS = [Precision.w4a16, Precision.w4]`
  (`models/llama_v3_2_3b_instruct/model.py:59`).
- `_REALIZABLE_PRECISION_PATTERNS` in `models/templates/llm/quantize.py:126-135` contains **only**
  `w4a16` and `w4`. A recipe YAML with `blocks.default.qtype: int8` makes `derive_precision()` raise
  *"does not match any precision AI Hub Models can realize today"*.
- `get_hub_compile_options` rejects any other Precision.
- The manifest's "and part of the model is quantized to w8a16" refers only to **lm_head + KV cache**
  being int8, not to a w8a16 whole-model mode.

### 6.2 Per-layer mixed precision — minimal, but real **[local]**

Two class attributes on the quantizable model control it:
`int8_param_names: tuple[str, ...] = ()` and `fp16_param_names: tuple[str, ...] = ()`
(`models/templates/llm/model.py:2505-2508`). Both are **empty for Llama 3.2 3B**; `intern3_5_vl_2b`
uses `fp16_param_names = ("model.model.layers.2.mlp.down_proj.weight",)` as precedent. A subclass
could list sensitive tensors (e.g. the handful your D1 sweep shows have the worst per-channel error)
to hold them at int8-PCQ or fp16. **`_hold_params_at_fp16` only runs for `w4a16`.** This is a
legitimate, low-risk lever but requires a code patch and an export round trip; expect single-digit
recovery. Confidence: medium.

### 6.3 `w4` (int4 weights, **fp16 activations**) — the one you should actually try

**[local]** `_configure_quant_sim`, `precision == Precision.w4`:
```python
_set_lm_head_to_8b(quant_sim)
cls._apply_precision_activations(quant_sim, precision)   # -> sets ALL activation quantizers to float16
```
No KV-cache int8 tying, no 16×8 matmuls, **no activation encodings to be stale**.

| | w4a16 (current) | w4 (fp16 acts) |
|---|---|---|
| Weights | int4 PCQ | int4 PCQ (same) |
| Activations | int16 static encodings | **fp16 — no calibration** |
| KV cache | int8 | fp16 |
| Base-model Grace2 (genie, X Elite) **[local]** | 79.6 | 78.3 |
| Bundle size | 2.6 GB | **~2.6 GB** (weights unchanged) |
| Device RAM/session | ~3.7 GB | **~4.1-4.4 GB** (KV 4096×28×8×128×2: 235 MB int8 → 470 MB fp16; plus wider intermediate buffers) |
| tok/s on 8 Gen 3 | 19 | **estimate 11-16** (fp16 HTP matmul throughput < int16; unmeasured) |

Both fit comfortably in your 9.3 GB available RAM and 33 GB storage. **At `--context-lengths 2048`
the KV cost halves again.**

Qualcomm publishes a `DEFAULT_W4` checkpoint, so you can run **exactly the trick you already ran**,
but with the `w4/model.encodings` asset instead of `w4a16/model.encodings` — and this time there is
nothing stale to inherit, because the file carries essentially only *param* encodings:

```python
# build_ft_ckpt.py, one-line change:
enc = CachedWebModelAsset.from_asset_store(Q.model_id, Q.model_asset_version, "w4/model.encodings").fetch()
```
then run `refresh_param_scales.py` (MSE-optimal clipping) on the result, then
`qai-hub-models export llama_v3_2_3b_instruct --checkpoint ./ft_w4_ckpt --context-lengths 2048`.
Confidence this builds and exports: medium-high. Confidence it meaningfully recovers accuracy *if*
hypothesis A (activations) is right: high. If hypothesis B (weights) is right, it recovers little —
which is why D1 comes first.

---

## 7. Cheap mitigations without re-quantisation

### 7.1 Weight scales (free, you already wrote it)

Switch from `max(published, min-max)` (0.173) to **MSE-optimal per-channel clipping** (0.120).
31% less weight error for zero compute. This alone is worth one export. Confidence it helps: high;
confidence it is sufficient: low.

### 7.2 Genie sampler / decoding

Your `genie_config.json` already has `temp: 0.1, top-k: 1`, which is greedy — `top-k: 1` makes
`temp` and `top-p` irrelevant. **There is no accuracy left on the table in the sampler.**
What *is* available and cheap:
- **Shorten the context**: re-export at `context-lengths 2048`. Less KV, less drift, less RAM.
- **Harden the prompt**: shrink the JSON schema, put the 12 pattern names as a terse enumerated list
  immediately before the answer, and move the schema *after* the data so it is closest to generation.
  Malformed JSON under quantisation is usually a "the constraint is too far back in context" problem.
- **Retry-on-parse-failure** in `genie_runner.py`: on malformed JSON, re-prompt with the partial
  output and a one-line "emit only valid JSON" nudge. Cheap, recovers most of the format loss, does
  nothing for the 45% pattern accuracy.
- Genie has **no grammar/constrained-decoding** support in 2.50. If you move to GenieX you should
  re-check this.
- `spill-fill-bufsize: 0` and `use-mmap: false` are performance, not accuracy, knobs.

### 7.3 LoRA-α scaling at merge (good diagnostic, mediocre fix)

Merge `W + γ·(α/r)·BA` and sweep `γ ∈ {0.7, 0.85, 1.0, 1.25, 1.5}`. With α/r = 2.0 you have room in
both directions.
- If accuracy **rises as γ→0** toward 20%: the delta is creating outliers that min-max crushes → the
  fix is better weight scales (§7.1), not less fine-tuning.
- If accuracy **rises as γ grows**: the fine-tuning signal is being drowned by quantisation noise →
  boosting γ increases SNR (at some cost to host-model quality). This is the hypothesis-B remedy and
  it is *free*.
Evaluate the whole sweep under **D1 host fake-quant**, not on device. Folklore, not a published
method (cf. https://llamafactory.readthedocs.io/en/latest/getting_started/merge_lora.html).
Confidence it helps: medium-low, but the information value is high and the cost is ~1 h.

### 7.4 SmoothQuant applied offline while reusing the published activation encodings

**The maths.** For a linear `Y = X W` with per-input-channel scales `s`:

```
Y = (X · diag(s)^-1) · (diag(s) · W)
```

Standard choice: `s_j = max|X_j|^α / max|W_j|^(1-α)`, α ∈ [0.5, 0.85]
(SmoothQuant, https://arxiv.org/abs/2211.10438).

**Folding is free in Llama.** Pre-norm blocks feed q/k/v from `input_layernorm` and gate/up from
`post_attention_layernorm`; **RMSNorm's learnable `weight` is an elementwise per-channel multiply, so
dividing it by `s` is exact and costs nothing at runtime.** Then multiply the consuming weight by `s`.
(Confirmed in SmoothQuant and in AMD Quark / Intel Neural Compressor implementations:
https://quark.docs.amd.com/latest/pytorch/smoothquant.html,
https://github.com/intel/neural-compressor/blob/master/docs/source/PT_SmoothQuant.md)

**Does it invalidate the published activation encodings? Yes, by construction — that is the point.
But the direction is controllable and favourable.** Dividing channel *j* by `s_j > 1` **shrinks** that
activation. So instead of SmoothQuant's statistical formula, solve the *constrained* problem:

```
s_j = max( 1 ,  max|X_j^merged| / E_j )
```

where `E_j` is the range the published encoding allows for that channel. The smoothed activations then
**fit under the stale ranges**. The encodings become *conservative* (some int16 dynamic range unused)
rather than *clipping*. **Under-using an int16 range costs ~nothing; clipping costs everything.**
That asymmetry is what makes the trick viable at all. Confidence it is mathematically sound: high.

**And the weight-side cost is near zero for you**, because your weight encodings are **per-output-
channel symmetric**: scaling a weight *column* by `s_j` is absorbed by re-deriving that channel's
scale. SmoothQuant's usual weight-precision penalty does not bite here. Confidence: high.

**Caveats (why this is plan C, not plan A):**
1. Qualcomm activation encodings are typically **per-tensor**, so `E_j` is one number for the whole
   tensor. Per-channel `s` still helps (it pulls down the worst channel, which is what sets the
   per-tensor max) but you must re-verify the resulting per-tensor max. Confidence: medium-high.
2. **Only q/k/v and gate/up inputs are cleanly foldable.** `o_proj`'s input is the attention output
   and `down_proj`'s input is `SiLU(gate)·up` — neither has a preceding affine to absorb `s`. Folding
   into the previous linear is possible but, per Neural Compressor's own docs, "may compromise
   quantization". **And `down_proj`'s input is frequently the worst offender in Llama.** Confidence: high.
3. **RoPE breaks it for K/V.** The rotation is applied after the q/k projection, so a per-channel `s`
   on q/k output does not commute with RoPE unless `s` is constant within each rotary pair. Since your
   prime suspects are the **KV int8 tensors** (§1.3), SmoothQuant largely **cannot reach the tensors
   that are most likely broken.** Confidence: medium-high. *This is the decisive objection.*
4. It does not fix a shifted zero-point, only a scale.

**Verdict: elegant, mathematically compatible in principle, but it cannot reach the KV path and is a
workaround for not recalibrating. Rank it below both §6.3 (w4) and §2 (real calibration).**

### 7.5 Rotation methods (SpinQuant / QuaRot) — incompatible with frozen encodings

QuaRot (https://arxiv.org/abs/2404.00456) and SpinQuant (https://arxiv.org/abs/2405.16406) spread
outlier energy via orthogonal rotations. R1/R2 fold into weights; R3/R4 need **online Hadamard
kernels** that QNN/Hexagon will not give you. More importantly, **a rotation changes every activation
distribution by design — scales must be calibrated with the rotations in place.** There is no variant
compatible with a frozen pre-existing encoding file. Confidence: high. (`SpinQuant` *is* in the
`qai-hub-models` recipe vocabulary and would run as a pre-sim step **[local]**, but it is not in the
Llama 3.2 3B manifest recipe, it is pre-sim-only, and it still requires a full Calibration afterwards —
so it is only reachable from inside the §2 route, as a possible add-on.)

### 7.6 Quantisation-aware fine-tuning (out of scope for 20 h, note for later)

If you ever redo the fine-tune against a frozen-encoding deployment: **RoLoRA**
(https://arxiv.org/abs/2407.08044, Findings EMNLP'24) reports **+29.5 points** on commonsense
reasoning for W4A4 LLaMA2-13B vs plain LoRA, by keeping the model outlier-free *during* fine-tuning.
**ApiQ** (https://arxiv.org/abs/2402.05147) initialises LoRA to preserve *activations*. **QA-LoRA**
(https://arxiv.org/abs/2309.14717) merges exactly into quantised weights via the zero-point.
**LoftQ** (https://arxiv.org/abs/2310.08659). **Quaff** (https://arxiv.org/abs/2505.14742).
None is a 20-hour option.

---

## 8. Ranked plan

Scoring = (expected recovery) × P(success) / time.

| # | Option | Exp. recovery | P(success) | Time | Score |
|---|---|---|---|---|---|
| **0** | **D1 host fake-quant replay** (§1.6) — not a fix, a decider | n/a | 0.9 | **1 h** | **essential** |
| **1** | **Export at `w4` (fp16 activations) with MSE-optimal param scales** (§6.3 + §7.1) | +25-45 pts *if* activations are the cause | 0.65 | 1 h local + 2-4 h Hub | **highest** |
| **2** | **Calibration-only AIMET re-quantise on your own prompts, w4a16** (§2.5, §3, §4.3) | +25-45 pts | 0.5 (memory/time risk) | 3-5 h + 2-4 h Hub | high |
| 3 | MSE-optimal param scales alone, w4a16 re-export (§7.1) | +3-10 pts | 0.85 | 0.5 h + 2-4 h Hub | medium (fold into 1 or 2, never spend a round trip on it alone) |
| 4 | LoRA-α sweep at merge, validated under D1 (§7.3) | 0-15 pts | 0.35 | 1 h (host only) | medium |
| 5 | Prompt hardening + JSON retry in `genie_runner.py` (§7.2) | +5-15 pts on *valid-JSON rate*, ~0 on pattern acc | 0.8 | 1 h, no export | medium — do it anyway, it is free |
| 6 | Constrained SmoothQuant fitted to published ranges (§7.4) | 0-20 pts | 0.25 (cannot reach KV) | 4-6 h | low |
| 7 | LPBQ-64 weights via monkeypatch (§2.5 trap) | +5-20 pts | 0.3 (unvalidated for Llama, may break export) | 4 h + Hub | low |
| 8 | Runtime LoRA adapter (§5) | n/a | **~0.05** | ≫20 h | **do not attempt** |
| 9 | SeqMSE / AdaScale / SpinQuant recipes | +5-15 pts | 0 on your hardware (40 GB CUDA) | — | **not reachable** |

### Best plan (fits ~20 h, two AI Hub round trips max)

**Hour 0-1 — D1 + D2 (decide the root cause).**
Host fake-quant replay with the device's exact per-channel int4 scales, fp16 activations, your real
eval set; plus `‖ΔW‖/‖W‖`. Also sweep published / widened / MSE-optimal scales inside D1.

**Hour 1-2 — Build the `w4` checkpoint** (one-line change to `build_ft_ckpt.py`, §6.3) and run
`refresh_param_scales.py` on it. In parallel, start the Kaggle calibration job (below).

**Hour 2-6 — AI Hub export round trip #1: `w4`, `--context-lengths 2048`.** Profile + download +
on-device eval. This is the highest-probability single shot because it removes the stale-activation
variable entirely without needing calibration data or a big GPU.

**In parallel, hour 1 onward — Kaggle CPU session: calibration-only w4a16 with your own prompts.**
Use the `_has_onnx_on_disk` shortcut (§4.3) by copying your existing `model_dynamic.onnx` +
`model.data` into `-o`. Recipe = `calib_only_w4a16.yaml` with `num_iterations: 8`,
`--context-length 2048 --calibration-sequence-length 1024`, `CUDA_VISIBLE_DEVICES=""`.
Prefer a Kaggle **TPU VM** session (≈330 GB RAM, CPU-only torch) over the 30 GB CPU session if the
30 GB one OOMs. Then apply MSE-optimal param scales on top of the freshly calibrated encodings.

**Hour 6-14 — AI Hub export round trip #2:** whichever of the two checkpoints wins on host eval.
(Evaluate both on host first with `qai-hub-models ... demo/evaluate --checkpoint <dir>`; do not spend
a round trip on an unvalidated checkpoint.)

**Throughout — free wins:** prompt hardening, JSON retry in `genie_runner.py`, context length 2048.

### Fallback

If both exports land below ~70%: ship the **w4** bundle (whatever it scores) with prompt hardening +
JSON retry + a deterministic rule-based classifier as a fallback for low-confidence windows, and
document the quantisation gap. Do **not** burn the remaining hours on SmoothQuant or runtime LoRA.

### What to stop believing

- "The base model is unaffected, so the quantisation is fine." It is at chance; the test has no power.
- "16-bit activations are safe." Only when calibrated on *this* model with *this* prompt distribution.
- "Host 4-bit ≈ device 4-bit." NF4-bs64 is ~3× finer than per-channel int4-PCQ.

---

## Sources

**Verified locally (qai-hub-models 0.63.0)**
`models/llama_v3_2_3b_instruct/{quantize.py,manifest.yaml,model.py,numerics.yaml,README.md}`,
`models/templates/llm/{quantize.py,model.py,_utils.py}`,
`models/templates/lm_schema/{recipe.py,precision.py,dataset.py}`,
`models/templates/phi/model.py`, `configs/manifest_yaml.py`,
`utils/quantization_aimet_onnx.py`, `utils/checkpoint.py`, `datasets/wikitext/wikitext.py`.

**Qualcomm**
- https://github.com/qualcomm/ai-hub-models/blob/main/tutorials/llm/quantize_llama3.md
- https://aihub.qualcomm.com/models/llama_v3_2_3b_instruct
- https://workbench.aihub.qualcomm.com/docs/hub/quantize_examples.html
- https://workbench.aihub.qualcomm.com/docs/hub/generated/qai_hub.submit_quantize_job.html
- https://github.com/qualcomm/ai-hub-apps/tree/main/tutorials/llm_on_genie
- Genie LoRA & draft switching: https://docs.qualcomm.com/nav/home/lora_lora.html?product=1601111740062489
- Genie usage: https://docs.qualcomm.com/nav/home/how_to_use_genie.html?product=1601111740062489
- QAIRT tools: https://docs.qualcomm.com/bundle/publicresource/topics/80-63442-10/general_tools.html
- QNN-EP LoRA (adapter binary sections): https://github.com/microsoft/onnxruntime/pull/24026
- `genie-t2t-run` CLI: https://docs.qualcomm.com/bundle/publicresource/80-63442-10/topics/genie-t2t-run.md
- Genie LoRA: https://docs.qualcomm.com/bundle/publicresource/80-63442-10/topics/lora.md
- Genie API index / revision history: https://docs.qualcomm.com/bundle/publicresource/80-63442-100/topics/api_root.md ·
  https://docs.qualcomm.com/bundle/publicresource/80-63442-100/topics/revision_history.md
- QAIRT LoRA v2 / v3 overviews: https://docs.qualcomm.com/bundle/publicresource/80-63442-50/topics/lora_v2_0_overview.md ·
  https://docs.qualcomm.com/bundle/publicresource/80-63442-50/topics/lora_v3_overview.md ·
  https://docs.qualcomm.com/bundle/publicresource/80-63442-50/topics/lora_intro.md
- Genie dialog JSON: https://docs.qualcomm.com/doc/80-63442-100/topic/json.html
- QNN weight sharing: https://docs.qualcomm.com/doc/KBA-250306025001/KBA-250306025001_REV_1_QNN_Weight_Sharing_Feature.pdf
- https://docs.pytorch.org/executorch/stable/llm/build-run-llama3-qualcomm-ai-engine-direct-backend.html

**Papers**
SmoothQuant https://arxiv.org/abs/2211.10438 ·
LLM.int8() https://arxiv.org/abs/2208.07339 ·
Massive Activations https://arxiv.org/abs/2402.17762 ·
CushionCache https://arxiv.org/abs/2406.12016 ·
Quaff https://arxiv.org/abs/2505.14742 ·
Atom https://arxiv.org/abs/2310.19102 ·
COMET https://arxiv.org/abs/2410.12168 ·
GPTQ https://arxiv.org/abs/2210.17323 ·
AWQ https://arxiv.org/abs/2306.00978 ·
QuaRot https://arxiv.org/abs/2404.00456 ·
SpinQuant https://arxiv.org/abs/2405.16406 ·
QA-LoRA https://arxiv.org/abs/2309.14717 ·
LoftQ https://arxiv.org/abs/2310.08659 ·
L4Q https://arxiv.org/abs/2402.04902 ·
ApiQ https://arxiv.org/abs/2402.05147 ·
RoLoRA https://arxiv.org/abs/2407.08044 ·
IR-QLoRA https://arxiv.org/abs/2402.05445 ·
MergeQuant https://arxiv.org/abs/2503.07654 ·
calibration-robustness counterpoint https://arxiv.org/abs/2405.20835

**Community**
https://kaitchup.substack.com/p/dont-merge-your-lora-adapter-into ·
https://github.com/huggingface/peft/pull/1532 ·
https://quark.docs.amd.com/latest/pytorch/smoothquant.html ·
https://github.com/intel/neural-compressor/blob/master/docs/source/PT_SmoothQuant.md
