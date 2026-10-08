# training_plan.md — Where, What, How Much, How Long

> Written 2026-10-01. Zero-cost budget. Focus: fine-tuning Llama 3.2 3B as the multi-role domain agent + synthesizer, then getting the tuned model back onto the QIDK NPU.
> Companion to `plan.md` (overall plan) and `context.md` (repo review).

---

## 0. TL;DR

| Question | Answer |
|---|---|
| Train on the QIDK NPU? | **No.** The HTP is an inference engine (fixed-point int4/int16, no backprop, no training runtime in QAIRT/Genie). The QIDK only *runs* the result |
| Where then? | **Laptop RTX 4050 (6 GB) in WSL, QLoRA 4-bit.** Free, private, no session limits. **Kaggle free GPUs** (T4, 30 GPU-h/week, ~29 GB RAM) as overflow and for RAM-heavy steps |
| How does the tuned model get back to the NPU? | Merge LoRA → Qualcomm's `qai_hub_models` Llama 3.2 3B pipeline with our checkpoint → **recompute weight encodings data-free** (same `min_max` per-channel 4-bit scheme Qualcomm used) + **reuse Qualcomm's activation encodings** → **Qualcomm AI Hub compile (free cloud)** → 3 context binaries → same `genie_config.json` → push |
| What do we train? | **One multi-role LoRA** (5 domain agents + synthesizer, role given in the system prompt), not 6 adapters |
| How much data? | ~4,500 train / ~400 dev examples, ~1,000 tokens each. Teacher = **Claude (me)** writes ~400 gold examples; a generator built from them scales to the rest |
| How long? | Pilot ~30 min. Full run **≈ 6–12 h (one overnight)** on the 4050 for 2 epochs. To be confirmed by the pilot's measured tokens/s |
| Biggest risk | The re-export round trip. **We prove it first with the *unmodified* base model** before training anything |

---

## 1. What I verified on this machine today

| Item | Finding |
|---|---|
| GPU | RTX 4050 Laptop, 6,141 MiB VRAM, driver 592.82, visible inside WSL |
| RAM / disk | Windows 15.6 GB RAM; **WSL limited to ~7.7 GB** (default). Disk: C: 74 GB free, WSL ext4 925 GB free |
| Base model | `meta-llama/Llama-3.2-3B-Instruct` in WSL HF cache (`~/.cache/huggingface/hub/...0cb88a4f...`). Both safetensors shards complete (254/254 tensors, byte sizes match headers) |
| Deployed bundle | `models/genie_bundle/llama_v3_2_3b_instruct-genie-w4a16-qualcomm_snapdragon_8gen3/` — tokenizer **semantically identical** to the HF base (vocab, merges, added tokens, pre/post-processors). `config.json` identical except `transformers_version` |
| Bundle defect (fixed) | `part_2_of_3.bin` was an interrupted download: 561,184,768 B, an exact prefix of `part_2_of_3.recovered.bin` (901,410,816 B). Context-binary header = `[u64 header_size][u64 blob_size]`; recovered = 20,480 + 901,390,336 = exact. Part 1 and part 3 also match exactly. **Swapped in the recovered file**; old one kept as `part_2_of_3.bin.truncated` (delete when happy). SHA-256s written to `SHA256SUMS.txt` in the bundle folder |
| Device copy | QIDK not connected today. When plugged in: `adb shell sha256sum /data/local/tmp/genie_bundle/*.bin` and compare with `SHA256SUMS.txt` |
| Qualcomm checkpoint | `~/.qaihm/qai-hub-models/models/llama_v3_2_3b_instruct/v4/llama32_ckpt_w4a16/`: fp32 ONNX weights (`model.data` 14.4 GB), prefill (seq128) and decode (seq1) graphs, `model.encodings` (AIMET v5) |
| Encodings | `quant_scheme: min_max`, `per_channel_quantization: true`, params 4-bit symmetric (1,232 tensors) + lm_head 8-bit; activations 16-bit (10,255) / 8-bit (1,456). Attention is rewritten as split heads (`q_proj_sha.0..23`, `k/v_proj_sha.0..7`) and `o_proj_conv` |
| Python envs | No training or `qai_hub_models` env currently installed (pyenv 3.11.9 is bare). `~/.qai_hub/client.ini` exists, so the AI Hub token is already configured |
| Old LoRA adapter | **Not found anywhere** (no `adapter_model.safetensors` on disk). We start fresh |

