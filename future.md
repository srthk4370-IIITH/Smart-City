# future.md — where this system goes next

A decision document, not a survey. It answers three questions the owner asked: (1) can we have a
separate cross-domain reasoner on this board, (2) what features does that unlock, (3) what
non-LLM ML actually belongs here. Everything is written for someone who already knows
`app/backend/`, `genied`, the Genie bundle layout and HANDBOOK §2.11–2.16.

Two labels are used throughout and they mean different things:

* **[VERIFIED]** — read directly out of the QAIRT 2.50.0.260828 SDK on this machine
  (`~/qairt/qairt/2.50.0.260828`, readable from WSL), out of this repo, or off a live vendor page
  fetched on 2026-10-14.
* **[UNVERIFIED]** — plausible, sourced where possible, but not confirmed on this device or in
  this SDK. Treat every number in an [UNVERIFIED] row as an estimate.

---

## Recommended path

**Do not ship a second base model. Ship one base model with several LoRA adapters in a single
LoRA-v3 context binary, and switch between them with the alpha vector ("Hot Switch").**

The cross-domain reasoner then becomes a *trained* adapter — genuinely different weights, its own
persona, its own output contract — not a second 2.9 GB bundle and not just another system prompt.
The same mechanism gives a `chat` adapter for the conversational interface the owner actually
wants, and a `forecast` adapter later, at no extra resident cost beyond the adapter weights.

### Why this and not a second model

1. **The second-bundle failure already has a root cause, and it is not fixable by configuration.**
   HANDBOOK §2.12 traced "could not create context from binary / err 1002" to the CDSP SMMU
   refusing a 112 MB `fastrpc_mmap` on `compute_cb2` with `-22 EINVAL` — DSP *address-space*
   exhaustion for the fastrpc session, not host RAM. The margin was 6.4 MB on a ~1.12 GB part.
   Holding two ~3 GB models mapped at once sits on the wrong side of that margin by a wide margin.
   Every runtime knob tested (`spill-fill-bufsize`, `mmap-budget`, `use-mmap`, `context.size`,
   `allow-async-init`) left `Allocated total size = 270369280 across 5 buffers` unchanged.
2. **Genie supports LoRA on HTP, in this SDK version, for exactly this model.** `GenieDialog.h`
   exposes `GenieDialog_applyLora`, `GenieDialog_setLoraStrength`, `GenieDialog_releaseLoraMemory`
   and `GENIE_DIALOG_PARAM_APPLIED_LORA_ADAPTER`. The LoRA-v3 tutorial's worked example *is*
   Llama-3.2-3B with adapters named `elementary`, `long`, `function`. [VERIFIED]
3. **Hot Switch makes the swap free.** In the Hot Switch variant all adapters are compiled into one
   concurrency and loaded permanently; "switching" is done by changing the alpha vector at execute
   time, with no binary-section apply and no reload. The SDK's own KPI table lists adapter-switch
   time as "N/A" because there is no switch. Cost is RAM (all adapters resident). [VERIFIED]
4. **It is the only path that also solves the conversational interface.** A chat persona needs
   different behaviour from a JSON-emitting domain agent — different stop behaviour, different
   verbosity, different refusal style. Prompting one JSON-tuned 3B into both roles is where 3B
   models fall over. An adapter is the right size of lever.

### What it costs — honestly

The expensive part is not runtime, it is **export**. Today the bundle is produced by
`qai-hub-models export ... --target-runtime genie`, which compiles in Qualcomm's cloud. **AI Hub
does not offer a LoRA-enabled export** — `training/EXPORT_RESEARCH.md` already concluded this
("LoRA adapters on Genie/QNN-HTP: not available through AI Hub or qai-hub-models. Ruled out.")
and nothing found since contradicts it. LoRA-v3 must be built with the local x86 toolchain that
ships in the SDK:

```
qairt-lora-mapper  →  qairt-lora-model-creator  →  qairt-converter
                   →  qairt-quantizer  →  qairt-lora-importer
                   →  qnn-context-binary-generator --adapter_weight_config <yaml>
```

All six binaries are present at `~/qairt/qairt/2.50.0.260828/bin/x86_64-linux-clang/`. [VERIFIED]

That means doing locally what was deliberately offloaded to AI Hub: converting and quantizing a
~14 GB fp32 ONNX graph **per concurrency**, on a WSL box with ~9 GB RAM and 48 GB swap. Realistic
estimate: **2–4 weeks of engineering, with a real chance of failure on quantization quality or on
graph-count/SMMU limits**, and Kaggle or a rented box needed for the heavy steps. [UNVERIFIED]

### The decision rule

Spend **one week** on a feasibility spike before committing (details in the roadmap). If the spike
cannot get a two-adapter Llama-3.2-3B LoRA-v3 binary to load on the board, fall back to
**Option B: a small second model in its own process, loaded lazily for chat only** (§A, §B).
Do not fall back to two large models; that is already known to fail.

---

## A. Candidate models for an on-device cross-domain reasoner

### A.0 The one fact that matters most

