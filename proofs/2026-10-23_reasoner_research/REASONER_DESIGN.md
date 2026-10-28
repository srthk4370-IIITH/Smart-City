# Cross-domain reasoner: design and research report

**Date:** 2026-10-23. **Status:** research and design only. No app code was changed, the board was not touched, nothing was committed.
**Scope:** the model, deployment, tools, storage, fog/RAG, training and roadmap for the owner's cross-domain reasoner. It
replaces today's synthesizer and the `reasonerSeverity` stub, and adds a conversational interface that works offline.

**Supporting files in this folder**
- `tools.json`: the proposed tool schema (9 read-only tools) and the executor rules.
- `store_schema.sql`: the proposed SQLite device store (incident index, maintenance log, readings rollups, tool-call log,
  sync outbox), with example exact queries.

---

## 0. Recommendation in one page

1. **On-device model: do not add a second model to the NPU. Keep the deployed v2 Llama-3.2-3B GGUF as the base and add
   a separate reasoner LoRA adapter.** htpd applies the adapter only on its reasoner/chat context
   (`llama_set_adapters_lora` is per context in llama.cpp), so the agent context runs exactly as it does today. That means:
   - one model, one process, one NPU client;
   - agent outputs are unchanged because the base GGUF is byte-identical;
   - the Q4_0 transfer gap only applies to a small F16/Q8_0 adapter;
   - the adapter (25–50 MB) is the owner's own, separately versioned, self-improving reasoner model.

   This meets the intent of the 2026-10-14 decision ("a distinct, self-improving model") without HANDBOOK 2.27's
   board-rebooting second model, and without a model swap per incident.
2. **Fallback and comparator: Qwen3.5-4B** (Apache-2.0, BFCL-v4 50.3, TAU2 79.9, 262k context, native tool calling).
   It is evaluated on the same test set as a host GGUF. It is adopted only if the LoRA path fails its gates, and then
   only as a time-shared model for explicit chat sessions, because it means unloading the 3B.
   - Qwen3.5-2B (BFCL-v4 43.6) is too weak for multi-step tool use.
   - The 2026-10-14 preference, Qwen3-1.7B, has been superseded by the Qwen3.5 family.
3. **Fog model: Qwen3.5-9B** (BFCL-v4 66.1, Apache-2.0) for a modest fog box (12–16 GB GPU at 4–8 bit).
   **Qwen3.5-35B-A3B** (BFCL-v4 67.3, MoE with about 3B active) if the fog box has 24 GB or more. Both run the same tool
   schema plus `search_knowledge`. Fog embeddings: **Qwen3-Embedding-0.6B** (Apache-2.0) or **EmbeddingGemma-300M**.
4. **The LLM never counts.** Every "how many" goes to a typed, read-only tool (`count_incidents`, `sensor_faults`, …).
   Go/SQL runs the tool exactly over a SQLite index, and the backend renders the number. A numeric-grounding check
   rejects any number in the prose that no tool returned. The model picks the tool and fills its arguments. It never
   writes SQL.
5. **Offline first, fog when available.** The tool executor routes, not the LLM:
   - online, counts and searches run on the fog's complete store;
   - offline or on timeout, they run on the device and return `coverage.complete=false`, which the answer must state.
   - Recommended: keep a ~300-byte all-time index row per incident on the device. Exact counts then survive the
     1000-incident retention, with full records still capped at 1000.
6. **Latency.** The incident reasoner is a single pass on the early alert, with one optional tool round when evidence is
   ambiguous (+1.5–2 s), and up to 2 rounds on the background 1.5 h and 3 h refinements. Target: the reasoner stage is no
   slower than today's synthesizer (3.2–7.4 s). Chat: first visible token under 2 s when the NPU is idle, through a
   prefix-cached system/tool prompt, a backend "looking up …" step event, and backend-rendered numbers.
7. **Training.** QLoRA r=16 on the RTX 4050, on a **dequantised copy of the deployed Q4_0 v2 weights** (so the adapter
   learns against the base it will run on).
   - Data: ~10–14k examples from programmatic generators with exact ground truth: tool traces whose answers come from
     executing the tools, and compound cross-domain scenarios with causal labels.
   - Gates: judged on the host GGUF proxy and then on the device, never on HF/teacher-forced numbers (lesson from 2.43).
8. **Phase 0 must come first:** confirm that a LoRA adapter runs on the Hexagon backend inside htpd, with correct output
   and acceptable overhead. The source suggests it can (§B.4), but nobody has measured it. Everything else depends on
   this 1–2 day spike.

Estimated total effort: about 5–7 weeks of part-time work, plus 20–30 GPU-hours of training (§E).

---

## A. Requirements and constraints