---

## 2. Where to train — options compared (zero cost)

| Option | Can train 3B QLoRA? | Pros | Cons | Verdict |
|---|---|---|---|---|
| **QIDK NPU (HTP V75)** | No | — | Inference-only, quantized, no gradients; QAIRT has no training API | Ruled out |
| QIDK CPU | Technically, but absurdly slow | — | Days per epoch, thermal | Ruled out |
| **Laptop RTX 4050 6 GB (WSL)** | Yes (4-bit base ≈ 2.2 GB + LoRA + activations with grad checkpointing ≈ 4.5–5.5 GB at seq 1536) | Free, private, unlimited hours, data never leaves | Tight VRAM; ~5 effective TFLOPs; WSL RAM must be raised | **Primary** |
| **Kaggle Notebooks** | Yes (T4 16 GB or 2×T4; P100) | Free, 30 GPU-h/week, 12 h sessions, ~29 GB RAM | Upload data (derived features only), weekly quota, T4 has no bf16 (fp16) | **Overflow + RAM-heavy export step** |
| Google Colab free | Yes (T4) | Easy | ~12 GB RAM, session cut-offs, unpredictable quota | Backup only |
| Qualcomm AI Hub | No (compile/profile/inference only) | **Free cloud compile to QNN context binaries** for SM8650 | Not for training | Use for export |

Data note: sending *derived feature windows* (no personal data; occupancy is empty anyway) to Kaggle is low-risk, but your PRD says raw SCRC data must not go to public clouds. We upload only processed training JSONL, never the raw CSVs.

---

## 3. The deploy round trip (most important part)

Training is easy. **Getting a tuned model onto the HTP is what can fail**, so we de-risk it first.

```
HF base (bf16) ──QLoRA──► LoRA adapter (~50–100 MB)
        │                         │
        └──────── merge (CPU) ◄───┘
                     │
            merged HF checkpoint (bf16, ~6.4 GB)
                     │  qai_hub_models llama_v3_2_3b_instruct pipeline (our checkpoint)
                     ▼
     Qualcomm-format ONNX (split-head attention, Conv projections), fp32 weights
                     │
   encodings: param  → recompute min_max per-channel symmetric (4-bit; lm_head 8-bit)   ← data-free, exact same rule
              activ. → copy Qualcomm's 11,711 activation encodings by tensor name        ← assumption: LoRA shifts ranges only slightly
                     ▼
     Qualcomm AI Hub compile job (free) → 3 context bins (prefill ar128 + decode ar1, cl4096)
                     ▼
     same genie_config.json + tokenizer → adb push → genie-t2t-run on QIDK
```

### Why this should work

- Weight quantization is `min_max` per output channel, so it depends **only on the weights**. Recomputing it for new weights is exactly what AIMET would have done.
- Activation encodings need calibration data. Reusing Qualcomm's is an approximation, but they are 16-bit (wide headroom) and a rank-16 LoRA changes activations modestly. If quality drops, we recalibrate activations with ~100–200 samples on Kaggle (Phase T-6b).

### Spike first (Day 1–2): the round trip with the unmodified base

1. New WSL venv `~/venvs/qaihm` with `qai-hub-models[llama-v3-2-3b-instruct]` (same major version as the cached `v4` assets).
2. Run the export path with **our own** copy of the HF base checkpoint and the **recomputed** weight encodings + Qualcomm's activation encodings → AI Hub compile.
3. Push to the device next to the official bundle and compare greedy outputs on ~20 prompts.
   **Pass:** outputs match the official bundle on ≥ 18/20 prompts (exact or near-identical text).
4. To check while doing it: whether the installed `qai_hub_models` version accepts a custom checkpoint path directly. If it doesn't, we write the weight-injection step ourselves: map HF tensors → their ONNX initializers (split q/k/v by head, Linear→Conv layout) and rewrite `model.data`. This is mechanical, and the layer names above already show the mapping.

**If the spike fails:** fall back to base model + prompting + RAG on device (still the full agentic app), and report fine-tuning gains from host-side evaluation only. We find this out in 2 days, not after a week of training.

---

## 4. What we train