**Qualcomm AI Hub does not publish ready Genie bundles for Snapdragon 8 Gen 3 any more.** Checked
on 2026-10-14: every precompiled `GENIE` / `GENIEX_QAIRT` w4a16 row on the Qualcomm model cards
targets 8 Elite, 8 Elite Gen 5, X Elite, X2 Elite, SA87xx or Dragonwing IQ parts. 8 Gen 3 appears
in none of them.
([Qwen3-1.7B](https://huggingface.co/qualcomm/Qwen3-1.7B),
[Llama-v3.2-3B-Instruct](https://huggingface.co/qualcomm/Llama-v3.2-3B-Instruct)) [VERIFIED]

`training/EXPORT_RESEARCH.md` found the same thing in the library: 8 Gen 3 is gone from
`supported_chipsets` and `release-assets.yaml` in qai-hub-models v0.63, but
`devices_and_chipsets.yaml` still maps `Samsung Galaxy S24 → qualcomm-snapdragon-8gen3` and
nothing enforces the list. **This project's own bundle is proof that the compile still works** —
so "export it yourself" is a real option, just not a cheap one (~14 GB upload, 2–3 h compile).

Both vendor pages also carry: *"Genie support will be deprecated soon."* Qualcomm's replacement is
**GenieX** (`https://github.com/qualcomm/geniex`), which offers a QAIRT NPU backend and a
llama.cpp backend. This is a migration risk worth a line in the risk register, not an emergency.
[VERIFIED]

### A.1 The candidates

Sizes below use the method HANDBOOK §2.15 established, because it is the only one that predicts
latency on this board. Decode is memory-bandwidth-bound at ~49 GB/s measured, so
**tok/s ≈ 49 GB/s ÷ (layer weights at 4 bits + `lm_head` at 16 bits)**. The embedding table does
*not* count: it is a `Gather` of one 6 KB row per token. Note how badly a large vocabulary hurts a
small model — `lm_head` is kept at 16 bits in the w4a16 recipe, so a 151k–262k vocab can cost more
per token than all the transformer layers.

| Model | Params | Vocab | Est. bytes/decode token | Est. tok/s on 8 Gen 3 | Ready SM8650 Genie bundle? | Licence |
|---|---|---|---|---|---|---|
| **Llama 3.2 3B Instruct** (current) | 3.2B | 128k | **2.20 GB** (measured) | **22.4** (measured) | We built one. Not published. | Llama 3.2 Community |
| Llama 3.2 1B Instruct | 1.2B | 128k | ~1.1 GB (0.6 layers + 0.53 `lm_head`) | ~45 | No | Llama 3.2 Community |
| Qwen3-0.6B | 0.6B | 151k | ~0.6 GB (0.3 + 0.31) | ~80 | No (GenieX llama.cpp q4_0 "Universal" only) | Apache-2.0 |
| Qwen3-1.7B | 1.7B | 151k | ~1.3 GB (0.85 + 0.47) | ~38 | No | Apache-2.0 |
| Qwen3-4B / 4B-Instruct-2507 | 4B | 151k | ~2.6 GB | ~19 | No (8 Elite / X2 only) | Apache-2.0 |
| **Qwen3.5-0.8B** | 0.8B | ~151k | ~0.7 GB | ~70 | No | Apache-2.0 |
| **Qwen3.5-2B** | 2B | ~151k | ~1.6 GB | ~30 | No | Apache-2.0 |
| Qwen3.5-4B | 4B | ~151k | ~2.6 GB | ~19 | No | Apache-2.0 |
| Gemma 4 E2B-it | ~2.3B eff. (5.1B w/ emb) | 262k | ~1.1 GB text-only mobile build reported | ~40 | No; QAT GGUF + "wNa8o8" LiteRT-LM mobile build exist | Apache-2.0 |
| Gemma 4 E4B-it | ~4.5B eff. | 262k | ~2.5 GB mobile build reported | ~20 | No; listed on AI Hub catalogue, runtime unclear | Apache-2.0 |
| Phi-4-mini-instruct | 3.8B | 200k | ~2.7 GB | ~18 | No; GGUF via GenieX llama.cpp | MIT |
| Phi-4-mini-reasoning | 3.8B | 200k | ~2.7 GB, **plus** long CoT output | ~18, effectively much worse | No | MIT |
| SmolLM3-3B | 3B | 128k | ~2.1 GB | ~23 | No | Apache-2.0 |
| DeepSeek-R1 distills (1.5B/7B Qwen) | 1.5B+ | 151k | ~1.2 GB+ | ~40 | No | MIT (distill weights) |

Sources for the 2026 entries: Qwen3.5 Small (0.8B / 2B / 4B / 9B, Apache-2.0, released 1–2 Mar
2026, native multimodal, 262k context) —
[Qwen announcement](https://x.com/Alibaba_Qwen/status/2028460046510965160),
[MarkTechPost](https://www.marktechpost.com/2026/03/02/alibaba-just-released-qwen-3-5-small-models-a-family-of-0-8b-to-9b-parameters-built-for-on-device-applications/).
Gemma 4 (E2B/E4B/26B-MoE/31B, Apache-2.0, released 2 Apr 2026; QAT checkpoints Jun 2026; mobile
builds ~1.1 GB E2B / ~2.5 GB E4B in a `wNa8o8` format aimed at LiteRT-LM, not llama.cpp) —
[google/gemma-4-E2B-it-qat-mobile-transformers](https://huggingface.co/google/gemma-4-E2B-it-qat-mobile-transformers),
[Gemma (Wikipedia)](https://en.wikipedia.org/wiki/Gemma_(language_model)).
The AI Hub generative-AI catalogue filtered to 8 Gen 3 currently lists Gemma-4-E4B-it,
Intern3.5-VL-2B/4B, Qwen2.5-VL-7B, Qwen3-0.6B/1.7B/4B/4B-Instruct-2507/8B, Qwen3-VL-4B/8B and
SmolLM2-1.7B-Instruct as *models*, but the cards do not promise a Genie bundle for that chipset.
[VERIFIED by fetch, 2026-10-14]

### A.2 Reading of the table

| Option | What it gives | Cost | Risk | Available today? |
|---|---|---|---|---|
| **LoRA adapter on the existing 3B** (recommended) | A real second persona, 0 ms swap under Hot Switch, 22 tok/s | Local LoRA-v3 export chain; 2–4 weeks | Quantization quality; SMMU limits on the bigger graph | Toolchain yes, our bundle no |
| **Qwen3.5-0.8B as a second process** | ~70 tok/s chat model; small enough that co-residency is plausible | Own export (~1–2 weeks), own tokenizer, own prompt work | Co-residency unproven; 0.8B reasoning is weak for cross-domain synthesis | No bundle; export yourself |
| **Qwen3.5-2B / Qwen3-1.7B as a second process** | ~30–38 tok/s, genuinely better reasoning than 0.8B | Export + ~1.3–1.6 GB of extra DSP mappings | Co-residency materially less likely | No bundle; export yourself |
| **Phi-4-mini-reasoning** | Best math/CoT of the small reasoners | No speed gain over the 3B; long CoT output makes it *slower* end-to-end; MIT licence is nice | Verbose reasoning fights the strict-JSON contract and the policy gate | No bundle |
| **Gemma 4 E2B** | Apache-2.0, QAT weights, strong for its size | 262k vocab makes `lm_head` expensive; mobile format targets LiteRT-LM, not Genie | Format mismatch is the whole problem | No Genie bundle |
| **Stay on one model, second *prompt* only** | Zero work | No new capability; 3B struggles to be both a JSON agent and a chat partner | Low | Yes, today |

**Plain statement: none of these is available as a ready SM8650 Genie bundle today.** Any
second-model plan starts with an export, so the marginal cost of instead doing a LoRA export is
smaller than it looks — and the LoRA route avoids a second resident context entirely.

**On reasoning quality for this task specifically.** The job is not maths. It is: read 4–8
structured evidence blocks, find the one cross-domain story that explains them, emit strict JSON
citing evidence ids. That is a *structure-following* task, and the current fine-tune already hits
0.852 pattern / 0.87 status / 0.815 cause with 1.0 JSON validity. A generic 2B model will not beat
a task-tuned 3B on this. The argument for a second model is **conversational latency and
behaviour**, not synthesis accuracy. Be clear about that when deciding.

---

## B. Two models on one NPU — what QAIRT 2.50 actually supports

### B.1 Verified in the SDK on this machine

| Mechanism | Where | What it actually does | Does it solve our problem? |
|---|---|---|---|
| `GenieDialog_applyLora(dialog, engineRole, name)` | `include/Genie/GenieDialog.h:481` | Applies a named LoRA adapter to a live dialog. Docs: "When switching LoRA adapters, it is recommended to call `GenieDialog_reset`." | **Yes** — this is the swap primitive |
| `GenieDialog_setLoraStrength(dialog, engineRole, tensorName, alpha)` | `GenieDialog.h:505` | Sets an alpha value on the base graph's alpha tensor | **Yes** — this is Hot Switch |
| `GenieDialog_releaseLoraMemory(dialog, engineRole, name)` | `GenieDialog.h:530` | Frees an adapter's memory; re-applying later re-pays the load | Useful for RAM pressure |
| `GenieNode_saveLora` / `applyLora` / `setLoraStrength` | `include/Genie/GenieNode.h:389–494` | Same, on the Pipeline/Node API | Alternative API surface |
| `GENIE_DIALOG_PARAM_APPLIED_LORA_ADAPTER` | `GenieDialog.h:94` | `GenieDialog_getValue` reports which adapter is live | Needed for a safe runtime |
| **`shared-engine: true`** (dialog + standalone-engine JSON) | `docs/.../Genie/general/library/dialog/json.html` | "This feature allows an engine to be shared across multiple dialogs which might be of different dialog types and have different features like LoRA Config **for the same context binaries**." Each dialog keeps its own KV Manager, IO Buffer and LoRA Config. Requires `allow-async-init: true`. Supported dialogs: Eaglet, SSD, Basic. Backend: QnnHtp. | **Partly** — it makes N personas cheap *on one model*; it does **not** let two different models share anything |
| `engine::role` + `--allow_engine_switch` | dialog JSON; `genie-t2t-run` | Multiple engines with roles (`target`, `draft`) in one dialog — this is the speculative-decoding path, not a general two-model path | No |
| `QNN_HTP_CONTEXT_CONFIG_OPTION_WEIGHT_SHARING_ENABLED` (=1) | `QnnHtpContext.h` | Weight sharing across contexts. Already active in our bundle: `graphBlobInfoV2` reports identical `sharedWeightsSize` for ar128 and ar1 (HANDBOOK §2.15) | Already on; shares weights of the *same* model |
| `QNN_HTP_CONTEXT_CONFIG_OPTION_LORA_WEIGHT_SHARING_ENABLED` (=13) | `QnnHtpContext.h` | "one additional replaceable weight blob" | Supports the LoRA path |
| `QNN_HTP_CONTEXT_CONFIG_OPTION_LORA_WEIGHT_SHARING_RAM_PRELOAD_ENABLED` (=16) | `QnnHtpContext.h` | Preloads adapter weights into RAM so a switch does not hit storage | Directly reduces swap latency |
| `QNN_HTP_CONTEXT_CONFIG_OPTION_REFERENCE_WEIGHT_SHARING_ENABLED` (=18) | `QnnHtpContext.h` | Weight sharing between context binaries targeting **different SoCs**; warns total RAM may increase if sharing is not optimal | Not our case |
| `spill-fill-bufsize` | dialog JSON | "Should be set greater than the spill-fill required by **each** context binary in the model." Qualcomm's own long-context llama3-3b example uses `320000000`. Ours is `0`. | Relevant if a multi-context group is attempted |
| `max_spill_fill_buffer` / `max_spill_fill_buffer_for_group` / `group_id` | QNN docs (3 hits for `group_id`) | Context-binary groups sharing one spill-fill buffer | Reduces VTCM spill duplication across contexts; **does not** reduce the fastrpc mappings that actually failed |
| `direct-io` (new in 2.50) | dialog JSON | Loads context-binary weights straight into DMA buffers via `/dev/udmabuf`, skipping a host copy. Needs `/dev/udmabuf` and a large enough `size_limit_mb`. | Could cut model init; worth a test independent of all this |
| `GenieDialog_save` / `GenieDialog_restore` | `GenieDialog.h:434,449` | Persist and restore full dialog state to a path | **Conversation persistence, for free** |

### B.2 LoRA-v3: the four variants, and which one to pick

From `docs/QAIRT-Docs/QNN/general/tutorial/lora_v3_overview.html` and
`lora_v3_optimizations.html`. [VERIFIED]

| Variant | Switch cost | RAM | Accuracy | Use for |
|---|---|---|---|---|
| Regular LoRA v3 | Apply a binary section per switch (weights **and** encodings) | Baseline | Best — each adapter keeps its own quantization | Adapters whose weight distributions differ a lot |
| `--quant_updatable_mode none` (No-Updateable) | Cheaper (weights only) | Better | Worse if adapters cannot share encodings | Adapters that are close to each other |
| **Grouped LoRA** | Free *within* a group; group change applies an encodings-only section first | Better | Good | Several adapter families |
| **Hot Switch** | **None** — change the alpha vector at execute time | **Increased** (all adapters always loaded) | Same, *if* quantization params match across adapters | **Our case: 3–5 small personas** |

Hot Switch requires the adapters to be concatenated into a single concurrency in PEFT before the
QAIRT tools see them, and the docs recommend pairing it with `--quant_updatable_mode none`.
Genie-side it is just `GenieDialog_setLoraStrength(dlg, role, "alpha-domain", 1.0)` +
`setLoraStrength(..., "alpha-chat", 0.0)` + `GenieDialog_reset`.

The Genie config shape is already documented for Llama-3.2-3B:

```json
"lora": {
  "version": 1,
  "alpha-tensor-name": "lora_alpha",
  "adapters": [
    { "version": 1, "name": "ar128_cl2048_2_of_3_domain",     "alphas": ["alpha-domain"],
      "bin-sections": ["ar128_cl2048_2_of_3_domain.bin"] },
    { "version": 1, "name": "ar128_cl2048_2_of_3_synth",      "alphas": ["alpha-synth"],
      "bin-sections": ["ar128_cl2048_2_of_3_synth.bin"] }
  ],
  "groups": [ { "version": 1, "name": "groupA", "members": ["...","..."],
                "quant-bin-sections": ["..._encodings.bin", ""] } ]
}
```

Also present: `"skip-lora-validation": true` on the QnnHtp block, which skips CRC validation when
binary sections are applied — expect to need it while iterating, and to turn it off for a release.

### B.3 Memory headroom on this board, concretely

The constraint is **not** the 12/16 GB of LPDDR. It is the CDSP SMMU context bank for the fastrpc
session, measured in HANDBOOK §2.12:

```
fastrpc_mmap failed to map buffer fd 76, addr 0x6d48bae000, length 0x6ffd980,
    domain 3, flags 0x3, ioctl ret 0xffffffff, errno Bad address
fastrpc_internal_mem_map: failed to map fd 76, len 0x6ffd980, flags 3, map 0, err -14
```

A 112 MB mapping was refused while the live 3-model-part bundle was already mapped. Live `part3` is
1,122,754,560 bytes and loads; 1,129,140,224 bytes does not. **Treat any plan that adds more than a
few hundred MB of mapped DSP memory to the same process as unproven until measured.**

What is *not* yet known and should be measured in the spike:

* Does a **separate process** with its own fastrpc session get its own SMMU context bank? If yes,
  a small second model in its own `genied2` may co-reside where a single fatter bundle cannot.
  This is the cheapest high-value experiment in this whole document. [UNVERIFIED]
* Does `enable-graph-switching: true` (the §2.12 fix) also relieve the mapping pressure of a
  LoRA-v3 binary's extra concurrency graphs? Probably yes by the same mechanism — graphs are
  instantiated lazily rather than all at load. [UNVERIFIED]

### B.4 Ruled out for the two-model problem

| Idea | Why not |
|---|---|
| Two full ~2.9 GB bundles alternating | Already failed in practice; root-caused to DSP address space, and no runtime knob moved the allocation (§2.12) |
| `shared-engine` across two different models | The docs say "for the same context binaries". It shares an engine, not weights across models |
| `REFERENCE_WEIGHT_SHARING` | For sharing across SoCs, and warns RAM may go *up* |
| AI Hub LoRA export | Not offered. Confirmed in `training/EXPORT_RESEARCH.md` and nothing since contradicts it |
| Keeping both bundles on disk and reloading per call | ~700 ms init was already 18% of a call with the model *cached*; a cold 2.9 GB swap is seconds. This is the thing the owner wants to avoid |

---

## C. A conversational interface on this device

### C.1 What the SDK already gives you [VERIFIED]

| Need | Mechanism | Status |
|---|---|---|
| Keep the model loaded between turns | `genied` already holds one `GenieDialog` alive over a loopback socket | **Built** |
| Streaming tokens | `GenieDialog_query` callback with `SENTENCE_BEGIN/CONTINUE/END`; `genied` already frames these | **Built** |
| Interrupt / abort | `GenieDialog_signal(dlg, GENIE_DIALOG_ACTION_ABORT)`; `genied` sends `0xFF` to trigger it | **Built** |
| **Pause / resume** | `GENIE_DIALOG_ACTION_PAUSE` → query returns `GENIE_STATUS_WARNING_PAUSED`; resume with `GenieDialog_query(dlg, NULL, GENIE_DIALOG_SENTENCE_RESUME, ...)`. Callback fires `SENTENCE_RESUME` at the boundary | **New in this SDK, unused.** Lets an incident pre-empt a chat turn and resume it afterwards |
| **System-prompt / prefix caching** | `GENIE_DIALOG_SENTENCE_REWIND` (sentence code 5). "Genie can reuse the KV cache values from a previous query to speed up the processing of a new, similar query... particularly useful where the new query shares a common prefix." CLI: `genie-t2t-run -w "<new query>"` | **The single biggest conversational win available.** Our prompts share a long fixed preamble |
| Multi-turn state persistence | `GenieDialog_save(dlg, path)` / `GenieDialog_restore(dlg, path)` | Unused; gives chat history across app restarts |
| Stop sequences at runtime | `GenieDialog_setStopSequence` | Unused; would replace part of the `answerscan`/`trimscan` logic |
| Priority between dialogs | `GenieDialog_setPriority`, `setPerformancePolicy` | Unused; lets incidents outrank chat |
| On-device embeddings for grounding | `GenieEmbedding.h` + a bge-large tutorial for HTP | Available; a retrieval index over campus docs is feasible |

**Caveat on REWIND, from the docs:** "KV$ prefix match works well with the KV update method
`SMART_MASK`. With `POINTER_SHIFT` we observed that in a few cases it throws memory
register-related errors for weight-shared bins." Our bundle *is* weight-shared. Check and pin the
KV update method before relying on rewind.

### C.2 What works at 3B scale and what does not

| Capability | Verdict at 3B | Note |
|---|---|---|
| Strict JSON emission | **Works** — 1.0 validity on 54 held-out windows, after fine-tuning | This is the existing proof |
| Answering from a grounded context block | **Works**, if the numbers are in the prompt | Always inject the sensor rows; never ask the model to recall them |
| Answering from model memory about the campus | **Does not work.** Will hallucinate building names, thresholds and history | Make this architecturally impossible, not a prompt instruction |
| Arithmetic over many rows ("average PM2.5 last week") | **Does not work reliably** | Compute in Go, hand the model the answer to phrase |
| Multi-turn coherence over ~10 turns | Works with full history in context; our ctx is 2048/4096 so history must be truncated | Summarise older turns into one line |
| Tool / function calling | **Marginal.** A 3B will emit a tool call in the right shape if fine-tuned for it, but will choose the wrong tool and invent arguments under distribution shift | Do **not** build an open tool-calling loop |
| Open-ended chat with no schema | Poor without a chat adapter | This is the argument for the `chat` LoRA |

### C.3 The design that will actually work

Make the conversational interface a **constrained query planner, not an agent**:

1. The model's only job is to map a question onto **one of ~12 fixed query templates** plus
   arguments (sensor id, domain, time range, aggregation). Emit that as JSON — the same contract
   the system already validates well.
2. Go executes the query against the sensor store. Deterministic, exact, auditable.
3. A second, short LLM call turns the returned rows into a sentence, with the rows in the prompt
   and an explicit "if the rows do not answer the question, say so".
4. The policy gate validates step 1's JSON against the template enum exactly as it validates agent
   output today. Reuse `policy.go` wholesale.

With prefix caching on the fixed preamble, step 1 should be a short prefill plus ~30 tokens of
decode. At 22 tok/s that is **~1.5–2 s to first useful response**; step 3 adds ~2 s.
[UNVERIFIED — estimate from §2.15's measured rates]

Latency levers that are already known-good or known-dead, from HANDBOOK:

* `genied` resident dialog: removes ~700 ms init per call. **Known-good, built.**
* Batched `genie-app`: ~630 ms saved per extra agent in an incident. **Measured, not wired in.**
* Grammar-constrained decoding: **+440 ms init, 0 tokens saved. Rejected** (§2.16). Keep it in mind
  only as a *correctness* guarantee, never as a latency play.
* LADE lookahead: −24% decode on one prompt, but only 4/13 identical outputs on different prompts.
  **Rejected as unsafe** (§2.14 region).
* `direct-io` + `/dev/udmabuf`: untested, new in 2.50, targets exactly the init cost. **Test it.**

---

## D. ML beyond LLMs

The system already has strong deterministic statistics: SMA, EMA, trend, curvature, oscillation,
flat-run over a 4 h / 5 min window, exposed as E1..E8, plus a multivariate denoising autoencoder in
`src/smart_city_edge/anomaly_model.py` (16→64→16→64→16, ONNX-exportable) with training scripts
(`train_anomaly.py`, `train_domain_anomaly.py`). So the bar for "adds capability" is high. Each
row below says what the existing statistics *cannot* do.

| Method | What it adds that neither the rules nor the LLM can do | Compute | CPU or NPU? | Verdict |
|---|---|---|---|---|
| **Causal discovery across domains (PCMCI+ / tigramite, lagged Granger as a baseline)** | A *learned, data-backed* lagged dependency graph: "occupancy→co2 at lag 2, ac_units_on→power at lag 0, power→room_temp at lag 4". Today the synthesizer guesses cross-domain links from a prompt. This replaces guessing with evidence ids. | Offline nightly over weeks of history; 18 vars × ~20 lags is seconds to low minutes on CPU | **CPU, offline** | **Build this first.** Highest value per unit of effort; directly serves "cross-domain reasoning" |
| **Change-point detection (PELT / BOCPD, `ruptures`)** | *When* a regime changed, with a confidence. Trend/curvature tell you the slope now; they do not localise a break or survive a step change cleanly | O(n log n) on a 4 h window; microseconds | **CPU, online** | **Build.** Cheap, becomes a new evidence id (E9) |
| **Drift / stuck-sensor detection (CUSUM, Page-Hinkley)** | Slow calibration drift, which is invisible to a 4 h window by construction | Trivial, incremental | **CPU, online** | **Build.** Directly feeds maintenance scheduling |
| **Cross-sensor residual / virtual sensors** | Predict `room_temp` from `ac_units_on` + `weather.temp` + `occ`; a large residual means *one of these sensors is wrong*, and the prediction is a replacement value. Single-sensor stats can never detect this | Ridge or a 3-layer MLP per target; microseconds | **CPU** | **Build.** Best sensor-fault detector available here, and it is tiny |
| **Matrix profile (STUMPY)** | Motifs and discords over *weeks*: "this exact pattern happened 4 times before, always on Mondays". Gives the LLM precedent, which it currently has none of | O(n log n); a month of 5-min data per sensor is ~9k points — milliseconds | **CPU, offline/nightly** | **Build after causal discovery.** Great UI story ("seen 4 times before") |
| **Isolation Forest / robust Mahalanobis** | A calibrated, explainable joint-anomaly score with per-feature attribution, as a sanity check on the autoencoder | Trivial | **CPU** | **Optional.** Mainly a validator for the AE you already have |
| **Autoencoder (have it) / USAD / TranAD** | TranAD and USAD add adversarial/attention training for multivariate anomalies. Real papers, real gains on benchmarks — but on 18 sensors with physics-constrained relationships the residual models above will beat them | AE: negligible. TranAD: training is non-trivial, inference still small | **CPU** | **Skip TranAD/USAD.** Not enough data diversity here to pay off |
| **Classical forecasting (seasonal-naive, Holt-Winters, STL)** | Predictive alerts instead of reactive ones. A campus has hard daily and weekly seasonality; seasonal-naive is a brutally strong baseline | Microseconds | **CPU** | **Build this before any foundation model.** Measure it. It may be all you need |
| **N-BEATS / TiDE / PatchTST (trained per-site)** | Better multi-horizon accuracy than Holt-Winters when there is enough history | Training offline; inference ~1 ms | **CPU** | Only if the seasonal baseline is measurably insufficient |
| **TS foundation models (TiRex, Chronos-2, TimesFM-2.5)** | Zero-shot forecasting with no per-sensor training, plus probabilistic intervals | Vendor-run edge-CPU benchmark on an i7-6600U, 2048-step context, 32-step horizon: **TiRex 0.093 s/forecast, Chronos-2 0.309 s, TimesFM-2.5 2.35 s, PatchTST-FM 13.76 s** ([NX-AI / HF blog](https://huggingface.co/blog/BobWue/edge)) | **CPU only.** No Genie/QNN export path exists for any of them | **Not yet.** Revisit when a baseline proves insufficient. Note the benchmark is vendor-produced |
| **Running any TSFM on the Hexagon NPU** | — | Would need its own ONNX→QNN conversion, fixed shapes, and would contend with the LLM for the same DSP address space that already failed | — | **Ruled out for now** |

### D.1 The one that matters most, in more detail

**Cross-domain causal discovery is the thing that makes the "cross-domain reasoner" real.**

Right now Mode 3's synthesizer is an LLM asked to find relationships between domains with nothing
but the current window to go on. A nightly PCMCI+ run over months of history produces a stable,
testable graph of lagged dependencies. Feed the *relevant edges* into the synthesizer prompt as new
evidence ids and the model stops inventing links and starts citing them — which the policy gate can
then validate, exactly as it validates E1..E8 today. That is a measurable accuracy and
explainability win with no NPU cost.

Practical notes: `tigramite` is the reference implementation of PCMCI/PCMCI+ (Runge et al., *Nature
Communications* 2019). F-PCMCI (Castri et al., CLeaR 2023,
[paper](https://proceedings.mlr.press/v213/castri23a.html)) adds transfer-entropy feature selection
for speed but pulls in Java + IDTxl, which is a poor fit for an edge box — run plain PCMCI+ on the
board or, better, run it on a laptop nightly and ship the resulting graph as a JSON artifact the
device reads. Keep lagged Granger as a cheap always-on cross-check: when the two disagree, do not
show the edge.

---

## E. Future features

| Feature | What it gives | Depends on | Cost | Risk | Ready today? |
|---|---|---|---|---|---|
| **Conversational campus query** | "Why did B3 CO2 spike yesterday?" answered from the store | §C design + a `chat` adapter (or a small second model) | Medium | Hallucination if not template-constrained | Partly — `genied` + REWIND exist |
| **Forecast / predictive alerts** | Gate fires on a *predicted* threshold crossing, not an actual one | §D seasonal baseline + a confidence band | Low | False alarms; needs a separate, stricter gate than the reactive one | Buildable in days |
| **Cross-building correlation** | "Three buildings share this pattern → it's the chiller loop, not the room" | A building/topology model (`topology.py` exists) + the causal graph | Medium | Needs more than one building's data | Partly |
| **Energy optimisation recommendations** | "Setting 24 °C instead of 22 °C in B3 saves ~X kWh" | A regression of `power_kw` on `ac_units_on`, `room_temp`, `occ`, `weather.temp`; **not** the LLM | Medium | Counterfactual claims the system cannot validate — must be labelled as estimates and gated by a human | No |
| **Maintenance scheduling** | A ranked work queue from drift/stuck/residual detectors | §D drift + residual models | Low | Low | Buildable in weeks |
| **Operator feedback → DPO** (see below) | The model gets better at *this campus* from work operators already do | The approve/dismiss records the system already keeps | Medium | Needs volume; needs a re-export | **Data collection can start this week** |
| **Federated / multi-device** | Several boards, one campus view; adapters trained on pooled experience | A sync protocol; the app already runs a local HTTP API | High | Security; the app already uses an unauthenticated local adbd (see memory note) — do not extend that pattern over a network | No |
| **Offline-first / edge-cloud split** | Board stays authoritative; cloud only for training and long history | Clean separation of "decide" (edge) and "learn" (cloud) | Medium | Scope creep | Design it now, build later |

### E.1 Operator feedback → preference data. Do this.

This is the strongest fit in the whole document and it costs almost nothing to start.

`app/backend/server.go:309–316` already handles `approve` and `dismiss`, and **`dismiss` requires a
note** (`http.Error(w, "dismiss needs a note", 400)`). `reason.go:114` stores
`Approval string // pending | approved | dismissed`. That is, verbatim, a preference-pair
generator: every dismissal is a *rejected* completion with a human-written reason attached, and
every approval is a *chosen* one.

Concrete plan:

1. **This week, change nothing but the logging.** Persist, alongside each incident: the exact
   prompt, the raw model output *before* policy repair, the repaired output, the approval verdict,
   the note, and the operator id. Without the raw pre-repair output you cannot build pairs later.
2. When a dismissal has a note that implies a correction ("this is a sensor fault, not a real
   spike"), capture the corrected label through the UI rather than only as free text. One extra
   dropdown turns a vague note into a training example.
3. At ~300–500 pairs, run DPO on the existing QLoRA adapter (same Kaggle setup already used for
   training). DPO is well suited here because the pairs are naturally same-prompt,
   different-output.
4. Re-export. If the LoRA-v3 path from §B is working by then, this becomes "ship a new adapter
   file", not "rebuild a 3 GB bundle" — which is a second, large argument for §B.
5. Cheaper intermediate that needs no retraining: mine dismissal notes for **new policy-gate
   rules**. If operators keep dismissing "critical" on `tds` during the 06:00 flush, that is a rule,
   not a model problem.

Watch for the obvious failure: operators approving everything to clear the queue. Track the
approve rate per operator and treat a rate above ~95% as unusable signal.

---

## Ruled out, and why

| Ruled out | Reason | Evidence |
|---|---|---|
| Two full LLM bundles resident or alternating | CDSP SMMU / fastrpc address-space exhaustion, 6.4 MB from the cliff; no runtime knob changed the allocation | HANDBOOK §2.11, §2.12 [VERIFIED on device] |
| `shared-engine` as a two-model solution | It shares an engine across dialogs "for the same context binaries" | Genie engine-sharing doc [VERIFIED in SDK] |
| Grammar-constrained decoding for latency | +440 ms init, 0 tokens saved; jump-forward needs a draft engine (`eaglet`/`spd`), not `dialog.type: basic` | HANDBOOK §2.16 [VERIFIED on device] |
| LADE lookahead decoding | −24% decode on one prompt but only 4/13 byte-identical on others | HANDBOOK §2.14 region [VERIFIED on device] |
| Tuning decode further | 49.3 GB/s measured against a ~59 GB/s NPU DMA ceiling — 84% of the roof. `llm_decode_*` perf profiles are V79+, rejected on V75 | HANDBOOK §2.15 [VERIFIED on device] |
| AI Hub as the LoRA export path | Not offered | `training/EXPORT_RESEARCH.md` [VERIFIED] |
| Expecting a ready SM8650 bundle for any new model | Qualcomm's published bundles target 8 Elite / X Elite / Dragonwing only | Vendor model cards, 2026-10-14 [VERIFIED] |
| Phi-4-mini-reasoning as the reasoner | Same bytes/token as our 3B, so no speed gain, and long CoT makes end-to-end *worse* against a strict-JSON contract | Table A.1 [UNVERIFIED estimate + MIT licence is the only clear win] |
| TranAD / USAD | Residual and physics-consistency models will outperform them on 18 correlated sensors with known relationships | Judgement call, state it as such |
| A TSFM on the NPU | No export path, and it would contend for the DSP address space that already failed | §D + §B.3 |
| Open-ended LLM tool-calling loop | A 3B picks the wrong tool and invents arguments under distribution shift | §C.2 |
| More context-binary splits (4-way) | `NUM_SPLITS = 3` is hardcoded in `llama_v3_2_3b_instruct/model.py` and the reused activation encodings are keyed to those split names | HANDBOOK §2.12 [VERIFIED] |

---

## Roadmap

### Next week — cheap experiments that decide everything

1. **Co-residency probe (half a day).** Push any small Genie bundle you can get — even a
   GenieX/llama.cpp q4_0 Qwen3-0.6B — and start it in a *second process* while `genied` holds the
   3B. Watch `adb logcat` for `fastrpc_mmap`. **This single test decides whether Option B exists.**
2. **KV rewind spike (one day).** `genie-t2t-run -c <cfg> -p "<prompt A>" -w "<prompt B>"` with our
   two prompts sharing the real preamble. Measure TTFT with and without. Also confirm the KV update
   method is `SMART_MASK`, not `POINTER_SHIFT`, since our bins are weight-shared.
3. **`direct-io` test (half a day).** Check `/dev/udmabuf` exists on the board and its
   `size_limit_mb`; set `"direct-io": true` and measure init. It targets the 18% we care about.
4. **Start logging preference data (one day).** Raw pre-repair output + prompt + verdict + note.
   Pure backend change, no model work, and it is the input to everything in §E.1.
5. **Seasonal-naive forecast baseline (one day).** 7-day × 5-min seasonal profile per sensor, with
   residual bands. Measure MAE. This is the yardstick every later forecasting idea must beat.

### Next month — the LoRA-v3 feasibility spike, and the non-LLM wins

6. **LoRA-v3 spike, timeboxed to two weeks.** Train two tiny PEFT adapters on the existing merged
   checkpoint (`domain`, `chat`), concatenate them into one concurrency, and drive
   `qairt-lora-mapper → model-creator → converter → quantizer → lora-importer →
   qnn-context-binary-generator`. Target the **Hot Switch** variant with
   `--quant_updatable_mode none`. Use `skip-lora-validation: true` and
   `enable-graph-switching: true` while iterating. **Exit criterion: the binary loads on the board
   and `setLoraStrength` changes the output.** Quality comes later. If it does not load in two
   weeks, stop and take Option B.
7. **Change-point + drift + residual detectors.** Pure CPU, pure Go or Python, new evidence ids
   E9–E11, wired into the existing rule agents and the policy gate's evidence check.
8. **Nightly PCMCI+ job off-device**, emitting a campus causal graph as JSON. Hand the relevant
   edges to the synthesizer prompt.
9. **Wire in the batched `genie-app` path** (`genieapp.go`) that is already measured and sitting
   unused: ~630 ms saved per extra agent in a Mode-3 incident.

### Next quarter — the features

10. **Conversational query** per §C.3: 12 query templates, Go executes, LLM phrases, policy gate
    validates. Ship behind the `chat` adapter if §6 succeeded, behind a careful system prompt if
    not.
11. **Predictive alerts** on top of §5, with their own stricter gate and their own approval queue —
    do not let forecast alarms pollute the incident queue's precision.
12. **First DPO run** once there are ~300–500 pairs. Ship as an adapter if §6 succeeded.
13. **Matrix profile precedent search** ("seen 4 times before, always after the 06:00 flush").
14. **GenieX migration assessment.** Qualcomm's own model cards say Genie "will be deprecated
    soon". Budget a week to find out what that means for a 2.50 Genie bundle and for the LoRA APIs,
    before it becomes urgent.

---

## Open questions for the owner

1. **Is a two-week LoRA-v3 export spike acceptable spend?** It is the fork in the road. Everything
   downstream — chat persona, DPO shipping cost, the cross-domain reasoner itself — gets cheaper if
   it works and stays expensive if it does not.
2. **If the spike fails, which fallback?** (a) small second model in its own process, accepting an
   export and co-residency risk, or (b) one model, two system prompts, and spend the saved effort
   on the non-LLM ML in §D instead. (b) is the lower-risk answer and may be the better one.
3. **Is the cross-domain reasoner required to be a *different model*, or is "different trained
   behaviour, same weights file" enough?** The owner's stated motivation was that a dedicated
   reasoner opens the door to a conversational interface. A LoRA adapter opens that door too, at a
   fraction of the cost. If the requirement is literally "two models", say so now, because it
   changes the plan.
4. **How much history exists?** Causal discovery, matrix profile and seasonal forecasting all need
   weeks-to-months of 5-min data. If there is only days, §D's ordering changes.
5. **What is the acceptable chat latency?** ~1.5–2 s to first token with prefix caching on the
   3B, or ~0.5 s with a 0.8B second model. If 2 s is fine, the second model loses most of its
   remaining justification.
6. **Does the campus actually want recommendations, or only explanations?** Energy optimisation
   means the system proposes *actions with costs*. That is a different liability posture from
   "here is what happened and why", and the policy gate's enums would have to grow.
7. **How many operators, and will they really use approve/dismiss?** The DPO plan is only as good
   as the labelling behaviour. If one person clicks approve on everything, there is no signal.
8. **Is GenieX migration in scope this year?** The vendor says Genie is going away. Doing it early
   is cheap; doing it under pressure is not.

---

## Source index

**Verified in the SDK at `~/qairt/qairt/2.50.0.260828` (QAIRT 2.50.0.260828221209):**

* `include/Genie/GenieDialog.h` — LoRA APIs (L464–532), save/restore (L434, L449), signal (L600),
  `GENIE_DIALOG_PARAM_APPLIED_LORA_ADAPTER` (L94)
* `include/Genie/GenieNode.h` — `GenieNode_saveLora` / `applyLora` / `setLoraStrength` (L389–494)
* `docs/QAIRT-Docs/Genie/general/library/dialog/json.html` — full dialog schema, LoRA v1 and
  v2/v3 schemas, `shared-engine`, `skip-lora-validation`, `spill-fill-bufsize`, `direct-io`
* `docs/QAIRT-Docs/Genie/general/library/engine/json.html` — standalone-engine schema
* `docs/QAIRT-Docs/Genie/general/tutorials/dialog/engine_sharing/engine_sharing.html`
* `docs/QAIRT-Docs/Genie/general/tutorials/dialog/rewind/rewind.html` — KV rewind / prefix match
* `docs/QAIRT-Docs/Genie/general/tutorials/dialog/pause_resume/pause_resume.html`
* `docs/QAIRT-Docs/Genie/general/tutorials/dialog/llama-3-3b/htp/android/eaglet/lora/lora.html`
* `docs/QAIRT-Docs/QNN/general/tutorial/lora_v3_overview.html` — the full offline LoRA-v3 toolchain
* `docs/QAIRT-Docs/QNN/general/tutorial/lora_v3_optimizations.html` — No-Updateable, Grouped,
  All-Updateable, Float-Only, **Hot Switch**
* `docs/QAIRT-Docs/QNN/api-rst/...QnnHtpContext.h.html` — weight-sharing and LoRA context config
  options 1, 13, 16, 18
* `bin/x86_64-linux-clang/` — `qairt-lora-mapper`, `qairt-lora-model-creator`,
  `qairt-lora-importer`, `qairt-lora-adapter-bin-updater`, `qnn-context-binary-generator`

**Verified in this repo:**

* `HANDBOOK.md` §2.11 (graph-count cliff), §2.12 (CDSP SMMU root cause + `enable-graph-switching`
  fix), §2.15 (memory-bandwidth roof, 2.20 GB/token, 49.3 GB/s, part sizes), §2.16 (grammar
  rejected)
* `Code/smart-city-edge-agent/training/EXPORT_RESEARCH.md` — AI Hub export path, QAIRT 2.50
  default, 8 Gen 3 no longer in `supported_chipsets`, LoRA not available via AI Hub
* `Code/smart-city-edge-agent/app/genied/main.go` — resident dialog daemon, abort protocol
* `Code/smart-city-edge-agent/app/backend/genieapp.go` — measured batching (3.15 s vs 3.74 s/query)
* `Code/smart-city-edge-agent/app/backend/server.go:309`, `reason.go:114` — approve/dismiss records
* `Code/smart-city-edge-agent/src/smart_city_edge/anomaly_model.py` — existing autoencoder

**Fetched from the web, 2026-10-14:**

* https://huggingface.co/qualcomm/Llama-v3.2-3B-Instruct — asset table, no 8 Gen 3, Genie
  deprecation note
* https://huggingface.co/qualcomm/Qwen3-1.7B — asset table, GenieX llama.cpp only
* https://aihub.qualcomm.com/models?domain=Generative+AI&chipsets=Snapdragon%C2%AE+8+Gen+3+Mobile
* https://geniex.aihub.qualcomm.com/en/models/supported.md — GenieX runtimes and model sources
* https://github.com/qualcomm/geniex
* https://huggingface.co/google/gemma-4-E2B-it-qat-mobile-transformers and
  https://en.wikipedia.org/wiki/Gemma_(language_model) — Gemma 4 sizes, dates, licence
* https://x.com/Alibaba_Qwen/status/2028460046510965160 and
  https://www.marktechpost.com/2026/03/02/alibaba-just-released-qwen-3-5-small-models-a-family-of-0-8b-to-9b-parameters-built-for-on-device-applications/
  — Qwen3.5 Small sizes, licence, dates
* https://huggingface.co/blog/BobWue/edge — TSFM edge-CPU latency benchmark (vendor-run)
* https://proceedings.mlr.press/v213/castri23a.html — F-PCMCI