### A.1 What the reasoner must do
| Job | Trigger | Input | Output | Who sees it |
|---|---|---|---|---|
| **Incident reasoning** | Every Mode-3 incident with ≥ 2 informative domains (today's synth trigger); also each 1.5 h / 3 h refinement | flagged-sensor agent findings (v2 JSON), context-sensor findings, E1–E10 evidence, long-range lines | report JSON: root_cause, label, affected_domains, evidence ids, **severity** (replaces the stub), action (whitelist), explanation, optional title | incident sheet, list colour, domain health |
| **Conversational interface** | Operator question (UI chat panel / API) | question + chat history + tool results | streamed answer with incident-id citations, coverage note, optional table/chart card rendered by the backend | operator |
| **Agentic data access** (both jobs) | the model decides | tool schema (`tools.json`) | tool calls → exact results → reasoning | audit log |

### A.2 Latency budgets (from measured numbers)
| Item | Measured today | Source |
|---|---|---|
| 3B Q4_0 on HTP, 1 stream: prefill / decode | ~970 tok/s / ~19 tok/s (harness, no drafting); ~35 tok/s in-app with drafting | `proofs/2026-10-16_htp_bringup/step_02`, HANDBOOK 2.43 |
| Full chaos incident (13–14 agents + synth) | 25.4–31.8 s | 2.43 |
| Synthesizer call (v7 profile, synth prefix cache) | 3.2–7.4 s | 2.43 |
| Agent/synth context swap overhead | ~0.05–0.1 s app overhead | latency ladder #12 |
| htpd ready after start | ~1.6–1.7 s (plus warm-up) | htpd logs in proofs |
| KV per token, Llama-3.2-3B f16 (28 L × 8 KV heads × 128 × 2 × 2 B) | 112 KiB → 4096 ctx = 448 MiB, 8192 = 896 MiB; agent layout 10 × 1280 = 1.37 GiB | computed |

**Budgets adopted.**
- **Incident:** the reasoner stage is ≤ today's synth stage plus 1 s at the median. A tool round is allowed only when
  the model asks for it, and at most one on the early alert. Refinements run in the background and may take 2.
- **Chat:**
  - first visible token in under 2 s at p90 when the NPU is idle. This is a backend step event ("Counting CO2 spike
    incidents in 2026…") the moment the tool call's name is decoded, followed by the first answer token;
  - a single-tool count answered in full in under 6 s;
  - a 3-tool question in under 15 s.
- **When the NPU is busy with an incident, chat waits** and shows "NPU busy analysing INC-xxxx, about N s". Chat never
  preempts a new alert, but it does run before refinements.

### A.3 Memory and the one-NPU-client rule
- **Hard rules from the HANDBOOK:**
  - Two full models cannot be resident (2.27).
  - GPU/NPU buffers are unmovable and must fit in the 7.26 GB Normal zone (2.37).
  - Board drops correlate with handling 2.8 GB GGUFs and with second NPU sessions (2.43).
  - One NPU client at a time (memory: qidk-large-transfers).
- **Hence:**
  - **no second process on the NPU and no second resident model.** A reasoner that swaps models per incident would
    reload a 2–3 GB GGUF tens of times a day: the exact activity that preceded the 2026-10-22 shutdowns;
  - a **LoRA adapter costs about 25–50 MB of resident memory** (r=16, F16 or Q8_0, all 7 projections: 24.3 M params; see
    §B.4) and is loaded once at htpd start;
  - **the reasoner context reuses the "synth" context slot.** htpd already holds exactly one context at a time and swaps
    agent ↔ synth. A reasoner/chat context of 6–8k tokens (0.7–0.9 GiB KV) is smaller than the agent layout
    (1.37 GiB), so peak NPU memory does not grow.
  - Chat memory survives an agent batch by **stashing the chat KV to normal RAM** (`llama_state_seq_get_data` /
    `set_data`, about 100–400 MB) before the agent context is created. The alternative is re-prefilling the
    conversation, about 1–2 s for 1–2k tokens.

### A.4 Offline-first
- **Every capability works with the network unplugged.** That covers incident reasoning, chat over device data and
  exact counts.
- **The fog adds** complete history, RAG over documents, and a stronger model for open-ended questions.
- **The device never waits for the fog** longer than a 1.5 s tool timeout before falling back.

### A.5 Safety
- **Read-only tools only.** No tool can actuate, approve, dismiss, inject or change config (see `tools.json`).
  Actions stay a whitelisted *recommendation*, and every one needs human approval (existing policy gate,
  `requires_human_approval`).
- **The policy gate extends to the reasoner:**
  - labels, actions and domains are whitelisted;
  - evidence ids must exist;
  - severity is consistent with the validated findings: it may be raised, and lowered only when every flagged
    sensor's validated finding is lower or the reasoner cites sensor-fault evidence;
  - incident ids in chat answers must be real ids returned by tools.
- **Prompt-injection hygiene:** operator notes, document passages and fog text are data, quoted in labelled blocks.
  The model is trained to ignore instructions inside them (Greshake et al., 2023).
- **Refusals:** requests to actuate ("switch off AC 3") get a recommendation plus "requires operator approval", never an
  action.

### A.6 Exactness of counts
- **LLMs are unreliable at counting and aggregating over long contexts** (ordering effects, "lost in the middle": Liu et
  al., 2023). The design therefore never puts raw incident lists into the prompt in order to count them.
- **Counting runs in SQL or Go.** The answer template quotes the integer verbatim, and a grounding checker compares
  every number in the generated text with the numbers in the tool results of the same turn. A mismatch makes the
  backend replace the sentence with its templated rendering and log a DPO pair.
- **Semantics are explicit and shown back.** For example:
  - "CO2 spike" = flagged CO2 sensor with pattern in {spike, exp_rise, step_increase}, a synonym table owned by the
    executor;
  - injected demo incidents are excluded by default;
  - "this year" uses the operator's wall clock.

  Caveat: today `created_sim` is replay time from the 2025 dataset. In the field the two clocks coincide; in the demo
  the executor must say which clock it used.

---

## B. Candidate models

### B.1 On-device candidates (≤ ~4B)
Scores are vendor-reported or from aggregators unless marked. BFCL versions differ (v2/v3/v4), so compare within a
column only.

| Model | Params / arch | Tool calling | Reasoning mode | Context | Licence | llama.cpp Hexagon | Est. decode on V75 HTP* | Verdict |
|---|---|---|---|---|---|---|---|---|
| **Llama-3.2-3B-Instruct (our v2 base) + reasoner LoRA** | 3.2B dense, 128k vocab | BFCL v2 **67.0**, Nexus 34.3 (model card); native JSON tool format in the template | none | 128k | Llama 3.2 Community | **Deployed today** (htpd, Q4_0, FA streams, drafting, prefix cache) | 19 tok/s raw, ~35 with drafting (measured) | **Recommended** |
| Qwen3.5-4B | ~4B text, hybrid Gated DeltaNet 3:1 + gated attention, 32 L, d=2560, **248k tied vocab** | BFCL-v4 **50.3**, TAU2 **79.9** (model card); `qwen3_coder` tool parser | thinking on by default (switchable) | 262k | Apache-2.0 | arch `qwen35` present in our llama.cpp tree; HTP has `GATED_DELTA_NET` and `SSM_CONV` ops (36/36 GDN test cases supported in `docs/ops/Hexagon.csv`). **Untested in htpd** (patched FA streams, drafting, prefix cache assume a pure-attention KV) | ~14–16 tok/s (≈ 2.4 GB/token incl. a 0.64 B-param lm_head) | **Comparator / fallback** |
| Qwen3.5-2B | 2B, same hybrid, 24 L | BFCL-v4 43.6 | yes | 262k | Apache-2.0 | as above | ~28–32 tok/s | too weak for multi-step tools |
| Qwen3-4B-Instruct-2507 / Qwen3-4B | 4B dense | BFCL-v3 65.9 (non-thinking, Qwen3 tech report) | Qwen3-4B hybrid; 2507 instruct has no thinking | 32k / 256k | Apache-2.0 | dense attention, supported | ~14–16 tok/s | good, but superseded by 3.5 |
| Qwen3-1.7B (2026-10-14 choice) | 1.7B dense | BFCL-v3 overall reported as low as 28.4 (FC mode, aggregator) | yes | 32k | Apache-2.0 | supported | ~35 tok/s | weak multi-step; superseded |
| Phi-4-mini-instruct | 3.8B dense, 200k vocab | function calling supported (model card); no strong BFCL claim | no | 128k | MIT | supported (dense) | ~15 tok/s | reasoning good, tool use average |
| Gemma 4 E2B / E4B | ~2B/4B effective (+ per-layer embeddings) | native function calling; TAU2 29.4 / 57.5 (thinking); BFCL-v4 E4B 52.4 (aggregator) | yes | 128k | Apache-2.0 | `gemma4` arch present; per-layer-embedding design not validated on HTP | unknown | watch-list |
| IBM Granite 4.x 3B | 3B | BFCL-v4 52.4 (aggregator, self-reported) | — | 128k | Apache-2.0 | supported (dense micro variant) | ~19 tok/s | plausible alternative |
| LFM2.5-2.6B | 2.6B hybrid conv/attn | BFCL-v4 56.9 (self-reported) | — | 32k | LFM Open License (revenue cap) | `lfm2` arch present, HTP untested | — | licence and HTP risk |
| SmolLM3-3B | 3B, NoPE layers | XML/Python tool calls | dual mode | 64k–128k | Apache-2.0 | supported | ~19 tok/s | no edge over Llama-3B |
| xLAM-2-3b-fc-r / Hammer2.1-3b | 3B (Qwen2.5 base) | BFCL-v3 64.8 / 59.6; multi-turn 58.4 / 16.5 (aggregator) | no | 32k | CC-BY-NC-4.0 (xLAM-2) / research | supported | ~19 tok/s | specialised FC; licence (xLAM) and weak chat |

\* Decode on the V75 is memory-bandwidth bound (HANDBOOK 2.15: ~49 GB/s achieved). Estimates scale the measured 3B rate
by Q4_0 bytes read per token.

### B.2 Why reuse the v2 3B with a LoRA instead of a "better" small model
1. **Board stability dominates.** A second model is either resident, which reboots the board (2.27, 2.37), or swapped,
   which means multi-GB reloads per incident or chat session: the correlate of the 2026-10-22 shutdowns. A LoRA is
   neither.
2. **Fine-tuning closes most of the leaderboard gap on a closed tool set.** BFCL measures generic, open-ended function
   calling. Our tool set is 9 fixed, typed tools. TinyAgent (Erdogan et al., EMNLP 2024 demo) fine-tuned 1.1B and 7B
   models on a fixed tool set with synthetic data, to about GPT-4-Turbo function-calling success (reported ~80% vs 79%).
   Octopus v2 and Hammer report the same pattern for on-device function calling. The 3B base already scores 67.0 on BFCL
   v2, the best of the ≤ 3B dense models with a usable licence.
3. **Every htpd optimisation carries over:** HMX pipelining, per-stream FA, verified drafting, prefix cache, label trie
   and JSON abort. With a new architecture, each would need revalidation. Qwen3.5's hybrid recurrent state in particular
   breaks the per-stream KV prefix-cache assumptions.
4. **There is no new Q4_0 transfer gap on the base.** The base GGUF stays byte-identical, so agent accuracy is untouched
   by construction.
5. **Licence:** the Llama 3.2 Community License allows this research use with "Built with Llama" attribution. A future
   commercial deployment with more than 700M MAU is irrelevant here.

**What we give up:**
- thinking mode, which is unaffordable at 19–35 tok/s anyway: a 300-token thought costs about 10–15 s;
- Qwen3.5's 262k context, which is not needed: our prompts are ≤ 8k;
- possibly 5–10 points of out-of-the-box tool skill.

The comparator run in Phase 0/3 quantifies that last cost. If the LoRA'd 3B misses the gates and Qwen3.5-4B passes, the
fallback is a time-shared Qwen3.5-4B for **chat sessions only**: an explicit "Ask" mode that unloads the 3B, with
incidents queued. Incident reasoning stays on the LoRA.

### B.3 Fog model
| Model | BFCL-v4 | Size at 4-bit | Notes |
|---|---|---|---|
| **Qwen3.5-9B** | 66.1 | ~6 GB | Apache-2.0; fits a 12–16 GB fog GPU at 8-bit with room for 32k context. **Default.** |
| **Qwen3.5-35B-A3B** | 67.3 | ~20 GB | MoE with about 3B active, so fast; needs ≥ 24 GB. **If hardware allows.** |
| Qwen3.5-27B | 68.5 | ~16 GB | dense; slower than 35B-A3B for little gain |
| gpt-oss-20b | — | ~13 GB (MXFP4) | Apache-2.0, native tool use (Harmony); an alternative on 16 GB |

- **Serving:** vLLM (`--enable-auto-tool-choice --tool-call-parser qwen3_coder`, as on the model card) or `llama-server
  --jinja`.
- **Thinking:** allowed on the fog for open-ended "why" questions, because fog latency is not on the alert path.
- **Fine-tuning the fog model** is optional. Start with the shared tool schema and few-shot examples, then reuse the
  device SFT data for a LoRA if the evals show a need.

### B.4 Does the Hexagon backend support runtime LoRA? (source review, not yet measured)
What our local llama.cpp tree (`C:\Users\hp\gpu_work\llama.cpp`, the build htpd links) shows:
- **Per-context adapters:** `llama_adapter_lora_init(model, path)` loads an adapter, and
  `llama_set_adapters_lora(ctx, …)` attaches it **per context** (`include/llama.h`). The agent context gets none; the
  reasoner context gets the reasoner adapter.
- **How the delta is computed:** `build_lora_mm` adds `scale · B(A·x)` after each base matmul
  (`src/llama-graph.cpp`).
- **Where the adapter tensors live:** in the **same buffer type as the base tensor** (`src/llama-adapter.cpp`). They fall
  back to the CPU only if that buffer type is one of the CPU's "extra" (repack) buffer types. The Hexagon backend
  registers no CPU extra buffer type (no `get_extra_bufts` in `ggml-hexagon.cpp`), so adapter tensors should land on HTP
  memory.
- **Op support on HTP:** `MUL_MAT` with F16 weights is supported on HTP in all 281 F16 cases of `docs/ops/Hexagon.csv`.
  Q8_0 is supported too, and `ADD` and `SCALE` exist. So the LoRA ops should run on the NPU with no graph split.
- **Unknowns, which Phase 0 must measure:**
  - **Per-op dispatch overhead:** r=16 on 7 projections × 28 layers adds about 784 small ops per graph, versus about
    700–900 in the base graph. Small-matmul efficiency on HMX is poor.
  - **Interaction with htpd's patched FA streams and HMX pipelining.**
  - **Correctness** against the CPU backend (cosine/greedy agreement).
- **Bandwidth cost** (r=16, all 7 projections: 24.3 M params): F16 = 48.6 MB per token (+2.5% over ~1.9 GB of Q4_0
  weights), Q8_0 ≈ 26 MB (+1.4%). r=32 doubles that.
- **Mitigations if dispatch overhead is large:**
  - apply LoRA to fewer modules (q, v, o, down);
  - use r=8–16;
  - fuse A and B across q/k/v.
  - Last resort, a **merged multi-task model**: retrain the v2 agent data and the reasoner data jointly into one GGUF.
    There is no adapter at runtime, but the risk of forgetting the agent task is real (2.43 top-up lessons), and the
    agents would have to be re-accepted.
- **Activated LoRA (aLoRA; Greenewald et al., 2025):** our llama.cpp exposes `llama_adapter_get_alora_*`. With aLoRA,
  the adapter is active only after an invocation sequence, so the base model's KV for the shared prefix (the incident's
  sensor blocks) could be reused between base and adapter. A later optimisation, not needed for v1.

---

## C. Architecture

### C.1 Components
```
                        ┌──────────────────────────── QIDK (offline-capable) ───────────────────────────┐
 sensors → Engine (13 h RAM) ──► rules/event gate ──► Reasoner pipeline (reason.go)                     │
              │                                         ├─ agents batch ──► htpd ctx A (no adapter)       │
              │ 5-min + hourly                          └─ reasoner     ──► htpd ctx R (+ reasoner LoRA)  │
              ▼                                                   ▲  tool calls (JSON)                     │
         SQLite store (store_schema.sql) ◄── ToolExecutor (Go, read-only) ──► Fog client (HTTPS, 1.5 s timeout)
         incident index (all time), maintenance,              ▲                                           │
         readings, tool_call log, outbox ──── sync ───────────┼──────────────────────────────► FOG SERVER   │
                                                              │                                           │
 UI: incident sheet  /  "Ask" chat panel ── /api/ask (SSE) ───┘                                           │
                        └──────────────────────────────────────────────────────────────────────────────┘
 FOG: Postgres(+pgvector) or SQLite(+sqlite-vec) full store · embeddings (Qwen3-Embedding-0.6B) · docs index ·
      LLM server (Qwen3.5-9B) with the same tools + search_knowledge · read-only API for the device
```

### C.2 Tool schema (full text in `tools.json`)
| Tool | Exact? | Where it runs | Used in |
|---|---|---|---|
| `count_incidents(time, domain, metric, node, severity[], pattern, label, approval, include_injected, group_by)` | yes (SQL COUNT/GROUP BY) | fog if online, else device | chat |
| `find_incidents(time, filters…, text, limit≤10)` | yes (list) | fog/device; `text` = BM25 on device, hybrid on fog | chat |
| `get_incident(id, detail)` | — | device (full if retained), else fog | chat, incident ("similar past incident") |
| `sensor_faults(time, domain, basis=ai/confirmed/replaced, distinct_sensors, fault_kind)` | yes | fog/device | chat |
| `get_sensor_history(node, metric, time, agg, stats_only)` | yes; returns evidence lines H1..Hn, not raw series, by default | device (RAM 13 h → SQLite 30 d raw / hourly forever) → fog | incident, chat |
| `related_context(ref, hours)` | — | device (orchestrator causal map) | incident |
| `list_sensors`, `domain_health` | — | device | chat |
| `search_knowledge(query, k)` | — | **fog only**; returns `available:false` offline | chat |

**Design rules:**
- **Typed, closed tools, not text-to-SQL.** The model fills enums and dates and the executor builds parameterised SQL.
  Text-to-SQL by a 3B model is too error-prone, and it is an injection surface.
- **Results are compact.** Counts are integers plus a `coverage` object. Lists are capped at 10 items. History comes
  back as evidence-style lines (the agents' E-line style, `H1..Hn`), so tool results stay at about 100–250 tokens.
- **Enums are enforced at decode time.** The decoder uses htpd's existing label trie (`HTPD_PATTERN_TRIE` + request
  `labels`), extended to the tool-name and enum argument keys. Go re-validates every argument.

### C.3 Decoding protocol and loop (both flows)
- **Format: the Llama 3.x native JSON tool call.** The assistant turn emits `{"name": "...", "parameters": {...}}`
  followed by `<|eot_id|>`, and the result returns in an `ipython` turn (Llama 3.1/3.2 template; llama.cpp `chat.h`
  supports it natively).
- **Final outputs:**
  - incident reasoning: the report JSON (same keys as today plus `severity` and `title`);
  - chat: plain text with `[INC-0123]` citations.
- **Loop in Go (`reasoner_agent.go`):**
  ```
  for step := 0; step < maxSteps; step++ {            // 1 early alert, 2 refinement, 4 chat
      out := htpd.Run(kind="reason"|"chat", prompt, stream=true, labels=toolEnums)
      if call, ok := parseToolCall(out); ok {
          if !schema.Valid(call) || dup(call) { appendToolError(); continue }   // counted against maxSteps
          res := executor.Run(ctx, call)                // read-only, 1.5 s fog timeout, cached per turn
          logToolCall(); appendIpythonTurn(res)          // KV for the prefix is kept: only the new turn is prefilled
          continue
      }
      return policyGate(out)                             // report JSON / chat text + numeric grounding + id check
  }
  return fallback()                                      // incident: today's fallbackReport; chat: templated tool summary
  ```
- **No ReAct free-text "Thought:" lines on the device.** Each one costs decode time at about 20 tok/s. Function calling
  with an implicit plan is enough for 1–3 step queries (ReAct: Yao et al., 2023). Parallel calls (LLMCompiler; Kim et
  al., 2024) are unnecessary: tools run in milliseconds and the cost is NPU decode, not tool latency.

### C.4 Incident-time flow (replaces synthPrompt and reasonerSeverity)
1. **Agents run unchanged** (ctx A, no adapter).
2. **If ≥ 2 informative domains** (today's rule), build the reasoner prompt: today's `synthPrompt` content, with v2
   fields (`event_active`, `onset`, `fault_kind`), the calibrated confidence and the long-range lines.
   - The system turn and the tool schema form a fixed prefix (~600 tokens), **prefix-cached per adapter**
     (`HTPD_SYNTH_PREFIX_CACHE`).
   - The cache key must include the adapter id.
3. **Early alert: maxSteps = 1.** The trained policy is to call `related_context` or `get_sensor_history` only when a
   context domain is missing or ambiguous, for example "is the CO2 rise explained by occupancy?" when no occupancy feed
   exists for that room. Otherwise it answers directly.
4. **Policy gate:**
   - schema;
   - whitelists;
   - evidence ids (`S#.E#`, `R#`, `H#`) must exist in the prompt or in tool results;
   - severity consistency (§A.5);
   - `affected_domains` completion (2.33).

   If the gate rejects the report, `fallbackReport` builds one, as today.
5. **`reasonerSeverity` becomes:** use the reasoner's severity if it passed the gate, else today's rule. The function
   signature is unchanged (severity.go was designed for this swap).
6. **Refinements** (background, `maxSteps = 2`) may fetch 12 h history and look up similar past incidents
   (`find_incidents(text=…, node=…)`) for recurrence ("third time this week").

### C.5 Chat flow
- **API:**
  - `POST /api/ask {session, question}` returns an SSE stream of `step` (tool name + human text), `token`, `card`
    (backend-rendered table or number, with `query_id`), `done {citations, coverage, source: device|fog}`;
  - `GET /api/ask/sessions/{id}` returns the history;
  - `GET /api/tools/{name}?…` is a debug-only endpoint for the deterministic executor.
- **Scheduling:**
  - the existing single NPU queue gets a `chat` job class: after new alerts and operator jobs, before refinements;
  - a chat turn yields between steps if an alert arrives;
  - a turn already decoding finishes its current step, at most ~2–4 s. An alert arriving mid-step waits for it;
  - an htpd `cancel` is a later option.
- **Context management:**
  - **window:** chat context 8192, holding the system and tool schema (~600 tokens), the last 6 turns, and tool
    results summarised after use;
  - **KV stash:** before an agent batch, htpd stashes the chat sequence's KV to RAM and restores it afterwards. If the
    stash is lost, the backend re-sends the transcript;
  - **thermal guard:** chat respects it; when the board is hot, chat answers fall back to the templated
    tool-result-only mode, clearly labelled.
- **Speed trick for counts:**
  - when the tool returns a scalar or a group table, the backend immediately pushes a `card` (the exact number, its
    definition and its coverage);
  - the model then writes one or two sentences of interpretation;
  - the operator sees the correct number in about 1.5–2 s, even before the prose.
- **Example:**
  - **Q:** "How many sensors were faulty this year and had to be changed?"
  - **Calls:** `sensor_faults(time={preset:this_year}, basis=ai)` → 7 sensors;
    `sensor_faults(time={preset:this_year}, basis=replaced)` → 2 sensors;
  - **Answer:** "7 sensors were flagged as faulty this year [INC-0412, …]; 2 of them were replaced (maintenance log).
    Device data covers all 2026 incidents."
  - **Today:** the `replaced` basis returns `count:0, note:"no maintenance records exist"`. The model is trained to say
    that replacements are not being recorded yet, rather than inventing a number.

### C.6 Storage on the device
- **SQLite (`store_schema.sql`)** via `modernc.org/sqlite`, which is pure Go and keeps the `CGO_ENABLED=0 GOOS=linux
  GOARCH=arm64` build in `app/build.sh`.
  - **Writes:** `persist()` (store.go) writes the JSONL line and upserts the index rows in one place.
  - **Rebuild:** the index can be rebuilt from `incidents.jsonl` plus `incidents.archive.jsonl` at start-up.
  - **WAL mode:** brownout-safe (2.34).
- **Retention:**
  - full records: last 1000 (existing `SCE_MAX_INCIDENTS`);
  - index rows: all time (~300 B per incident);
  - readings: 5-min for 30 days, hourly forever, about 10 MB per year for ~30 series.
  - The existing archive file keeps full records off the hot path, as today. Deleting it is a policy choice.
- **New data we must start capturing now** (otherwise questions are unanswerable):
  - **maintenance records**, through a "Sensor replaced / recalibrated / inspected OK" action on the incident sheet;
  - **operator-confirmed faults** (approval of `sensor_fault` incidents already exists);
  - **readings beyond 13 h** (they vanish on restart today).

### C.7 Fog: sync, RAG, routing
- **Sync (device → fog, one-way for data):**
  - an append-only `outbox` of incident versions, maintenance rows, hourly readings and tool-call logs;
  - `POST /sync` batches carry `(device_id, seq)`, are gzip JSON over HTTPS with mTLS, and are idempotent (upsert by
    `(id, version)`);
  - the fog acknowledges the highest seq, and the device deletes rows up to it;
  - a reconnect resumes from the last ack;
  - the fog never sends commands. Model/adapter updates follow the existing manual deploy rule (`.part` + md5 + `mv`,
    app stopped).
- **Fog store:** PostgreSQL with the same tables, plus `pgvector` holding embeddings of each incident's
  title + root cause + explanation + operator note, of maintenance notes and of document chunks (SOPs, equipment
  manuals, HANDBOOK sections). For a single-box fog, SQLite with `sqlite-vec` is enough.
- **RAG:**
  - hybrid BM25 plus vector, top-k 5, with the passages quoted with source ids (Lewis et al., 2020);
  - embeddings: Qwen3-Embedding-0.6B (Apache-2.0, multilingual) or EmbeddingGemma-300M (308M, under 200 MB quantised,
    768-d with Matryoshka truncation, built for on-device use);
  - the device does **not** need embeddings for v1: its tools are structured, and `text` search is BM25 in Go.
- **Routing, done by the executor and not the LLM:**
  - the device model always runs the chat, which keeps latency and behaviour consistent;
  - when online, `count_incidents`, `find_incidents`, `sensor_faults` and long-range `get_sensor_history` execute on
    the fog (complete history) and return `coverage.source=fog`;
  - `search_knowledge` exists only online;
  - offline, the device answers and sets `coverage.complete=false` whenever the time range starts before the oldest
    full record, unless the all-time index covers it.
  - **Escalation:** for open-ended questions ("why does KH03 keep having CO2 problems?") the device can offer
    "Ask the fog model". That sends the question plus the device's tool results to the fog LLM, which runs its own loop
    over the full store and documents, and the answer is labelled as coming from the fog. This is opt-in per question.

### C.8 htpd changes (all backwards compatible, behind flags)
- **Loading:** `--reasoner-lora <path>` loads the adapter once at start-up.
- **New request kinds:**
  - `reason`, the synth context with the adapter attached;
  - `chat`, the same context with a session id, a KV stash and restore, and incremental prefill of new turns only.
- **Decoding:**
  - stops at a closed JSON object (tool call or report) or at EOT for chat text;
  - `labels` extend to the tool name and enum arguments (the existing trie code);
  - prefix-cache keys include the adapter id.
- **Unchanged:** the agents request path (byte-identical when the reasoner is off). Phase 0 verifies this at the
  run-to-run floor (21–24 of 25).
- **Backend switch:** `reasoner_version` file or env (`stub` = today, `lora1` = new), read once at start, mirroring
  `agent_version`.

---

## D. Training and fine-tuning plan

### D.1 Hardware and base
- **Hardware:** laptop RTX 4050 Laptop GPU (6 GB VRAM), sessions of 6–8 h under `run_v2.ps1`-style supervision (WMI
  launch, checkpoints, STOP file, lid open, GPU pause at 76 °C). v2 measured a peak of ~4.2 GiB VRAM at max length
  1152.
- **Base weights:** the **dequantised deployed `ft_v2_q4_0.gguf`**, converted back to HF bf16 with gguf-py, then loaded
  in 4-bit NF4 for QLoRA. The adapter then trains against exactly the deployed base (a quantisation-aware LoRA in the
  spirit of QA-LoRA and LoftQ). This directly attacks the 2.43 lesson that HF gains do not reach the Q4_0 model on the
  NPU.
- **LoRA settings:**
  - r=16 (alpha 32), dropout 0.05, all 7 projections (as v2). Try r=8 if Phase 0 shows op overhead;
  - LR 1e-4, cosine schedule, 2 epochs;
  - loss on assistant tokens only (tool calls and final answers), not on tool results or the system turn;
  - max length 2048, with long chats truncated to the last turns; packing off.
- **Effort:** about 10–14k examples × 2 epochs, averaging ~1.3k tokens. That is roughly 25–35k sequence passes at
  ~2.5–3.5 s each, so **about 20–30 GPU-hours (3–4 sessions)**.

### D.2 Data (generated locally; nothing leaves the laptop)
| Set | Size | How the labels are exact |
|---|---|---|
| **T1 tool traces, single-turn** | ~4k | Synthetic incident histories (12–24 months) are built by running the app's own engine and rules over the real 2025 series, with random scenario injections, random sensor faults (v2 fault kinds) and random maintenance events. They are written into the same SQLite schema, mixed with the real `incidents.jsonl` (32+ incidents). **Question templates** (~150, for counts, group-bys, time ranges, faults, replacements, lists, details and health) are paraphrased by a local teacher; the **gold tool call** comes from the template slots, the **gold answer** from *executing* the tool, and the wording from templates or the teacher, with numbers inserted by code. |
| **T2 multi-turn and follow-ups** | ~1.5k | "And last month?", "which building?", "show me the worst one" → `get_incident`; ellipsis resolution; corrections. |
| **T3 negatives and safety** | ~1k | Actuation requests → recommend plus approval; out of scope → polite no; unanswerable (no maintenance data, offline fog-only) → say so with coverage; prompt-injection text in operator notes → ignore; ambiguous terms → one clarifying question *or* state the assumed definition (trained default: state it). |
| **R1 incident reports** | ~4k | A **compound cross-domain scenario generator** with a causal ground truth extends `server.go Scenarios` (only `crowded_room` is cross-domain today) using the `orchestrator.go` causal map: heat → AC load and power ↑ and indoor temp; occupancy → CO2, power and AC; outdoor PM plus wind → indoor PM; tank leak vs high usage (occupancy); a sensor fault vs a real event (a flatline with a correlated neighbour still moving); **coincidences** (two independent events; label = the dominant one; explanation says unrelated); single-domain with steady context. **Agent findings are the real v2 GGUF outputs** on those windows (run on the host GGUF proxy), so the reasoner learns the agents' real error profile, including invalid or rule-fallback agents. Root cause, label, severity, affected domains and action come from the generator plus the policy tables; the wording comes from templates or the teacher. |
| **R2 tool-using incident reports** | ~1k | Cases where the needed context is missing from the prompt and a `related_context` / `get_sensor_history` call changes the answer, plus matched cases where calling is unnecessary (teaches *when not* to call). |
| **G general retention** | ~0.5k | Self-distilled answers from Llama-3.2-3B-Instruct itself on generic operator chit-chat, keeping conversational tone without third-party data. |

**Teacher:**
- **Default:** deterministic templates for everything numeric. A local LLM is used only for paraphrase and
  explanations: Qwen3.5-4B or 9B on the laptop GPU via llama.cpp, or the fog box once it exists.
- **No cloud teacher.** The rule is that project data never goes online. Kaggle (used before for calibration) only
  with explicit owner approval, since it is an upload.

**QA, as for v2 (`checks_v2.py`):**
- every gold tool call executes;
- every number in a gold answer appears in its tool results;
- every evidence id exists;
- class balance holds;
- a 60-sample private HTML review page;
- hold-outs: test months (Nov–Dec), about 15% of question templates, and about 15% of the scenario compositions are
  never seen in training.

### D.3 Format (one training example, Llama 3.2 template, shortened)
```
<|start_header_id|>system<|end_header_id|>
You are the cross-domain reasoner of a smart-campus edge monitor ... Tools are read-only ...
Never compute counts yourself; call a tool. Cite incident ids. Environment: ipython
[tools.json definitions, compact]<|eot_id|>
<|start_header_id|>user<|end_header_id|>
How many incidents regarding a CO2 spike happened this year?<|eot_id|>
<|start_header_id|>assistant<|end_header_id|>
{"name": "count_incidents", "parameters": {"time": {"preset": "this_year"}, "metric": "co2", "pattern": "spike"}}<|eot_id|>
<|start_header_id|>ipython<|end_header_id|>
{"count": 14, "definition": "flagged CO2 with pattern spike|exp_rise|step_increase, injected excluded", "coverage": {"source": "device", "complete": true, "from": "2026-01-01"}, "query_id": "q81"}<|eot_id|>
<|start_header_id|>assistant<|end_header_id|>
14 incidents this year involved a CO2 spike (counting spikes, exponential rises and step increases on flagged CO2 sensors, demo injections excluded).<|eot_id|>
```

### D.4 Evaluation (gates are judged on the host GGUF proxy first, then on the device through the app)
| Suite | Metric | Gate |
|---|---|---|
| **ToolEval-QIDK** (~600 held-out chat items) | BFCL-style AST match of tool name and arguments; executable match (same result set) | AST ≥ 92%, exec ≥ 95% |
| Counting subset (~300) | exact final number vs SQL ground truth; **ungrounded-number rate** | exact ≥ 98% after the backend card; ungrounded numbers 0 shown (checker) and ≤ 2% generated |
| Negatives / safety (~150) | correct refusal, recommendation, coverage statement | ≥ 95%; actuation compliance 0 |
| **Incident reports** (~500 held-out compound scenarios) | label accuracy, severity accuracy, affected-domain F1, evidence-id validity, policy pass, tool-call appropriateness (precision/recall of "needed a call") | label ≥ today's synth + 10 pts (today's baseline measured in Phase 0); severity ≥ stub; policy ≥ 98% |
| Report quality | operator rubric 1–5 (correct cause, actionable, concise), 50 pairs, blind A/B vs today's synth | win-rate ≥ 60% |
| **Agent regression** | agents identical with the reasoner adapter loaded but not attached | within the run-to-run floor (≥ 21/25 identical; host400 pattern within ±1 pt) |
| **Latency on the device** | reasoner stage p50/p95; chat first visible token, full answer; added NPU time per incident | §A.2 budgets |
| **Through the app** (memory: test through the app) | `stress_app.py` + a new `ask` phase: random questions, faults, offline/online toggles, alerts mid-chat | no board drop, thermal guard respected, ≥ 95% checks |

### D.5 Avoiding the Q4_0 transfer gap
1. Train against the dequantised Q4_0 base (D.1).
2. Export the adapter with `convert_lora_to_gguf.py --base <dequantised v2 HF>` as **F16**. Then try Q8_0 and accept
   only if host GGUF results match F16.
3. **Evaluate checkpoints only as GGUF.** Run the host llama.cpp CPU with base Q4_0 + adapter
   (`proofs/2026-10-22_host_gguf_eval` proxy), then the device. Select the checkpoint on the GGUF score, never on
   HF dev loss.
4. **No imatrix change:** the base GGUF is untouched. The imatrix lever matters only in the merged multi-task fallback,
   where the imatrix must include reasoner and chat prompts.
5. Keep a **forgetting guard** like the v2 top-up: evaluate every ~300 steps on a fixed GGUF mini-suite and stop if it
   regresses.

### D.6 Self-learning after launch
- **Logging:** every chat turn logs the question, tool calls, results, answer and operator feedback (👍/👎 and an
  optional correction) to `tool_call` and the incident log.
- **`export_feedback.py` gains:**
  - SFT positives (approved, grounded);
  - DPO pairs (an ungrounded or policy-repaired answer as *rejected*, the backend's templated or corrected answer as
    *chosen*; DPO: Rafailov et al., 2023).
- **Retraining:** the adapter is retrained periodically on the laptop and deployed as a small file. Any retrain of the
  domain agents (a new base) requires retraining the adapter: a coupling to keep scripted.

---

## E. Phased roadmap

| Phase | Work | Effort | Exit gate |
|---|---|---|---|
| **P0 Feasibility spikes** | (a) Build a random-init r=16 adapter for the v2 GGUF; run htpd on the device (**app stopped, one NPU client, no other daemon**, small push via `.part` + md5 + `mv`): output parity vs the CPU backend, latency overhead per token, memory, agents unchanged with the adapter loaded but not attached. (b) Host GGUF baselines on a 100-item pilot ToolEval: v2 3B prompt-only, base Llama-3.2-3B, Qwen3.5-4B, Qwen3.5-2B. (c) Measure today's synth on 100 compound scenarios (the label baseline). | 2–3 days | LoRA on HTP correct, adapter overhead ≤ 10% per decode token, agents identical → **LoRA path GO**; else choose r/modules or the merged multi-task fallback |
| **P1 Data layer and executor** | SQLite store plus a rebuild from JSONL; readings rollups; maintenance log plus a UI action; ToolExecutor with all 9 tools, coverage logic, synonym tables; `/api/tools/*` debug; Go tests comparing every tool with hand-written SQL on fixtures | 4–6 days | 100% of tests; executor p95 < 20 ms on device |
| **P2 Generators and data** | incident-history synthesiser; question templates and paraphrase; compound-scenario generator with causal labels; run v2 agents on the host GGUF to get real findings; QA checks and review page | 5–7 days | QA green; owner reviews 60 samples (AskUserQuestion) |
| **P3 Training** | QLoRA r=16 on the dequantised v2 base, 3–4 sessions; GGUF eval every 300 steps | 20–30 GPU-h (+ supervision) | host GGUF gates (§D.4) |
| **P4 htpd and backend integration** | `reason` / `chat` kinds, adapter attach, prefix-cache key, KV stash; `reasoner_agent.go` loop; policy gate for reports and chat; `reasonerSeverity` swap; `/api/ask` SSE; chat UI panel with cards and citations; `reasoner_version` switch | 6–8 days | device gates via the app (§D.4), board stable through a full `stress_app.py` plus an `ask` phase |
| **P5 Fog** | fog service (sync endpoint, Postgres or SQLite store, embeddings, docs index, Qwen3.5-9B server with the same tools); device fog client with a 1.5 s timeout; offline/online toggle tests (unplug mid-chat) | 5–8 days (+ fog hardware) | complete-history counts match the device's all-time index; offline fallback always answers with coverage |
| **P6 Latency pass** (accuracy first, then latency) | trim the tool schema; drafts per tool-call template (`HTPD_ROLE_DRAFT`); aLoRA prefix reuse; Q8_0 adapter; r=8 if the gates allow | 3–5 days | reasoner stage ≤ today's synth; chat first token < 2 s p90 |

### Risks and mitigations
| Risk | Likelihood | Mitigation |
|---|---|---|
| LoRA ops slow or unsupported in the patched HTP build | medium | P0 decides early. Fallbacks, in order: fewer modules or lower rank; merged multi-task GGUF (re-accept the agents); time-shared Qwen3.5-4B for chat only |
| **Board instability** during tests | medium | one NPU client, app stopped for device spikes, adapter pushes are small but still use `.part` + md5 + `mv`; no second daemon; collect evidence (`on_reconnect.sh`) |
| 3B too weak for multi-step queries | medium | narrow typed tools, backend cards for numbers, a max-step cap, Qwen3.5-4B comparator in P0/P3, fog escalation for open-ended questions |
| Counting semantics disputed ("spike" vs "rise"; AI-flagged vs confirmed) | high | definitions returned by the tools and shown in answers; `basis` parameter; owner signs off the synonym table |
| No replacement data exists | certain today | add the maintenance action now (P1); until then the answer says replacements are not recorded |
| Chat starved by incidents or thermal throttling | medium | queue priority, a "busy" message, templated tool-only answers when hot; a heatsink (already advised) |
| Base coupling: an agent retrain breaks the adapter | certain on retrain | scripted adapter retrain; adapter metadata records the base md5 and htpd refuses a mismatched pair |
| Sim vs wall time ambiguity in demos | high in demo | the executor states its clock; demo mode defaults to sensor time |
| Prompt injection through notes or documents | low–medium | data-in-quotes, T3 training, read-only tools, policy gate |
| Llama licence attribution | low | "Built with Llama" in the About screen and docs |

### Decisions needed from the owner (to ask via AskUserQuestion before P1)
1. Accept the **LoRA-on-v2-3B** primary plan over a separate Qwen model? This revisits the 2026-10-14 Qwen3-1.7B
   preference.
2. Keep an **all-time compact incident index** on the device (exact offline counts), or strictly the last 1000?
3. Which **definition of "faulty sensor"** is the default: AI-flagged, operator-confirmed, or both reported?
4. Add the **"Sensor replaced / recalibrated" operator action** now, so replacement counts become possible?
5. **Fog hardware** available (GPU VRAM), which picks Qwen3.5-9B vs 35B-A3B.

---

## Sources
- Llama 3.2 3B Instruct model card (BFCL v2 67.0, Nexus 34.3; licence): https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct
- Llama 3 herd of models (Dubey et al., 2024): https://arxiv.org/abs/2407.21783
- Qwen3.5-4B model card (architecture, BFCL-v4 50.3, TAU2 79.9, Apache-2.0, tool parser): https://huggingface.co/Qwen/Qwen3.5-4B
- Qwen3.5 small models release coverage: https://gigazine.net/gsc_news/en/20260303-qwen-3-5-small , https://insiderllm.com/guides/qwen-3-5-small-models-9b-beats-30b/
- Qwen3 Technical Report (BFCL-v3, Qwen3-4B 65.9 non-thinking): https://arxiv.org/abs/2505.09388
- BFCL-v4 aggregated scores (self-reported, unverified): https://llm-stats.com/benchmarks/bfcl-v4 ; https://benchlm.ai/benchmarks/bfclV4
- Berkeley Function Calling Leaderboard (Patil et al., ICML 2025): https://gorilla.cs.berkeley.edu/leaderboard.html ; Gorilla: https://arxiv.org/abs/2305.15334
- xLAM-2 / Hammer2.1 BFCL-v3 figures (aggregator): https://benchmarklist.com/models/xlam-2-3b-fc-r/ , https://benchmarklist.com/models/hammer2.1-3b/
- APIGen-MT / xLAM-2 (Prabhakar et al., 2025): https://arxiv.org/abs/2504.03601 ; Hammer (Lin et al., 2024): https://arxiv.org/abs/2410.04587 ; ToolACE: https://arxiv.org/abs/2409.00920
- Gemma 4 (Apache-2.0, function calling, TAU2 figures): https://the-decoder.com/googles-gemma-4-is-now-available-with-apache-2-0-licensing-for-the-first-time/ , https://ai.google.dev/edge/litert-lm/models/gemma-4
- Phi-4-mini technical report: https://arxiv.org/abs/2503.01743
- Small-model on-device agents: TinyAgent (Erdogan et al., 2024): https://arxiv.org/abs/2409.00608 ; Octopus v2: https://arxiv.org/abs/2404.01744 ; "Small Language Models are the Future of Agentic AI" (Belcak et al., 2025): https://arxiv.org/abs/2506.02153
- Overviews of 2026 small models for tool calling (secondary): https://www.digitalapplied.com/blog/small-language-models-on-device-agents-2026-guide , https://vdf.ai/blog/best-local-llm-for-agents-tool-calling/
- ReAct (Yao et al., 2023): https://arxiv.org/abs/2210.03629 ; LLMCompiler (Kim et al., 2024): https://arxiv.org/abs/2312.04511 ; Toolformer: https://arxiv.org/abs/2302.04761
- Lost in the Middle (Liu et al., 2023): https://arxiv.org/abs/2307.03172
- Indirect prompt injection (Greshake et al., 2023): https://arxiv.org/abs/2302.12173
- RAG (Lewis et al., 2020): https://arxiv.org/abs/2005.11401
- EmbeddingGemma: https://developers.googleblog.com/en/introducing-embeddinggemma/ , https://huggingface.co/blog/embeddinggemma ; Qwen3 Embedding: https://arxiv.org/abs/2506.05176
- LoRA: https://arxiv.org/abs/2106.09685 ; QLoRA: https://arxiv.org/abs/2305.14314 ; QA-LoRA: https://arxiv.org/abs/2309.14717 ; LoftQ: https://arxiv.org/abs/2310.08659 ; DPO: https://arxiv.org/abs/2305.18290
- Activated LoRA (Greenewald et al., 2025): https://arxiv.org/abs/2504.12397
- llama.cpp function calling (Llama 3.x native handler, `--jinja`): https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md
- llama.cpp server LoRA hot-swap (`--lora`, `--lora-init-without-apply`, `/lora-adapters`, per-request `lora`): https://github.com/ggml-org/llama.cpp/tree/master/tools/server ; discussion: https://github.com/ggml-org/llama.cpp/issues/10374
- llama.cpp Hexagon backend (experimental, PR #16547; Q4_0/Q8_0/MXFP4): https://dragonwingdocs.qualcomm.com/blogs/llamacpp-on-dragonwing
- Local source checked (the build htpd links): `C:\Users\hp\gpu_work\llama.cpp` — `include/llama.h` (`llama_set_adapters_lora`, aLoRA API), `src/llama-adapter.cpp` (adapter buffer placement), `src/llama-graph.cpp` (`build_lora_mm`), `ggml/src/ggml-hexagon/ggml-hexagon.cpp`, `docs/ops/Hexagon.csv` (F16 MUL_MAT 281/281, GATED_DELTA_NET 36/36 supported)
- Project evidence: HANDBOOK 2.15, 2.27, 2.32–2.33, 2.37–2.43; `proofs/2026-10-16_htp_bringup` (PP ~970 tok/s, TG ~19 tok/s, 1 stream); `app/backend/{reason.go, severity.go, store.go, orchestrator.go, server.go}`; `app/htpd/htpd.cpp`; `training/RETRAIN_V2_SPEC.md`, `training/v2/train_v2.py`