### 4.1 One adapter, six roles

| Role (system prompt) | Input | Output |
|---|---|---|
| `hvac_agent` | KH floor/unit AC stats: on-fraction, compressor, setpoint vs room temp, alarms, malfunction codes, filter sign | `DomainFinding` JSON |
| `indoor_air_agent` | SR-AQ: CO2 (level + rate), PM, temp, RH, noise; inferred occupancy | `DomainFinding` |
| `energy_agent` | SR-EM / EM / SL: power vs hour-of-week baseline, PF, voltage | `DomainFinding` |
| `water_agent` | WL level + rate, WF flow, WD quality | `DomainFinding` |
| `weather_context_agent` | WE + nearest outdoor AQ | `DomainFinding` (context only) |
| `synthesizer` | 2–5 `DomainFinding`s + evidence table + retrieved context | `RootCauseReport` JSON |

Routing (which agents to call) stays **deterministic** (rules/anomaly flags decide affected domains). No LLM orchestrator, and no orchestrator training.

### 4.2 Training data

| Source | Count (train) | Notes |
|---|---|---|
| Fault-injected scenarios on **real** KH windows (Jan–Aug 2025) | ~3,000 agent + ~1,200 synthesizer | Known label by construction: HVAC fault/overload/filter, ventilation insufficient, outdoor ingress, abnormal load, power quality, leak/drain, low supply, water quality, heat load, sensor fault |
| Normal / insufficient-data / sensor-fault negatives | ~15 % of the above | Teaches "normal" and "UNKNOWN" instead of inventing problems |
| **Gold examples written by me (Claude)** | ~400 | Cover every role × label, varied phrasing, honest uncertainties, correct evidence citing |
| **Dev** (Sep–Oct windows) | ~400 | Early stopping, prompt tuning |
| **Test** (Nov–Dec + human-labelled real events) | ~300 injected + ~150 real | Never trained on; real set reported separately |

**How the targets are written (teacher = me):**
1. I write the ~400 gold examples directly in-session, from real windows plus the injection metadata (label, mechanism, affected evidence IDs).
2. From these I build a **grounded generator**: per label and role, a set of observation/causal-chain patterns that fill in the actual numbers, deltas vs baseline and evidence IDs from each scenario. Several phrasings are rotated so the model doesn't memorise one sentence.
3. Every generated target must pass the **PolicyGate validator** (schema, evidence ⊆ event IDs, action enum) before entering the set.
4. I re-read a random ~5 % sample and fix the generator when something reads wrong; you spot-check ~30.

### 4.3 Example size

| Part | Tokens |
|---|---|
| System prompt (role, rules, schema) | ~250 |
| Evidence table (stats + baselines + IDs) | ~300–450 |
| Retrieved context (specs, topology, similar incidents) | ~150–250 |
| Target JSON | ~150–300 |
| **Typical total** | **~1,000** (max_seq_len 1,536) |

---

## 5. Hyperparameters (QLoRA on RTX 4050)

```yaml
base: meta-llama/Llama-3.2-3B-Instruct (local HF cache)
quantization: 4-bit NF4, double quant, compute dtype bfloat16 (Ada supports bf16)
lora: r=16, alpha=32, dropout=0.05
target_modules: [q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj]  # ~24M trainable params
max_seq_len: 1536
micro_batch: 1, grad_accum: 16  (effective batch 16)
epochs: 2  (~560 optimizer steps for 4,500 examples)
lr: 2e-4, cosine, warmup 3 %
gradient_checkpointing: true
loss: assistant tokens only (prompt masked)
eval: every 100 steps on dev (loss) + JSON-validity/grounding script every epoch
seed: 42; checkpoints kept: best 2
```

Embeddings and `lm_head` stay frozen (tied embeddings; keeps the 8-bit lm_head encoding valid).

---

## 6. How long it will take

### 6.1 Compute estimate (to be replaced by pilot measurement)

- Trainable LoRA, frozen 4-bit base, with recomputation: ≈ 5 × 3.2 B FLOPs ≈ 1.6 × 10¹⁰ FLOPs per token.
- Tokens: 4,500 examples × ~1,000 tokens × 2 epochs ≈ **9 M tokens** → ≈ 1.4 × 10¹⁷ FLOPs.
- RTX 4050 Laptop, bitsandbytes 4-bit dequant overhead, power-limited: realistic **3–6 effective TFLOPs**.

