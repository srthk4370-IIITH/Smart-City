# Plan: close the NPU accuracy gap (94 % host → 54 % device)

Status 2026-10-07 14:00 IST. Deadline Thu 14:00, so ~24 h. Nothing below has been started except the
v2 export already in flight. Full research in `QUANT_RESEARCH.md`.

---

## 1. Measured facts

| | pattern accuracy | JSON valid | evidence valid | latency |
|---|---|---|---|---|
| host, NF4 4-bit + bf16 (150 ex) | **94.0 %** | 100 % | 100 % | - |
| device, w4a16 (46 ex) | **54.3 %** | 89.1 % | 87.0 % | 5.3 s |
| device, base model (46 ex) | 13.0 % | 71.7 % | 23.9 % | 6.7 s |

JSON is valid 89 % of the time on device, so this is **real prediction loss, not formatting**.

## 2. Two assumptions I had wrong (found during research)

1. **"The base model is unaffected, so the reused encodings are fine."** Invalid. The base model scores
   13-20 % on a 12-class task where chance is ~8 %. It is at the floor, so it *cannot* show degradation.
   That comparison proves nothing.
2. **"94 % on host proves 4-bit is enough."** Invalid. Host used bitsandbytes **NF4**: block size 64,
   non-uniform, one scale per 64 weights. The device uses **per-channel int4**: one scale per output
   channel (thousands of weights), uniform. The device scheme is far coarser. The two are not comparable.

So the cause is **not yet proven**. Two candidates:
- **(a) weights**: per-channel int4 is too coarse for the LoRA-merged weights.
- **(b) activations**: we reuse Qualcomm's *base-model* activation ranges; 1,456 of those tensors are
  int8, and fine-tuning shifts the distributions they were calibrated for.

## 3. Step 0 — decide between (a) and (b) before spending any export time

**Host fake-quant replay** (~1 h, laptop GPU, free, no export):
apply the device's exact per-channel int4 weight scales to the merged weights, keep activations in fp16,
and re-run the same 150-example eval.

| result | meaning | action |
|---|---|---|
| stays ~90 % | weights are fine → **activations are the cause** | Step A is the fix |
| falls to ~55 % | **weights are the cause** | Step B is the fix |
| falls to ~70 % | both contribute | do A, then B |

Also report `‖ΔW‖/‖W‖` from the LoRA merge (expected 0.5-3 %) against the 12-17 % quantisation noise.
**This is the single most valuable hour available and everything else keys off it.**

## 4. Step A — export at precision `w4` instead of `w4a16`  *(primary fix if activations are the cause)*

Verified in the installed toolchain:
- `SUPPORTED_PRECISIONS = [Precision.w4a16, Precision.w4]` (`llama_v3_2_3b_instruct/model.py:58`)
- for `w4` the code sets activations to float16 — source comment: *"For w4 (no activation quantization):
  use fp16"* (`templates/llama3/model.py:~500`)
- a published `w4/model.encodings` asset exists, same as the `w4a16` one we already use

So `w4` **removes the stale activation encodings entirely** — there are none. Weights stay 4-bit, and we
keep the MSE-optimal weight scales. Change is small: fetch `w4/model.encodings`, set
`{"precision": "w4"}`, export with `--precision w4`.

- Cost: one export cycle. Measured last night: ~25 min upload + ~20 min compile + ~15 min download ≈ **1-1.5 h**.
- Risk: fp16 activations use more bandwidth → generation may be slower, and device RAM per session rises.
  Must measure tokens/s and RAM before adopting. Mitigation: keep the current bundle and only swap if better.
- Qualcomm's own published numbers show `w4` costing the base model very little vs `w4a16`.

## 5. Step B — real AIMET recalibration on our own data  *(the proper fix; needed if weights are the cause)*

Run Qualcomm's actual quantisation on the **fine-tuned** checkpoint, which recomputes **both** weight and
activation encodings:

```
python -m qai_hub_models.models.llama_v3_2_3b_instruct.quantize \
    --checkpoint <merged> --precision <calibration-only recipe>.yaml \
    --context-length 2048 -o <out>
```

Two things make this feasible and worth it:
- The default recipe's **SeqMSE/AdaScale steps are the only CUDA-gated ones**. A *calibration-only* recipe
  (min-max + percentile over N batches) runs on CPU. Recipe YAML is in `QUANT_RESEARCH.md`.
- **Calibration data matters more than anything here.** The default is wikitext; our prompts are rigid
  JSON-schema sensor prompts that look nothing like prose. Calibrating on ~110 of our real agent
  prompt/response pairs (~80 k tokens, matching Qualcomm's volume) targets the ranges at our actual
  distribution. There is no CLI flag for this; it is a small monkeypatch of the dataset loader.
- Where: **Kaggle** (30 GB RAM, free) is the safe host; the laptop has 9 GB + 64 GB swap and would thrash.
  Estimated 2-4.5 h, plus an export cycle.

## 6. Ruled out (do not spend time)

| option | why not |
|---|---|
| Runtime LoRA on Genie (keep base weights, apply adapter on device) | the base context binaries must be compiled LoRA-aware; not exposed by AI Hub or `qai-hub-models` 0.63.0 |
| `w8a16` (8-bit weights) | not in this model's `SUPPORTED_PRECISIONS` |
| SeqMSE / SpinQuant | ~40 GB VRAM |
| SmoothQuant offline | cannot reach the int8 KV/RoPE tensors that are the prime suspects, and would invalidate the reused encodings |

## 7. Free wins to fold in regardless (no export needed)

- **Context length 2048 instead of 4096** at export: our prompts are 550-1,600 tokens. Smaller KV cache →
  less memory and measurably faster decode.
- **Prompt hardening**: put the output schema last, immediately before the answer.
- **Keep** greedy decoding, early-stop, the exact-prompt cache and the policy repairs already shipped.

## 8. Proposed order, with the clock

| when | what | hours |
|---|---|---|
| now | finish v2 (w4a16 + MSE-optimal scales), validate on device, 46 ex | 0.5 (already running) |
| then | **Step 0 diagnostic** on host | 1.0 |
| then | **Step A**: `w4` export + MSE-optimal scales + ctx 2048 → validate | 1.5 |
| parallel | **Step B** on Kaggle if Step 0 says weights, or if A under-delivers | 3-5 |
| finally | pick the best bundle on device evidence, re-run latency + scenarios | 1.0 |

Total 4-8 h of the ~24 available. The app keeps a validated working bundle at every moment; a new one is
only swapped in after it beats the incumbent on the 46-example device eval.

## 9. Honest expectation

I cannot promise 94 % on device. Per-channel int4 is structurally coarser than the host's NF4, so some gap
may be irreducible without a precision change that this model's toolchain does not offer. Realistic
outcome: **75-90 %**, with Step A the cheapest large win and Step B the best shot at the top of that range.
If both land and we are still short, the honest framing for the eval is the measured
host-vs-device quantisation cost, which is a real and interesting finding, backed by the error table in
`HANDBOOK.md` §2.7.