| Where | Effective speed | Full run (2 epochs) | Pilot (300 ex, 1 epoch) |
|---|---|---|---|
| Laptop RTX 4050 | ~200–400 tok/s | **≈ 6–12 h** | ≈ 15–30 min |
| Kaggle T4 (fp16) | ~350–600 tok/s | ≈ 4–7 h (fits a 12 h session) | ≈ 10–15 min |

### 6.2 Everything else

| Step | Where | Time |
|---|---|---|
| Env setup (2 venvs, WSL memory) | Laptop | 1–2 h |
| Export round-trip spike (base) | Laptop/Kaggle + AI Hub | 1–2 days incl. debugging; AI Hub compile ~30–90 min per job |
| Data pipeline + fault injection (from `plan.md` Phase 1–3) | Laptop CPU | 3–4 days (parallel with spike) |
| Gold examples (me) + generator + validation | Laptop | 2–3 days (parallel) |
| Baseline eval of **untuned** model (prompt + RAG) on dev/test | Laptop 4-bit or QIDK | ½ day |
| Pilot training + measurement | Laptop | ½ day |
| Full training | Laptop overnight | 1 night |
| Merge + export + AI Hub compile + push + device eval | Laptop + AI Hub + QIDK | 1 day |
| **Total to a tuned model on the QIDK** | | **≈ 8–10 working days** (spike, data and gold examples overlap) |

The per-domain anomaly autoencoders (Layer 1) train in minutes on CPU and are not on the critical path.

---

## 7. Acceptance gates (when do we keep the adapter?)

Evaluated on the test split, on the device (w4a16), against the **untuned model with the same prompts + RAG**:

| Metric | Gate |
|---|---|
| Valid JSON (after ≤ 1 repair retry) | ≥ 97 % |
| Evidence grounded before policy gate | ≥ 98 % |
| Taxonomy accuracy, injected test | ≥ untuned + 10 points |
| Taxonomy accuracy, **real** human-labelled test | not worse than untuned |
| Output tokens per call | ≤ untuned (shorter is faster) |
| Host-fp vs device-w4a16 agreement | ≥ 90 % same label (otherwise recalibrate activations) |

---

## 8. Step-by-step order (what we do, who does it)

| Step | What | Who |
|---|---|---|
| T-0 | Create `C:\Users\hp\.wslconfig` (`memory=12GB`, `swap=32GB`) → `wsl --shutdown` | **You** (I give the file) |
| T-1 | Venv `~/venvs/train`: CUDA torch, transformers, peft, bitsandbytes, datasets, accelerate | Me (commands) + **You** (run) |
| T-2 | Venv `~/venvs/qaihm`: `qai-hub-models[llama-v3-2-3b-instruct]` pinned; check `qai-hub configure` token works | Me + **You** |
| T-3 | **Export spike** with the unmodified base (§3), device comparison | Me (scripts) + **You** (device + AI Hub jobs) |
| T-4 | Data: ingest → 5-min windows → fault injection → scenarios (train/dev/test by month) | Me |
| T-5 | Gold examples (me) → generator → validator → `sft_{train,dev}.jsonl` | Me (+ **You** spot-check 30) |
| T-6 | Baseline: untuned model + prompts + RAG on dev/test | Me + **You** (device runs) |
| T-6b | (If needed) activation recalibration recipe on Kaggle | Me |
| T-7 | Pilot QLoRA (300 ex) → measure tok/s and VRAM → finalise schedule | **You** (run) + me |
| T-8 | Full QLoRA overnight | **You** (start it) |
| T-9 | Merge → export → AI Hub compile → push → device eval vs gates | Me + **You** |

---

## 9. What I need from you to start

1. OK to create `C:\Users\hp\.wslconfig` (raises WSL RAM to 12 GB). Without it, merging/exporting a 3B model in 7.7 GB will swap or crash.
2. Plug in the QIDK when convenient, so we can verify the on-device bundle hash and run the spike comparison.
3. Confirm the AI Hub account still works (`~/.qai_hub/client.ini` exists; a token may have expired).
4. A Kaggle account (free, phone-verified for GPU), only if we need the overflow.
