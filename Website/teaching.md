# Teaching guide: the evidence website, explained

This guide is for the team. Read it and you should be able to explain every page, chart, number, decision,
sensor and answer on the evidence website, and handle the follow-up questions.

- **How it is ordered.** Each part starts in plain language and then gives the exact detail.
- **Where the numbers come from.** Every number is copied from the site's data (`Website/data/...`). The dataset id is given in backticks, e.g. `acc_device54_engines`.
- **When the data disagree with memory, the data win.** Always quote the dataset.

Contents
1. The project in 10 lines
2. Glossary
3. How to read the site
4. Every dataset and graph (by topic)
5. Every decision, and how to defend it
6. The sensors and the raw data
7. Use case and measured situations
8. Statistics primer (with worked examples from our data)
9. Honest limits and what we say if asked
10. Q&A cheat sheet

---

## 1. The project in 10 lines

1. **What.** "Agentic Edge AI for Smart Cities" is an AI that watches the IIIT-H campus sensors and writes a short report when something goes wrong. The sensors cover indoor and outdoor air, water, power, HVAC, weather and occupancy. Each report says what happened, how bad it is, the likely cause and a safe action, and every claim cites a numbered piece of evidence. There are 174 sensors and 33.2 M readings for 2025 (`uc_coverage`).
2. **Why.** Threshold rules raise 20,538 warning/critical breaches in a year (`uc_breaches_monthly`). Only 7,767 of those last 8 or more readings (`uc_breaches_need_action`), and the rules explain none of them. At the same detection rate (78%), our agents cut false alarms on calm windows from 43% to 27% (`uc_alert_reduction`).
3. **Where it runs.** Everything runs on one Qualcomm **QIDK** board, with no cloud and no laptop: sensor statistics, AI inference, safety checks and storage. The board uses the **Snapdragon 8 Gen 3 (SM8650)** chip, and the AI runs on its **Hexagon NPU (V75)**. Zero bytes leave campus per incident (`uc_edge_offline`).
4. **The model.** It is one **Llama 3.2 3B** model, fine-tuned with **QLoRA** on worked examples built from the real campus data. v1 had 6,480 examples in 5 roles. v2, now in training, has 35,946 training rows in 6 roles, including a new HVAC agent. The model was quantised to 4-bit with **GPTQ** so it fits and runs on the NPU.
5. **Three modes.** **Mode 1** is rules only (the status quo baseline). **Mode 2** is a single AI call over all problem sensors. **Mode 3** is the multi-agent mode: one **domain agent** per alarming sensor, then a **synthesizer** (the "reasoner") combines their findings into one root cause.
6. **When the AI is called.** Cheap statistics run all the time. The **event gate** calls the AI only when a sensor stays warning, critical or faulty for **8 readings**. Sensors that alarm together are batched into one incident.
7. **htpd.** This is our own batched NPU daemon, built on llama.cpp's Hexagon backend. It serves all the agents of an incident in one sweep over the model weights. A 12-agent incident fell from about 47 s on Qualcomm's Genie runtime to 20.7 s (`lat_chaos_genie_vs_htpd`), with no loss of accuracy (`acc_device54_engines`).
8. **Refinement and 12 h checks.** The first report is an **early alert**. Each Mode 3 incident is re-analysed automatically at **+1.5 h and +3 h** of sensor time, because accuracy rises from 42% at 40 min to 88% at 3 h (`ad_placement_curve`). Two CPU checks look at the last **12 h**, one for level shift and one for slow drift. They raise old steps caught from 73% to 93% (`ad_longrange_arms`).
9. **Safety.** A **policy gate** checks every AI answer: valid JSON, whitelisted labels, real evidence ids, and no shut-down or actuation orders. The AI never actuates anything: a **human approves or dismisses** every recommendation, and those verdicts become new training data (`uc_human_in_loop`).
10. **Where we are.** The v1 model runs on htpd on the QIDK today:
    - device pattern accuracy 90.7%, n = 54;
    - median incident 3.8 s;
    - app stress test 132/135, and the 3 failures were heat.

    The v2 retrain is 60% done: step 2,685 of 4,494 in the build-time status, best dev loss 0.066 at step 2,400 (`status.json`, `tv2_loss_curve`).

---

## 2. Glossary

Each line gives the meaning, then why the term matters for this project. Terms are grouped by area.

### Hardware and runtimes
| Term | Meaning | Why it matters here |
|---|---|---|
| **QIDK** | Qualcomm Innovators Development Kit: a phone-class development board. | Our edge device. Everything runs on it. |
| **SM8650 / Snapdragon 8 Gen 3** | The system-on-chip inside the QIDK. It has CPU cores, an Adreno 750 GPU and a Hexagon NPU. | Fixes what the hardware can and cannot do. For example, it does not support `w4` precision (fp16 activations); Qualcomm lists that only for 8 Elite / X Elite. |
| **NPU** | Neural Processing Unit: the chip's AI accelerator. | Runs our model. It is faster than the GPU at every incident size (`hw_grid`). |
| **Hexagon / HTP** | Qualcomm's DSP/NPU family. HTP = Hexagon Tensor Processor, the NPU proper (version V75 on this chip). | "llama.cpp Hexagon backend" and "HTP" both mean "running on the NPU". |
| **HMX** | Hexagon Matrix eXtensions: the NPU's matrix-multiply unit. | Our patch `GGML_HEXAGON_HMX_PIPE_ALL=1` pipelines decode-sized matmuls on HMX. In the A/B harness, v4 (which includes it) brought 13 agents from 28.1 s to 17.5 s (`lat_htpd_ab`). |
| **Adreno 750 GPU** | The phone GPU, run through llama.cpp OpenCL. | The professors' "why not GPU?". It needs about 8.4 s per agent and gains nothing from batching (`hw_gpu_batched`, `hw_grid`). |
| **DDR / memory bandwidth** | How fast weights stream from RAM to the NPU. | Decode moves 2.20 GB of weights per token, at about 49.3 GB/s, which is ~84% of the 59 GB/s NPU DMA ceiling. Decode is bandwidth-bound, so the lever is fewer weight sweeps (batching), not config knobs (`lat_call_breakdown`, folded `lat_bandwidth_roof`). |
| **SMMU / unmovable memory** | NPU and GPU buffers must fit in a 7.26 GB "Normal" memory zone. | A second 3B model makes Android's OOM killer reboot the board. That is why only one model is on the NPU at a time (HANDBOOK 2.27, 2.37). |
| **Genie** | Qualcomm's GenAI runtime for LLMs on the NPU (from AI Hub). | Our first NPU runtime (the "Genie era"). It cannot batch. |
| **genied** | Our persistent Genie daemon: one dialog kept alive instead of one process per call. | One call went from 3640 to 2543 ms, and first token from 1.2 s to 0.31 s (`lat_genied`). |
| **Qualcomm AI Hub** | Qualcomm's cloud service that quantises and compiles a model for SM8650. | Produced the Genie bundle (w4a16). |
| **QAIRT / QNN / SNPE** | Qualcomm's lower-level AI SDKs. | Considered and not used for the LLM (`uc_edge_offline`, folded `hw_platform_paths`). |
| **llama.cpp** | An open-source C++ LLM runtime with CPU, OpenCL (GPU) and Hexagon (NPU) backends. | Its Hexagon backend is the base of htpd. Its OpenCL backend was used for the GPU study. |
| **GGUF, Q4_0 / Q8_0** | llama.cpp's model file format and its 4-bit and 8-bit block-quantised weight types. | Our device weights were repacked exactly into GGUF Q4_0/Q8_0 so htpd runs the *same* weights as Genie. |
| **htpd** | Our batched NPU daemon: a TCP server on port 8091 holding one model with two contexts. The agent context has 13 streams x 768 tokens; the synthesizer context is 4096 tokens. | The main latency lever. Version v6 is deployed. |
| **adbd loopback** | The board's own Android debug daemon, at 127.0.0.1:5555. | Android apps cannot open the NPU. Our app asks the local adbd to start the backend as the shell user, which can (`hw_platform_paths` A11 failed, A12 shipped). |
| **Thermal guard** | Software that pauses NPU work when the board is too hot. | Chaos peaks reach 95-96 °C. The only app stress failures were thermal (`hw_board_thermal`, `ux_stress_runs`). |

### Model and training
| Term | Meaning | Why it matters here |
|---|---|---|
| **Llama 3.2 3B (Instruct)** | Meta's 3-billion-parameter instruction model. | Small enough for a phone NPU (about 2.9 GB bundle), yet good enough once fine-tuned. |
| **Fine-tune / SFT** | Further training on our own worked examples (supervised fine-tuning). | Pattern accuracy rose from 20% (base) to 94% (fine-tuned) on the laptop eval (`acc_v1_host_eval`). |
| **LoRA** | Low-Rank Adaptation: train small add-on matrices instead of all the weights. | Makes training fit a 6 GB laptop GPU. |
| **QLoRA** | LoRA on a 4-bit (NF4) quantised base model. | What we used for both v1 and v2. |
| **LoRA rank (r)** | Size of the add-on matrices. More rank means more capacity, plus more memory and time. | v2 uses r = 32 (`tv2_plan`). |
| **Adapter / merge** | The trained add-on (~100 MB), folded into the full model before export. | Merge, then export, then device test. |
| **Step / epoch / grad accumulation** | One optimiser update. One epoch is one pass over the data. Grad accumulation sums 16 mini-batches per step. | v2 runs 2 epochs = 4,494 steps at about 40 s/step. Logged train loss is divided by 16 to compare it per token (`tv2_loss_curve`). |
| **Train / dev loss** | Error on the training data, and on held-out development data. | If dev loss rises while train loss falls, the model is overfitting. That has not happened so far: per-token train loss is about equal to dev loss. |
| **Quantisation (int4, w4a16)** | Store weights in 4 bits. `w4a16` means 4-bit weights and 16-bit activations. | Needed to fit and to speed the NPU. It cost accuracy until GPTQ (`acc_quant_waterfall`). |
| **RTN** | Round-to-nearest quantisation (plain rounding). | 73.9% pattern on host (diagnostic) vs 89.1% with GPTQ. |
| **GPTQ** | Post-training quantisation that rounds weights one column at a time and corrects the error it introduces in the remaining columns, calibrated on our own prompts. | Recovered most of the int4 loss. The weights land exactly on the int4 grid, with 0 mismatches over 1,232 tensors. |
| **MSE-clipped scales** | Clipping weight ranges to minimise mean squared error. | Rejected: it made accuracy worse (39.1%) because it cut the few large weights LLMs rely on. |
| **Activation ranges / calibration** | The min/max ranges used to quantise activations. | Recalibrating them on Kaggle with 149 k tokens gave no gain once BOS was fixed, so the published ranges were kept. |
| **BOS token / double BOS** | The beginning-of-sequence token. Genie adds its own, so our prompts carried two. | The single biggest device loss: fixing it took the same weights from 67.4% to 82.6% (`acc_quant_waterfall`). |
| **NF4** | 4-bit NormalFloat, the format QLoRA uses for the frozen base on the laptop. | The "host 4-bit" numbers (94%) come from NF4, not from the NPU format. |
| **Imatrix** | Importance matrix: guides GGUF quantisation using activations from real prompts. | The planned v2 export path (GGUF Q4_0 with an imatrix from our own prompts). |
| **SFT positives / DPO pairs** | Training data from operator verdicts: approved answers (SFT), and preferred-vs-rejected answer pairs (DPO, Direct Preference Optimisation). | Self-learning. One approved incident gave 2 SFT positives and 1 DPO pair (`uc_human_in_loop`). |
| **Teacher rules** | The rule engine that produced the status, cause and action labels for training. | Makes the status, cause and action comparisons with Mode 1 **circular**. Only *pattern* is an independent comparison (`acc_v1_rules_vs_llm_fair`). |

### Inference and latency
| Term | Meaning | Why it matters here |
|---|---|---|
| **Token** | A word piece, the unit the model reads and writes. | Fewer output tokens means less decode time. The fine-tuned model writes 84 tokens vs 199 for the base (`acc_v1_output_tokens`). |
| **Prefill** | Processing the whole prompt in parallel before the first output token. | About 1380-1481 tok/s on Genie. It is the smaller part of a call. |
| **Decode** | Generating the output one token at a time. Each token streams all the weights once. | 70-78% of a call (`lat_call_breakdown`). Bandwidth-bound. |
| **TTFT** | Time to first token. | 1.2 s became 0.31 s with genied. |
| **tok/s** | Decode speed in tokens per second. | ctx 2048 raised it from 20.7 to 25.0 tok/s (`lat_ctx2048`). |
| **Context window (ctx)** | The maximum number of tokens (prompt plus output) the model can hold. | ctx 2048 by default; ctx 4096 only for big prompts such as chaos synthesizer prompts (~3,400 tokens). Evidence is never trimmed to fit. |
| **KV cache** | Stored attention keys and values of past tokens, so they are not recomputed. | Its size is read on every decode step: 469 MB at ctx 4096 vs 235 MB at ctx 2048. |
| **Prefix cache** | Keeping the KV of the unchanging system-prompt prefix of each role across incidents. | Prefill fell from 8.7 to 6.8 s for 13 agents (HANDBOOK 2.37). |
| **Batching / streams** | Running many prompts together, so one weight sweep serves all of them. | The core idea of htpd: 13 agent streams per sweep. |
| **Flash attention (FA streams)** | A memory-efficient attention kernel. Our patch runs it per stream on the NPU. | Without it, batching was not faster than running agents one by one. |
| **Drafting (n-gram, verified)** | Guess the next few tokens from earlier text, then check all the guesses in one pass. A guess is kept only if it equals what greedy decoding would produce. | Lossless speed: 13 agents went from 22 to 16.4 s (HANDBOOK 2.37). |
| **Speculation on the synthesizer / LADE** | Other speed-up methods (lookahead decoding, speculation) that are not lossless here. | Rejected: they changed the answers. With LADE, 13 of 14 answers changed and a stuck sensor was read as normal (`lat_rejected_ideas`). |
| **Grammar-constrained decoding** | Forcing the output to follow a JSON grammar. | Rejected: about +0.45 s init and no tokens saved. |
| **Continuous batching** | Adding requests to a running batch. | Rejected on QAIRT 2.50: it cut 11 of 12 answers short. |
| **Greedy decoding** | Always pick the most likely token (no sampling). | Makes answers reproducible and cacheable. The bundle defaulted to temperature 0.8 until we forced greedy. |
| **NEON argmax** | ARM SIMD code that finds the most likely token, with the same first-max tie-break. | v6: A/B total went from 30.3 to 27.7 s, with 25/25 identical texts. |
| **Byte-identical / noise floor** | The same outputs, character for character. Batched float sums are not bit-reproducible, so the same binary run twice gives 21-24 of 25 identical. | "Identical" claims are judged against that floor (`lat_htpd_ab`). |
| **Exact-prompt cache** | Re-using the stored answer when an identical prompt is re-run. | A compare rerun takes 0 NPU calls and about 3 ms. |

### Agent design
| Term | Meaning | Why it matters here |
|---|---|---|
| **Mode 1 / 2 / 3** | Rules only / one AI call / domain agents plus synthesizer. | Mode 1 is the status-quo baseline. Mode 3 is the shipped design. |
| **Domain agent / role** | One AI call that analyses one sensor of one type (air, water, power, weather, occupancy; HVAC in v2) over its window. | Specialised prompts, so the agents can run in parallel in one htpd batch. |
| **Synthesizer / reasoner** | The cross-domain AI call that combines the agents' findings into one root-cause label and report. | The planned cross-domain reasoner replaces today's stub for severity and titles. |
| **Pattern** | The shape the agent names. The 12 v1 patterns are spike, dip, step_increase, step_decrease, gradual_increase, gradual_decrease, exponential_increase, oscillation, erratic, flatline, throttling and stable. | Pattern accuracy is our main independent accuracy measure. |
| **Status / severity** | normal, warning, critical or sensor_fault. Incident severity follows the reasoner (critical > warning > sensor_fault > normal). | Before 2.38, severity was fixed by the rules when the incident was created. |
| **Cause / action** | Likely cause label, and safe action label (derived by policy from cause and status). | Deriving the action: 0.778 → 0.815 (`acc_device54_engines`, folded). |
| **Evidence ids (E1-E8, E9/E10)** | Numbered facts in the prompt (statistics, trend, jumps...). E9 = 12 h view (level shift / drift); E10 = recent episodes. | Every claim must cite real ids. The policy gate rejects invented ids. |
| **Policy gate** | The automatic check on every AI answer: JSON, whitelisted labels, real evidence ids, no actuation. | 44/44 agent answers passed in the final app run (`uc_human_in_loop`). |
| **Transparent repairs** | Gate fixes that are recorded in the incident's `repairs` field: derive a missing action, split packed evidence ids, salvage malformed JSON. | Raised the agent pass rate from 3/6 to 5/6 on the demo scenarios (`ad_policy_gate`). |
| **Event gate** | Calls the AI only when a warning, critical or fault status lasts **8 readings** (persist readings). It re-arms after the sensor returns to normal. | 2,000 calm readings produced 0 incidents (`uc_alert_reduction`, folded `ad_event_gate`). |
| **Persist readings (8)** | The number of consecutive abnormal readings needed. 8 x 5 min = 40 min of sensor time, about 16 s at the 2 s demo poll. | The agents were trained on events at least 7 readings old. Younger windows were misread. |
| **Batch window** | A short wait so that sensors alarming together join one incident. It closes after 1 reading when no other sensor is waking up. | -4 s on every isolated incident (`lat_batch_window`). |
| **Poll / demo clock** | One reading every 2 s of wall time = 5 min of campus time. | All "16 s", "37 s" and "74 s" demo times come from this clock. |
| **Window length** | How much history an agent reads. 48 points x 5 min = 4 h. | 4 h was best (pattern 64%); 2, 8 and 12 h were all worse, p < 0.0001 (`ad_window_headline`). |
| **Event age / time since onset** | How long ago, at the window's end, the event started. | Accuracy rises with age: 42% at 40 min, 88% at 3 h (`ad_placement_curve`). |
| **Placement study** | The same 208 events placed at 6 onsets (20 min to 3 h before the window end). | Shows why refinements exist. |
| **Refinement (EARLY / REFINED 1.5 h / 3 h)** | Automatic re-analysis of every Mode 3 incident 18 readings (1.5 h) and 36 readings (3 h) after the original window. | The refined finding replaces the early one, and the history is kept. |
| **12 h checks (level shift, slow drift)** | CPU detectors over the last 12 h of each flagged sensor. They add evidence lines E9/E10. | Old steps 73% → 93% (p = 0.0005); drifts 83% → 95% (p = 0.016). |
| **Recurring-excursion detector / daily baseline** | Two candidate 12 h detectors: repeated small excursions, and "same hours yesterday". | Both rejected, because real sensors do both all the time (`ad_longrange_ablation`, `ad_daily_baseline_rejected`). |
| **Old step / long drift / recurring small spikes** | Case families: a step 2.5-8 h ago; a drift over 6-12 h; repeated sub-threshold spikes. | The families the 4 h agent misses. Recurring small spikes are still unsolved (32-52%). |

### Data and evaluation
| Term | Meaning | Why it matters here |
|---|---|---|
| **Threshold breach** | One contiguous run above a warning or critical limit on one metric. | 20,538 breaches in 2025 (`uc_breaches_monthly`). |
| **Warning / critical / floor** | Per-metric limits from `training/features.py`. The floor is the minimum noise/size used so tiny changes are not treated as events. | See section 6 for every metric. |
| **Calm window** | A real 4 h window whose truth is "normal": no rule fires and no injection. | Injections ride on calm windows, and false alarms are measured on them. |
| **Injection** | A synthetic pattern or fault added to a real calm window, so the true label is known exactly. | Gives exact ground truth on real sensor noise. |
| **Hard negative / routine** | A real or synthetic normal behaviour that looks like trouble: tank refill, load switching, daily cycles, HVAC cycling, schedules. Labelled normal. | v1 called about 31% of routines alarms. v2 trains on them (`ds_routine`). |
| **Train / dev / test split (by month)** | Train Jan-Aug, dev Sep-Oct, test Nov-Dec 2025. | Time split: no future data leaks into training. Detectors were tuned on dev and tested once on test. |
| **Held-out sensors (seen / unseen)** | About 15% of sensors per role are never used in training (v2). Results are reported separately for seen and unseen sensors. | Tests generalisation to new sensors (`ds_heldout`). Weather is tested on seen stations only (a stated limit). |
| **Leakage** | Test information reaching training. | Prevented by the month split, held-out sensors, and dev-only tuning. |
| **Case family** | A kind of example (e.g. old step, long drift, sensor fault, routine). | `ds_families`, `ad_window_per_family`. |
| **Detection rate (flag rate)** | Fraction of injected events where the system says "not normal". | 78% for rules vs 77.5% for agents: equal (`uc_alert_reduction`). |
| **False alarm (rate)** | Fraction of calm windows (truth normal) flagged as not normal. | 43% for rules vs 27% for agents (`uc_alert_reduction`). It is over-counted, because "calm" real data still holds real events. |
| **Pattern / status / cause accuracy** | Fraction of answers whose label equals the gold label. | The headline metrics. |
| **Chaos test** | Every sensor failing at once in one incident. | The worst case for latency and heat. 10-12 agents plus the synthesizer now take about 21 s, down from 40.8-48.9 s on Genie (`ux_chaos_incidents`). |
| **Fault injection (app)** | Deliberately breaking things on the device (killing processes, bad outputs...) to test recovery. | Before vs after the fixes (`ux_fault_injection`). |
| **Stress run** | A scripted run of scenarios and chaos through the real app API, with pass/fail checks. | 132/135 on the final build, 238/240 earlier (`ux_stress_runs`). |

### Statistics (details in section 8)
| Term | Meaning | Why it matters here |
|---|---|---|
| **n** | The number of samples behind a value. | Always read it. n = 54 is small; n = 2416 is large. |
| **95% CI (Wilson)** | A confidence interval for a proportion that stays sensible near 0% and 100%. | The whiskers on every accuracy bar. |
| **95% CI (t)** | A confidence interval for a mean of a few timed runs, using Student's t. | Used for timing means with n = 3 (`lat_call_breakdown`). |
| **McNemar (exact)** | A paired test: on the same cases, compares "only A right" against "only B right". | The right test for "same windows, two systems" (`acc_device54_engines`, `ad_longrange_arms`, `ad_placement_curve`, `ad_window_headline`). |
| **Two-proportion z-test** | An unpaired test of two rates. | What the Proofs page's automatic "Analysis" line uses. |
| **p-value** | If there were truly no difference, the probability of seeing a difference at least this large. | p < 0.05 counts as "significant". p = 0.45 means "no evidence of a difference". |
| **Effect size, Cohen's h** | Difference between two proportions on an arcsine scale. 0.2 is small, 0.5 medium, 0.8 large. | Says whether a significant difference is also a big one. |
| **n.s.** | Not significant (p ≥ 0.05). | Read it as "no worse", not "better". |
| **Pareto front** | The best detection achievable at each false-alarm rate. | Used to tune the 12 h detectors (`ad_detector_tuning_frontier`). |
| **Ablation** | Remove one component and re-measure. | With vs without the recurring-excursion detector (`ad_longrange_ablation`). |

---

## 3. How to read the site

### 3.1 Access: password and encryption
- **One password.** There are no accounts. The password is checked against a **bcrypt** hash (cost 12) stored in the site.
- **Everything is encrypted.** Every content file is encrypted: page bodies, data JSON and screenshots. Each `dist/**/*.enc` file holds a 12-byte IV followed by AES-256-GCM(gzip(plaintext)), with a 16-byte tag.
  - The key is derived with **PBKDF2-SHA256** (600,000 iterations, random salt) from the same password.
  - bcrypt and PBKDF2 run in parallel. The key is kept only if bcrypt accepts the password and the key decrypts a canary file.
- **Session only.** After unlock, the key lives in `sessionStorage` and is gone when the tab closes. The **lock** button clears it at once.
- **Failed attempts.** After 3 failures, each try must wait longer: 1 s, 2 s, 4 s and so on, up to 30 s (per tab).
- **Hosting.** The site is static on Cloudflare Pages, with no server code. Every library is vendored (no CDN at runtime). The password is never stored in plain text.
- **What to say.** "The files on the server are unreadable without the password. Decryption happens only in your browser."

### 3.2 Navigation
- **Nav bar.** One floating pill nav: **Deck · Route · Decisions · Proofs · Raw data · Q&A**.
- **Start here.** A "Start here" path on the Deck page leads through **Route → Decisions → Q&A**. Every other page ends with a "Next →" link (the Deck has none since 2026-10-19: Start here is its next step).

### 3.3 The pages
**Deck (home).**
- Title: "An AI agent that reads building sensors and reports faults, on the phone chip, offline".
- Two anchor numbers, read live from the data:
  - **≈ 47 s → 20.7 s**: a 12-agent incident, Genie → htpd (`lat_chaos_genie_vs_htpd`);
  - **42 % → 88 %**: agent pattern accuracy at alert time (40 min) → refined at 3 h, n = 208 events (`ad_placement_curve`).
- A **status strip** from `status.json`: v2 training step (with a progress bar), best dev loss, ETA, and what is deployed. A link under it, "Training v2: progress, losses, interruptions, acceptance →", opens the Route training section.
- A **deck viewer.** Drop in a **PDF** (rendered exactly with pdf.js) or a **PPTX** (best-effort renderer). It plays full-screen with arrow keys, click or swipe, and shows a slide counter. The file stays in memory only: it is forgotten on reload and never uploaded.

**Route.** The chronological story.
- **No separate anchor row** (since 2026-10-19): the page's one statement is "22 steps from spec to a standalone board". The 47 s → 20.7 s anchor stays on the Deck, and 54 % → 90.7 % is the Accuracy route card, so neither is repeated.
- **The journey.** 22 steps from the spec (2026-09-17) to this site (2026-10-19). They sit in 4 collapsible phases: "Build v1 on the laptop", "Onto the board", "After the mid-evaluation", "Retrain v2 and this site". Only the last phase starts open.
  - Each step shows date, phase, what was done, a before → after metric, and an outcome badge.
  - Outcomes: **Kept 17, Dropped 2** (GPU study, daily baseline), **Pending 3** (mid-evaluation asks, v2 training, evidence site).
  - Filter chips show All / Kept / Dropped / Pending. Clicking a step opens its evidence chart inline.
- **Training v2 · where it stands** (new 2026-10-19, `#/route?s=training`). The professor's "where is training, and what then?" in one place:
  - statement "60 % trained: step 2,685 of 4,494" and a full-width progress bar, with best dev loss (step), s/step, training hours left, state and build time, all from `status.json` (read from the training log when the site is built);
  - **loss card** (`tv2_loss_curve`, log scale): dev loss at every eval (8 so far, 0.131 → 0.066) and train loss per token every 5 steps; train sits on dev, so no overfitting;
  - **sessions card**: optimizer step over wall-clock time (folded `tv2_progress`), with a red hollow dot for each of the 8 interruption causes (hover: cause and fix) and a "Causes and fixes" table (start failure, RAM, BSOD 0xD1 in vfpext.sys, thermal sleep, supervisor death, checkpoint interval, lid standby, battery);
  - **What v2 changes, and why**: young events, any window length (2-12 h, 21 lengths), 12 h history line, new patterns and 7 fault kinds, 8,292 routine hard negatives, HVAC agent (6 roles, 35,946 examples vs 6,480, LoRA r=32), at most 2 observations plus new fields;
  - **v2 ships only if it beats v1 on the board**: the acceptance criteria (spec #20) as a checklist and the five steps after training (best checkpoint → merge → GGUF Q4_0 for htpd → acceptance, v1 kept as revert → latency pass → confidence recalibration and the reasoner).
- **Latency route.** Three waterfall tabs:
  - **13 agents** (`lat_route_13_agents`): starts at ≈ Genie 22-25 s (midpoint). htpd v1 is *slower* at first (a red bar). HMX pipe, drafting and caches win it back, down to 14.7 s.
  - **3-call incident** (`lat_route_incident`): crowded room, 18.7 s → 11.6 s.
  - **One agent call** (`lat_route_agent_call`): ≈ 3.9 s → 2.5 s. Bars marked ≈ are derived: separately measured deltas applied to the first value.
- **How to read a waterfall.** Each bar is one change, and its height is the time saved (or added). The last bar is where we ended.
- **Tried and rejected.** A strip of 13 speed ideas, each with its loss written out. For example, "Parallel NPU sessions: would make 4 agents 3× slower: 23.6 s → 76.5 s" and "LADE: would change 13 of 14 answers". Clicking one opens its evidence.
- **Accuracy route.** A line chart of pattern accuracy:
  - kept route (blue): fine-tuned laptop 94% → 1st NPU export 54.3% → GPTQ → BOS fixed 82.6% → live 54 windows 85.2% → htpd 90.7%;
  - dropped tries (red hollow dots): base model 20%, MSE-clipped 39.1%, recalibrated 60.9%.
  - Headline: "a prompt bug mattered most" (the double BOS).
- **Peak-end card.** "The shipped agent now catches 93% of old steps (was 73%)" (`ad_longrange_arms`).

**Decisions.** Every decision we took and every option we rejected (section 5).
- Topic filter: Use case, Latency, Hardware, Accuracy, Agent design, Refinement, Training (= training_v2 + dataset_v2), App/UX, Ops (= ops + timeline).
- Status filter: **Kept / Replaced / Pending**.
- Each card shows what was chosen, why, the evidence chart, and the rejected options, each with what it would have cost.
- **7 featured groups** show first (was 12 before 2026-10-19); "Show all 30" opens the rest.
- If the evidence text contains "n.s.", "not significant", "within noise" or only p ≥ 0.05, the page labels the result **"no worse"**, not "better". Example: htpd vs Genie accuracy, p = 0.45.

**Proofs.** Every measured result, as one card per dataset.
- **At most 7 cards per tab** (since 2026-10-19); a "Show N more results" button adds the rest. The Training v2 tab starts with an "Overview" link to the Route training section.
- **Tabs.** 11 topic tabs, each with a count: Use case 9, Latency 11, Hardware 5, Accuracy 7, Agent design 12, Refinement 2, Training v2 5, Dataset v2 10, App/UX 6, Ops 2, Timeline 1. That is 70 datasets, plus more folded inside them.
- **What a card has:**
  - the **claim** (the takeaway) above the chart, and **why it matters** below it;
  - `n` and unit, and a method line ("made by `<script>`" plus the first sentence of the notes);
  - an automatic **Analysis** line comparing ours with the baseline. It gives the difference, the 95% CI of the difference, a p-value from a two-proportion z-test (or from the two CIs) and Cohen's h. Hover to see all comparisons.
- **Buttons on a card:**
  - **Numbers**: the data as a table;
  - **Δ vs baseline**: a dot chart of the differences, green = better, red = worse, grey = **n.s.** with an "n.s." badge;
  - a script chip;
  - a **source chip**, which links to `#/proofs?file=<path>` and lists every result citing that file.
- **Table cards.** Some datasets show as tables, not charts: platform paths, scenario outcomes, two-windows, self-learning.
- **Deep links.** `#/proofs?id=<dataset>` or `?file=<path>`.
- **Also on the page:**
  - a **screenshot gallery** of the app: 7 before screens (14 Oct), 8 after screens (16 Oct report page) and 10 refined re-analysis screens. Some states are synthetic, and most after-screens come from a laptop backend with mock agents unless marked QIDK.
  - **Download the numbers**: 8 gzip packs of aggregates and per-sample scores, with no raw inputs. They are decrypted in the browser.
- **Caveat.** The automatic Analysis line uses an *unpaired* test. Where the dataset has its own paired McNemar test, quote that one instead (it is the stricter and more correct test; see 8.4).

**Raw data** (`#/rawdata`, also linked from Proofs). The cleaned SCRC sensor data for 2025, encrypted.
- **Views:** a sensor picker, then a **Year** view (hourly), a **Week** view and a **Day** view (full 5-min detail).
- **Overlays:**
  - warning/critical thresholds;
  - breaches with reasons;
  - shaded train/dev/test months (blue/amber/violet bands);
  - held-out sensors;
  - the windows used as training bases (v1 teal, v2 pink).
- **Analysis panel and story.** There is an analysis panel per sensor and metric. A "From raw windows to training examples" panel says: "Only calm real windows became bases; every label comes from a known injection or rule".
- **Privacy.** Occupancy rooms appear only as codes (Room A, B…). See section 6.

**Q&A.** 84 professor-style questions (build of 2026-10-19 20:13), each with a one-line answer and its evidence charts. Some answers also carry a "situation" card from `data/situations/` (chaos, crowded room, PM spike, power throttling, stuck sensor, tank leak, ventilation failure).
- **Use case.** A "Use case" block sits near the top, with two anchors (20,538 breaches → 2,190 persistent and critical; false alarms 43 % → 27 %). The 47 s → 20.7 s anchor is no longer repeated here (it is the Deck anchor).
- **Search.** Offline search with a synonym map (e.g. "gpu" also finds "npu"/"adreno", and "fp" finds "false alarms") and one-typo tolerance.
- **Topic chips.** 17 categories: use case 12, accuracy 10, agent design 7, latency 7, data 7, situations 5, hardware 5, safety 5, false alarms 4, next 4, status quo 3, model 3, training 3, thermals 3, robustness 2, limits 2, status 2.
- **Side card and end.** One "What we have not measured yet" card (energy, Mode 1/2/3 grid, alert flood per hour, htpd vs Genie n.s., arithmetic in agent free text, log-only numbers). The former "Current status" card was removed (it repeated the Deck strip). "In short" ends on one anchor, 20 % → 94 %.
- **Likely first questions.** 9 are pinned, e.g. "Against what did you measure accuracy?" and "Why the NPU and not the GPU?".
- **Honest answers** (with "not measured", "planned", "unsolved", "circular" and similar) are highlighted, not hidden.

### 3.4 Colours (one meaning per colour, everywhere)
| Colour | Meaning |
|---|---|
| **Blue accent `#4c7dff`** | **Ours**: our choice or our result. |
| Grey `#6b6e76` (and lighter greys) | Alternatives and baselines (rules, base model, Genie, GPU...). |
| Reference (thin or neutral mark) | "ref" series: published ceilings, threshold rules in a 3-way chart, etc. |
| Muted red `#d77a72`, hollow marker | Rejected or dropped option. |
| Anchors: muted red "before" → bright green "after" | Before/after big numbers. |
| Green `#46c98a` / red `#ef6a5f` / grey `#9a9ca3` | In Δ charts: better / worse / not significant. |
| Kept green, replaced amber, pending violet | Decision and route outcome badges. |
| Severity: red critical, amber warning, green normal ("FINE"), purple fault | The same colours as the app. |
| Topic colours | Latency cyan, hardware orange, accuracy green, agent design violet, refinement teal, training amber, dataset pink, app sky, ops red, timeline silver, use case light blue. |
| Raw-data domains | Air light blue, water cyan, power yellow, weather orange, occupancy pink, HVAC mint. |
| Split bands | Train blue, dev amber, test violet (shaded). |

All text meets a ≥ 4.5:1 contrast ratio. Colour is never the only cue: badges and labels repeat it.

### 3.5 Chart conventions
- **Hover** shows the exact value, **n**, the **95% CI** (where one exists) and the source file.
- **CI whiskers** are the thin error bars on bars and dots. If two whiskers overlap a lot, the difference is probably not significant. Check the paired test to be sure.
- **ciDot charts** show a point plus its 95% CI. In Δ charts, a dashed line at 0 means "no change".
- **Waterfalls** show the latency route. Bars marked "≈" are derived or midpoints of logged ranges, not single runs.
- **Highlighted x.** Some line charts mark one x value, e.g. "4 h" in the window study and "40 min" in the placement curve. That is the operating point the app uses.
- **Expand button** (top-right of every chart) opens a full-screen copy:
  - wheel or pinch to zoom, drag the slider to pan;
  - click legend items to hide a series;
  - the toolbar has box zoom, reset, data table and save PNG.
- **Lazy drawing.** Charts are drawn only when scrolled into view. A blank card for a moment is normal.
- **Ranges.** Where the source logged only a range (e.g. Genie 46-48 s), the chart uses the **midpoint** and the note says so. Say "about 47 s".

---

## 4. Every dataset and graph

One entry per Proofs card, by topic, in the same order as the Proofs tabs. Datasets folded into a card (shown as "Also (...)" in its notes) are explained inside it. For each entry: what is plotted, how it was measured, the result, how to read it, the takeaway, caveats, how to explain it, and the likely follow-up.

### 4.1 Use case

The use-case topic answers "what is this system for, and does it help an operator?" It has 9 cards. They cover the size of the problem (sensors, breaches), what the agents add over plain threshold rules (fewer false alarms, explanations, cross-domain reports), and the practical promises (fast, offline, a human decides). Several smaller datasets are folded into these cards: `ad_event_gate`, `ds_source_data`, `hw_platform_paths` and `ad_self_learning`.

Colour convention on every chart: the "ours" series is the blue accent, "alt" series (alternatives, before-states, status quo) are grey, and "ref" series are reference values (published ceilings, plain measurements, rule baselines).

---

#### `uc_coverage` — What the system watches: IIIT-H campus sensors, 2025
- **Claim on the card:** "174 sensors, 33.2 M readings, 8 domains, 12 months". **Why it matters:** "A campus produces more readings than any person can watch; the system watches them all on one board."
- **What is plotted:** a bar chart with one bar per domain (x). Main series "sensors" (ours, blue) gives the sensor count per domain (y, unit sensors). A second series, "readings (millions)" (alt, grey), gives readings per domain in millions. No CI whiskers, because these are counts.
- **How it was measured:** the counts come from the website's raw-data index (`Website/data/raw/index.json`, `Website/data/raw/s/*.json`), which `Website/build/collect/rawdata.py` builds from the 2025 campus CSVs. The domain mapping and file inventory come from `plan.md` and HANDBOOK 2.36. Collector: `Website/build/collect/use_case.py`.
- **Result in numbers (uc_coverage):**

  | domain | sensors | readings |
  |---|---|---|
  | Indoor air | 12 | 2,420,597 (2.42 M) |
  | HVAC floors | 5 | 1,024,376 (1.02 M) |
  | HVAC units | 87 | 26,328,340 (26.33 M) |
  | Occupancy | 7 | 341,287 (0.34 M) |
  | Outdoor air | 10 | 1,385,747 (1.39 M) |
  | Power | 11 | 591,238 (0.59 M) |
  | Water | 40 | 976,118 (0.98 M) |
  | Weather | 2 | 150,279 (0.15 M) |

  Totals block: sensors 174, readings 33,217,982, months 12, breaches 20,538, critical breaches 6,923, windows_used 48,838, examples_v1 7,980, examples_v2 40,858, real_windows 2,589,199.
  - **Folded `ds_source_data`** ("Source data: IIIT-H campus sensors, 2025 (14 CSVs, 4.6 GB, ~37 M rows)"), unit million rows, rows per CSV file:

    | content | rows (M) | file | nodes |
    |---|---|---|---|
    | HVAC (room AC units) | 11.5 | SR-AC.csv | 87 |
    | outdoor air | 9.5 | air_qulaity.csv | 10 |
    | indoor air | 7.0 | SR-AQ.csv | 12 |
    | solar / LT panel power | 1.8 | SL.csv | 9 |
    | water flow | 1.7 | WM-WF.csv | 25 |
    | main energy meters | 1.2 | EM.csv | 3 |
    | wireless network | 0.9 | WN.csv | 79 |
    | room energy | 0.7 | SR-EM.csv | 3 |
    | water tank level | 0.37 | WM-WL.csv / WL.csv | 9 |
    | occupancy | 0.3 | SR-OC.csv | 2 |
    | weather | 0.1 | we.csv | 2 |
    | water quality | 0.03 | WM_WD.csv | 9 |

    Notes: row counts only; the data stays private on the laptop. The SR-OC occupancy/temp/RH columns are empty in the CSV, so occupancy was extracted separately (`extract_occupancy.py`). Timestamps mix +00:00 and +05:30.
- **How to read it:** look at the HVAC units bar first. 87 of the 174 sensors and 26.33 M of the 33.2 M readings are room AC units. Water has the second-most sensors (40) but few readings each.
- **Takeaway:** 174 sensors produce 33.2 M readings in one year, far more than a person can watch.
- **Caveats / limits:** "readings" (33.2 M, per metric per sensor as the raw index counts them) and "rows" (CSV lines, roughly 35 M summed over the 12 listed files, "~37 M" in the title) are different units. Do not mix them. For example, HVAC units show 26.33 M readings but SR-AC.csv has 11.5 M rows. The data does not explain how rows become readings. The wireless network file (79 nodes) is in the source inventory but is not one of the 8 monitored domains. The domain-level breach charts (`uc_breaches_*`) cover 6 domains: HVAC floors and Occupancy are absent there.
- **Explain it to a professor:** "This is the whole 2025 IIIT-H sensor estate we built on: 174 sensors in 8 domains, 33.2 million readings. Half the sensors are room AC units, which is why HVAC dominates the readings. The point is scale: one board watches all of it continuously."
- **Likely follow-up:** Q: "Did you train on all 33 M readings?" A: No. The totals record 48,838 windows used, 7,980 training examples for v1 and 40,858 for v2, cut from 2,589,199 possible real windows. The test months (Nov-Dec) are held out.

---

#### `uc_breaches_monthly` — Threshold breaches per month and domain (2025, real data)
- **Claim on the card:** "20,538 warning/critical breaches in a year, 6,923 critical". **Why it matters:** "This is the alert flood a threshold system hands an operator."
- **What is plotted:** a stacked bar chart. x is the month (Jan-Dec 2025); y is the number of breaches. There is one stacked segment per domain: Indoor air, Water, Outdoor air, Power, HVAC units, Weather (all role alt, grey shades, because this is the status-quo rule view). Each point also carries a `critical` count in its tooltip. No CIs.
- **How it was measured:** a breach is one contiguous run above a warning or critical limit on one metric. The counts are aggregated from the per-sensor breach lists in `Website/data/raw/s/*.json` (built by `Website/build/collect/rawdata.py`). Collector: `Website/build/collect/use_case.py`.
- **Result in numbers (uc_breaches_monthly)**, as total breaches (critical in brackets):

  | month | Indoor air | Water | Outdoor air | Power | HVAC units | Weather |
  |---|---|---|---|---|---|---|
  | Jan | 469 (10) | 142 (72) | 635 (36) | 92 (27) | 37 (22) | 13 (0) |
  | Feb | 366 (60) | 189 (58) | 658 (25) | 213 (52) | 181 (95) | 0 (0) |
  | Mar | 496 (93) | 184 (40) | 642 (8) | 231 (86) | 201 (134) | 0 (0) |
  | Apr | 601 (112) | 159 (98) | 269 (2) | 124 (70) | 266 (225) | 0 (0) |
  | May | 683 (74) | 192 (54) | 174 (4) | 368 (102) | 214 (198) | 20 (4) |
  | Jun | 482 (44) | 630 (350) | 100 (2) | 327 (121) | 168 (166) | 78 (3) |
  | Jul | 700 (61) | 403 (220) | 83 (0) | 295 (119) | 157 (140) | 57 (16) |
  | Aug | 520 (10) | 343 (174) | 88 (5) | 342 (139) | 143 (136) | 239 (113) |
  | Sep | 669 (57) | 359 (285) | 90 (1) | 338 (127) | 135 (132) | 211 (99) |
  | Oct | 795 (82) | 660 (598) | 156 (3) | 336 (164) | 156 (153) | 86 (14) |
  | Nov | 497 (55) | 462 (431) | 295 (7) | 322 (206) | 111 (76) | 6 (2) |
  | Dec | 350 (15) | 704 (556) | 466 (33) | 325 (220) | 33 (27) | 2 (0) |

  Year totals: Indoor air 6,628, Water 4,427, Outdoor air 3,656, Power 3,313, HVAC units 1,802, Weather 712. Total 20,538, of which 6,923 are critical. (Before 2026-10-19 the site counted only high-side pH breaches: 19,819 / 6,282.)
- **How to read it:** look at the height of the stacks: hundreds to about 2,000 breaches every month. Then notice the seasonal pattern. Outdoor air is high in winter (Jan-Mar, Nov-Dec), weather peaks in Aug-Sep (monsoon), and water peaks in Jun, Oct and Dec with mostly critical breaches.
- **Takeaway:** a rules-only system gives an operator roughly 20,538 alerts a year, about 56 a day on average.
- **Caveats / limits:** these are counts of rule breaches. A breach is not necessarily a real problem. Many are short blips or normal routines such as tank refills. Counts are per metric, so one physical event on a multi-metric sensor can count more than once. The "per day" figure above is 20,538 / 365 and is not stated in the data.
- **Explain it to a professor:** "We counted every contiguous run above a warning or critical limit in 2025's real data: 20,538 breaches, 6,923 of them critical. This is what an operator would be paged with under today's threshold approach, and it is why the system has an event gate and an AI layer in front of the operator."
- **Likely follow-up:** Q: "Why does water have so many critical breaches in October?" A: The data shows 653 water breaches in Oct, 593 of them critical. The cause is not in the data. The card only aggregates counts; it does not diagnose them.

---

#### `uc_breaches_need_action` — How many breaches deserve attention: all vs lasting >= 8 readings (40 min) vs critical
- **Claim on the card:** "20,538 breaches -> 7,767 persistent -> 2,190 persistent and critical". No "why" field.
- **What is plotted:** a grouped bar chart. x is the domain; y is the number of breaches. There are 3 series:
  - "all breaches" (alt, grey);
  - "lasting >= 8 readings (pass the event gate)" (ours, blue);
  - "critical and lasting" (ref).
- **How it was measured:** the same breach lists as `uc_breaches_monthly`, filtered with the app's own persistence rule of 8 consecutive readings. On the raw 5-min data that is 40 min; in the demo clock (2 s polls) it is about 16 s. Sources: `Website/data/raw/index.json`, `Website/data/raw/s/*.json`, `Website/build/collect/rawdata.py`. Collector: `Website/build/collect/use_case.py`.
- **Result in numbers (uc_breaches_need_action, `per_domain`):**

  | domain | all | critical | lasting (gated) | critical and lasting |
  |---|---|---|---|---|
  | Indoor air | 6,628 | 673 | 3,309 | 262 |
  | Water | 4,427 | 2,936 | 116 | 17 |
  | Outdoor air | 3,656 | 126 | 1,971 | 119 |
  | Power | 3,313 | 1,433 | 199 | 157 |
  | HVAC units | 1,802 | 1,504 | 1,676 | 1,415 |
  | Weather | 712 | 251 | 496 | 220 |
  | **total** | **20,538** | 6,923 | **7,767** | **2,190** |

- **How to read it:** compare the grey and blue bars within each domain. Water drops from 4,427 to 116 and power from 3,313 to 199, so most water and power breaches are short blips. HVAC barely drops (1,802 to 1,676): AC breaches persist.
- **Takeaway:** the persistence gate alone removes 62% of breaches (20,538 to 7,767), and only 2,190 are both lasting and critical.
- **Caveats / limits:**
  - This is a filter on rule breaches, not a measure of AI accuracy.
  - "Lasting" uses the same 8-reading rule as the app's event gate, but on raw 5-min data. In the live demo the readings are 2 s apart.
  - A short breach can still matter. A very short critical spike would not pass this gate.
  - The 62% figure is computed here (1 - 7,767/20,538); it is not printed on the card.
- **Explain it to a professor:** "Most threshold breaches are short. If we only escalate those that persist for 8 readings, which is the same rule the app uses before it calls the AI, 20,538 drops to 7,767, and only 2,190 of those are critical. That is the workload the AI actually sees."
- **Likely follow-up:** Q: "Why 8 readings?" A: The `ad_event_gate` table (folded into `uc_alert_reduction`) says the agents were trained on events at least 7 readings old, and younger windows were misread.

---

#### `uc_alert_reduction` — Status quo (threshold rules) vs our agents on the same real windows
- **Claim on the card:** "Same detection (78%), false alarms 43% -> 27%". **Why it matters:** "Fewer false alarms at equal detection is what makes operators trust and act on alerts."
- **What is plotted:** a grouped bar chart with two x groups, "detects injected events" and "false alarms on calm windows". y is a fraction (0-1). Series: "threshold rules (status quo)" (alt, grey) and "event gate + fine-tuned agents" (ours, blue). Each bar has 95% Wilson CI whiskers.
- **How it was measured:** this is the 4 h arm of the window-length study (`proofs/2026-10-16_window_study/summary.json`, `RESULTS.md`).
  - Faults were injected into real windows from the held-out test months (Nov-Dec).
  - The same fine-tuned Llama 3.2 3B ran on the QIDK NPU through htpd v6, with greedy decoding.
  - Rules (Mode 1) were scored on the same windows.
  - "Detects" uses the 364 injected cases. "False alarms" uses the 77 calm windows whose truth is normal.
  - A flag means status != normal or pattern != stable/vacant/occupied.
  - The event-gate facts come from `proofs/2026-10-16_htpd_app_stress_full.log` and HANDBOOK 4.1.
  - Collector: `Website/build/collect/use_case.py`, which reads `rules_detection_all_events`, `rules_false_alarm_clean`, `detection_all_events` and `false_alarm_clean` from summary.json.
- **Result in numbers (uc_alert_reduction):**

  | | detects injected events | false alarms on calm windows |
  |---|---|---|
  | threshold rules | 0.78 (284/364, CI 0.735-0.82) | 0.429 (33/77, CI 0.324-0.54) |
  | agents | 0.775 (282/364, CI 0.729-0.815) | 0.273 (21/77, CI 0.186-0.381) |

  Extra fields: event_gate_calm_readings 2000, event_gate_incidents 0.
  - **Folded `ad_event_gate`** ("Event gate: when the AI is called", n=2000):
    - Series "readings at rest -> incidents": 2,000 calm readings produced 0 incidents.
    - Series "stress 'quiet' phase": a 90 s random drift in band produced 0 incidents.
    - Notes: only a warning, critical or fault status lasting 8 readings (~16 s at 2 s polls) calls the AI. Everything alarming at about the same time is batched into one incident. The batch window closes after 1 reading when no other sensor is abnormal-but-young (HANDBOOK 2.29).
    - Table:

      | rule | value | why |
      |---|---|---|
      | persist readings | 8 | agents were trained on events >= 7 readings old; younger windows were misread |
      | poll | 2 s = 5 min sensor time | demo clock |
      | re-arm | after return to normal | one report per abnormal episode |
      | agent cap | none (was 3, then 8) | every alarming sensor gets an NPU agent |

- **How to read it:** first check that the two "detects" bars are equal (0.78 vs 0.775, with heavily overlapping CIs). Then compare the false-alarm bars: 0.429 vs 0.273. Their CIs (0.324-0.54 and 0.186-0.381) overlap only slightly.
- **Takeaway:** at the same detection rate, the agents raise about a third fewer false alarms than the threshold rules (43% to 27%).
- **Caveats / limits:**
  - The false-alarm comparison rests on n=77 calm windows, and the CIs overlap a little. The data contains no paired significance test for rules vs agent.
  - "Clean" windows are real data and contain real dips and spikes, so both rates over-count. On the strict-clean subset (19 windows) the agent's false-alarm rate is 5% (window_study RESULTS.md).
  - The series name says "event gate + fine-tuned agents", but the study sends each window straight to the agent. The event gate's own evidence is the separate 2,000-readings / 0-incidents figure.
  - Detection is about 78% for both. The agent does not catch more events; it adds an explanation and fewer false alarms.
  - The roles are air quality, water and power only (weather excluded: no continuous 12 h windows).
- **Explain it to a professor:** "On the same held-out windows with injected faults, threshold rules and our agents both detect about 78% of events. On real calm windows the rules flag 43% and the agents 27%. And before the AI is even called, the event gate turned 2,000 calm readings into zero incidents."
- **Likely follow-up:** Q: "Is 43% vs 27% significant?" A: The Wilson 95% intervals are 0.324-0.54 vs 0.186-0.381, so they overlap slightly. With n=77 the difference is suggestive but not proven by the CIs alone. The data has no paired McNemar test for this specific comparison.

---

#### `uc_time_to_insight` — Time from alert to an explained, evidence-cited report (QIDK, through the app)
- **Claim on the card:** "An explained report in ~4 s typically, 21 s when 12 sensors fail at once". **Why it matters:** "Rules alert instantly but explain nothing; the agents explain within seconds, on the board."
- **What is plotted:** a grouped bar chart. x has 3 situations; y is seconds. Series: "before (Genie)" (alt, grey), "now (htpd v6)" (ours, blue) and "threshold rules" (ref; only for the typical incident, at 0.001 s, i.e. effectively instant). No CIs.
- **How it was measured:**
  - The chaos and median numbers come from the app stress test through the real app on the QIDK (`proofs/2026-10-16_htpd_v6_app_stress_tail.log`, HANDBOOK 2.37).
  - The "13 agents (A/B)" numbers come from the htpd A/B harness (`proofs/2026-10-16_htpd_ab/RESULTS.md`).
  - The Genie chaos value is the midpoint of 46-48 s, and the Genie 13-agent value the midpoint of 22-25 s.
  - Collector: `Website/build/collect/use_case.py`.
- **Result in numbers (uc_time_to_insight):**

  | situation | Genie | htpd v6 | rules |
  |---|---|---|---|
  | 12-sensor chaos incident | 47 | 20.7 | - |
  | 13 agents (A/B) | 23.5 | 14.7 | - |
  | typical incident (median) | 3.8 | 3.8 | 0.001 |

  Notes: refined re-reads land at +1.5 h and +3 h of sensor time (~37 s and ~74 s on the 2 s demo clock). The first token arrives in ~0.3 s with a resident model.
- **How to read it:** the typical incident is the same 3.8 s on both runtimes. The gain is in big incidents: 47 s to 20.7 s.
- **Takeaway:** a typical explained report takes 3.8 s; a 12-sensor failure takes 20.7 s on htpd, down from about 47 s on Genie.
- **Caveats / limits:**
  - The Genie values are midpoints of ranges recorded in the HANDBOOK, not single runs.
  - The time shown is the analysis time after the event gate. The gate itself adds ~16 s of demo time (8 readings at 2 s polls), plus the batch window; see `uc_example_incident`.
  - The "13 agents (A/B)" row is agents only (no synthesizer) and comes from a harness, not the app.
  - The rules bar at 0.001 s is a symbolic "instant", not a measurement.
- **Explain it to a professor:** "Rules alert instantly but say nothing about why. Our agents return an evidence-cited explanation in a median of 3.8 seconds on the board. When 12 sensors fail at once, the batched NPU daemon brings that from about 47 seconds down to 20.7."
- **Likely follow-up:** Q: "Why is the typical incident not faster with htpd?" A: Small incidents have 1-2 agents. htpd's gain comes from serving many agents in one weight sweep, so with few agents the two runtimes are about equal (HANDBOOK 2.37: "small incidents: about equal").

---

#### `uc_example_incident` — One incident end to end: crowded room (CO2 + power), as measured
- **Claim on the card:** "From first abnormal reading to an approved-ready report in ~32 s of demo time". No "why".
- **What is plotted:** a waterfall. x is the phases in order; y is seconds, accumulating to the total. One series, "phase" (ours, blue).
- **How it was measured:**
  - A real 3-call `crowded_room` incident in the app (2 domain agents + synthesizer), traced with `SCE_GENIE_TRACE=1` in the Genie/genied era (HANDBOOK 2.29).
  - The gate time is computed at 2 s polls.
  - Collector: `Website/build/collect/use_case.py`.
- **Result in numbers (uc_example_incident):**
  - abnormal for 8 readings (event gate): 16.0 s
  - batch window (2 sensors): 4.0 s
  - 2 NPU domain agents: 7.112 s
  - synthesizer root cause: 4.457 s
  - app overhead: 0.011 s
  - The sum is 31.58 s, the "~32 s" in the claim. The notes add that on htpd v6 the same scenario's analysis took 7.5 s (3 NPU calls); `uc_cross_domain` lists 7.525 s.
- **How to read it:** the biggest block is the deliberate 16 s event gate, not the AI. App overhead is 11 ms.
- **Takeaway:** about half the 32 s is the deliberate waiting rule that suppresses false alarms; the AI takes about 11.6 s (Genie era), and the app adds almost nothing.
- **Caveats / limits:**
  - The 16 s gate and 4 s batch window are demo-clock times (2 s per reading). In real sensor time 8 readings are 40 min.
  - The model times are from the Genie era. On htpd v6 the analysis part is 7.5 s.
  - After this, the operator approves or dismisses, and refinements re-read at +1.5 h and +3 h. Neither is included.
  - Single trace, n not stated.
- **Explain it to a professor:** "Here is one real cross-domain incident, a crowded room raising CO2 and power, timed phase by phase. 16 seconds is our deliberate persistence check, 4 seconds waits for co-occurring sensors to join, the two NPU agents take 7.1 s and the root-cause synthesizer 4.5 s. Our own code adds 11 milliseconds."
- **Likely follow-up:** Q: "Why not shorten the 16 s gate?" A: The gate requires 8 persistent readings because the agents were trained on events at least 7 readings old and misread younger windows (`ad_event_gate` table). On real 5-min data it is the 40-min persistence that cut breaches from 20,538 to 7,767 (`uc_breaches_need_action`).

---

#### `uc_cross_domain` — Cross-domain incidents: one report across several domains (Mode 3, QIDK)
- **Claim on the card:** "All 4 multi-sensor incidents span 2-4 domains in one report". **Why it matters:** "Real causes cross domains: a crowded room raises CO2, power and cooling together."
- **What is plotted:** a bar chart. x is the incident; y is the number of distinct domains examined by the NPU agents. One series, "domains examined by NPU agents" (ours, blue). The tooltip carries agents, NPU calls, total seconds, the synthesizer's root-cause label and whether the report passed validation.
- **How it was measured:** incidents from the final htpd v6 app stress run (`proofs/2026-10-16_htpd_v6_app_stress_report_final.json`). Each point is one incident, and y is the number of distinct domains among its agents. Collector: `Website/build/collect/use_case.py`.
- **Result in numbers (uc_cross_domain):**

  | incident | domains | agents | NPU calls | total s | root-cause label | report valid |
  |---|---|---|---|---|---|---|
  | M3 crowded_room | 2 | 2 | 3 | 7.525 | power_load_anomaly | true |
  | chaos simultaneous #1 | 4 | 12 | 13 | 20.698 | weather_driven | true |
  | chaos simultaneous #2 | 4 | 10 | 11 | 20.617 | hvac_or_thermal_issue | true |
  | chaos staggered #1 | 4 | 11 | 12 | 20.752 | weather_driven | true |

- **How to read it:** every incident spans 2-4 domains and ends in one valid report with one root-cause label. NPU calls = agents + 1 (the synthesizer).
- **Takeaway:** one incident becomes one report spanning several domains, produced on the NPU in 7.5-20.8 s.
- **Caveats / limits:**
  - The notes say plainly that there is no independent root-cause ground truth yet; cross-domain injections are planned. This card shows that the reports span domains, not that the root-cause labels are correct.
  - n=4 incidents. The app check "names several domains" ran on the 3 chaos incidents only (3/3); the crowded room (2 domains) is the 4th bar. The claim now counts the plotted bars (fixed 2026-10-19).
  - Chaos incidents are artificial "everything goes haywire" stress rounds.
- **Explain it to a professor:** "In Mode 3 each alarming sensor gets its own NPU agent, and a synthesizer writes one report. In the final stress run, incidents spanned 2 to 4 domains, and every report passed the policy gate with a single root-cause label. We have not yet verified those labels against injected cross-domain ground truth."
- **Likely follow-up:** Q: "Is 'weather_driven' correct for chaos #1?" A: That is not in the data. Chaos rounds perturb all sensors at random, so there is no true root cause to compare against. Ground-truth cross-domain injections are planned.

---

#### `uc_human_in_loop` — Safety: every answer is checked, nothing is actuated, a person decides
- **Claim on the card:** "100% of agent answers pass the gate; 0 automatic actions". **Why it matters:** "Operators approve or dismiss every recommendation; their verdicts become training data (SFT/DPO)."
- **What is plotted:** a bar chart (fraction). Series:
  - "our system" (ours, blue) with 3 bars: policy-gate pass rate in the app, evidence-id validity in the host eval, and actions executed without approval (0).
  - "base model, no fine-tune" (alt, grey) with one bar: evidence-id validity.
  - Wilson 95% CI whiskers on the rate bars.
- **How it was measured:**
  - Policy-gate pass: every agent answer in the Mode-3 and chaos incidents of the final v6 app stress run (`proofs/2026-10-16_htpd_v6_app_stress_report_final.json`). The collector counts `valid` agents.
  - Evidence ids: the v1 host evaluation on 150 held-out windows (`Code/smart-city-edge-agent/training/results/agents_20261006_2101/eval.json`).
  - The policy design is in HANDBOOK 2.33. The self-learning capture is in HANDBOOK 2.28 and ppt.md.
  - Collector: `Website/build/collect/use_case.py`.
- **Result in numbers (uc_human_in_loop):**
  - agent answers passing the policy gate (app, v6): 1.0, 44/44, CI 0.9197-1.0
  - evidence ids valid (host eval), fine-tuned: 1.0, 150/150, CI 0.975-1.0
  - evidence ids valid (host eval), base model: 0.3467, 52/150, CI 0.2752-0.4258
  - actions executed without approval: 0
  - **Folded `ad_self_learning`** ("Self-learning data capture: first real export"): from one approved incident, 2 SFT positives and 1 DPO pair (policy-corrected vs raw). Every LLM call stores the prompt, raw output, parsed output, validity, errors and repairs, and every incident stores the operator's approval and note. DPO pairs need no labelling.
- **How to read it:** start with the evidence-id bars: 150/150 fine-tuned vs 52/150 base. The base model often cites evidence that does not exist. Then the 44/44 gate pass in the real app.
- **Takeaway:** every answer is machine-checked, the fine-tuned model always cites real evidence, nothing acts on its own, and operator decisions feed back as training data.
- **Caveats / limits:**
  - "Pass the gate" means the answer is valid JSON with whitelisted labels and real evidence ids, and does not try to actuate. It does not mean the answer is correct.
  - The policy gate also repairs answers transparently (see `ad_policy_gate` in the agent-design topic). So 100% partly reflects the repairs.
  - 44 answers come from one stress run.
  - "0 automatic actions" holds by design: the system never actuates, and a dismissal needs a note.
  - Self-learning is shown from one incident only; no retraining from it has happened yet.
- **Explain it to a professor:** "The model never acts. Every answer goes through a policy gate that checks the JSON, the allowed labels and that every evidence id it cites really exists, and a person approves or dismisses. Fine-tuning moved valid evidence citation from 35% for the base model to 100%."
- **Likely follow-up:** Q: "What happens when an answer fails the gate?" A: HANDBOOK 2.33: if the synthesizer fails policy, a report is assembled from the agents' own findings (Mode 3) or the rule findings (Mode 2) and marked as such, so the operator always gets a report.

---

#### `uc_edge_offline` — Runs on the edge: everything on one QIDK board, no cloud
- **Claim on the card:** "Sensor data, AI inference, safety checks and storage all stay on the board". **Why it matters:** "Works with no internet; no campus data (e.g. room occupancy) leaves the site."
- **What is plotted:** a bar chart. Series "one agent call on the board" (ours, blue; y in seconds) has three bars: NPU via genied, NPU via htpd per agent when 13 are batched, and GPU. Series "bytes leaving campus per incident" (ref, unit bytes) has one bar at 0.
- **How it was measured:**
  - The genied value is the measured single-call time (HANDBOOK 2.24).
  - The htpd value is 14.7 s / 13 agents (the A/B harness, `proofs/2026-10-16_htpd_ab/RESULTS.md`), computed in the collector as round(14.7/13, 2).
  - The GPU value is the 1-agent cell of the placement grid (`proofs/2026-10-16_hw_grid/samples.jsonl`).
  - The path inventory comes from `problems_setup.md` and HANDBOOK 2.37.
  - Collector: `Website/build/collect/use_case.py`.
- **Result in numbers (uc_edge_offline):**
  - NPU (genied): 2.543 s
  - NPU (htpd, 13 in one batch, per agent): 1.13 s
  - GPU (Adreno, 1 agent): 10.01 s
  - bytes leaving campus per incident: 0
  - Notes: the app reaches the NPU through the board's own adbd, because Android apps cannot open it directly. The board idles at ~43 C, and chaos peaks reach 95-96 C (heatsink advised). Energy per incident has not been measured (no free power rail).
  - **Folded `hw_platform_paths`** ("Every runtime path tried on the QIDK and where each ended", n=14; y=1 marks a shipped path):

    | # | approach | result | why |
    |---|---|---|---|
    | A1 | llama.cpp on the CPU | works, slow | bandwidth-bound decode on CPU; never the main path |
    | A2 | llama.cpp + GGML_QNN fork | abandoned | days with no result; oscillated between Genie and GGUF |
    | A3 | llama.cpp + OpenCL on Adreno GPU | tried 2026-10-16: not viable | ~8.4 s per agent, no batching gain (hw_grid) |
    | A4 | SNPE | not used | superseded by QAIRT; no LLM story |
    | A5 | QAIRT/QNN hand-built context binaries | not used for the LLM | 1-3 weeks; hand-rolled LLM loop |
    | A6 | ONNX Runtime + QNN EP | host-side calibration only | same problems as A5 for a 3B LLM |
    | A7 | ExecuTorch / MLC-LLM / TFLite | not tried | MLC targets the GPU; TFLite irrelevant for a decoder LLM |
    | A8 | Qualcomm AI Hub -> Genie bundle | SHIPPED (Genie era) | 1-3 days; quantises and compiles for SM8650 |
    | A9 | laptop web app + adb shell per call | dropped | not edge: unplug the laptop and the demo dies |
    | A10 | Go binary on device (shell user) + PWA | worked | laptop-free; shell user can open the NPU |
    | A11 | APK running Genie in the app sandbox | FAILED (14001) | the vendor DSP service refuses apps (also in permissive mode) |
    | A12 | APK + local adbd loopback (127.0.0.1:5555) | SHIPPED | app asks the board's own adbd to start the backend as shell |
    | A13 | JNI against the Genie C API | deferred | would not help: the sandbox cannot open the NPU |
    | 2.37 | llama.cpp Hexagon backend (htpd) | SHIPPED (current, opt-in file switch) | batched agents per weight sweep; patches FA_STREAMS, HMX pipe, drafting, prefix cache |

- **How to read it:** the per-agent cost on the NPU is 1.13 s when batched, against 10.01 s on the GPU. The bytes-out bar is 0. Then use the table to show the engineering route: three paths shipped (A8 Genie, A12 app access through local adbd, htpd).
- **Takeaway:** the whole pipeline (sensors, LLM, policy gate, storage) runs on one board with no cloud, and the NPU is the right engine on it.
- **Caveats / limits:**
  - "0 bytes" is a design property, not a packet-capture measurement; the data contains no network trace.
  - Energy per incident is not measured.
  - The htpd per-agent number is an average inside a 13-agent batch. A single agent alone does not get 1.13 s; the A/B harness shows 4 agents take 4.8 s.
  - The app uses a local adbd loopback because the vendor DSP service refuses sandboxed apps (A11, error 14001). This is a workaround that depends on adb being enabled on the board.
  - htpd is an opt-in file switch (HANDBOOK 2.37: `/data/local/tmp/smart_city_edge/npu_engine` containing `htpd`).
- **Explain it to a professor:** "Everything runs on the Snapdragon board: the sensors' data, a 3B LLM on the Hexagon NPU, the policy checks and the incident store, so nothing about campus occupancy leaves the site. We tried 14 runtime routes. Genie via AI Hub and later our own batched llama.cpp-Hexagon daemon shipped, and the GPU was 4-9 times slower per agent."
- **Likely follow-up:** Q: "Why go through adbd instead of a normal Android app?" A: A11 in the table: running Genie inside the app sandbox failed with 14001 because the vendor DSP service refuses apps, even in permissive mode. A12, asking the board's own adbd at 127.0.0.1:5555 to start the backend as the shell user, is the shipped workaround.

---

### 4.2 Latency

The latency topic tells the story of how one agent call and one incident got faster, in two eras. In the Genie era (Qualcomm's runtime) we tuned settings, context size and a persistent daemon (genied). In the htpd era we moved to our own batched llama.cpp Hexagon daemon, so many agents share one pass over the weights. A recurring rule across these cards: a change ships only if the outputs stay identical (byte-identical, or within the measured noise floor for batched runs).

---

#### `lat_call_breakdown` — Where one agent call goes (Genie profiler, live fine-tuned bundle, ctx 4096)
- **Claim on the card:** "Decode is 70-78% of a call: the target is fewer tokens and fewer weight sweeps". **Why it matters:** "Knowing where time goes stopped us tuning knobs that cannot matter."
- **What is plotted:** a stacked bar chart with phases on x (model init, prefill, decode, plus dialog free for the second series); y is milliseconds. Series:
  - "548-token prompt, 59 tokens out (3 runs, 2026-10-14)" (ours, blue), with t-based 95% CI whiskers (n=3);
  - "800-token prompt, 109 tokens out (2026-10-13)" (alt, grey).
- **How it was measured:** Genie's own `--profile` output on the live fine-tuned bundle at ctx 4096 (HANDBOOK 2.8, 2.13, 2.15, 5). The notes record that shell `date` arithmetic had been wrong (1.67 s vs 5.97 s), so only profiler numbers are used. Collector: `Website/build/collect/latency.py`.
- **Result in numbers (lat_call_breakdown):**
  - 548-token prompt: model init 694.7 ms (CI 677.7561-711.5772), prefill 397.0 ms (388.394-405.606), decode 2646.3 ms (2574.5736-2718.093). Total about 3738 ms, of which decode is about 71%.
  - 800-token prompt: model init 635, prefill 541, decode 4678, dialog free 89 ms. Decode is about 79%.
  - Notes: prefill runs at about 1380-1481 tok/s, decode at about 22-23 tok/s.
  - **Folded `lat_bandwidth_roof`** ("Decode is at the memory-bandwidth roof"; claim "~84% of the measured NPU DMA ceiling: config knobs can save ~440 ms at most"):
    - measured NPU read bandwidth during decode: 49.3 GB/s (ours);
    - published ceilings (ref): NPU DMA (DDR->VTCM), V75: 59 GB/s; whole-device practical peak, 8 Gen 3: 68 GB/s;
    - notes: 2.20 GB of weights stream from DDR per decode token (part 2 901 MB + part 3 1301 MB; part 1 is the embedding table, one 6 KB row per token), and 2.20 GB x 22.4 tok/s = 49.3 GB/s. lm_head (788 MB at 16 bit) is about 36% of the traffic;
    - table: part_1_of_3 788 MB embedding table (Gather); part_2_of_3 901 MB transformer layers; part_3_of_3 1301 MB transformer layers + lm_head.
  - **Folded `lat_genie_settings`** ("Genie runtime settings (base model, 200-token generations)"):
    - wall time for 200 tokens: 3 threads, mask 0xe0 (old) 11.9 s; 4 threads, mask 0xf0 (used) 11.7 s; use-mmap false 14.4 s; poll false 12.4 s;
    - notes: init 0.67/0.65/3.0/0.68 s; decode 18.9/19.2/18.9/18.2 tok/s. The poll=false A/B/A on the fine-tune gave 21.0 vs 22.6-22.9 tok/s (7-8% slower);
    - table:

      | config | decode tok/s run1 | run2 | run3 | temp C |
      |---|---|---|---|---|
      | poll=true | 22.9 | 22.4 | 22.6 | 46 |
      | poll=false | 21.0 | 21.0 | 20.8 | 54 |
      | poll=true (control) | 22.6 | 22.4 | 23.0 | 57 |

  - **Folded `lat_word_limits`** ("Word limits on free-text fields (synthesizer)"): synthesizer output before 187 tokens, after 111 (midpoints of 184-190 and 102-120). That took a synthesizer call from about 11 s to 7-8 s. Label, evidence and action were unchanged.
- **How to read it:** the decode segment dwarfs init and prefill. Then read the bandwidth roof: at 49.3 of 59 GB/s, decode cannot be tuned much. The only levers are fewer output tokens (word limits) or fewer weight sweeps (batching, which htpd does later).
- **Takeaway:** decode is bandwidth-bound and is 70-78% of a call, so the strategy became "generate fewer tokens and share weight sweeps", not "tune knobs".
- **Caveats / limits:**
  - n=3 for the main series. The 800-token series is a single run on a different day.
  - The ceilings (59, 68 GB/s) are published figures, not measured by us.
  - The settings table mixes board temperatures (46-57 C).
  - The "70-78%" range is approximate; the two series compute to about 71% and 79%.
- **Explain it to a professor:** "With Genie's profiler, about three quarters of an agent call is decode. Every decode token streams 2.2 GB of weights from DRAM, which at 22.4 tok/s is 49.3 GB/s, about 84% of the published NPU DMA ceiling. So we stopped tuning runtime knobs and attacked the number of tokens and the number of weight passes."
- **Likely follow-up:** Q: "Why not quantise lm_head to cut the 36%?" A: HANDBOOK 2.15 says it would cut decode by 20-25%, but it needs a re-export, which was out of scope while the model was frozen.

---

#### `lat_route_agent_call` — Latency route, one agent call (Genie era)
- **Claim on the card:** "~3.9 s -> 2.5 s per agent call before the move to htpd". No "why".
- **What is plotted:** a waterfall with steps on x and y in ms per agent call. One series, "agent call" (ours, blue). Points carry `delta`, `section` and `derived` (true means computed by applying a measured delta).
- **How it was measured:** each step was measured on its own, on different prompts and days. The intermediate bars apply each measured delta to the first value; the last bar is the directly measured genied number. The notes say: "Not an additive experiment." Sources: HANDBOOK 2.14, 2.10, 2.22, 2.18, 2.24, 2.21. Collector: `Website/build/collect/latency.py`.
- **Result in numbers (lat_route_agent_call):**

  | step | ms | delta | section | derived |
  |---|---|---|---|---|
  | Genie CLI, ctx 4096 (fine-tuned) | 3947 | baseline | 2.14 | no |
  | allow-async-init | 3882 | -65 ms init | 2.10 | yes |
  | ctx 4096 -> 2048 | 3161 | -721 ms | 2.22 | yes |
  | stop before 'action' | 2962 | -199 ms | 2.18 | yes |
  | genied persistent dialog | 2543 | 3640 -> 2543 ms measured | 2.24 | no |

  - **Folded `lat_action_trim`** ("Stop generating the 'action' field that policy derives anyway"; claim "-199 ms per agent call; 14 findings checked, 0 problems"): baseline 3838.9 ms (58 chunks) vs trim 3640.1 ms (55 chunks). The first attempt (2.10) was rejected because a comma straddling a read boundary produced invalid JSON; it was fixed with a []byte buffer and a 16-byte holdback. The trim must apply to agent calls only: trimming the synthesizer broke its report (2.21).
  - **Folded `lat_async_init`** ("allow-async-init: true (A/B/A, Genie profiler)"; claim "-65 ms per call, init only, no accuracy risk"): init (mean of 3) false @49 C 703, false @48 C (control) 711, true @68 C 640 ms. Decode tok/s for the same arms: 23.11, 22.78, 22.45.
- **How to read it:** follow the bars down. The two biggest single drops are ctx 2048 (-721 ms) and the persistent genied dialog (the final measured 2543 ms).
- **Takeaway:** four safe changes cut a single agent call from 3947 ms to 2543 ms, all without changing answers.
- **Caveats / limits:**
  - The waterfall is partly derived: the intermediate bars are arithmetic, not measurements.
  - The final genied measurement (3640 -> 2543) starts from a different baseline (3640) than the waterfall's 3947.
  - async-init's "true" arm ran hotter (68 C), so its small decode drop may be thermal.
- **Explain it to a professor:** "In the Genie era we took a single agent call from 3.9 s to 2.5 s with four changes: asynchronous init, a smaller compiled context, not generating a field the policy derives anyway, and a persistent daemon instead of a process per call. Each was gated on identical outputs. The intermediate bars are our measured deltas applied in sequence, not one continuous experiment."
- **Likely follow-up:** Q: "Why does stopping before 'action' not hurt?" A: The policy gate derives the action itself, and the trim was checked on 14 findings with 0 problems. It is restricted to agent calls because trimming the synthesizer broke its report (HANDBOOK 2.21).

---

#### `lat_ctx2048` — Context 4096 -> 2048: same weights, re-exported (mean of 14 role/pattern prompts)
- **Claim on the card:** "-721 ms per call, 20.7 -> 25.0 tok/s, 14/14 byte-identical". **Why it matters:** "The KV buffer is part of every decode step's memory traffic; we used ~610 of 4096 slots."
- **What is plotted:** a stacked bar with phases (init, prefill (ttft), decode) and y in ms. Series: "ctx 4096" (alt, grey) and "ctx 2048" (ours, blue).
- **How it was measured:**
  - The same checkpoint, weights and quantisation were recompiled with `--context-lengths 2048`.
  - Results are means over 14 role/pattern prompts. Identity was checked with `compare_bundles.py` (HANDBOOK 2.22, 2.32, ppt.md).
  - Collector: `Website/build/collect/latency.py`.
- **Result in numbers (lat_ctx2048):**
  - ctx 4096: init 761.4, prefill 386.6, decode 3736.8 ms.
  - ctx 2048: init 768.4, prefill 302.0, decode 3100.1 ms.
  - Decode rate 20.7 vs 25.0 tok/s. Identical outputs 14/14.
  - The KV cache is 469 MB at 4096 and 235 MB at 2048. End to end on a real 3-call crowded_room incident: 18691 -> 14727 ms. ctx 1024 was rejected because generation reaches ~1120 tokens and synthesizer prompts are longer.
  - **Folded `lat_two_windows`** ("Two context windows: ctx 2048 by default, ctx 4096 only when a prompt needs it"):
    - window swap cost (load the ctx-4096 dialog): 0.9 s;
    - gate: outputs identical with normal/large alternating, 1.0 (5/5, CI 0.5655-1.0);
    - rule: switch when estTokens*1.08 + 320 + 40 > 2048. Chaos synthesizer prompts (18+ sensors) need about 3,400 tokens. Evidence is never trimmed to fit.
- **How to read it:** init is unchanged, while prefill (-22%) and decode (-17%) shrink. The 14/14 identity proves nothing else changed.
- **Takeaway:** a smaller compiled context, with no retraining, saved 721 ms per call and changed no answer.
- **Caveats / limits:**
  - This is Genie-era work. In htpd, contexts are configured differently (13 streams x 768 for agents, 4096 for the synthesizer, HANDBOOK 2.37).
  - The 5/5 two-window identity check is small (CI lower bound 0.5655).
  - Large prompts pay a 0.9 s swap.
- **Explain it to a professor:** "The KV cache is a fixed buffer sized by the compiled context, and it is read on every decode step. We used about 610 of 4096 slots, so we recompiled at 2048 with identical weights: 25.0 instead of 20.7 tokens per second, 721 ms saved per call, and 14 of 14 outputs byte-identical."
- **Likely follow-up:** Q: "What happens when a prompt does not fit in 2048?" A: The backend switches to a ctx-4096 dialog when estTokens*1.08 + 320 + 40 > 2048, at a cost of about 0.9 s. Evidence is never trimmed, and outputs were identical on the 5/5 alternating check.

---

#### `lat_genied` — genied: one persistent Genie dialog instead of a process per call
- **Claim on the card:** "3640 -> 2543 ms per call; first token 1.2 s -> 0.31 s; 28/28 identical". No "why".
- **What is plotted:** a grouped bar chart. x is "single agent call" and "time to first token"; y is ms. Series: "per-call CLI" (alt, grey) and "genied daemon" (ours, blue).
- **How it was measured:**
  - The gate is `training/export/verify_daemon.py`: 14 prompts sent forward and then in reverse (so each prompt follows a different predecessor), compared with the CLI.
  - Sources: HANDBOOK 2.24 and 2.19. Collector: `Website/build/collect/latency.py`.
- **Result in numbers (lat_genied):**
  - single agent call: 3640 ms (CLI) vs 2543 ms (genied).
  - time to first token: 1200 vs 312 ms.
  - identity: 28/28.
  - idle CPU: poll on 359%, poll off 0%. With poll on, genied drove the board to 94 C. With poll off the speed is unchanged (3670 vs 3686 ms).
- **How to read it:** both bars drop. The time to first token drops the most (about 4x), which is what makes the UI feel responsive.
- **Takeaway:** keeping the model loaded saves about 1.1 s per call and gives a first token in 0.31 s, with identical outputs.
- **Caveats / limits:** the daemon has to run with poll off; otherwise it busy-waits and overheats the board. In this era, batching (genie-app) is off while genied is up, because two resident models hit the DSP SMMU limit and can reboot the board.
- **Explain it to a professor:** "Genie's CLI loads the model for every call. Our daemon holds one dialog open and resets it between calls. That cut a call from 3.64 to 2.54 s and the first token from 1.2 to 0.31 s, and 28 of 28 outputs matched the CLI byte for byte even with the prompt order reversed."
- **Likely follow-up:** Q: "How do you know reset does not leak state between calls?" A: The forward-then-reverse order means each prompt follows a different predecessor the second time, and all 28 were byte-identical to the stateless CLI.

---

#### `lat_route_incident` — Latency route, one 3-call cross-domain incident (crowded_room)
- **Claim on the card:** "18.7 s -> 11.6 s for the same 3-call incident". No "why".
- **What is plotted:** a waterfall. x is the cumulative steps; y is ms for the whole incident analysis (2 agents + synthesizer). One series, "incident analysis" (ours, blue). Each point is tagged with its HANDBOOK section.
- **How it was measured:** each step is a measurement of the real crowded_room incident in the app on that day (HANDBOOK 2.17, 2.20, 2.22, 2.29, 5, 2.13, 2.14). Collector: `Website/build/collect/latency.py`.
- **Result in numbers (lat_route_incident):**
  - crowded_room, batch OFF (Genie CLI): 18691 ms (2.17)
  - genie-app batching ON: 17726 (2.17)
  - inter-call gap 600 -> 250 ms: 17393 (2.20)
  - ctx 2048 bundle: 14727 (2.22)
  - genied + zero gap (trace): 11570 (2.29)
  - Notes: the event-gate batch window adds a further -4 s for isolated incidents and -2 s for cross-domain ones (`lat_batch_window`), outside the analysis time.
  - **Folded `lat_gap_sweep`** ("Inter-call gap re-measured: decode rate of the second call (tok/s)"; claim "No cliff any more: gap 600 -> 250 ms (CLI), 0 ms with genied"):
    - ascending gap: 0.0 s 22.53, 0.2 s 22.2, 0.3 s 21.94, 0.4 s 22.31, 0.6 s 22.31, 1.0 s 22.29 tok/s;
    - descending gap: 0.0 s 22.43, 0.3 s 22.42, 0.6 s 22.44, 1.0 s 22.1 tok/s;
    - notes: on 2026-10-07 (base model, before async init) a back-to-back session decoded at about 9 instead of about 19 tok/s. Real 3-call incident: 17726 -> 17393 ms. The 2500 ms bundle-change gap was kept.
  - **Folded `lat_genieapp_batch`** ("genie-app: N queries in one process (init paid once)"; claim "3.15 s per extra query vs 3.74 s per CLI call; 16/16 byte-identical"):
    - total wall time for N queries: 1 = 3.92 s, 2 = 7.022, 3 = 10.12, 5 = 16.537;
    - through the Go code, 3 prompts per-call took 16.41 s vs 13.748 s batched (1331 ms per extra prompt including the 600 ms gap). On a real incident, batch OFF 18691 vs ON 17726 ms;
    - batching was turned off while genied is up (a second model copy hits the DSP SMMU limit).
  - **Folded `lat_phase_trace`** ("Inside one 3-call incident (genied, SCE_GENIE_TRACE=1)"; claim "11.57 s total, of which ~11 ms is app overhead"): agents (2617 + 4488) 7112 ms, synthesizer 4457 ms, non-model time 11 ms.
- **How to read it:** the biggest drops are the ctx 2048 bundle (17393 -> 14727) and genied with zero gap (14727 -> 11570). The phase trace then shows nothing is left in the app: 11 ms.
- **Takeaway:** the same 3-call incident went from 18.7 s to 11.6 s in the Genie era, and what remains is pure model time.
- **Caveats / limits:**
  - The steps were measured on different days. Run-to-run variation is not given per step.
  - genie-app batching was later turned off when genied came in, so it is not part of the final stack.
  - On htpd v6 this incident takes 7.525 s (`uc_cross_domain`).
- **Explain it to a professor:** "We followed one real cross-domain incident through every Genie-era change: 18.7 s down to 11.6 s. A millisecond trace then showed that 11.57 s of it is model time and only 11 ms is our app, so further gains had to come from the model runtime. That is what led to htpd."
- **Likely follow-up:** Q: "Why was there an inter-call gap at all?" A: It guarded one CLI process's NPU teardown before the next process started. The sweep shows no decode-rate cliff at any gap now (21.94-22.53 tok/s), and with genied there is no teardown, so the gap is 0 (HANDBOOK 2.24).

---

#### `lat_batch_window` — Event-gate batch window: closes early when no other sensor is waking up
- **Claim on the card:** "-4 s on every isolated incident, cross-domain batching intact". No "why".
- **What is plotted:** a grouped bar chart. x is 3 scenarios; y is seconds of batch-window wait. Series: "before" (alt, grey) and "after" (ours, blue).
- **How it was measured:** the gate's own trace (`gate: batch opened` / `closed` log lines), HANDBOOK 2.29. Collector: `Website/build/collect/latency.py`.
- **Result in numbers (lat_batch_window):**
  - power_throttling (isolated): 6.0 -> 2.0 s
  - ventilation_failure (isolated): 6.0 -> 2.0 s
  - crowded_room (2 sensors): 6.0 -> 4.0 s
  - Notes: crowded_room "before" was at least 6.0 s.
- **How to read it:** isolated incidents now wait 1 reading (2 s) instead of 3. The 2-sensor incident waits 2 readings and is still a single incident.
- **Takeaway:** the batch window no longer waits when nothing else is waking up: 4 s saved per isolated incident.
- **Caveats / limits:** there is a trade-off (HANDBOOK 2.29). A correlated sensor that is not yet abnormal at all one reading after the first one matures will now form its own incident instead of joining. The times are on the 2 s demo clock. The 6.0 s "before" for crowded_room is a lower bound.
- **Explain it to a professor:** "After the 8-reading gate, the old code always waited 3 more readings so co-occurring sensors could join one incident, even when nothing else was abnormal. Now the window closes after one reading unless another sensor is abnormal-but-young. Isolated incidents save 4 s, and the crowded-room case still forms one incident."
- **Likely follow-up:** Q: "Can this split an incident that should be one?" A: Yes, if a correlated sensor is not yet abnormal at all one reading later (HANDBOOK 2.29). The scenario catalogue's only multi-target scenario still batches correctly.

---

#### `lat_rejected_ideas` — Tried and rejected: speed-ups that were slower or changed the answers
- **Claim on the card:** "The two fastest ideas were wrong: 1 in 14 and 1 in 12 answers identical". **Why it matters:** "A fast wrong answer is worse than a slow right one; every change is gated on output identity."
- **What is plotted:** a bar chart. Series "time change vs shipped (negative = faster)" (alt, grey) gives y in % time change, with a `why` in the tooltip. Series "identical answers" (ref; fraction with Wilson CIs) is shown for 3 of the ideas.
- **How it was measured:**
  - Each idea was A/B tested against the shipped configuration (HANDBOOK 2.12, 2.13, 2.14, 2.16, 2.25, 5, 2.19, 2.26, and `proofs/2026-10-16_hw_grid/samples.jsonl` for the GPU).
  - Basis of each % (from the notes): LADE is decode time, FWD_LEVEL vs basic. Continuous batching is an apparent 76% speed-up that came from truncation. Grammar and 3-graph are init+decode or total per call. Parallel is 2 x 200-token calls. GPU is grid INC-0407 vs Genie.
  - Collector: `Website/build/collect/latency.py`.
- **Result in numbers (lat_rejected_ideas):**

  | idea | time change % | why | identical answers |
  |---|---|---|---|
  | LADE lookahead decoding | -32.5 | answers changed; stuck sensor -> 'normal' | 0.0714 (1/14, CI 0.0127-0.3147) |
  | continuous batching (shared engine) | -76.0 | 'speedup' was truncated answers | 0.0833 (1/12, CI 0.0149-0.3539) |
  | grammar-constrained decoding | +18.1 | +440 ms init, 0 tokens saved | - |
  | 3-graph bundle | +14.8 | slower on every call | 1.0 (12/12, CI 0.7575-1.0) |
  | DSP RPC knobs | +1.6 | within noise | - |
  | two NPU sessions in parallel | +224.2 | 3x slower; crashed the board once | - |
  | GPU instead of NPU (1 agent) | +154.7 | slower at every size; no valid JSON at ctx 4096 | - |

  Notes: pre-warming the CLI was impossible because Genie reads the prompt to EOF first. Folded sub-datasets:
  - **`lat_rejected_continuous_batching`** ("Rejected: Genie shared-engine continuous batching truncates answers"; claim "The 76% 'speedup' was answers stopping early"): identical answers with 3 prompts concurrently were 0.0833 (1/12, CI 0.0149-0.3539). Run sequentially on the same shared-engine daemon, every answer was cut after 300-480 ms. `-slots` stays at the default 1 (re-verified 28/28).
  - **`lat_rejected_grammar`** ("Rejected: grammar-constrained decoding (xgrammar JSON schema)"; claim "+440 ms init, 0 tokens saved"): baseline init 713 / decode 2613 ms vs grammar init 1163 / decode 2765.5 ms (means of 2 runs: init 695/731 vs 1130/1196; decode 2574/2652 vs 2750/2781; 59 vs 62 tokens). Jump-forward only exists in draft-engine dialogs (eaglet/spd).
  - **`lat_rejected_lade`** ("Rejected: LADE lookahead decoding is fast and wrong"; claim "-20% decode, but 1 in 14 answers identical; a stuck sensor became 'normal'"):
    - decode on a single prompt: basic 2733.5, ALWAYS_FWD_ONE 1889, FWD_MAX_HIT 1933.5, FWD_LEVEL 1846 ms;
    - identical over 14 role/pattern prompts, FWD_LEVEL vs basic: 0.0714 (1/14);
    - notes: the first A/B (one prompt, repeated) looked like a clean 14% win (3947 -> 3380 ms). On 24 different prompts the answers diverged ('flatline'/'sensor_fault' -> 'flat78'/'normal', PM10 -> PM2.5). The minimal setting window=gcap=4 ngram=3 gave 4/13 identical and was slower (18.2 vs 19.7 tok/s).
  - **`lat_rejected_multigraph`** ("Rejected: 3-graph bundle (for LADE) is slower than the live 2-graph bundle"):
    - live 2 graphs: init 695, ttft 397, decode 2646, total 3738 ms;
    - 3 graphs basic: 845, 597, 2849, total 4291 ms;
    - it first failed to load with err 1002 (CDSP SMMU refusing a 112 MB mapping), which `enable-graph-switching: true` fixed. A 6.4 MB larger part3 was the difference. Only add graphs if they buy more than about 550 ms.
  - **`lat_rejected_parallel_npu`** ("Rejected: two Genie sessions in parallel on one NPU (2 x 200 tokens)"):
    - wall time: sequential back-to-back 33.8 s, sequential with a 0.5 s gap 23.6 s, parallel (B starts 2 s after A) 76.5 s;
    - in parallel the sessions ran at 4.9 / 10.0 tok/s, and B waited 54 s to initialise. One Genie session uses about 3.7 GB. The first parallel attempt crashed the board.
  - **`lat_rejected_prewarm`** ("Rejected: pre-warming genie-t2t-run / streaming a script to genie-app"):
    - time from writing the query line to output appearing: unpadded 60 s, +5 KB padding 82 s;
    - Genie reads the whole prompt (and genie-app the whole script) before touching the DSP. mkfifo is refused by SELinux everywhere. A persistent engine needed the C API, hence genied.
  - **`lat_rejected_rpc`** ("Rejected: DSP RPC knobs do not touch decode"): decode with rpc_control_latency 100 (live) 2638.5, rpc_control_latency 0 2643, rpc 0 + polling 9999 2681 ms. All within noise. mmap-budget 0 -> 25 changed init only by noise. direct-io produced no output. llm_decode_* profiles are V79+ only.
- **How to read it:** the two bars far to the left (fastest) are LADE and continuous batching. Their "identical answers" bars sit near 0. Everything else is slower.
- **Takeaway:** every speed-up that looked big either changed the answers or was slower; identity gating caught both cases.
- **Caveats / limits:**
  - The LADE bar (-32.5%) is a single-prompt decode-time comparison. The folded claim says "-20% decode", the multi-prompt framing in HANDBOOK 2.14. The data does not reconcile the two figures exactly; quote -32.5% as "single prompt, FWD_LEVEL".
  - The % values are computed on different bases (decode only vs total).
  - The identity rate is only plotted for 3 of the 7 ideas.
  - The board crashed once in the parallel test.
- **Explain it to a professor:** "We publish the ideas that failed too. Lookahead decoding cut decode time by a third on one prompt but changed 13 of 14 answers, one of them turning a stuck sensor into 'normal'. Continuous batching's 76% 'speed-up' was answers being truncated. Grammar decoding, a 3-graph bundle, parallel sessions and the GPU were simply slower."
- **Likely follow-up:** Q: "Isn't non-identical output acceptable if it's still correct?" A: The project rule is to never trade accuracy for latency. Without ground truth on every prompt, identity is the safe gate, and the LADE divergences included real errors (sensor_fault -> normal, PM10 -> PM2.5).

---

#### `lat_htpd_ab` — htpd A/B harness: 3 real incidents (4, 8, 13 agents), agents only
- **Claim on the card:** "13 agents 28.1 s -> 14.7 s; identical texts 25/25 vs v5". No "why".
- **What is plotted:** a grouped bar chart. x is the incident size (4, 8, 13 agents); y is seconds (agents only, no synthesizer). There are 7 configuration series: v6 (NEON argmax) + prefix cache is ours (blue), and all others are alt (grey). A full table sits underneath.
- **How it was measured:**
  - The A/B harness (`proofs/2026-10-16_htpd_ab/ab.py`, `ab.sh`, `ab2.sh`, `ab3.sh`) ran 3 real incidents x 2 reps per configuration; the total is from rep 2.
  - The board was cooled below 55 C before each config.
  - Identity is an exact text match against the previous config over 25 outputs. The run-to-run identity noise floor (same binary twice) is 21-24/25.
  - Proof: `proofs/2026-10-16_htpd_ab/RESULTS.md`. Collector: `Website/build/collect/latency.py`.
- **Result in numbers (lat_htpd_ab):**

  | config | 4 agents s | 8 agents s | 13 agents s | total s | prefill 13 s | identical |
  |---|---|---|---|---|---|---|
  | v1 (first htpd) | 15.3 | 20.0 | 28.1 | 63.4 | 8.6 | - |
  | v4 (HMX pipe + legacy prefill + parked + drafting) | 6.2 | 10.2 | 17.5 | 33.9 | 8.7 | 24/25 vs pcA |
  | v5 + HTPD_PREFIX_CACHE=1 (pcA) | 5.2 | 8.7 | 15.5 | 29.4 | 6.8 | - |
  | v5 + prefix cache (pcB, rerun) | 5.3 | 8.9 | 17.3 | 31.5 | 7.1 | 20/25 vs base |
  | v5 + prefix cache | 5.4 | 9.0 | 15.9 | 30.4 | 7.9 | - |
  | v6 (NEON argmax) + prefix cache | 4.8 | 8.2 | 14.7 | 27.7 | 7.2 | 25/25 vs v5 |
  | v5 + prefix cache (after v6) | 5.5 | 8.9 | 15.9 | 30.2 | 7.1 | 25/25 vs v6 |

- **How to read it:** compare v1 with v6 at 13 agents (28.1 -> 14.7 s) and at 4 agents (15.3 -> 4.8 s). Then look at the three v5 reruns (15.5, 17.3, 15.9 s at 13 agents) to see the run-to-run spread.
- **Takeaway:** the final htpd (v6) is about 2x faster than the first htpd at 13 agents and about 3x at 4 agents, with outputs identical to v5.
- **Caveats / limits:**
  - One rep is reported per cell (rep 2 of 2), and repeats of v5 vary by up to 1.8 s at 13 agents. Small differences such as v5 vs v6 at 13 agents (15.5-17.3 vs 14.7) are close to the noise.
  - Batched float sums are not bit-reproducible, so identity is judged against the 21-24/25 floor (HANDBOOK 2.37). The "20/25 vs base" entry is just below the floor.
  - The times are agents only; the synthesizer is excluded.
- **Explain it to a professor:** "We A/B tested each htpd version on the same three real incidents with the board cooled between runs. The first version was actually slower than Genie at 13 agents (28.1 s), and the final one takes 14.7 s, with texts identical to the previous version 25 of 25 times. The repeated v5 runs show our noise is about a second or two."
- **Likely follow-up:** Q: "Why is identity sometimes 20/25 or 24/25 and not 25/25?" A: With batching, floating-point sums are not bit-reproducible. Running the same binary twice already gives 21-24/25 identical, so that is the noise floor. Accuracy on 54 device windows did not drop: htpd final scored pattern 90.7 vs Genie 85.2 (HANDBOOK 2.37).

---

#### `lat_htpd_levers` — htpd: what each change bought (QIDK, 13-stream agent context)
- **Claim on the card:** "Verified drafting: 4 agents 14.9 s -> 5.8 s with identical answers". No "why".
- **What is plotted:** a grouped bar chart. x is the lever (with its incident size); y is seconds. Series: "before" (alt, grey) and "after" (ours, blue).
- **How it was measured:** individual on-device measurements per lever (HANDBOOK 2.37 table; `proofs/2026-10-16_htpd_ab/RESULTS.md`). The HMX pipe "before" value is the midpoint of 28-31 s. Collector: `Website/build/collect/latency.py`.
- **Result in numbers (lat_htpd_levers):**

  | lever | before s | after s |
  |---|---|---|
  | HMX pipe (13 agents) | 29.5 | 24.0 |
  | drafting (13 agents) | 22.0 | 16.4 |
  | drafting (4 agents) | 14.9 | 5.8 |
  | prefix cache prefill (13) | 8.7 | 6.8 |
  | prefix cache prefill (4) | 3.1 | 2.0 |
  | NEON argmax (A/B total) | 30.3 | 27.7 |

  Notes:
  - GGML_HEXAGON_FA_STREAMS=1 (per-stream flash attention on HTP) is what made batching faster than sequential at all (see `hw_htp_batching`).
  - Drafting is lossless: a draft is kept only when it equals the greedy choice.
  - NEON argmax: 25/25 identical.
  - HTPD_LEGACY_PREFILL keeps the old prefill order, because the equal-ubatch order changed about 30% of outputs.
  - Rejected: speculation on the synthesizer (changed outputs), 8-bit KV (2x slower), and thread/ubatch/power knobs.
- **How to read it:** drafting at 4 agents is the largest relative gain (14.9 -> 5.8 s). It helps small batches most, because they leave the most spare compute per weight sweep.
- **Takeaway:** each htpd lever was measured separately, and the biggest one, verified n-gram drafting, cut 4-agent time by more than half without changing answers.
- **Caveats / limits:**
  - The levers were measured at different stages, so their savings do not add up exactly to the v1 -> v6 change.
  - The "prefix cache" rows are prefill time only, not total time.
  - The HMX "before" is a range midpoint.
  - The data gives no repeat count per lever.
- **Explain it to a professor:** "In htpd we changed one thing at a time. Pipelined matrix units, verified drafting (we guess tokens from n-grams and keep a guess only if it equals what greedy decoding would produce), caching each role's system-prompt prefix, and a faster argmax. Drafting is the big one: 4 agents in 5.8 s instead of 14.9 s, with identical answers by construction."
- **Likely follow-up:** Q: "If drafting is lossless, why not use it on the synthesizer too?" A: Speculation on the synthesizer was tried and rejected because it changed outputs (notes, HANDBOOK 2.37). HANDBOOK 2.37 also says the synthesizer and Mode 2 do use drafting in the integrated backend, so their wording may differ slightly from Genie's. This is a nuance worth checking before claiming either way.

---

#### `lat_route_13_agents` — Latency route, 13 agents in one incident (agents only, A/B harness)
- **Claim on the card:** "13 agents: 22-25 s on Genie -> 14.7 s on htpd v6". No "why".
- **What is plotted:** a waterfall over versions (x); y is seconds. Series "13 agents" (ours, blue) and "4 agents" (alt, grey).
- **How it was measured:** the A/B harness values from `proofs/2026-10-16_htpd_ab/RESULTS.md`, plus the Genie reference from HANDBOOK 2.37 (13 agents is the midpoint of 22-25 s). Collector: `Website/build/collect/latency.py`.
- **Result in numbers (lat_route_13_agents):**

  | step | 13 agents s | 4 agents s |
  |---|---|---|
  | Genie (genied) | 23.5 | 15.0 |
  | htpd v1 | 28.1 | 15.3 |
  | htpd v4: HMX pipe + legacy prefill + drafting | 17.5 | 6.2 |
  | htpd v5 + prefix cache | 15.5 | 5.2 |
  | htpd v6: NEON argmax | 14.7 | 4.8 |

- **How to read it:** note that htpd v1 goes up from Genie (23.5 -> 28.1 s). Batching alone was not enough until HMX pipelining and drafting arrived.
- **Takeaway:** a new runtime first made things worse, and then the measured levers made it about 1.6x faster than Genie at 13 agents and about 3x at 4 agents.
- **Caveats / limits:**
  - On the 4-agent series, the first x label reads "Genie (genied), 13 agents", but the value 15.0 is the Genie 4-agent figure. The label is shared with the 13-agent series.
  - The Genie value is a range midpoint.
  - The steps are agents only.
- **Explain it to a professor:** "Switching runtimes was not an instant win: our first batched daemon was slower than Genie. Only after pipelining the matrix units, verified drafting and prefix caching did 13 agents drop to 14.7 s, and 4 agents from 15 s to 4.8 s."
- **Likely follow-up:** Q: "Why was v1 slower despite batching?" A: Decode is bandwidth-bound and batching only pays if all streams share one weight sweep efficiently. The HMX pipe (13 agents 28-31 -> ~24 s) and drafting (22 -> 16.4 s) were needed (`lat_htpd_levers`).

---

#### `lat_chaos_genie_vs_htpd` — Through the app: chaos incidents, Genie vs htpd (final)
- **Claim on the card:** "≈ 47 s -> 20.7 s for a 12-agent incident (QIDK, through the app)". **Why it matters:** "Decode is bandwidth-bound, so serving all agents in one weight sweep is the lever."
- **What is plotted:** a grouped bar chart. x is 6 test situations; y is seconds. Series: "Genie (genied)" (alt, grey) and "htpd final" (ours, blue).
- **How it was measured:**
  - The app stress test (`stress_app.py --only scenarios,chaos`) drives only the app's own API on the QIDK. The final htpd values come from `proofs/2026-10-16_htpd_v6_app_stress_report_final.json` and `_tail.log`.
  - The Genie values are midpoints of HANDBOOK 2.37 ranges (46-48, 41-46, 49-57, 22-25 s).
  - The A/B rows come from the harness.
  - Collector: `Website/build/collect/latency.py`.
- **Result in numbers (lat_chaos_genie_vs_htpd):**

  | situation | Genie | htpd final |
  |---|---|---|
  | 12 agents + synth | 47 | 20.7 |
  | 10 agents + synth | 43.5 | 20.6 |
  | 11 agents, staggered | 53 | 20.8 |
  | A/B 13 agents (agents only) | 23.5 | 14.7 |
  | A/B 4 agents | 15 | 4.8 |
  | Mode 3 median | 3.8 | 3.8 |

  App stress v6 overall: 132/135 checks passed. The 3 failures are thermal (96 C peak, guard tripped twice), per RESULTS.md and HANDBOOK 2.37.
- **How to read it:** on Genie, time grows with the number of agents. On htpd it is flat at about 20.7 s for 10, 11 and 12 agents, because they share one weight sweep.
- **Takeaway:** large incidents are more than 2x faster through the real app on htpd, and small ones are unchanged.
- **Caveats / limits:**
  - The Genie values are range midpoints from earlier runs, not paired runs on the same day.
  - htpd heats the board more: chaos peaks reach 95-96 C and the thermal guard trips on back-to-back chaos incidents, so a heatsink is advised.
  - One run per situation.
- **Explain it to a professor:** "Through the real app, a 12-sensor chaos incident went from about 47 s on Genie to 20.7 s on htpd. The time no longer grows with the number of agents, because all agents ride on the same pass over the weights. A typical small incident stays at 3.8 s."
- **Likely follow-up:** Q: "Did speed cost accuracy?" A: On 54 device windows, htpd final scored pattern 90.7 / status 94.4 / cause 87.0 / JSON 100 / policy 100, against Genie's 85.2 / 87.0 / 81.5 / 100 / 100 (HANDBOOK 2.37). With n=54 a few points are within noise, but there is no drop.

---

### 4.3 Hardware

The hardware topic answers the evaluators' question "GPU only, NPU only, or hybrid?" and documents the board's physical limits: heat and memory. The NPU is the Hexagon (V75) on the Snapdragon 8 Gen 3 (SM8650). The GPU is the Adreno 750. "HTP" means the Hexagon Tensor Processor, i.e. the NPU, reached through llama.cpp's Hexagon backend. "Genie NPU" means the same NPU reached through Qualcomm's Genie runtime.

---

#### `hw_grid` — Placement grid: the same incidents on Genie NPU, GPU and llama.cpp HTP (wall time)
- **Claim on the card:** "GPU-only is slower than the NPU at every incident size". **Why it matters:** "The evaluators asked for GPU only, NPU only and hybrid; the data decides."
- **What is plotted:** a grouped bar chart. x is the incident size (1 agent; 2, 4, 8, 13 agents + synthesizer); y is wall seconds. Series:
  - "Genie NPU (app, genied)" (ours, blue);
  - "GPU only, sequential (ctx 4096)" (alt, grey);
  - "GPU only, small footprint (ctx 1024)" (alt);
  - "llama.cpp HTP, 13 parallel streams" (alt);
  - "llama.cpp HTP, sequential" (alt).
  - The tooltips carry the peak temperature and the number of calls.
- **How it was measured:**
  - Five real app incidents were replayed as workloads (`proofs/2026-10-16_hw_grid/workload_INC-0407/0392/0384/0116/0401.json`) on each placement.
  - 1 rep per cell, board cooled between cells.
  - The Genie times are the original app incidents' `total_ms`.
  - Raw rows: `proofs/2026-10-16_hw_grid/samples.jsonl`, `htp/samples.jsonl`, `log.txt`, `manifest.json`. GPU bring-up logs: `proofs/2026-10-16_gpu_bringup/*/ladder.log`.
  - Collector: `Website/build/collect/hardware.py`.
- **Result in numbers (hw_grid):**

  | incident | Genie NPU | GPU seq ctx 4096 | GPU ctx 1024 | HTP 13 streams | HTP sequential |
  |---|---|---|---|---|---|
  | 1 agent | 3.93 (1 call) | 10.01 (peak 87.2 C) | - | - | - |
  | 2 agents + synth | 14.35 (3) | 30.01 (93.5 C) | - | 24.45 (80.6 C) | 26.36 (76.8 C) |
  | 4 agents + synth | 19.37 (5) | 48.96 (94.6 C) | 64.73 (95.8 C, 4 calls) | 34.46 (86.1 C) | 37.51 (81.8 C) |
  | 8 agents + synth | 34.94 (9) | 86.67 (95.0 C) | 133.66 (96.2 C, 8 calls) | 47.19 (88.4 C) | 61.93 (90.3 C) |
  | 13 agents + synth | 53.62 (14) | 137.6 (96.2 C) | - | 48.22 (91.5 C) | 82.62 (95.0 C) |

  `genie_reference` (per-incident Genie decode rates):
  - INC-0407: 1 agent, 3.929 s, 27.0 tok/s.
  - INC-0392: 2 agents, 14.352 s, 25.11 / 23.97 tok/s.
  - INC-0384: 4 agents, 19.37 s, 25.82 / 26.48 / 26.0 / 25.72 tok/s.
  - INC-0116: 8 agents, 34.94 s, 24.53-24.9 tok/s.
  - INC-0401: 13 agents, 53.618 s, 23.24-24.48 tok/s.
  - **Folded `hw_gpu_bringup_failures`** ("GPU bring-up: first runs killed (OOM), then the ladder fix"; y = exit code):
    - run1 01_bb_tiny_np1: 137 (killed, 5771 MB available);
    - run2 01_bb_tiny_np1: 137 (killed after drop_caches);
    - run3 05_bb_real_kvu_np124_mc3: 134 (abort: OpenCL work-group bug);
    - run4 after mc3 patch: 0;
    - notes: GPU (kgsl) and NPU buffers are unmovable and must fit in the 7.26 GB Normal zone, and Genie alone holds about 3.1 GB. Loading a second 3B on the GPU made the OOM killer pick system processes, and Android rebooted. The fix: llama.cpp at oom_score_adj 1000, drop_caches + compact_memory before each load, one rung at a time. No reboot since. Work-group fix: `app/htpd/patches/opencl_mc3_workgroup.patch`.
  - **Folded `hw_grid_peak_temp`** ("Placement grid: peak board temperature per run"): the same peak_c values as in the table. GPU runs peaked at 87-96 C, HTP runs at 77-95 C.
- **How to read it:** at each size, the grey GPU bars are 2.5-3x taller than the blue Genie bar. Then notice that at 13 agents the HTP 13-stream bar (48.22 s) is the only one below Genie (53.62 s). That was the first sign that batched HTP could win, which led to htpd.
- **Takeaway:** the GPU is slower than the NPU at every incident size, and batched llama.cpp on the NPU already beat Genie at 13 agents before any tuning.
- **Caveats / limits:**
  - 1 rep per cell.
  - The Genie column comes from the original app runs, while the GPU/HTP columns are replays. All use the same prompts.
  - GPU at ctx 4096 produced no valid JSON (json 0/n in log.txt), so its times are for unusable output. Only the ctx-1024 runs produced valid JSON (4/4, 8/8).
  - The HTP numbers here are untuned (before HMX pipe, drafting and prefix cache). htpd final is much faster (`lat_chaos_genie_vs_htpd`: 20.7 s for 12 agents + synth).
  - Hybrid placements (agents on GPU + synthesizer on NPU) were also slower per HANDBOOK 2.37, but they are not plotted.
  - The ctx-1024 "calls" counts (4, 8) suggest the synthesizer was not run there; the data does not say why.
- **Explain it to a professor:** "To answer 'GPU or NPU', we replayed the same five real incidents on Genie-on-NPU, llama.cpp-on-GPU and llama.cpp-on-NPU. The GPU was 2.5 to 3 times slower at every size, and at full context it did not even produce valid JSON. Batched llama.cpp on the NPU, still untuned, already beat Genie at 13 agents, so we built htpd on it."
- **Likely follow-up:** Q: "What about a hybrid, agents on GPU and synthesizer on NPU?" A: HANDBOOK 2.37 says hybrid placements were slower than the NPU at every size too. Two models also cannot both stay resident: unmovable GPU+NPU buffers must fit in the 7.26 GB Normal zone, and Genie alone holds about 3.1 GB.

---

#### `hw_grid_agreement` — Do GPU/HTP answers agree with the Genie NPU answers? (agent calls, same prompts)
- **Claim on the card:** "llama.cpp on the NPU agrees with Genie on 22/26 agent patterns; the GPU on 8/12". No "why".
- **What is plotted:** a grouped bar chart. x is the field (pattern, status, likely_cause, valid JSON); y is a fraction. Four alt (grey) series, one per placement, with Wilson 95% CI whiskers.
- **How it was measured:** for every agent call in the placement grid, the GPU or HTP answer was compared with the Genie answer to the same prompt. This is agreement with Genie, not accuracy against ground truth. Sources: `proofs/2026-10-16_hw_grid/samples.jsonl`, `htp/samples.jsonl`. Collector: `Website/build/collect/hardware.py`.
- **Result in numbers (hw_grid_agreement):**

  | placement | pattern | status | likely_cause | valid JSON |
  |---|---|---|---|---|
  | GPU seq ctx 4096 | - | - | - | 0.0 (0/28, CI 0.0-0.1206) |
  | GPU ctx 1024 | 0.6667 (8/12, CI 0.3906-0.8619) | 0.75 (9/12, CI 0.4677-0.9111) | 0.75 (9/12, CI 0.4677-0.9111) | 1.0 (12/12, CI 0.7575-1.0) |
  | HTP 13 streams | 0.8462 (22/26, CI 0.6647-0.9385) | 0.8846 (23/26, CI 0.7102-0.96) | 0.8077 (21/26, CI 0.6212-0.9149) | 1.0 (27/27, CI 0.8754-1.0) |
  | HTP sequential | 0.8462 (22/26) | 0.8846 (23/26) | 0.8077 (21/26) | 1.0 (27/27) |

- **How to read it:** first the GPU ctx 4096 bar at 0 valid JSON: unusable. Then HTP vs GPU-1024 on pattern, 0.85 vs 0.67. Note also that HTP parallel and sequential give exactly the same agreement, so batching did not change answers in this check.
- **Takeaway:** llama.cpp on the NPU stays close to Genie's answers (85% pattern agreement) and always produces valid JSON; the GPU either breaks the JSON or agrees less.
- **Caveats / limits:**
  - Agreement is not accuracy. Genie itself is wrong sometimes, and on 54 device windows htpd final was more accurate than Genie (HANDBOOK 2.37).
  - The samples are small (12 GPU calls, 26-27 HTP calls) and the CIs are wide.
  - HANDBOOK 2.37 quotes 82% GPU agreement from a wider check. The saved grid rows give 8/12 = 67% for pattern, and the card shows the saved rows.
  - Why the HTP denominators are 26 for the fields but 27 for JSON is not in the data.
  - These are untuned HTP builds, before htpd's levers.
- **Explain it to a professor:** "Speed is only useful if the answers survive the move. On identical prompts, llama.cpp on the NPU matched Genie's pattern 22 of 26 times with always-valid JSON. The GPU at full context produced no valid JSON at all, and at reduced context matched only 8 of 12."
- **Likely follow-up:** Q: "Is 85% agreement good enough?" A: The decisive check is accuracy against ground truth. On 54 device windows htpd final scored pattern 90.7 vs Genie 85.2, with JSON and policy both at 100 (HANDBOOK 2.37), so the disagreements did not make it worse.

---

#### `hw_gpu_batched` — GPU (Adreno 750, llama.cpp OpenCL): batched decode does not scale (600-token prompt, 80 tokens)
- **Claim on the card:** "1 stream 16.7 tok/s; 8 streams together only 12.4 tok/s". No "why".
- **What is plotted:** a line chart. x is the number of parallel streams B (1-8); y is total decode tok/s across all streams. Series (all alt, grey): "decode tok/s, all streams (unified KV)", "decode tok/s, shared prefix" and "decode tok/s, split KV". A ref series, "wall s per batch (unified KV)", is in seconds.
- **How it was measured:** `llama-batched-bench` on the device's own weights, repacked to Q4_0/Q8_0 so the comparison is like for like, with 600-token prompts and 80 generated tokens. Logs: `proofs/2026-10-16_gpu_bringup/run4_gpu_only_mc3fix/ladder.log` and `run5_gpu_only_opts/ladder.log`; HANDBOOK 2.37. Collector: `Website/build/collect/hardware.py`.
- **Result in numbers (hw_gpu_batched):**
  - unified KV, total decode tok/s: B=1 16.73, B=2 11.01, B=3 11.85, B=4 12.24, B=6 11.02, B=8 12.41.
  - shared prefix: B=1 16.59, B=2 14.1, B=4 18.6.
  - split KV: B=1 16.52, B=2 15.79, B=4 18.12.
  - wall s per batch (unified): B=1 7.852, B=2 21.316, B=3 31.786, B=4 43.07, B=6 73.727, B=8 97.407.
  - Notes: the OpenCL matmuls do not batch. Prefill on the GPU is about 195 tok/s, vs about 970 tok/s on HTP and about 1380 tok/s in Genie.
  - **Folded `hw_gpu_bench_knobs`** ("GPU llama-bench: prefill/decode with each knob"):
    - prefill pp600: baseline 184.83, dp4a 63.73, ubatch 128 176.51, ubatch 256 177.64, ubatch 1024 160.36, flash attention on 123.75 tok/s;
    - decode tg80: baseline 21.78, dp4a 21.99, flash attention on 7.52 tok/s;
    - notes: dp4a cut prefill to 64 tok/s, flash attention on cut decode to 7.5 tok/s, and ubatch gave no gain. None was adopted.
- **How to read it:** a scaling line would rise with B. Here it stays flat at about 11-12 tok/s, below the single-stream value, while wall time per batch grows almost linearly (7.9 s to 97.4 s).
- **Takeaway:** on this GPU, running agents together is no faster than running them one after another, so the GPU cannot use the batching trick that saves the NPU.
- **Caveats / limits:**
  - This is a synthetic benchmark, not app incidents (those are in `hw_grid`).
  - The shared-prefix and split-KV variants reach about 18 tok/s at B=4, a small gain only, and they were only measured up to B=4.
  - llama-bench's baseline decode (21.78 tok/s, tg80) is higher than batched-bench's B=1 (16.73) because the tools measure differently; the data does not explain the gap.
- **Explain it to a professor:** "We tested whether the Adreno GPU could serve many agents at once. Total throughput stayed at about 12 tokens per second whether 1 or 8 streams ran, so 8 agents take about 8 times as long. The OpenCL matrix kernels do not batch, and no knob we tried fixed that."
- **Likely follow-up:** Q: "Could a different GPU framework (MLC, Vulkan) batch better?" A: That is not in the data. MLC-LLM was listed as "not tried" (A7 in `hw_platform_paths`).

---

#### `hw_htp_batching` — NPU via llama.cpp Hexagon: batched decode before/after the per-stream flash-attention patch
- **Claim on the card:** "13 streams: 15 tok/s total before the patch, 75 tok/s after". **Why it matters:** "Batching only pays if all agents share one sweep over the weights; this patch made that true on the NPU."
- **What is plotted:** a line chart. x is the number of parallel streams B (1, 2, 4, 8, 13); y is total decode tok/s across all streams. Series: "before (FA on CPU)" (alt, grey), "FA on HTP, KV unified" (alt) and "FA_STREAMS patch (shipped in htpd)" (ours, blue). The tooltips carry wall_s and prefill_tok_s.
- **How it was measured:** a ladder of llama.cpp Hexagon runs with 600-token prompts and 80 tokens each (`proofs/2026-10-16_htp_bringup/ladder.log`, `real_fa_kvu.txt`, `real_fa_streams_patch.txt`, `knob_sweep.txt`; HANDBOOK 2.37). Collector: `Website/build/collect/hardware.py`.
- **Result in numbers (hw_htp_batching):**

  | B | before (FA on CPU) tok/s / wall s / prefill tok/s | FA on HTP, KV unified | FA_STREAMS patch |
  |---|---|---|---|
  | 1 | 18.91 / 4.849 / 968.56 | 17.37 / 5.255 / 922.31 | 17.58 / 5.22 / 895.34 |
  | 2 | 2.89 / 57.582 / 562.81 | - | - |
  | 4 | 5.04 / 69.114 / 427.01 | 28.92 / 14.065 / 800.35 | 30.2 / 13.082 / 965.23 |
  | 8 | 9.52 / 79.519 / 390.21 | 51.89 / 20.167 / 612.81 | 54.13 / 17.412 / 858.95 |
  | 13 | 15.32 / 91.801 / 326.02 | 48.11 / 37.966 / 477.05 | 75.2 / 23.805 / 781.97 |

  Notes: wall time for 13 agents was 91.8 s before, 38.0 s with FA on HTP, and 23.8 s with the streams patch.
  - **Folded `hw_htp_knob_sweep`** ("HTP runtime knobs (13 streams, 600-token prompts, 32 tokens)"), decode tok/s for all streams (prefill tok/s, wall s):
    - POWER_MODE=sustained_high_performance: 75.0 (780.38, 15.542)
    - POWER_MODE=burst: 81.66 (802.82, 14.81)
    - FA_HEAD_SPLIT=1: 81.28 (796.04, 14.917)
    - FA_SELECT=1: 81.73 (98.68, 84.132)
    - FA_SELECT=2: 79.87 (786.92, 15.12)
    - MM_SELECT=1: 32.74 (47.09, 178.348)
    - MM_SELECT=2: 80.61 (776.95, 15.2)
    - OPPOLL=1: 79.25 (744.77, 15.722)
    - Notes: burst vs sustained power mode is +9%. FA_SELECT=1 and MM_SELECT=1 are 5-10x slower. The others are within noise. Defaults were kept.
- **How to read it:** the blue line climbs steadily to 75.2 tok/s at 13 streams. The "before" line collapses at B=2 (2.89 tok/s) and only crawls back to 15.32. The middle line flattens at 13 streams (48.11 tok/s).
- **Takeaway:** our per-stream flash-attention patch makes the NPU scale almost linearly with agents (13 agents: 91.8 s to 23.8 s), which is the foundation of htpd.
- **Caveats / limits:**
  - This is a synthetic benchmark (600-token prompts, 80 tokens), not app incidents.
  - The knob sweep uses 32 tokens, so its tok/s numbers are not directly comparable with the ladder.
  - Burst mode gave +9% but was not adopted. The notes say "defaults kept", and the data does not say why; heat is a plausible reason but is not stated.
  - B=2 was not measured for the patched builds.
- **Explain it to a professor:** "In stock llama.cpp, flash attention for batched streams fell back to the CPU, so 13 streams managed only 15 tokens per second in total. We patched it to run per-stream attention on the Hexagon NPU. Now 13 streams decode at 75 tokens per second together and 13 agents finish in 23.8 s instead of 91.8 s."
- **Likely follow-up:** Q: "Why does the NPU batch well when the GPU does not?" A: Decode is bandwidth-bound (`lat_bandwidth_roof`: 49.3 GB/s of a 59 GB/s ceiling). Once attention runs on the HTP per stream, all 13 streams share one sweep over the weights. The GPU's OpenCL matmuls do not batch (`hw_gpu_batched`).

---

#### `hw_board_thermal` — QIDK board temperatures (measured)
- **Claim on the card:** "Idle ~43 C after the UI fix; chaos peaks 94-96 C need a heatsink". No "why".
- **What is plotted:** a bar chart. x is the board state; y is degrees C. One series, "measured" (ref).
- **How it was measured:** board temperature readings logged during development and stress runs (HANDBOOK 2.30, 2.35, 2.37, 2.27, 5; `proofs/2026-10-16_htpd_v6_app_stress_tail.log`; `future.md`; ppt.md). "Right after inference" is the midpoint of 63-69 C. Collector: `Website/build/collect/hardware.py`.
- **Result in numbers (hw_board_thermal):**

  | state | C |
  |---|---|
  | idle, any dashboard tab | 50 |
  | rest after 3 incidents (CPU) | 39 |
  | right after inference | 66 |
  | idle, DeerFlow UI (before power fix) | 75 |
  | idle, after UI power fix | 43 |
  | genied poll busy-wait (before fix) | 94 |
  | 13-agent chaos, before pacing | 94 |
  | chaos with thermal pacing (Genie) | 90 |
  | htpd chaos peaks | 96 |

  Notes: the guard pauses above 88 C NPU / 60 C skin. Before each NPU call at 88 C or more, the runner waits up to 15 s for 82 C. Use a heatsink or fan for the demo and the field.
  - **Folded `hw_ui_cpu`** ("The dashboard was the heater: app + WebView CPU"; claim "220% -> 5-11% CPU; board 75 C -> 43 C idle"), in % of one core:
    - before: idle (DeerFlow redesign) 220, incident sheet open 185;
    - after: 8 and 10 (8 is the midpoint of 5-11%);
    - cause: 22 px backdrop blurs re-rasterised under 60 fps infinite animations.
  - **Folded `hw_memory`** ("Memory on the QIDK"), resident MB:
    - Genie session (one 3B): 3700;
    - Genie unmovable share of the Normal zone: 3100;
    - edge-agent backend (24 min stress): 15;
    - genied daemon (24 min stress): 81;
    - genied with the ctx-4096 window: 237;
    - notes: the Normal zone is 7.26 GB. Two full models cannot be resident: loading the base 3B beside genied rebooted the board with 5.8 GB free (2.27). Soak: backend 24-27 MB, daemon 77 MB, no growth.
  - **Folded `ad_reasoner_plan`** ("Cross-domain reasoner: why it is a swap, and why it is parked"), download speed in MB/s:
    - AWS S3 us-west-2 (Qualcomm pre-quantised Qwen3-1.7B, 8.28 GB): 0.018;
    - HuggingFace (unquantised): 1.36;
    - notes: two full models cannot be resident, so the reasoner would be a per-incident swap (about +1.5 s on multi-domain incidents). future.md recommends LoRA adapters in one context binary instead of a second model. Today severity and titles come from a deterministic stub (`severity.go`, `title.go`) that the reasoner will replace.
- **How to read it:** two groups. Idle and normal operation (39-66 C) is fine. The peaks (90-96 C) come from heavy chaos incidents or from bugs that were fixed (poll busy-wait, the DeerFlow UI).
- **Takeaway:** the board idles cool after two fixes, but heavy multi-agent load on htpd reaches 96 C, so the deployment needs a heatsink or fan.
- **Caveats / limits:**
  - These are point readings from different days and conditions, not one controlled experiment.
  - The thermal guard tripped twice in the final v6 stress run and caused all 3 of its 3 failures (132/135).
  - The memory figures for the backend in the chart (15 MB) and in the notes (24-27 MB soak) differ; both are quoted as recorded.
  - The `ad_reasoner_plan` download speeds explain why the reasoner is parked, not thermals; it is folded here only because it is a memory constraint.
- **Explain it to a professor:** "The board idles at about 43 C now, after we found the dashboard's blur animations were burning 220% CPU. Under a 12-13-agent chaos incident htpd pushes it to 96 C, and a thermal guard pauses NPU work above 88 C, so the field unit needs a heatsink. Memory is the other hard limit: one 3B session takes about 3.7 GB, so a second model cannot be resident."
- **Likely follow-up:** Q: "Does the thermal guard drop analyses?" A: No. Since HANDBOOK 2.31 it queues work until the board cools (it waits up to 15 s for 82 C before each NPU call). In the v6 stress run the only failed checks were the thermal ones (96 C peak, guard tripped twice).

### 4.4 Accuracy

**Statistics you will meet in 4.4 to 4.6 (read once, reuse everywhere).**

- **Wilson 95% CI (`ci_method: "wilson95"`, the `lo`/`hi` whiskers).** A range that, for a rate k/n, would contain the true rate 95% of the time if the experiment were repeated. Wilson is used instead of the textbook "p plus/minus 1.96 sigma" because it behaves well with small n and with rates near 0% or 100% (it never leaves 0-1). Example from the data: 54/54 valid JSON gives 1.000 with a CI of 0.9336-1 (so "100%" really means "at least about 93%" at n = 54). Computed by `wilson()` in `Website/build/collect/_lib.py`. Rule of thumb: if two bars' whiskers overlap a lot, do not claim a difference without a paired test.
- **McNemar exact test (`paired_tests`, `p_mcnemar`, `p_exact`, `p_exact_recomputed`).** Used when two systems (or two settings) are scored on the *same* cases. Cases both get right or both get wrong say nothing about which is better; only the discordant pairs count: b = "right only with A", c = "right only with B". If A and B were equally good, each discordant case would be a coin flip, so p = two-sided binomial probability of a split at least as lopsided as b vs c out of b + c. Example: Genie vs htpd final pattern, 2 vs 5 discordant, p = 0.453 (2 x 29/128). Example: 0 vs 12 gives p = 2 x 0.5^12 = 0.000488. Computed by `mcnemar()`/`binom_two_sided()` in `_lib.py`; the window/placement/long-range studies also ship their own `paired_tests.txt`.
- **p-value.** The probability of seeing a difference at least this large if there were truly no difference. Below 0.05 = "significant" by convention. **n.s.** = not significant (p >= 0.05): the data cannot tell the two apart; it does *not* prove they are equal. A `p_mcnemar` shown as `0` in the data means it rounded to 0 at 4 decimals; the exact value is in `p_exact_recomputed` (e.g. 8.55e-14).
- **Cohen's h.** An effect size for the difference between two proportions (h = 2 asin(sqrt p1) - 2 asin(sqrt p2); about 0.2 small, 0.5 medium, 0.8 large). It does **not** appear in any accuracy, agent_design or refinement dataset; if asked, say we report the raw difference plus CIs and paired p-values instead.
- **"k reconstructed as round(rate x n)".** Some older evaluations kept only rates, not per-sample rows. The collector rebuilds k from the rate. Such tables have no per-sample pairing, so no McNemar is possible for them.
- **Chart colour convention (all sections).** Series or point with `role: "ours"` = accent blue (the shipped choice). `alt` = grey (alternatives). `ref` = dashed/muted grey (a reference or diagnostic, not a competitor). `meta.chart.highlight_x` marks the chosen option (e.g. "4 h"). `unit: "fraction"` is displayed as percent.

---

#### `acc_v1_host_eval` — Fine-tuned vs base vs rules, 150 held-out Nov-Dec windows (laptop, 4-bit)
- **Claim on the card:** "Fine-tuning: pattern 94% vs 20% base and 68% rules" / **Why it matters:** "The base model invents formats and numbers; fine-tuning makes every answer usable."
- **What is plotted:** grouped bar chart. x = metric (pattern, status, cause, action, evidence valid, valid JSON); y = accuracy (fraction, shown as %). Series: "fine-tuned Llama 3.2 3B" (ours, blue), "base Llama 3.2 3B" (alt, grey), "rules (Mode 1)" (alt, grey; pattern only). Wilson 95% whiskers on every bar.
- **How it was measured:** laptop GPU, model loaded 4-bit NF4 (the QLoRA training format), 150 held-out windows from the test months Nov-Dec 2025 (30 per role: air_quality, water, power, occupancy, weather). Each window is a real calm 4 h window with one synthetic pattern injected, so the pattern label is exact. Source: `Code/smart-city-edge-agent/training/results/agents_20261006_2101/eval.json`, `eval.md`, HANDBOOK 2.7. Collector: `Website/build/collect/accuracy.py` (`v1_host()`).
- **Result in numbers:** fine-tuned pattern 0.94 (141/150, CI 0.8899-0.9681), status 0.9267 (139/150), cause 0.9333 (140/150), action 0.9067 (136/150), evidence valid 1.0 (150/150, CI 0.975-1), valid JSON 1.0 (150/150). Base: pattern 0.2 (30/150, CI 0.1438-0.2711), status 0.2933 (44/150), cause 0.18 (27/150), action 0.2267 (34/150), evidence valid 0.3467 (52/150), valid JSON 0.9933 (149/150). Rules: pattern 0.68 (102/150, CI 0.6017-0.7494).
- **How to read it:** look at the "pattern" group first (the only independent label), then "evidence valid": the base model writes valid JSON almost always (99%) but cites real evidence only 35% of the time, i.e. it fabricates.
- **Takeaway:** fine-tuning turns a model that guesses (20%) into one that is right 94% of the time on the laptop and always cites real evidence.
- **Caveats / limits:** k is reconstructed as round(rate x 150); `eval_agents.py` kept aggregates only, so there is no McNemar for this table. Status, cause and action labels are produced by the same teacher rules that Mode 1 runs, so only pattern is an independent comparison (HANDBOOK 2.36). Occupancy pattern labels are circular too (see `acc_v1_host_per_role`). Laptop NF4, not the device. The test set is class-balanced, not natural prevalence. Split is temporal only (train Jan-Aug, dev Sep-Oct, test Nov-Dec).
- **Explain it to a professor:** "We evaluated on 150 windows from months the model never saw. The pattern label is exact because we injected the pattern into real calm data. Fine-tuning lifts pattern accuracy from 20% to 94%, and the non-overlapping Wilson intervals (0.14-0.27 vs 0.89-0.97) make that unambiguous even without a paired test."
- **Likely follow-up:** "Q: Status and cause are 93%; is the model reasoning?" "A: Partly not provable here: those labels come from the same rule taxonomy Mode 1 uses, so 93% means it reproduces the taxonomy well. Our independent claim is the pattern gain (94% vs 68% rules), which carries through to cause and action."

#### `acc_v1_host_per_role` — Pattern accuracy per role (150 held-out windows, 30 per role)
- **Claim on the card:** "Fine-tuned 87-100% per role vs rules 53-63% (occupancy excluded: circular)" / **Why it matters:** not set in the data (meta.why absent).
- **What is plotted:** grouped bar chart. x = role (air_quality, water, power, occupancy, weather); y = pattern accuracy (fraction). Series: "fine-tuned" (ours, blue), "base" (alt), "rules (Mode 1)" (alt; the occupancy point carries the note "circular: occupancy labels come from the rules"). Wilson whiskers.
- **How it was measured:** same 150-window laptop run as `acc_v1_host_eval`, split 30 per role. Source `training/results/agents_20261006_2101/eval.json`, HANDBOOK 2.36. Collector `accuracy.py`.
- **Result in numbers:** fine-tuned: air 0.9667 (29/30), water 0.9667 (29/30), power 0.8667 (26/30), occupancy 1.0 (30/30), weather 0.9 (27/30). Base: air 0.0667 (2/30), water 0.1333 (4/30), power 0.1 (3/30), occupancy 0.5 (15/30), weather 0.2 (6/30). Rules: air 0.6333 (19/30), water 0.6 (18/30), power 0.5333 (16/30), occupancy 1.0 (30/30, circular), weather 0.6333 (19/30).
- **How to read it:** compare blue vs rules within each of the four continuous roles; ignore occupancy for the rules comparison.
- **Takeaway:** the fine-tune beats the rules on every non-circular role, by 27-37 points.
- **Caveats / limits:** n = 30 per role, so CIs are wide (e.g. power 0.7032-0.9469). Occupancy labels come from `occ_label`, the same logic as the rules, so the rules' 100% is by construction. k reconstructed from rates.
- **Explain it to a professor:** "Per role, the fine-tuned model is 87-97% on the four continuous sensors while the rule classifier is 53-63%. Occupancy is excluded from that comparison because its ground truth is generated by the rules themselves."
- **Likely follow-up:** "Q: Power is the weakest role at 87%. Why?" "A: The data does not say why; with 26/30 and CI 0.70-0.95 it is not significantly different from the other roles."

#### `acc_v1_rules_vs_llm_fair` — Pattern accuracy on the 4 non-circular roles (air, water, power, weather)
- **Claim on the card:** "Without the circular occupancy role: 92.5% vs 60.0%" / **Why it matters:** not set in the data.
- **What is plotted:** CI-dot chart (`ciDot`): one row "pattern, 4 roles", one dot per series with a 95% Wilson whisker. "fine-tuned" (ours, blue) vs "rules (Mode 1)" (alt).
- **How it was measured:** the four continuous roles of the 150-window laptop eval, pooled: n = 120. The collector sums round(rate x 30) per role (`accuracy.py`, lines 43-44). Source `eval.json`, HANDBOOK 2.36.
- **Result in numbers:** fine-tuned 0.925 (111/120, CI 0.8636-0.96); rules 0.6 (72/120, CI 0.5106-0.6832). HANDBOOK 2.36 also quotes rules 68.6% recomputed on all 900 test windows (prose; per-sample file not saved).
- **How to read it:** the two intervals do not come close to overlapping (0.68 upper vs 0.86 lower).
- **Takeaway:** the honest, non-circular rules-vs-AI number is 92.5% vs 60.0%.
- **Caveats / limits:** laptop, not device; no paired test (no per-sample rows); 68.6% on 900 windows is prose only.
- **Explain it to a professor:** "To avoid a circular comparison we drop occupancy, whose labels are rule-generated. On the remaining 120 windows the fine-tuned model is 32.5 points better than the threshold rules, with non-overlapping 95% intervals."
- **Likely follow-up:** "Q: Why does the card elsewhere say 68% for rules?" "A: 68% (102/150) includes occupancy, where rules are 100% by construction; without it the rules are 60%."

#### `acc_v1_output_tokens` — Mean answer length in tokens: fine-tuned vs base
- **Claim on the card:** "84 vs 199 tokens: shorter answers are faster answers" / **Why it matters:** "Decode is ~70% of a call, so every token saved is ~40-50 ms."
- **What is plotted:** grouped bar chart. x = role plus "ALL"; y = mean output tokens. "fine-tuned" (ours) vs "base" (alt). No CIs (means only).
- **How it was measured:** output token counts from the same 150-window laptop eval (`eval.json`). Collector `accuracy.py`.
- **Result in numbers:** fine-tuned: air 90.6, water 85.5, power 90.5, occupancy 66.8, weather 85.7, ALL 83.8. Base: air 218.1, water 210.2, power 220, occupancy 127, weather 218.3, ALL 198.7.
- **How to read it:** the ALL pair (83.8 vs 198.7).
- **Takeaway:** the fine-tune answers in less than half the tokens, which is a direct latency win on the NPU.
- **Caveats / limits:** laptop tokenizer counts; no spread or CI; the ms-per-token figure is from meta.why, not from this dataset. Later the `action` field was trimmed further (HANDBOOK 2.18), so the shipped length differs.
- **Explain it to a professor:** "Fine-tuning taught a compact JSON schema; the base model rambles. Since decode dominates call time, 115 fewer tokens per answer is several seconds saved per call."
- **Likely follow-up:** "Q: Is shorter output less informative?" "A: No: evidence validity is 100% for the fine-tune vs 34.7% for the base (`acc_v1_host_eval`)."

#### `acc_quant_waterfall` — Getting the fine-tune onto the NPU: pattern accuracy per export step
- **Claim on the card:** "54% -> 85%: the biggest gain was a double-BOS prompt bug, not quantisation" / **Why it matters:** "Host accuracy does not transfer to the device automatically; every step was measured on the same windows."
- **What is plotted:** waterfall (levels) chart. x = export step (1-10, in order); y = pattern accuracy (fraction). Each point carries its own role: step 1 laptop and steps 9-10 (live) are ours (blue); device attempts 2, 3, 6, 7, 8 are alt (grey); host diagnostics 4-5 are ref (dashed/muted). Wilson whiskers.
- **How it was measured:** steps 2-9 use the same 46 held-out windows; step 1 is the 150-window laptop eval; step 10 is the 54-window device set. "QIDK" steps ran on the Hexagon NPU via Genie with w4a16 (int4 weights, 16-bit activations); "host" steps are fake-quant simulations on the laptop (`fakequant_eval.py`, `training/results/fakequant_step0.jsonl`). Sources: HANDBOOK 2.7 and 2.36, `training/results/device_eval.md`, `ppt.md`. Collector `accuracy.py` (`quant()`).
- **Result in numbers:** 1 laptop NF4 0.94 (141/150); 2 first NPU export 0.5435 (25/46, CI 0.4018-0.6785); 3 + MSE-clipped scales 0.3913 (18/46); 4 diagnostic device int4 weights, fp activations (host) 0.7391 (34/46); 5 GPTQ int4, fp activations (host) 0.8913 (41/46); 6 GPTQ + base activation ranges (QIDK) 0.6739 (31/46); 7 GPTQ + Kaggle-recalibrated ranges 0.6087 (28/46); 8 GPTQ + recalibrated, BOS fixed 0.8261 (38/46); 9 GPTQ + published ranges, BOS fixed (live) 0.8261 (38/46, CI 0.6928-0.9091); 10 same live model, 54 windows 0.8519 (46/54, CI 0.734-0.923).
  - Folded `acc_device_v1_validation` and `acc_fakequant_host`: see their entries below.
- **How to read it:** follow the line left to right; the big jump is 6/7 -> 8 (BOS fix: 0.6739 -> 0.8261 range), not any quantisation trick. Steps 4-5 (host) show what quantisation alone costs: plain int4 0.7391, GPTQ 0.8913.
- **Takeaway:** on-device accuracy went 54% -> 85%; GPTQ recovered weight-rounding loss, and removing a duplicated BOS token was the single largest fix.
- **Caveats / limits:** five steps exist only as HANDBOOK prose (bundles overwritten), so k = round(rate x n) and no per-sample rows. Step 1 (n=150) and step 10 (n=54) use different window sets than steps 2-9 (n=46). With n = 46, CIs span about 25 points; step 9 vs 10 is the same model on different sets. Recalibrated ranges (step 7/8) did not beat the published ranges once BOS was fixed.
- **Explain it to a professor:** "The fine-tune was 94% on the laptop but 54% after the first NPU export. GPTQ int4 rounding closed most of the weight-quantisation gap in simulation (74% -> 89%), but the real culprit on the device was that Genie prepends its own BOS token, so every prompt had two, which the model never saw in training; fixing that took the device from 67% to 83%."
- **Likely follow-up:** "Q: How do you know the BOS bug was real and not noise?" "A: It was measured directly: 606 host tokens became 607 on the device (`acc_pipeline_parity` notes), and the same weights moved 0.6739 -> 0.8261 on the same 46 windows after stripping ours."

#### `acc_device_v1_validation` (folded into `acc_quant_waterfall`) — On-device validation that switched the app to the fine-tune (2026-10-07)
- **Claim on the card:** none (folded) / **Why it matters:** it is the gate that made the app use the fine-tune instead of the base model.
- **What is plotted:** grouped bar: x = pattern, policy pass; series "fine-tuned (n=20)" (ours) vs "base (n=20)" (alt); Wilson whiskers.
- **How it was measured:** first NPU export (before GPTQ and the BOS fix), 20 windows, on the QIDK. HANDBOOK 2.7, 2.36. Base run later overwritten (no per-sample rows).
- **Result in numbers:** fine-tuned pattern 0.45 (9/20), policy pass 0.8 (16/20); base pattern 0.2 (4/20), policy pass 0.2 (4/20). Per call: tuned 4.9 s vs base 7.5 s. Current live result: `device_eval.json` pattern 0.852, validated=True.
- **How to read it:** policy pass (0.8 vs 0.2) is the decisive bar; pattern was still low at this stage.
- **Takeaway:** even the first, flawed export beat the base model, so switching was safe.
- **Caveats / limits:** n = 20, CIs very wide (0.2582-0.6579 for 0.45); pre-GPTQ, pre-BOS-fix; numbers from HANDBOOK prose.
- **Explain it to a professor:** "Before trusting the fine-tune on the device we ran a 20-window gate; it beat the base on both pattern and policy pass and was faster per call, so the app switched. Accuracy was then raised to 85% by the steps in the waterfall."
- **Likely follow-up:** "Q: 45% seems poor; why ship it?" "A: It was the starting point that justified the switch; the live model is 0.852 on 54 windows (step 10)."

#### `acc_fakequant_host` (folded into `acc_quant_waterfall`) — Host fake-quant check: bf16 vs int4 (GPTQ merged) vs plain int4 (46 windows)
- **Claim on the card:** none (folded) / notes: "bf16 ceiling 0.913; GPTQ int4 0.891; round-to-nearest int4 (device weights) 0.739."
- **What is plotted:** bar per variant (x = variant), y = pattern accuracy, series role ours; points also carry status and cause.
- **How it was measured:** laptop simulation of quantisation on the same 46 windows, `training/results/fakequant_step0.jsonl`, HANDBOOK 2.7.
- **Result in numbers:** int4 fq_int4 (round-to-nearest, = device weights) pattern 0.7391 (34/46), status 0.783, cause 0.674; int4 merged (GPTQ) 0.8913 (41/46), status 0.913, cause 0.891; bf16 merged 0.913 (42/46), status 0.935, cause 0.913; int4 merged repeat 0.8913 (41/46), status 0.913, cause 0.891.
- **How to read it:** bf16 is the ceiling on these 46 windows; GPTQ gets within one window of it.
- **Takeaway:** with GPTQ, int4 weights cost about one window in 46 versus full precision; plain rounding costs eight.
- **Caveats / limits:** activations kept full precision here, so this isolates weight quantisation only; n = 46.
- **Explain it to a professor:** "We separated the weight-quantisation error from everything else by simulating it on the laptop: plain int4 rounding loses 17 points, GPTQ's error-compensating rounding loses about 2."
- **Likely follow-up:** "Q: Is the repeat run deterministic?" "A: Yes, the repeat reproduced 0.8913 exactly (greedy decoding)."

#### `acc_device54_engines` — Same fine-tuned weights on the QIDK NPU: Genie vs htpd (54 held-out windows)
- **Claim on the card:** "htpd is no worse: pattern 90.7% vs 85.2% on Genie (n = 54, p = 0.45)" / **Why it matters:** "A faster runtime is only acceptable if the answers do not get worse."
- **What is plotted:** grouped bar chart. x = metric (pattern, status, cause, action (derived), valid JSON, evidence valid, policy pass); y = fraction. Series: "Genie (QAIRT CLI/genied)" (alt), "htpd v1" (alt), "htpd final (v5/v6 + prefix cache)" (ours, blue). Wilson whiskers. Paired McNemar results attached.
- **How it was measured:** the same fine-tuned weights, three runtimes, on the QIDK NPU, 54 held-out device windows (about one per class). Windows paired across runs by role + gold label (each pair unique). Greedy decoding. Sources: `training/results/device_eval_samples.jsonl` and `device_eval.json` (Genie), `proofs/2026-10-16_htpd_accuracy/device54/` (htpd v1) and `device54_v5pc/` (htpd final), summaries; script `training/export/gpu/eval_htpd.py`; HANDBOOK 2.8, 2.37. Collector `accuracy.py` (`device54()`).
- **Result in numbers:**
  - Genie: pattern 0.8519 (46/54), status 0.8704 (47/54), cause 0.8148 (44/54), action (derived) 0.8148 (44/54), valid JSON / evidence / policy 1.0 (54/54).
  - htpd v1: pattern 0.8519 (46/54), status 0.8889 (48/54), cause 0.8333 (45/54), action 0.8519 (46/54), valid JSON 0.963 (52/54), evidence valid 0.9444 (51/54), policy pass 0.9444 (51/54).
  - htpd final: pattern 0.9074 (49/54, CI 0.8009-0.9598), status 0.9444 (51/54), cause 0.8704 (47/54), action 0.8889 (48/54), valid JSON / evidence / policy 1.0 (54/54).
  - McNemar (Genie vs htpd final): pattern 2 vs 5, p = 0.453; status 2 vs 6, p = 0.289; cause 1 vs 4, p = 0.375; action 1 vs 5, p = 0.219. (htpd v1 vs final): pattern 0 vs 3, p = 0.25; status 0 vs 3, p = 0.25; cause 0 vs 2, p = 0.5; action 0 vs 2, p = 0.5. All n.s.
  - Wall time for all 54: htpd v1 136 s, htpd final 78.6 s.
- **How to read it:** look at the blue bars vs Genie, then the p-values: blue is never lower, and none of the gains is significant.
- **Takeaway:** the faster batched runtime does not lose accuracy; it is nominally better (n.s.) and keeps JSON/evidence/policy at 100%.
- **Caveats / limits:** n = 54 is small; the 5-point pattern gain is within noise (p = 0.453), so the honest claim is "no worse", not "better". htpd v1 had 2 invalid JSON and 3 policy failures, fixed in the final version. Batched float sums are not bit-reproducible (21-24 of 25 identical texts run to run, HANDBOOK 2.37). The 900-window rerun is incomplete (`acc_test900_partial`).
- **Explain it to a professor:** "We replaced Qualcomm's Genie with our own batched llama.cpp-Hexagon daemon for speed, then re-ran the same 54 device windows. A paired McNemar test finds no significant difference on any field (p = 0.22-0.45), and the final daemon is never worse on any metric while taking 78.6 s instead of 136 s for the set."
- **Likely follow-up:** "Q: Why not say htpd improved accuracy?" "A: 5 vs 2 discordant windows is p = 0.453; that could easily be chance, so we only claim non-inferiority."

#### `acc_action_derived` (folded into `acc_device54_engines`) — Action generated by the model vs derived from (cause, status)
- **Claim on the card:** "Deriving the action: 0.778 -> 0.815, 2 fixed, 0 made worse" / **Why it matters:** the action is a deterministic function of (cause, status) in the training labels, so deriving it removes a model error source.
- **What is plotted:** bar, x = action; "generated by the model" (alt) vs "derived by policy.go" (ours); Wilson whiskers.
- **How it was measured:** Genie, same 54 device windows; gold actions were generated by `action_of(cause, status)` (`generate_dataset.py:360`, mirrored by `ActionOf` in `rules.go:283`); `policy.go` now always derives it. Source `device_eval_samples.jsonl`, HANDBOOK 2.8.
- **Result in numbers:** generated 0.7778 (42/54, CI 0.6506-0.868); derived 0.8148 (44/54, CI 0.6916-0.8962). Paired: 0 vs 2, p = 0.5, fixed 2, made worse 0.
- **How to read it:** "fixed 2, made worse 0" is the point, not the p-value.
- **Takeaway:** deriving the action can only help: it fixed 2 windows and broke none.
- **Caveats / limits:** n.s. (p = 0.5) because only 2 discordant cases; the action is now only as good as the cause.
- **Explain it to a professor:** "Since the action is defined as a lookup from cause and status, we stopped trusting the model's action field and compute it; on 54 windows that fixed 2 and changed nothing else."
- **Likely follow-up:** "Q: Then why does the model still output it?" "A: HANDBOOK 2.8: it still emits the field; it is ignored and disagreements are logged as a drift signal."

#### `acc_device54_per_role` (folded into `acc_device54_engines`) — Device pattern accuracy per role (54 windows)
- **Claim on the card:** none / notes: "9-12 windows per role: per-role differences are within noise."
- **What is plotted:** grouped bar, x = role, y = pattern accuracy; Genie (alt), htpd v1 (alt), htpd final (ours); Wilson whiskers.
- **How it was measured:** per-role split of the 54-window device runs (same sources as parent).
- **Result in numbers:** Genie: air 0.9167 (11/12), water 0.75 (9/12), power 0.8333 (10/12), occupancy 1.0 (6/6), weather 0.8333 (10/12). htpd v1: air 0.9167, water 0.9167 (11/12), power 0.8333, occupancy 1.0 (6/6), weather 0.6667 (8/12). htpd final: air 1.0 (12/12), water 1.0 (12/12), power 0.8333 (10/12), occupancy 1.0 (6/6), weather 0.75 (9/12).
- **How to read it:** weather is the weakest role on every runtime.
- **Takeaway:** no role gets worse on htpd final vs Genie; weather remains hardest.
- **Caveats / limits:** 6-12 windows per role; CIs are 30-50 points wide (e.g. weather 0.4677-0.9111). Meta n says 12 (per-role maximum).
- **Explain it to a professor:** "Per role the runtimes are indistinguishable given only 6-12 windows each; the breakdown is shown to prove that no role collapsed."
- **Likely follow-up:** "Q: Why is occupancy n = 6?" "A: The data gives 6 occupancy windows in the 54-window set; why it is half the others is not in the data."

#### `acc_test900_partial` (folded into `acc_device54_engines`) — 900-window device rerun: stopped after 39 windows (thermal stall at 91 C)
- **Claim on the card:** none / notes: "Incomplete: the run stopped on a one-off socket timeout (TimeoutError) at 91 C after 3 batches of 13. Shown only for completeness; wide CIs. The full 900-window rerun is still to do."
- **What is plotted:** bars for "htpd final, first 39 of 900" (ours): pattern, status, cause, valid JSON, policy pass.
- **How it was measured:** htpd final on the full 900-window test set, stopped early. `proofs/2026-10-16_htpd_accuracy/test900/samples.jsonl`, `test900.log`, HANDBOOK 2.37.
- **Result in numbers:** pattern 0.8974 (35/39, CI 0.7642-0.9594), status 0.9487 (37/39), cause 0.9231 (36/39), valid JSON 1.0 (39/39), policy pass 1.0 (39/39).
- **How to read it:** as a consistency check only: it agrees with the 54-window numbers.
- **Takeaway:** the first 39 of 900 look like the 54-window result; the big run is still owed.
- **Caveats / limits:** 39 windows, not a random sample of the 900 (first 3 batches); stopped by a thermal-related stall.
- **Explain it to a professor:** "We started the 900-window device evaluation but the board stalled at 91 C after 39 windows; those 39 agree with our 54-window result, and the full run is on our to-do list with cooling."
- **Likely follow-up:** "Q: Is thermal throttling going to affect accuracy?" "A: Not in the data; the stall stopped the run (a socket timeout), it did not change answers. Greedy decoding is deterministic up to batched float noise."

#### `acc_pipeline_parity` — Pipeline identity checks between training and the device
- **Claim on the card:** "Every identity gate passed: 400/400 prompts byte-identical to training" / **Why it matters:** not set; notes explain: the double-BOS bug proved small pipeline differences cost accuracy.
- **What is plotted:** bar chart (default type), x = check, y = count passing, each with n; single series "checks" (ours). No CIs (these are pass/fail counts).
- **How it was measured:** identity checks run at different times; sources are HANDBOOK 2.7, 2.9, 2.14, 2.22, 2.24, 2.32, 4.4. Collector `Website/build/collect/extras.py` (dataset lives under accuracy).
- **Result in numbers:** prompts byte-identical to training 400/400; GPTQ int4 tensors reproduced on device 1232/1232; activation encodings matched when rebuilding w4a16 11711/11711; verify_batch.py identical 16/16; verify_daemon.py identical (fwd + rev) 28/28; ctx 2048 vs 4096 identical 14/14; two-window gate identical 5/5. Notes: Genie prepends BOS itself (606 host tokens became 607 on device); stripping ours took the same weights from 67% to 83%. Greedy decoding is forced (the exported bundle defaulted to temp 0.8).
- **How to read it:** every bar is full (y = n).
- **Takeaway:** what runs on the device is provably the same prompt, weights and encodings as in training.
- **Caveats / limits:** the counts come from HANDBOOK prose, not re-run by the collector; "identical" for batched runs is judged against a run-to-run noise floor (HANDBOOK 2.37).
- **Explain it to a professor:** "After the BOS bug we stopped assuming the device matches training and checked it: prompts byte for byte, all 1,232 int4 tensors, and all 11,711 activation encodings match, and runtime changes like context length were verified to produce identical outputs."
- **Likely follow-up:** "Q: Why force greedy decoding?" "A: The exported bundle defaulted to sampling at temperature 0.8; that breaks caching and reproducibility (HANDBOOK 2.7)."

---

### 4.5 Agent design

Context in one paragraph: each domain agent is called once a sensor has been abnormal for 8 readings (`engine.go` `persistReadings`) and sees a 4 h window (48 five-minute points). The studies below ask (a) is 4 h the right length (window study), (b) where in that window events sit when the agent is called (placement study), (c) what to add for things a 4 h window cannot see (12 h CPU checks), and (d) how the policy gate treats answers. All window/placement/long-range studies use real held-out test-month data (Nov-Dec) with injected events, roles air quality, water and power (weather has no continuous 12 h windows), on the QIDK NPU via htpd v6, greedy decoding.

#### `ad_window_headline` — Window length study: 2, 4, 8, 12 h windows, same model on the QIDK NPU (604 cases x 4)
- **Claim on the card:** "4 h is the best single window: pattern 64% vs 42-56% elsewhere" / **Why it matters:** "The window decides what the agent can see; it was trained on 4 h, so other lengths lose accuracy."
- **What is plotted:** line chart, x = window length (2 h, 4 h, 8 h, 12 h; 4 h highlighted), y = fraction. Series: "pattern accuracy" (ours, blue), "status accuracy", "cause accuracy", "detection, injected events", "false alarms, calm windows" (all alt). Wilson bands.
- **How it was measured:** 604 cases x 4 lengths = 2416 NPU calls (htpd v6, 8 streams x 1024 ctx, batches of 8, greedy). Every window ends at the same instant; only the length changes (24/48/96/144 points). At 48 points the prompt is asserted byte-identical to training. Families: clean 80 (77 truth-normal), classic_* 169 (11 training patterns injected in the last 4 h), step_old 60, drift_long 60, subthr_spikes 75, real 160. Flag = status not normal or pattern not stable/vacant/occupied. Builder `training/window_study/window_study.py build`, seed 7. Sources: `proofs/2026-10-16_window_study/` (`summary.json`, `RESULTS.md`, `tables.md`, `manifest.json`, `paired_tests.txt`, `paired_tests.py`), HANDBOOK 2.38. Collector `agent_design.py`.
- **Result in numbers:** pattern (n=369) 2 h 0.458 (169), 4 h 0.637 (235, CI 0.587-0.684), 8 h 0.558 (206), 12 h 0.425 (157). Status 0.585 / 0.699 / 0.64 / 0.534. Cause 0.539 / 0.675 / 0.577 / 0.499. Detection of injected events (n=364) 0.665 / 0.775 / 0.799 / 0.821. False alarms on calm (n=77) 0.351 / 0.273 / 0.377 / 0.455. Strict clean subset (n=19): 5/5/0/0%.
- **How to read it:** follow the blue pattern line: it peaks at 4 h. Then note detection keeps rising with length while false alarms are lowest at 4 h.
- **Takeaway:** the trained length (4 h) gives the most accurate reading and the fewest false alarms; longer windows only buy detection.
- **Caveats / limits:** this tests the current model at out-of-distribution lengths, not a model trained at 8 or 12 h. "Clean" real windows hold real events, so false alarms are over-counted (strict clean n=19 bounds them below). One evaluation instant per case; the app re-evaluates every 5 minutes. Weather excluded; water has few distinct bases.
- **Explain it to a professor:** "We held everything fixed except the window length and ran 2,416 NPU calls. Pattern accuracy peaks at 4 h, 64% vs 42-56% elsewhere, and paired McNemar tests show 4 h beats every other length on classic patterns with p < 1e-10."
- **Likely follow-up:** "Q: Why is pattern accuracy 64% here when the device eval said 85-91%?" "A: This set is much harder: it includes old steps, long drifts and sub-threshold spikes that the training set never contained, and calm real windows with real events; on classic_* families at 4 h the per-family pattern rates are 0.611-1.0 (`ad_window_per_family`)."

#### `ad_window_paired` (folded into `ad_window_headline`) — Paired McNemar tests: 4 h vs every other length (same cases)
- **Claim on the card:** "4 h beats every other length on pattern accuracy, p < 0.0001" / **Why it matters:** CIs alone overlap for some comparisons; pairing on the same cases is the stronger test.
- **What is plotted:** p-values (`ref` series "p (McNemar)") per family/metric/comparison, plus a table.
- **How it was measured:** `proofs/2026-10-16_window_study/paired_tests.py` -> `paired_tests.txt`; collector recomputes exact p.
- **Result in numbers (table: family, metric, vs, only_4h, only_other, n, p_mcnemar, p_exact_recomputed):**
  - step_old flag: vs 2 h 10/2, n 60, p 0.0386; vs 8 h 6/14, p 0.1153 (0.115); vs 12 h 0/16, p 0 (0.0000305).
  - drift_long flag: vs 2 h 7/1, p 0.0703; vs 8 h 3/7, p 0.3438; vs 12 h 2/8, p 0.1094.
  - subthr_spikes flag (n 75): vs 2 h 7/16, p 0.0931; vs 8 h 12/23, p 0.0895; vs 12 h 6/21, p 0.0059.
  - classic_* pattern (n 169): vs 2 h 53/2, p 8.55e-14; vs 8 h 42/1, p 1e-11; vs 12 h 80/2, p 1.41e-21.
  - clean (truth normal) flag (n 77): vs 2 h 6/12, p 0.2379; vs 8 h 7/15, p 0.1338; vs 12 h 6/20, p 0.0094.
- **How to read it:** classic_* pattern rows are the accuracy claim; step_old vs 12 h (0/16) shows what longer windows do better; clean vs 12 h (6/20) shows the cost.
- **Takeaway:** 4 h wins on accuracy with overwhelming significance; 12 h significantly catches more old steps but also raises significantly more false alarms; 8 h vs 4 h is n.s. on drift, old steps and false alarms.
- **Caveats / limits:** many comparisons (15) without multiple-comparison correction; the classic_* results survive any correction, the marginal ones (0.0386, 0.0059, 0.0094) should be read with care.
- **Explain it to a professor:** "On the same 169 classic cases, 4 h is right where 12 h is wrong 80 times and the reverse only twice, p = 1.4e-21."
- **Likely follow-up:** "Q: For flags on clean windows, 'only_4h' means what?" "A: Windows flagged only at 4 h; on clean windows a flag is a false alarm, so 6 vs 20 against 12 h means 12 h raised 14 more false alarms (p = 0.0094)."

#### `ad_window_variety` (folded into `ad_window_headline`) — Variety of findings on 155 random real windows: distinct (pattern, status, cause)
- **Claim on the card:** none (folded) / **Why it matters:** checks whether the agent gives diverse answers on real traffic rather than one stock answer.
- **What is plotted:** bar/line of distinct outcome count per length (ours), with n and flagged fraction per point.
- **How it was measured:** the "real" family (random real windows, no injection) of the window study.
- **Result in numbers:** 2 h 18 distinct (n 160, flagged 0.55); 4 h 22 (n 155, flagged 0.671); 8 h 26 (n 157, flagged 0.732); 12 h 23 (n 160, flagged 0.706).
- **How to read it:** more distinct (pattern, status, cause) triples = richer output; flagged fraction rises with length.
- **Takeaway:** variety is similar across lengths (18-26); no length collapses to a single answer.
- **Caveats / limits:** no ground truth on these windows; "flagged" is not "wrong". Why n differs per length (155-160) is not in the data.
- **Explain it to a professor:** "On untouched real windows the agent produces 18-26 distinct findings depending on length; this is a sanity check against mode collapse, not an accuracy metric."
- **Likely follow-up:** "Q: 67% of real windows flagged at 4 h, is that a false-alarm rate?" "A: Not necessarily: these are random real windows, many contain real events; there is no label to say."

#### `ad_window_per_family` — Detection (flag) and pattern accuracy per case family and window length
- **Claim on the card:** "At 4 h, 83-100% of classic patterns are flagged; recurring small spikes only 32%" / **Why it matters:** not set.
- **What is plotted:** heatmap, x = window length, y (rows) = family, cell value = flagged rate; each cell also carries pattern accuracy, k, n, Wilson lo/hi.
- **How it was measured:** window study, per family (n 12-80 per family). Sources as `ad_window_headline`.
- **Result in numbers (flag rate 2/4/8/12 h; pattern acc 2/4/8/12 h):**
  - clean (n 58): flag 0.448/0.345/0.5/0.603; pattern 0.552/0.655/0.5/0.397.
  - clean_strict (n 19): flag 0.053/0.053/0/0; pattern 0.842/0.947/1/0.789.
  - classic_dip (13): flag 0.615/0.923/0.846/0.923; pattern 0.538/0.846/0.692/0.846.
  - classic_erratic (12): 0.75/1/1/0.917; 0.417/0.917/0.583/0.167.
  - classic_exponential_increase (18): 1/1/0.944/0.944; 0.556/0.944/0.667/0.611.
  - classic_flatline (18): 1/1/1/0.833; 1/1/0.944/0.778.
  - classic_gradual_decrease (12): 1/1/0.833/0.583; 1/1/0.667/0.5.
  - classic_gradual_increase (18): 0.778/1/1/1; 0.667/0.833/0.5/0.056.
  - classic_oscillation (12): 1/1/0.583/0.583; 1/1/0.417/0.25.
  - classic_spike (18): 0.5/0.833/0.667/0.889; 0.333/0.611/0.556/0.556.
  - classic_step_decrease (12): 0.583/0.917/0.833/0.667; 0.333/0.917/0.583/0.083.
  - classic_step_increase (18): 0.5/1/0.944/0.944; 0.278/0.944/0.667/0.333.
  - classic_throttling (18): 0.722/1/1/0.889; 0.611/1/0.889/0.556.
  - drift_long (60): 0.733/0.833/0.9/0.933; 0.217/0.267/0.367/0.35.
  - step_old (60): 0.6/0.733/0.867/1; 0.067/0.133/0.367/0.383.
  - subthr_spikes (75): 0.44/0.32/0.467/0.52; no pattern label.
- **How to read it:** read the 4 h column top to bottom: classic rows are 0.833-1.0 flagged; then scan right to see pattern accuracy collapse at 12 h (gradual_increase 0.056, step_decrease 0.083).
- **Takeaway:** 4 h flags nearly all classic events and names them well; longer windows flag old/slow events more but misname them; recurring small spikes are not solved at any length.
- **Caveats / limits:** n 12-18 for classic families, so differences under ~15 points are noise (RESULTS.md). Meta n = 75 is the largest family. The meta "clean" here is n 58 (vs 77 truth-normal in the headline); the exact subsetting rule is not in the data.
- **Explain it to a professor:** "Per family, the 4 h agent flags 83-100% of every trained pattern, but only 32% of recurring sub-threshold spikes, a pattern it was never taught; that gap is why the retrain v2 data adds it."
- **Likely follow-up:** "Q: Why does a 12 h window misname a gradual increase (5.6%)?" "A: The window study attributes it to statistics tuned for 4 h: at 12 h the same rise occupies a smaller part of the window; the model was trained only on 4 h."

#### `ad_window_old_events` — What longer windows catch: old steps, long drifts, recurring small spikes (detection)
- **Claim on the card:** "12 h catches every old step (73% -> 100%) but misnames them" / **Why it matters:** not set; it motivates the 12 h CPU checks.
- **What is plotted:** line chart, x = window length (4 h highlighted), y = detection fraction. Series (all alt): "old step (2.5-8 h ago)", "slow drift (6-12 h)", "recurring small spikes". Wilson bands.
- **How it was measured:** window study families step_old (60), drift_long (60), subthr_spikes (75: 3-5 spikes of 2-3.5x noise, below training spike size and warning limits, over 2-12 h, last in final 30 min). Any flag counts as detection.
- **Result in numbers:** old step 0.6 (36/60) / 0.733 (44) / 0.867 (52) / 1.0 (60/60, CI 0.94-1). Slow drift 0.733 / 0.833 / 0.9 / 0.933. Recurring small spikes 0.44 (33/75) / 0.32 (24) / 0.467 (35) / 0.52 (39). Notes: at 12 h, 25 of 39 sub-threshold detections are the agent calling the window flatline (a misreading).
- **How to read it:** old step and drift lines rise monotonically; spikes stay low and dip at 4 h.
- **Takeaway:** a longer window sees older and slower changes, but naming suffers (step_old pattern accuracy only 0.383 at 12 h, `ad_window_per_family`).
- **Caveats / limits:** detection = any flag, so a wrong label still counts; the 12 h spike gain is mostly flatline misreads.
- **Explain it to a professor:** "A 12 h window catches all 60 old steps versus 44 at 4 h, but the agent mostly misnames them, which is why we kept the 4 h agent and added cheap 12 h CPU detectors instead."
- **Likely follow-up:** "Q: Why not use 12 h then?" "A: Pattern accuracy drops to 42.5% and false alarms rise to 45.5% (`ad_window_headline`); the 12 h CPU checks get old steps to 93% with no new false alarms (`ad_longrange_arms`)."

#### `ad_window_subthr_called` (folded into `ad_window_old_events`) — What the agent called recurring sub-threshold spikes (top labels)
- **Claim on the card:** none / notes: "Mostly 'stable': the v1 model was never taught this pattern (fixed in retrain v2 data)."
- **What is plotted:** bars of label counts per window length (all alt).
- **How it was measured:** the 75 subthr_spikes cases, top 5 labels per length.
- **Result in numbers:** 2 h: stable 42, spike 10, erratic 8, dip 6, step_increase 6. 4 h: stable 51, spike 10, erratic 8, dip 4, oscillation 1. 8 h: stable 39, flatline 11, spike 9, dip 8, erratic 6. 12 h: stable 33, flatline 25, spike 8, dip 5, INVALID 3.
- **How to read it:** "stable" dominates; "flatline" grows with length.
- **Takeaway:** the model does not recognise recurring small spikes; at long lengths it misreads them as flatline.
- **Caveats / limits:** top labels only; counts per length do not sum to 75 here because only the top 5 are listed.
- **Explain it to a professor:** "When the event is a series of small spikes the model mostly says 'stable' because no training example looked like that; at 12 h it starts calling it 'flatline', a misreading."
- **Likely follow-up:** "Q: How is this being fixed?" "A: The notes say retrain v2 data includes this pattern; results of that retrain are not in these datasets."

#### `ad_window_rules_vs_agent` — Agent vs rules (Mode 1) on the same windows: detection and false alarms
- **Claim on the card:** "At 4 h the agent matches rule detection (78%) with fewer false alarms (27% vs 43%)" / **Why it matters:** "Status quo = threshold rules; the agent must not miss more while alarming less."
- **What is plotted:** line chart, x = window length (4 h highlighted), y = fraction. Series: "agent detection" (ours), "agent false alarms" (ours), "rules detection" (alt), "rules false alarms" (alt), "agent false alarms, strict clean" (ref). Wilson bands.
- **How it was measured:** the Mode 1 rule classifier scored on exactly the same window-study windows as the agent. n = 364 injected events, 77 calm truth-normal, 19 strict clean.
- **Result in numbers:** agent detection 0.665 / 0.775 (282/364) / 0.799 / 0.821; rules detection 0.624 / 0.78 (284/364) / 0.849 / 0.882. Agent false alarms 0.351 / 0.273 (21/77) / 0.377 / 0.455; rules false alarms 0.455 / 0.429 (33/77) / 0.636 / 0.701. Agent strict-clean false alarms 0.053 / 0.053 / 0 / 0 (n 19).
- **How to read it:** at 4 h compare the two detection lines (almost equal) and then the two false-alarm lines (agent lower).
- **Takeaway:** at the shipped 4 h, the agent detects as much as the rules while raising about a third fewer false alarms.
- **Caveats / limits:** no paired test is given for agent vs rules in this dataset; 21/77 vs 33/77 CIs (0.186-0.381 vs 0.324-0.54) overlap. Rules thresholds are tuned to 4 h too.
- **Explain it to a professor:** "On identical windows, the 4 h agent catches 77.5% of injected events vs 78.0% for the rules, but alarms on 27% of calm windows vs 43%. At longer windows rules catch more but alarm on up to 70% of calm windows."
- **Likely follow-up:** "Q: Is 27% vs 43% significant?" "A: No paired p-value for this comparison is in the data; the Wilson intervals overlap slightly, so treat it as a strong trend, not a proven difference."

#### `ad_window_cost` — Cost of a longer window (htpd, batches of 8)
- **Claim on the card:** "8 h costs +18% per agent, 12 h +32%" / **Why it matters:** not set; it is the latency side of the window decision.
- **What is plotted:** bar chart, x = window length (4 h highlighted). Series: "s per agent in a batch of 8" (ours, seconds), "prompt tokens (mean)" (alt, tokens), "output tokens (mean)" (alt, tokens), "prefill s per batch" (alt, seconds). Mixed units: read each series against its own unit.
- **How it was measured:** timing recorded per batch in the window-study run (n = 604 cases per length), htpd, batches of 8. Sources `proofs/2026-10-16_window_study/summary.json`, `tables.md`, HANDBOOK 2.38.
- **Result in numbers:** s per agent 1.091 / 1.164 / 1.374 / 1.536; prompt tokens 539.2 / 583.5 / 672 / 760.5; output tokens 69.3 / 71.5 / 74.1 / 72.3; prefill s per batch 3.81 / 4.29 / 5.23 / 6.49.
- **How to read it:** cost tracks prompt length (the series line grows); output length hardly changes.
- **Takeaway:** a longer window costs more for less accuracy, so 4 h is also the right cost point.
- **Caveats / limits:** means only, no spread; measured in batches of 8, not the app's single-incident mix.
- **Explain it to a professor:** "Going from 4 to 12 h adds about 180 prompt tokens, which raises per-agent time from 1.164 to 1.536 s; with lower accuracy at 12 h there is no reason to pay it."
- **Likely follow-up:** "Q: Why doesn't output length change?" "A: The answer is a fixed JSON schema; only the input series grows."

#### `ad_placement_curve` — When does the 4 h agent read an event right? Accuracy vs time since onset (208 events x 6)
- **Claim on the card:** "42% at 40 min (when the app asks) -> 88% at 3 h" / **Why it matters:** "The early alert is fast but reads young events poorly; this is why refinements at 1.5 h and 3 h exist."
- **What is plotted:** line chart, x = time since onset (20 min, 40 min, 1 h, 1.5 h, 2 h, 3 h; 40 min highlighted = today's call point), y = fraction. Series: "agent pattern accuracy" (ours), "agent status accuracy" (alt), "flagged at all" (alt), "rules pattern accuracy" (ref). Wilson bands.
- **How it was measured:** 208 events (10 patterns, about 21 each) injected into real calm test-month 4 h windows (air, water, power); each event placed with onset 4, 8, 12, 18, 24 or 36 readings before the window end; 1248 NPU calls, paired per event; htpd v6, 13 streams x 768 ctx; prompts byte-identical in format to training. Code `training/window_study/placement_study.py`; sources `proofs/2026-10-16_placement_study/` (`summary.json`, `RESULTS.md`, `tables.md`, `manifest.json`, `paired_tests.txt`), HANDBOOK 2.39. Collector `agent_design.py`.
- **Result in numbers:** pattern 0.236 (49/208) / 0.423 (88) / 0.572 (119) / 0.668 (139) / 0.76 (158) / 0.885 (184, CI 0.834-0.921). Status 0.567 / 0.615 / 0.712 / 0.74 / 0.788 / 0.865. Flagged 0.731 / 0.769 / 0.841 / 0.899 / 0.894 / 0.952. Rules pattern 0.255 / 0.327 / 0.361 / 0.596 / 0.606 / 0.567.
- **How to read it:** start at the highlighted 40 min point (0.423) and follow the blue line up to 3 h (0.885). Note that "flagged at all" is already 77% at 40 min: the agent knows something is wrong, it just cannot yet name it.
- **Takeaway:** the agent is asked early (fast alert) but reads events much better later, so re-reading at 1.5 h and 3 h is justified.
- **Caveats / limits:** "onset" is the true event start; in the app the 8-reading count starts when rules first see an abnormal value, which for slow events is later, so real delays are longer than 40 min. An injected slow rise reaches full amplitude at the window end whatever its length, so short slow rises are steep (calling them exponential is partly fair). Per-pattern n 19-21.
- **Explain it to a professor:** "We moved the same 208 events earlier and later in the 4 h window. At the moment the app calls the agent, about 40 minutes after onset, pattern accuracy is 42%; at 3 h it is 88%, and paired McNemar tests show every later point is better than 40 min at p < 1e-7."
- **Likely follow-up:** "Q: Why not just wait 3 h before alerting?" "A: Team decision: keep the early alert (flagged 77% at 40 min, rule status shows instantly) and add automatic refinements at 1.5 h and 3 h (`ref_device_runs`)."

#### `ad_placement_paired` (folded into `ad_placement_curve`) — Paired McNemar: 40 min vs every other onset (same 208 events)
- **Claim on the card:** "At 3 h: 105 events right that were wrong at 40 min, only 9 the other way (p < 0.0001)."
- **What is plotted:** two series of discordant counts per onset: "right only at 40 min" (alt) and "right only at the other onset" (ours), with p.
- **How it was measured:** `proofs/2026-10-16_placement_study/paired_tests.txt`; exact p recomputed by the collector.
- **Result in numbers:** 20 min: 40 right only at 40 min vs 1 right only at 20 min, p 3.82e-11. 1 h: 2 vs 33, p 3.67e-8. 1.5 h: 5 vs 56, p 5.65e-12. 2 h: 2 vs 72, p 2.94e-19. 3 h: 9 vs 105, p 6.81e-22.
- **How to read it:** at 20 min the comparison runs the other way (40 min is better than 20 min); from 1 h on, later is better.
- **Takeaway:** the improvement with time is not noise: every comparison is p < 1e-7.
- **Caveats / limits:** `p_mcnemar` shows 0 (rounded); use `p_exact_recomputed`.
- **Explain it to a professor:** "Because each event appears at every onset, we can count events that flip from wrong to right; at 3 h 105 flip to right and only 9 flip to wrong."
- **Likely follow-up:** "Q: What are the 9 that got worse at 3 h?" "A: Mostly spikes: at 3 h a spike is often called 'stable' (spike pattern accuracy 0.429 at 3 h, `ad_placement_heatmap`), which is why the app keeps an early spike/dip when the refinement only says 'stable'."

#### `ad_placement_heatmap` — Pattern accuracy per pattern and time since onset
- **Claim on the card:** "Steps are right from 1 h; oscillation and slow rises only at 3 h" / **Why it matters:** not set.
- **What is plotted:** heatmap, x = time since onset, rows = pattern (10), value = pattern accuracy; each cell has k, n, Wilson lo/hi.
- **How it was measured:** placement study, n = 19-21 per cell.
- **Result in numbers (20 min / 40 min / 1 h / 1.5 h / 2 h / 3 h):**
  - gradual_increase 0 / 0 / 0 / 0.048 / 0.429 / 0.857
  - gradual_decrease 0 / 0.286 / 0.714 / 1 / 1 / 1
  - exponential_increase 0.143 / 0.524 / 0.81 / 0.905 / 0.952 / 0.952
  - oscillation 0 / 0 / 0.048 / 0 / 0.238 / 1
  - flatline 0 / 0 / 0.333 / 1 / 1 / 1
  - erratic 0.048 / 0.048 / 0.143 / 0.19 / 0.238 / 0.667
  - spike 0.667 / 0.81 / 0.762 / 0.619 / 0.762 / 0.429
  - dip 1 / 1 / 1 / 1 / 1 / 0.952
  - step_increase 0.238 / 0.81 / 0.952 / 0.952 / 1 / 1
  - step_decrease (n 19) 0.263 / 0.789 / 1 / 1 / 1 / 1
- **How to read it:** each row turns "hot" at the time the pattern becomes recognisable; spike/dip are hot early and spike cools at 3 h.
- **Takeaway:** each pattern has its own "readable from" time: steps 1 h; flatline, gradual decrease, exponential rise 1.5 h; gradual increase, oscillation, erratic 3 h; spike/dip earliest.
- **Caveats / limits:** n 19-21 per cell; differences under ~20 points are noise.
- **Explain it to a professor:** "A flatline cannot be distinguished from 'stable' until it has lasted long enough, and an oscillation needs several periods; the heatmap shows exactly when each becomes readable, which set our refinement times of 1.5 h and 3 h."
- **Likely follow-up:** "Q: Why is flatline 0% at 40 min?" "A: At 40 min the agent calls 18 of 21 flatlines 'stable' (`ad_placement_called`): a short flat run looks like calm data."

#### `ad_placement_called` (folded into `ad_placement_heatmap`) — What the agent says instead, at 40 min and at 3 h (top 3 labels per pattern)
- **Claim on the card:** none (folded).
- **What is plotted:** a reference table (ref) per true pattern of the top labels at 40 min and 3 h.
- **How it was measured:** placement study outputs.
- **Result in numbers:** gradual_increase: 40 min exponential_increase 16, INVALID 3, stable 2; 3 h gradual_increase 18, exponential_increase 2, step_increase 1. gradual_decrease: stable 7, gradual_decrease 6, dip 5; 3 h gradual_decrease 21. exponential_increase: exponential_increase 11, spike 8, stable 2; 3 h exponential_increase 20, stable 1. oscillation: stable 8, spike 6, dip 5; 3 h oscillation 21. flatline: stable 18, spike 1, step_increase 1; 3 h flatline 21. erratic: spike 8, dip 6, stable 5; 3 h erratic 14, stable 3, spike 2. spike: spike 17, erratic 1, stable 1; 3 h spike 9, stable 5, erratic 3. dip: dip 21; 3 h dip 20, stable 1. step_increase: step_increase 17, exponential_increase 2, stable 1; 3 h step_increase 21. step_decrease: step_decrease 15, dip 3, INVALID 1; 3 h step_decrease 19.
- **How to read it:** early errors are "plausible neighbours" (a young ramp called exponential, a young flatline called stable), not random.
- **Takeaway:** early misreads are the model seeing too little of the event, which a later re-read fixes.
- **Caveats / limits:** top 3 labels only; "INVALID" means an answer whose label failed validation.
- **Explain it to a professor:** "The confusion is structured: a fresh gradual rise is called exponential 16 of 21 times at 40 min, and correctly called gradual 18 of 21 times at 3 h."
- **Likely follow-up:** "Q: Is calling a young gradual rise 'exponential' wrong?" "A: Partly fair: the injected rise reaches full amplitude at the window end, so a 40-min slow rise is steep (placement RESULTS.md limits)."

#### `ad_longrange_arms` — 12 h CPU checks (level shift + slow drift) added to the 4 h agent: test months
- **Claim on the card:** "Old steps 73% -> 93%, drifts 83% -> 95%, no new false alarms" / **Why it matters:** "Without the 12 h check we miss about 1 in 4 old steps; with it, 1 in 14."
- **What is plotted:** grouped bar chart, x = category (all injected events, false alarms piecewise-calm, old step, slow drift, recurring small spikes), y = fraction. Series: "agent 4 h (shipped)" (alt), "12 h detectors only" (ref), "agent 4 h + 12 h detectors (shipped)" (ours, blue), "agent 12 h" (alt). Wilson whiskers.
- **How it was measured:** detectors (`training/window_study/longrange.py`, mirrored in Go `longrange.go`, checked against 24 fixtures by `longrange_test.go`) tuned only on dev months Sep-Oct; tested once on Nov-Dec. Agent answers are the real NPU outputs from the window study (4 h prompts). The combined arm flags if either the agent or a detector flags. Calm reference = "piecewise-calm" (each 4 h slice passes the training generator's calm test), n = 39. Final params: kL 4, kD 4, rD 0.8, kE 99, cE 999, kQ 1 (kE/cE set out of reach = excursion detector disabled). Sources `proofs/2026-10-16_longrange/` (`evaluate_test.json/.md`, `RESULTS.md`, `params_final.json`, `paired_combined.txt`), HANDBOOK 2.39. Collector `agent_design.py`.
- **Result in numbers:**
  - Agent 4 h: all events 0.775 (282/364); false alarms 0.308 (12/39); old step 0.733 (44/60); slow drift 0.833 (50/60); small spikes 0.32 (24/75).
  - Detectors only: 0.346 (126/364); 0.026 (1/39); 0.683 (41/60); 0.4 (24/60); 0.053 (4/75).
  - Agent 4 h + detectors: 0.83 (302/364, CI 0.788-0.865); 0.308 (12/39); 0.933 (56/60, CI 0.841-0.974); 0.95 (57/60); 0.32 (24/75).
  - Agent 12 h: 0.821 (299/364); 0.333 (13/39); 1.0 (60/60); 0.933 (56/60); 0.52 (39/75).
  - Detectors fire on 10% (16/160, CI 0.062-0.156) of random real windows.
- **How to read it:** compare the blue bar to the "agent 4 h" bar in each group: old step and slow drift jump; false alarms stay at 12/39.
- **Takeaway:** cheap 12 h CPU checks recover most of what a 12 h agent would catch, without the 12 h agent's accuracy loss and with no new false alarms.
- **Caveats / limits:** recurring small spikes remain unsolved (32%). Test months lack water 36 h calm windows and weather 12 h windows; n per family 39-75. The detectors only add evidence lines (`S#.E9`/`S#.E10`) to the reasoner; in the app the reasoner decides, so the "OR" combination here is an upper bound on what the app does. Pattern accuracy is unchanged (64%) because the agent itself is unchanged. Detectors need 8 h of history.
- **Explain it to a professor:** "Rather than give the model a 12 h window it was not trained for, we run two CPU statistics over 12 h, a level-shift test and a linear-drift test with r-squared at least 0.8, tuned only on dev months. Combined with the 4 h agent they raise old-step detection from 73% to 93% (p = 0.0005) without adding a single false alarm on calm windows."
- **Likely follow-up:** "Q: The detectors alone have 2.6% false alarms; why does the combined arm keep 30.8%?" "A: Those 12 false alarms are the agent's own; the detectors added none (paired: 0 new on clean, `ad_longrange_paired`)."

#### `ad_longrange_paired` (folded into `ad_longrange_arms`) — Paired McNemar: agent alone vs agent + 12 h checks
- **Claim on the card:** "+12 old steps (p=0.0005), +7 drifts (p=0.016), 0 lost."
- **What is plotted:** discordant counts per family: "caught only with the 12 h checks" (ours) vs "caught only by the agent alone" (alt).
- **How it was measured:** `proofs/2026-10-16_longrange/paired_combined.txt`.
- **Result in numbers:** step_old 12 vs 0, n 60, p 0.0005 (0.000488); drift_long 7 vs 0, n 60, p 0.0156; subthr_spikes 0 vs 0, n 75, p 1; clean 0 vs 0, n 39, p 1.
- **How to read it:** the alt column is all zero by construction (adding an OR can only add flags), so the test asks whether the additions are more than chance.
- **Takeaway:** the gains are significant and nothing is lost; clean windows are untouched.
- **Caveats / limits:** "0 lost" is guaranteed by the OR design; the meaningful part is the size of the gain and the 0 on clean.
- **Explain it to a professor:** "On the same 60 old-step cases, 12 are caught only with the checks, 0 the other way, p = 0.0005."
- **Likely follow-up:** "Q: Why is the drift p larger?" "A: 7 discordant cases gives at best p = 2 x 0.5^7 = 0.0156."

#### `ad_longrange_per_family` (folded into `ad_longrange_arms`) — Long-range checks: detection per case family and arm
- **Claim on the card:** none (folded).
- **What is plotted:** detection per family (rows) and arm (x).
- **How it was measured:** as parent.
- **Result in numbers (agent 4 h / detectors only / combined / agent 12 h):** classic_dip 0.923/0/0.923/0.923; classic_erratic 1/0/1/0.917; classic_exponential_increase 1/0.667/1/0.944; classic_flatline 1/0.278/1/0.833; classic_gradual_decrease 1/0.167/1/0.583; classic_gradual_increase 1/0.222/1/1; classic_oscillation 1/0.333/1/0.583; classic_spike 0.833/0.056/0.833/0.889; classic_step_decrease 0.917/0.833/1/0.667; classic_step_increase 1/0.778/1/0.944; classic_throttling 1/0.278/1/0.889; clean 0.308/0.026/0.308/0.333; drift_long 0.833/0.4/0.95/0.933; step_old 0.733/0.683/0.933/1; subthr_spikes 0.32/0.053/0.32/0.52.
- **How to read it:** the combined column equals or exceeds the agent-4 h column everywhere; the detectors only add on step and drift families.
- **Takeaway:** the detectors are specialists for steps and drifts and do not disturb anything else.
- **Caveats / limits:** classic families n 12-18.
- **Explain it to a professor:** "The detectors alone catch almost no dips, spikes or erratic patterns; they are built for level shifts and drifts, and that is exactly where they add."
- **Likely follow-up:** "Q: classic_step_decrease went 0.917 -> 1.0; is that significant?" "A: It is one window (11/12 -> 12/12); not significant by itself."

#### `ad_longrange_ablation` — Ablation: with vs without the recurring-excursion detector (dev and test months)
- **Claim on the card:** "Dropping the excursion check cuts dev false alarms 15% -> 2% with the same old-step catch" / **Why it matters:** not set.
- **What is plotted:** grouped bar chart, x = split + family (dev clean, dev step_old, dev drift_long, dev subthr_spikes, dev real, test ...); y = fraction. Series "level shift + drift + recurring excursions" (alt) vs "level shift + drift (shipped)" (ours). Wilson whiskers.
- **How it was measured:** raw 12 h detectors on the 36 h daily-baseline case set (different from the window-study set). "clean"/"real" are false-alarm / fire rates, others are detection. Sources `proofs/2026-10-16_daily_baseline/ablation_no_excursions.txt`, `proofs/2026-10-16_longrange/RESULTS.md`.
- **Result in numbers:** with excursions: dev clean 0.15 (18/120), dev step_old 0.68 (51/75), dev drift_long 0.6 (45/75), dev subthr 0.16 (12/75), dev real 0.175 (21/120); test clean 0.2 (16/80), test step_old 0.86 (43/50), test drift_long 0.62 (31/50), test subthr 0.32 (16/50), test real 0.2875 (23/80). Shipped: dev clean 0.0167 (2/120), dev step_old 0.64 (48/75), dev drift_long 0.5733 (43/75), dev subthr 0.0133 (1/75), dev real 0.125 (15/120); test clean 0.0875 (7/80), test step_old 0.86 (43/50), test drift_long 0.56 (28/50), test subthr 0.1 (5/50), test real 0.2 (16/80).
- **How to read it:** compare "clean" bars (false alarms) first: big drop; then step_old: same or nearly same.
- **Takeaway:** the excursion detector mostly added false alarms; removing it costs little detection.
- **Caveats / limits:** dev and test use different n (dev 120/75, test 80/50). Test clean false alarms are 8.75% here vs 2.6% (1/39) in `ad_longrange_arms`: different case sets and calm definitions (36 h daily-baseline set vs piecewise-calm). Excursion detection was near chance in every variant (longrange RESULTS.md).
- **Explain it to a professor:** "We tried a third detector for recurring small excursions; on dev months it raised false alarms from 2% to 15% while barely changing detection, because real sensors have such excursions all the time, so we dropped it."
- **Likely follow-up:** "Q: Isn't dropping it giving up on sub-threshold spikes?" "A: Yes, and we say so: that pattern remains unsolved by both agent and detectors (32%)."

#### `ad_daily_baseline_rejected` — Rejected: 'same hours yesterday' baseline vs raw 12 h detectors (test months)
- **Claim on the card:** "Daily baseline: more false alarms (29% vs 20%), half the old steps (48% vs 86%)" / **Why it matters:** "Yesterday has its own events and noise; differencing adds them in instead of cancelling routine."
- **What is plotted:** grouped bar, x = family (clean, step_old, drift_long, subthr_spikes, real), y = fraction. "raw 12 h detectors" (ours) vs "daily baseline (rejected)" (alt). Daily-baseline points also carry which detector kinds fired.
- **How it was measured:** both detector sets include recurring excursions here (pre-ablation). Test months, 36 h contiguous windows. Sources `proofs/2026-10-16_daily_baseline/evaluate_test.json/.md`, `params.json`, `2026-10-16_daily_baseline.dev.log`.
- **Result in numbers:** raw: clean 0.2 (16/80), step_old 0.86 (43/50), drift_long 0.62 (31/50), subthr 0.32 (16/50), real 0.287 (23/80). Daily baseline: clean 0.287 (23/80; kinds recurring_excursions 22, slow_drift 1), step_old 0.48 (24/50; level_shift 20, recurring_excursions 17), drift_long 0.46 (23/50; recurring_excursions 14, slow_drift 13, level_shift 4), subthr 0.34 (17/50; recurring_excursions 17), real 0.3 (24/80; recurring_excursions 17, level_shift 7, slow_drift 1).
- **How to read it:** clean (lower is better) and step_old (higher is better): the baseline loses on both.
- **Takeaway:** subtracting yesterday makes things worse, so it was rejected.
- **Caveats / limits:** test months lack water 36 h calm windows; n 50-80.
- **Explain it to a professor:** "A natural idea is to subtract the same hours yesterday to cancel daily routine. Measured on held-out months it raised false alarms (29% vs 20%) and halved old-step detection (48% vs 86%), because yesterday's own events and noise get added in."
- **Likely follow-up:** "Q: Could a multi-day baseline work?" "A: The longrange RESULTS.md lists a per-sensor learned baseline over several days as an option; it is not tested in the data."

#### `ad_detector_tuning_frontier` — Detector tuning on dev months: best old-step catch for each false-alarm rate (Pareto front)
- **Claim on the card:** "At 15% false alarms the raw 12 h check catches 64% of old steps, the daily baseline 23%" / **Why it matters:** not set; shows the rejection is not a tuning accident.
- **What is plotted:** line chart, x = false-alarm rate on calm dev windows (rounded to 0.01), y = best level-shift true-positive rate at that false-alarm rate (the Pareto front of the grid). Series: "raw 12 h (daily_baseline set)" (ours), "daily baseline" (alt), "first raw grid (longrange set)" (ref). No CIs.
- **How it was measured:** grid search of 7680 parameter settings per grid on dev months only; sources `proofs/2026-10-16_daily_baseline/tune_grid_raw.jsonl`, `tune_grid_daily.jsonl`, `proofs/2026-10-16_longrange/tune_grid.jsonl`, `params.json`. Collector `agent_design.py`.
- **Result in numbers:** raw: (0.13, 0.187), (0.14, 0.427), (0.15, 0.64), (0.22, 0.747), (0.23, 0.76), (0.33, 0.773), (0.35, 0.84), (0.37, 0.853). Daily: (0.15, 0.227), (0.17, 0.32), (0.18, 0.453), (0.19, 0.507), (0.2, 0.573), (0.21, 0.587), (0.23, 0.667), (0.25, 0.693), (0.34, 0.76), (0.38, 0.787). First raw grid: (0.15, 0.3), (0.17, 0.483), (0.18, 0.65), (0.2, 0.717), (0.26, 0.767), (0.3, 0.8). The first grid found no setting under a 5% FP budget (params.json best_params null).
- **How to read it:** up-and-left is better; at any false-alarm budget around 0.15-0.23 the blue curve is above the daily baseline.
- **Takeaway:** over the whole tuning grid, the raw 12 h check dominates the daily baseline at low false-alarm budgets.
- **Caveats / limits:** these grids include the excursion detector (false alarms here are higher than the shipped 2% dev). Dev months only; no CIs; n of calm/old-step windows per grid not in this dataset (meta n null).
- **Explain it to a professor:** "To be sure the daily baseline was not just badly tuned, we compared the best achievable trade-off of each approach over 7,680 settings: at a 15% false-alarm budget the raw check catches 64% of old steps vs 23% for the baseline."
- **Likely follow-up:** "Q: Why was the first raw grid replaced?" "A: It found no setting under a 5% FP budget; the excursion ablation (`ad_longrange_ablation`) is what brought dev false alarms to 2%."

#### `ad_policy_gate` — Policy gate: transparent repairs raised the agent pass rate on demo scenarios
- **Claim on the card:** "Transparent repairs: agent pass rate 3/6 -> 5/6, nothing invented" / **Why it matters:** not set; notes: no actuation is ever allowed, every recommendation needs a human.
- **What is plotted:** bar chart (default). Series "agent pass rate" (ours): before repairs vs with repairs; series "v1 host: evidence valid" (alt): fine-tuned vs base. Wilson whiskers.
- **How it was measured:** 6 demo-scenario agent answers through the policy gate before and after adding repairs (HANDBOOK 2.7, 2.33, `ppt.md`); evidence-validity bars from `agents_20261006_2101/eval.json`. Collector `extras.py`. Repairs (each recorded in the incident's `repairs` field): action derived from the stated cause, packed evidence ids split ("S1.E5,S1.E7"), malformed JSON salvaged from the model's own fields, stray "]" removed. Invented labels are still rejected. A failed synthesizer answer is replaced by a report built from the agents' findings (Mode 3) or the rules (Mode 2).
- **Result in numbers:** pass rate before repairs 0.5 (3/6, CI 0.1876-0.8124); with repairs 0.8333 (5/6, CI 0.4365-0.9699). Evidence valid: fine-tuned 1.0 (150/150), base 0.3467 (52/150).
- **How to read it:** the two blue bars; then note the base model's 35% evidence validity is what the gate exists to catch.
- **Takeaway:** the gate fixes formatting, never content, and still rejects anything invented.
- **Caveats / limits:** n = 6, CIs overlap heavily; this is an illustration, not a statistical result. The two series measure different things and are only grouped on one card.
- **Explain it to a professor:** "Every model answer passes a deterministic policy gate. We added repairs that only reformat what the model already said, for example splitting packed evidence ids, and log each repair; that took the demo pass rate from 3/6 to 5/6 without accepting any invented label."
- **Likely follow-up:** "Q: Isn't salvaging malformed JSON risky?" "A: It extracts only the model's own stated fields; labels outside the taxonomy are still rejected, and each repair is visible in the incident's `repairs` field."

#### `ad_disagreement` (folded into `ad_policy_gate`) — AI vs rules disagreement in stress tests (surfaced, not overridden)
- **Claim on the card:** none / notes: "Rule right once (a missed pump oscillation); AI right twice (a CO2 episode already cleared). The report states the conflict."
- **What is plotted:** count of disagreements (ours) and who was right (ref).
- **How it was measured:** stress tests, 18 calls (`ppt.md`, HANDBOOK 2.33).
- **Result in numbers:** 3 disagreements in 18 calls (agent said normal on a rule-flagged sensor); rule right 1, AI right 2.
- **How to read it:** small counts; the point is the policy, not a rate.
- **Takeaway:** neither side overrides; the report tells the operator they disagree.
- **Caveats / limits:** 3 cases; anecdotal.
- **Explain it to a professor:** "When the agent says normal but the rule says warning, we do not pick a winner; the report states the conflict (`surfaceDisagreements`). In stress tests that happened 3 times in 18 calls; the rule was right once, the AI twice."
- **Likely follow-up:** "Q: Why not let the AI override the rules?" "A: With 1 of 3 cases the rule was right (a missed pump oscillation); a human decides."

#### `ad_review_answers` (folded into `ad_policy_gate`) — Diagnosis matches the injected scenario (review_answers.py, Genie build)
- **Claim on the card:** none / notes: "Two misses were the water tank: one the scenario refilling itself (fixed), one a genuine miss (surfaced to the operator)."
- **What is plotted:** one bar "matching the injected scenario" (ours), Wilson whisker.
- **How it was measured:** `review_answers.py` on 10 injected app scenarios, Genie build (`ppt.md`).
- **Result in numbers:** 0.8 (8/10, CI 0.4902-0.9433).
- **How to read it:** a whole-app check: right diagnosis for the scenario we injected.
- **Takeaway:** 8 of 10 end-to-end diagnoses match; one miss was a scenario bug, one a genuine miss.
- **Caveats / limits:** n = 10; Genie build, not htpd.
- **Explain it to a professor:** "Running 10 scripted scenarios through the real app, 8 diagnoses matched what we injected; of the two water-tank misses, one was our scenario refilling itself."
- **Likely follow-up:** "Q: What happens with a genuine miss?" "A: It is surfaced to the operator, who approves or rejects."

---

### 4.6 Refinement

Context: the placement study showed the agent reads young events poorly, so every Mode-3 incident is automatically re-analysed when its windows end 18 readings (1.5 h) and 36 readings (3 h) after the original window (`refine.go`). All sensors of the incident are re-read through the same pipeline (agents, synthesizer, policy gate, severity, title). The refined finding replaces the early one; `revisions[]` keeps history; the page shows EARLY / REFINED 1.5 h / REFINED 3 h badges. An early spike or dip is kept if the refinement only says "stable". Refinements never change approval or the event gate, queue behind new alerts, and are not done for Mode 1/2.

#### `ref_device_runs` — Refined re-analysis through the app on the QIDK: findings per stage (3 runs, 9 incidents)
- **Claim on the card:** "power_throttling: early 'exponential increase' -> refined 'throttling' (correct)" / **Why it matters:** "The early alert stays fast; the refined read uses the window where the agent is accurate (placement study)."
- **What is plotted:** timeline chart; lanes = runs (run 1, run 2 alt; run 3 ours); each dot = scenario @ stage (early, 1.5h, 3h), y = severity rank (0 normal, 1 sensor_fault, 2 warning, 3 critical), with agent pattern and whether the 12 h long-range check fired. A full table is attached.
- **How it was measured:** `app/tools/refine_check.py` on the real QIDK app (htpd v6, fine-tuned agents): restart the sensor clock once (1 s polls), build 45 readings of history, inject scenarios one after another without reset. Run 1 before the 12 h severity rule; run 2 after adding `longRangeRaise` (a 12 h finding raises a sensor its agent called normal to warning, `title.go`); run 3 with "keep worst severity" and demo scenarios that hold until cleared. Sources `proofs/2026-10-16_refined_reanalysis/device/`, `device_run2/`, `device_run3/` (`refine_check.jsonl`), `DEVICE_RESULTS.md`, HANDBOOK 2.39. Collector `Website/build/collect/refinement.py`.
- **Result in numbers (table, stage: severity / pattern / long-range fired / t since inject s):**
  - Run 1: stuck_sensor INC-0609: all stages sensor_fault / flatline / false (26.7, 44.8, 62.9 s; early analysis 2585 ms). tank_leak INC-0610: normal / stable at all stages; long-range fired at 1.5h and 3h (63.8, 81.9, 100 s; 2427 ms) — severity stayed normal (the gap). pm_spike INC-0611: critical / spike at all stages (16.5, 34.6, 52.7 s; 3418 ms).
  - Run 2: tank_leak INC-0612: early normal/stable; 1.5h warning/stable (long-range true); 3h warning/stable (67, 82.1, 100.2 s; 4899 ms). ventilation_failure INC-0613: early warning/exponential_increase (long-range true); 1.5h critical/spike; 3h critical/spike (30.8, 45.9, 61 s; 6584 ms). power_throttling INC-0614: early critical/exponential_increase; 1.5h critical/throttling; 3h critical/step_decrease (15.4, 33.5, 51.6 s; 4088 ms).
  - Run 3: power_throttling INC-0615: early critical/exponential_increase; 1.5h and 3h critical/throttling, long-range true throughout (18.5, 33.6, 48.7 s; 7478 ms). ventilation_failure INC-0616: early warning/exponential_increase; 1.5h critical/exponential_increase; 3h critical/throttling (27.7, 42.8, 61 s; 4870 ms). stuck_sensor INC-0617: sensor_fault/flatline throughout (27.9, 43, 61.1 s; 2590 ms).
  - 9/9 incidents reached the 3 h stage; revisions 1-2-3 per incident. Stages ~15-18 s apart at 1 s polls.
- **How to read it:** follow each scenario left to right across stages; the headline is power_throttling turning from "exponential_increase" (early) into "throttling" (refined) in runs 2 and 3, and tank_leak turning from normal to warning once the 12 h drift check raises it (run 2).
- **Takeaway:** the refinement pipeline works end to end on the device; it corrected a misread pattern and, after a fix, let a 12 h finding escalate a missed slow leak.
- **Caveats / limits:** 9 incidents, 5 scenario types: a functional demonstration, not an accuracy estimate. Run 2's 3 h "step_decrease" for power happened because demo scenarios ended after 30 readings (Hold=false), fixed in run 3. Run 3's ventilation 3 h label "throttling" describes a CO2 rise then plateau (held at peak), arguably not the scenario name. 12 h checks need 8 h of history; at the early stage only about 65 readings existed, so they were not active then in run 1. The demo clock is accelerated (1 reading per poll).
- **Explain it to a professor:** "We injected scenarios into the running app on the QIDK and captured the report at each stage. For power throttling, the early report said 'exponential increase', and both refinements corrected it to 'throttling'. Run 1 also exposed a gap, a slow tank leak seen only by the 12 h drift check stayed 'normal', which we fixed so that such a finding raises the sensor to warning."
- **Likely follow-up:** "Q: Can a refinement downgrade a critical alert?" "A: Run 3 adds 'keep worst severity': severity is never lowered by a refinement in run 3's rows; and an early spike/dip is kept when the refinement only says 'stable' (tested by `TestRefineKeepsEarlySpikeWhenEventOver`)."

#### `ref_go_tests` (folded into `ref_device_runs`) — Refinement unit tests (Go, -race, real engine + scripted mock agents)
- **Claim on the card:** none / notes: "5/5 refine tests pass; full suite: ok."
- **What is plotted:** bar of test duration in seconds per test (ours), status PASS.
- **How it was measured:** `go test -race` with the real engine and scripted mock agents; `proofs/2026-10-16_refined_reanalysis/go_test_output.txt`.
- **Result in numbers:** TestRefineDueAt18And36Readings 1.31 s PASS; TestRefineKeepsEarlySpikeWhenEventOver 1.27 s PASS; TestRefineKeepsApprovalAndGate 0.84 s PASS; TestRefineNeverPreemptsNewIncident 0.84 s PASS; TestRefinePersistenceAndBackCompat 0.86 s PASS.
- **How to read it:** the test names are the guarantees; durations are incidental.
- **Takeaway:** the refinement rules (timing, spike-keep, approval untouched, no pre-emption, persistence) are covered by passing tests.
- **Caveats / limits:** mock agents, not the NPU.
- **Explain it to a professor:** "Each design rule of refinement has a unit test with the race detector on: it fires at +18 and +36 readings, keeps an early spike when the event is over, never touches approval or the gate, never delays a new incident, and survives restarts with old data."
- **Likely follow-up:** "Q: Why plot durations?" "A: The chart needs a number; the evidence is PASS on all five."

#### `ref_ui_checks` (folded into `ref_device_runs`) — Refinement UI at phone width (360 px): no horizontal overflow on any screen
- **Claim on the card:** none / notes: "Headless Chrome over CDP at 360x780 @2x; no console errors. Badge sequence EARLY -> REFINED 1.5 h -> REFINED 3 h appeared on an open page without reload (SSE)."
- **What is plotted:** document scroll width in px per screen (ours); each point has overflowing element count.
- **How it was measured:** headless Chrome via CDP, 7 screens; `proofs/2026-10-16_refined_reanalysis/checks.json`, `notes.txt`; screenshots 01-13 PNG in the same folder.
- **Result in numbers:** early-detail, r15-detail, history-real, sheet-real, list, history-synth, sheet-kept: all scroll width 360, overflowing 0.
- **How to read it:** 360 = viewport width means no horizontal scroll.
- **Takeaway:** the new refinement UI fits a phone screen and updates live.
- **Caveats / limits:** one viewport size; automated layout check, not a user study.
- **Explain it to a professor:** "Every refinement screen was rendered at phone width and checked for horizontal overflow; none, and the badges advanced live over server-sent events."
- **Likely follow-up:** "Q: What is SSE?" "A: Server-sent events, a push channel from backend to page; the badge changed without a reload."

#### `ref_stage_timing` — Demo timing at 2 s polls: when each refined report lands after the early one
- **Claim on the card:** "Refined reports land 37 s and 74 s after the early one at 2 s demo polls" / **Why it matters:** not set; it tells the presenter how long to wait in a live demo.
- **What is plotted:** bar chart, x = stage (early, 1.5h, 3h), y = seconds after the early report (ours).
- **How it was measured:** laptop host backend with a mock LLM (no NPU), sensor clock at 2 s per reading; `proofs/2026-10-16_refined_reanalysis/inc0001_stage_poll_2s.log`, `notes.txt`. Collector `refinement.py`.
- **Result in numbers:** early 0 s; 1.5h 37 s; 3h 74 s. HANDBOOK: about 36 s and 72 s.
- **How to read it:** 18 readings x 2 s = 36 s and 36 readings x 2 s = 72 s, plus about 1 s of processing each.
- **Takeaway:** in the demo the refinements appear about half a minute and a minute and a quarter after the alert.
- **Caveats / limits:** mock LLM, laptop; on the device at 1 s polls the stages were ~15-18 s apart (`ref_device_runs`). In the field the real delays are 1.5 h and 3 h of sensor time.
- **Explain it to a professor:** "The refinement is triggered by readings, not wall clock; with the demo clock at one reading every 2 s, the 1.5 h and 3 h re-reads arrive after 37 and 74 seconds."
- **Likely follow-up:** "Q: What does a refinement cost on the NPU?" "A: Up to 3x the NPU work per incident, spread over 3 h of sensor time (HANDBOOK 2.39); per-stage NPU time is not in this dataset."

### 4.7 Training v2

Plain language: v1 of the domain agents knew only 4 h windows and events placed 1-3 h into the window. The window, placement and long-range studies showed that this misses young events (42% pattern accuracy at 40 min), other window lengths, old steps, slow drifts, and that routines cause about 31% false alarms on calm data (RETRAIN_V2_SPEC.md, "Why"). v2 is the final retrain of the domain agents: a bigger, harder dataset, a new HVAC agent, LoRA rank 32, trained on the laptop GPU (RTX 4050 6 GB, in WSL) in resumable 6-8 h sessions. These cards prove the training is real, show how far it has got, and record every failure along the way. None of them is an accuracy result. Accuracy comes from the NPU acceptance test after training (Spec #20).

Colour convention on all cards: blue = ours (v2), grey = alternative or comparison (v1, dev/test splits, train loss), reference = context such as event logs.

#### `tv2_plan`: Training setup, v1 (2026-10-07) vs v2 (in progress)
- **Claim on the card:** v2 has 35,946 examples, 6 roles, r=32 (v1: 6,480, 5 roles, r=16).
- **Why it matters:** It shows that v2 changes the data and capacity, not the model or the method. The NPU model stays the same size, so device speed stays comparable (Spec #18).
- **What is plotted:** A bar chart of train examples, v1 = 6,480 and v2 = 35,946 (blue), plus a side-by-side table.
- **How it was measured:** The numbers are read from the plan and pilot files: `proofs/2026-10-17_retrain_v2/plan.json`, `pilot.json`, `Code/smart-city-edge-agent/training/results/agents_20261006_2101/plan.json` and `train.log` (v1), `RETRAIN_V2_SPEC.md`, HANDBOOK 2.7 and 2.40. Collector: `Website/build/collect/training_v2.py`.
- **Result in numbers (tv2_plan table):**
  | | v1 | v2 |
  |---|---|---|
  | model | Llama-3.2-3B-Instruct | same |
  | method | QLoRA nf4 | QLoRA nf4 |
  | LoRA rank / trainable | r=16 / 24.3 M | r=32 / 48.6 M |
  | roles | 5 | 6 (+ HVAC) |
  | train examples | 6,480 | 35,946 |
  | epochs / optimizer steps | 2 / 810 | 2.0 / 4,494 |
  | grad accumulation | - | 16 |
  | lr / max length | - | 0.0002 / 1280 |
  | train tokens | - | 29,477,242 |
  | pilot tokens/s / peak VRAM | 401.5 / 4.24 GiB | 411 / 4.58 GiB |
  | estimated training hours | ~6.5 | 39.8 |
  | window lengths | 4 h only | 2-12 h (21 lengths) |
  | best dev loss | 0.027 | 0.066 (so far) |

  RESULTS.md adds: LoRA alpha 64 on all 7 projections, cosine schedule, and a tokenizer byte-identical to Meta's (sha256/16 `6b9e4e7fb171f92f`). The model was downloaded from the ungated `unsloth/` mirror.
- **How to read it:** Read the table row by row. Model and method are unchanged. Data is about 5.5x larger, LoRA capacity is doubled, and the run is about 6x longer.
- **Takeaway:** Same 3B model and method with about 5.5x more data, a sixth role and a doubled adapter.
- **Caveats / limits:** The 39.8 h estimate is pure GPU time from the pilot. Wall-clock time is much longer because of pauses and stops (see `tv2_sessions`). The best dev loss values (0.027 vs 0.066) are on different dev sets and cannot be compared.
- **Explain it to a professor:** We kept the base model and the QLoRA recipe fixed, so any change in behaviour comes from the data. v2 has 35,946 examples over 6 roles and 21 window lengths, against v1's 6,480 examples at 4 h only. We doubled the LoRA rank to absorb the larger task.
- **Likely follow-up:** "Q: Why not a bigger model?" / "A: Spec #18 keeps Llama 3.2 3B because NPU speed must stay the same. Latency on the board is the hard constraint, so we spent the extra capacity on adapter rank (48.6 M trainable) instead."

#### `tv2_loss_curve`: Dev loss and train loss per token (folds `tv2_v1_loss_curve`)
- **Claim on the card:** Dev loss fell from 0.1311 to 0.066. Train loss is close to dev loss, so there is no overfitting.
- **Why it matters:** Until the NPU acceptance test runs, loss is the only accuracy signal we have.
- **What is plotted:** A line chart. X = optimizer step. Y = loss on a log scale. Blue = dev loss every 300 steps (8 points). Grey = train loss per token every 5 steps (507 points). Folded: the v1 dev-loss curve, every ~50 steps (16 points, grey).
- **How it was measured:** The trainer evaluates on the dev split (1,947 rows) every 300 steps. Train loss is logged every 5 steps. The trainer logs loss summed over the 16 grad-accumulation micro-batches, so the collector divides by 16 to get loss per token. Sources: `proofs/2026-10-17_retrain_v2/train.log.txt`, `loss_points.json`, `best.json`, `plan.json`, `RESULTS.md`. The v1 curve comes from `training/results/agents_20261006_2101/train.log`.
- **Result in numbers:**
  - Dev loss by step (date): 300: 0.1311 (10-17 13:04), 600: 0.0985, 900: 0.0923, 1200: 0.0809, 1500: 0.0772, 1800: 0.0685, 2100: 0.0682, 2400: 0.066 (epoch 1.0683, 10-19 09:47). Best = 0.066 at step 2400.
  - Train loss per token: 1.2947 at step 5, 0.5023 at 50, 0.2836 at 100, then about 0.06-0.07 at the end (2500: 0.0609, 2510: 0.0667).
  - v1 (`tv2_v1_loss_curve`): 0.0927 at step 50, falling to 0.0271-0.0273 by steps 700-800. That run was 810 steps over 2 epochs, with 405 thermal pauses (67.9 min) and a peak GPU temperature of 87 C.
- **How to read it:** Look at the gap between the two lines, not at how low they go. When train loss sits on top of dev loss, the model is not memorising. Most of the drop happens in the first ~300 steps. After that the improvement is slow and steady. Between 1800 and 2100 the curve flattens (0.0685 to 0.0682), then improves again at 2400.
- **Takeaway:** Loss is still improving after one epoch and shows no sign of overfitting.
- **Caveats / limits:** Dev loss is not accuracy. The real gate is the QIDK NPU test on the test months (Spec #20). v1's 0.027 is on a different and easier dataset (4 h only, 5 roles), so the higher v2 number does not mean v2 is worse. Training is only about 60% done.
- **Explain it to a professor:** Dev loss fell from 0.131 to 0.066 over the first epoch, and train loss per token tracks it closely, so the model generalises to held-out dev rows rather than memorising. We do not treat this as accuracy. Acceptance is measured on the NPU against fixed thresholds after training.
- **Likely follow-up:** "Q: v1 reached 0.027. Isn't v2 worse?" / "A: No. The two runs use different dev sets. v2's dev set covers 21 window lengths, young events, faults, routines and a sixth role, so it is a harder task. The data note marks the two numbers as not comparable."

#### `tv2_sessions`: Every training session (folds `tv2_progress`, `tv2_speed`)
- **Claim on the card:** Training survives stops. Every session resumed from a checkpoint.
- **Why it matters:** The laptop cannot run for 40 h straight (heat, lid, battery, the user needs the machine). A resumable design is what makes the retrain possible at all.
- **What is plotted:** A timeline of 12 sessions, coloured by mode (full or background), with steps per session (blue). Folded: `tv2_progress` (a line of optimizer step against wall-clock time, where flat gaps are interruptions and drops are lost steps) and `tv2_speed` (a line of moving s/step reported by the trainer).
- **How it was measured:** Session start and end times, steps and summary lines are parsed from `proofs/2026-10-17_retrain_v2/train.log.txt` and `supervisor.log.txt`, and cross-checked with `power_events.txt`. Dates are inferred from HH:MM:SS by day roll-over from 2026-10-17. Hours, thermal pauses and peak temperature come from each session's own summary line. Collector: `training_v2.py`.
- **Result in numbers (key rows of the tv2_sessions table):**
  | start | steps | hours | mode | end / note |
  |---|---|---|---|---|
  | 10-17 02:00 | 0 | - | full, WSL 13 GB | restarted after 4 min (Windows had 0.7 GB free) |
  | 10-17 02:04 | 0 -> 300 | - | full, 10 GB | blue screen; steps 276-300 lost |
  | 10-17 10:04 | 275 -> 318 | 3.19 | full | thermal sleep froze it 2.6 h |
  | 10-17 14:15 | 318 -> 443 | 1.52 | full, 4 cores | supervisor died with the assistant's shell |
  | 10-17 23:31 | 443 -> 905 | 12.66 | full, 11 GB | lid closed, Modern Standby froze it 01:12-08:52; median 103.4 s/step |
  | 10-18 13:28 | 905 -> 1150 | 3.52 | background | clean stop |
  | 10-19 00:55 | 1647 -> 2419 | 9.06 | full | clean stop, best session (772 steps) |
  | 10-19 10:01 | 2419 -> 2514 | 1.11 | background | clean stop |
  - Totals: 12 sessions. The 10 sessions with a summary logged 37.22 h. Every session from the third onward ended with a clean stop. The last logged step is 2510, and the run stopped at 2,514 / 4,494 (RESULTS.md).
  - Median s/step per session: about 41-45, except the lid-standby night (103.4).
  - `tv2_speed`: 102 points shown. Min 33, median 43, max 363.7 s/step (the max is the standby gap folded into the moving average). RESULTS.md gives 45.5 s/step (79 steps/h) in background mode and 42 s/step (85 steps/h) in full mode overnight.
  - `tv2_progress`: 507 logged points. The step drops from 300 back to 280 after the BSOD (resume from checkpoint 275).
- **How to read it:** Each bar is a session. A gap between bars is time the laptop was off, stopped or frozen. In the progress line, steps go up steadily inside a session, stay flat across gaps, and drop once (the BSOD).
- **Takeaway:** 12 sessions, one crash, and at most 25 steps ever lost. Everything else resumed exactly.
- **Caveats / limits:** The first two sessions have no summary hours, because they ended in an interruption. Background and full mode run at the same speed because the GPU is the bottleneck. Wall-clock time far exceeds the 39.8 h estimate.
- **Explain it to a professor:** We train in user-started sessions that checkpoint every 14 steps, stop cleanly on a flag, on low battery or at a time limit, and auto-resume. Over 12 sessions the only lost work was 25 steps from one blue screen. Speed is about 42-45 s per optimizer step whenever the laptop is awake.
- **Likely follow-up:** "Q: Why 103 s/step in one session?" / "A: That night the lid was closed. Modern Standby froze WSL from 01:12 to 08:52 (`power_events.txt`), and the frozen time counts inside the session. The fix was to keep the lid open and set the lid action to 'Do nothing' in full mode. RESULTS.md records 0 standby events overnight after that."

#### `tv2_thermal_pauses`: GPU thermal guard, pauses per session
- **Claim on the card:** 1,103 pauses, 5.2 h paused in total. The GPU peaked at 87 C.
- **Why it matters:** It shows the heat cost of training on a laptop, and that the guard keeps the machine out of thermal sleep.
- **What is plotted:** A bar chart. X = session start. Y = minutes paused (blue). Second series = share of the session paused (grey, fraction).
- **How it was measured:** The training loop pauses when the GPU reaches the threshold: 81 C until 2026-10-17 14:15, then 76 C, because at 81 C the laptop had gone into thermal sleep. Counts and minutes come from the session summary lines in `train.log.txt`. The laptop locks the GPU power limit at about 50 W, so pausing is the only lever.
- **Result in numbers:** Minutes paused per session: 3.5, 18.2, 60.1, 38.2, 8.5, 12.9, 40.7, 16.2, 98.9 and 12.9, which sum to 310.1 min (about 5.2 h). Pauses per session: 21, 62, 219, 119, 26, 38, 128, 56, 386 and 48, which sum to 1,103. The share paused ranges from 0.018 (first session, old 81 C threshold) to 0.222. With the 76 C threshold it is typically 0.18-0.22. Peak was 87 C in every session.
- **How to read it:** Taller bars mean more time cooling. After the threshold was lowered, about a fifth of every session is spent paused.
- **Takeaway:** The guard costs about 20% of training time and keeps the laptop out of thermal sleep.
- **Caveats / limits:** Peak 87 C is reached even with the guard, because the guard reacts to temperature and does not prevent it. The 8% share in the 12.66 h session is diluted by the standby hours.
- **Explain it to a professor:** The laptop GPU cannot be power-capped further, so we pause training whenever it reaches 76 C. That cost 1,103 short pauses (5.2 h, about 20% of session time), but there has been no thermal sleep since the change.
- **Likely follow-up:** "Q: Why not just keep 81 C?" / "A: On 10-17 at 10:25 Windows put the laptop to sleep for thermal reasons ('Reason: Thermal Zone') and training froze for 2.6 h. A 20% slowdown is cheaper than losing hours."

#### `tv2_interruptions`: Interruptions, causes and fixes
- **Claim on the card:** Eight interruption causes were found, and each now has a guard.
- **Why it matters:** Credibility. Each failure was diagnosed from evidence and fixed. None was ignored.
- **What is plotted:** A bar chart of Windows power events by type (reference series): bugcheck (BSOD) 1, unclean reboot (event 41) 2, thermal sleep 1, Modern Standby lid 6. Below it, a table of the 8 causes.
- **How it was measured:** The Windows event log export (`power_events.txt`), the crash dump analysis (`crash_0xD1_analysis.txt`), `supervisor.log.txt` and RESULTS.md. Collector: `training_v2.py`.
- **Result in numbers (tv2_interruptions table):**
  1. 10-17 01:53-01:58: the session exited at once, 3 times. Cause: `Start-Process` split the `bash -lc` string. Fix: `start_v2.sh` wrapper.
  2. 10-17 02:03: Windows almost ran out of RAM (WSL at 13 GB with model files in page cache). Fix: WSL capped at 10/11 GB, and the supervisor drops the WSL cache when Windows has less than 2.5 GB free.
  3. 10-17 05:45: blue screen, steps 276-300 lost. Cause: bugcheck 0xD1 in `vfpext.sys` (the Hyper-V virtual switch used by WSL networking). Fix: WSL `networkingMode=none` while training, checkpoints every 14 steps, auto-resume at logon.
  4. 10-17 10:25-13:04: frozen 2.6 h by thermal sleep. Fix: GPU pause threshold 81 to 76 C, WSL limited to 4 cores.
  5. 10-17 13:05 and 15:43: the supervisor died, though training kept running (it was a child of the assistant's shell). Fix: launch through WMI, attach mode.
  6. 10-17: the new checkpoint interval was ignored (the Trainer restores `save_steps` from the checkpoint). Fix: `train_v2.py` rewrites `trainer_state.json` before resuming.
  7. 10-18 01:12-08:52 and 16:18-16:46: frozen by Modern Standby (lid closed). Fix: keep the lid open, lid action 'Do nothing' in full mode.
  8. 10-18 16:18: ran on battery (AC unplugged). Fix: the battery guard stops cleanly below 40%.
- **How to read it:** The bars show what Windows recorded. The table maps each event to its cause and fix.
- **Takeaway:** Every interruption was plumbing (OS, power, launcher) and none was the training code itself. Each now has a guard.
- **Caveats / limits:** One unclean reboot, on 2026-10-17 at 20:10, has no recorded cause and fell between sessions. The fix for the 0xD1 crash is a workaround that turns WSL networking off, not a driver fix.
- **Explain it to a professor:** Long GPU jobs on a consumer laptop fail for operating-system reasons: memory pressure, a Hyper-V network driver crash, thermal sleep, lid standby and battery. We traced each to evidence in the event log or crash dump and added a specific guard.
- **Likely follow-up:** "Q: How do you know the BSOD was the network driver?" / "A: The crash dump analysis (`crash_0xD1_analysis.txt`) names bugcheck 0xD1 DRIVER_IRQL_NOT_LESS_OR_EQUAL in `vfpext.sys`, the Hyper-V virtual-switch filter. With WSL networking off during training it has not recurred."

#### Current status (`status.json`, generated 2026-10-19 20:13)
- **Training v2:** state **running** at step 2,685 of 4,494, progress 0.5975 (about 60%). The last log line is at 2026-10-19 20:10:46. Best dev loss is 0.066 at step 2400. Recent speed is 44.0 s/step. Remaining training time is estimated at 22.1 h of GPU time only, excluding pauses, stops and non-running time. The trainer's own ETA text is "Tue 20 17:21". These values change with every build; the Route page shows them as a progress bar.
- **Deployed on the QIDK today:** still the **v1** fine-tuned model (GPTQ int4 repacked to GGUF Q4_0/Q8_0) on htpd v6, with Genie/genied kept as a fallback (revert path). On-device accuracy (n=54): pattern 0.907, status 0.944, cause 0.87, JSON 1.0, policy 1.0. Latency: Mode 3 median 3.8 s, 12-agent chaos 20.7 s, 13-agent A/B 14.7 s. Stress test: 132/135 passed, and all failures were thermal.
- **Next (from status.json):** finish v2 (4,494 steps); merge to GGUF Q4_0 (imatrix) and load into htpd; run NPU acceptance on the test months (Spec #20); latency pass back to 14.7 s or less (13 agents) and 3.8 s or less typical; cross-domain reasoner; 900-window rerun; Mode 1/2/3 labelled grid.
- **Explain it to a professor:** The board runs v1 today, with measured accuracy and latency. v2 is 60% trained and will replace v1 only if it passes the acceptance gates on the NPU.

---

### 4.8 Dataset v2

Plain language: these cards describe what the v2 model is being taught. The data comes from IIIT-H series generated with no new raw data (Spec #12). Some examples are real windows, and others have injected events, faults, routines and drifts. Every example has a deterministic, rule-based label and template-based wording that cites evidence ids. Splits are by time (train Jan-Aug, dev Sep-Oct, test Nov-Dec), and about 15% of sensors per role are never seen in training (Spec #21). Grey series on these cards are the dev and test splits, and blue is train. Collector for all cards: `Website/build/collect/dataset_v2.py`. Main source: `proofs/2026-10-17_retrain_v2/dataset_manifest.json`.

#### `ds_roles`: Rows per role and split (folds `ds_status`, `ds_v1_dataset`)
- **Claim on the card:** 35,946 train / 1,947 dev / 2,965 test rows.
- **Why it matters:** It shows balance across the six roles, including the new HVAC agent.
- **What is plotted:** Grouped bars by role. Blue = train, grey = dev and test. Folded: status-label bars, and v1 vs v2 train rows per role.
- **How it was measured:** Counted from the generated JSONL via `dataset_manifest.json`. Duplicates dropped: train 9, dev 2, test 1. File hashes (sha256/16): train `2bbbe5fe4f663975`, dev `7f4a0e3e4210773b`, test `6fdb17d5a5187913`.
- **Result in numbers:**
  - Train: air_quality 6,498; water 6,455; power 6,500; occupancy 4,995; weather 4,999; hvac 6,499.
  - Dev: 360 / 355 / 360 / 279 / 233 / 360.
  - Test: 540 / 505 / 540 / 420 / 420 / 540.
  - `ds_status` (train): normal 19,926; warning 7,266; critical 3,507; sensor_fault 5,247. Dev: 1,003 / 410 / 242 / 292. Test: 1,588 / 669 / 263 / 445.
  - `ds_v1_dataset`: v1 had 1,296 per role over 5 roles (6,480 in total). v1 split by time only, with the same sensors in every split. Its test was class-balanced, not natural prevalence, and water test used only 31 calm base windows.
- **How to read it:** The bars are near-equal per role. Occupancy and weather are lower by quota (5,000 vs 6,500), not by accident.
- **Takeaway:** Six balanced roles, about 5.5x v1, and about 55% of train rows are normal.
- **Caveats / limits:** The quotas were chosen by hand (`ds_mix`). The dev set is small per role (233-360 rows).
- **Explain it to a professor:** The dataset has 35,946 training rows spread almost evenly across six roles, with separate time-split dev and test sets. About half the rows are normal by design, so the model learns when not to alarm.
- **Likely follow-up:** "Q: Why is weather dev only 233?" / "A: Dev uses Sep-Oct windows, and per-role availability varies. Weather is also tested on seen stations only (decision D8), so fewer distinct dev windows were available."

#### `ds_families`: Case families, i.e. what each example teaches (folds `ds_confidence`, `ds_event_active`, `ds_mix`, `ds_patterns`)
- **Claim on the card:** Events are 29% of rows. The rest teaches faults, routines, drifts and old shifts.
- **Why it matters:** v1 failed on exactly the non-event families (old shifts, long drifts, routines). This card shows they are now in the data.
- **What is plotted:** Bars per family, train (blue) and dev/test (grey). Folded: confidence-target histogram, `event_active` true/false bars, sampling mix weights and per-role quotas, and train rows per role x pattern.
- **How it was measured:** The family tag of each generated row, taken from `dataset_manifest.json`. Families: event = one of the patterns; routine / real_routine = normal routines that look like alarms (hard negatives); old_shift / long_drift / recurring = what the 4 h v1 agent missed; fault = the 7 fault kinds; compound = two shapes in one window.
- **Result in numbers:**
  - Train: event 10,294; hvac 6,499; occupancy 4,995; fault 3,033; stable 2,023; routine 1,959; compound 1,516; real_routine 1,513; old_shift 1,265; long_drift 1,265; recurring 509; real_longrange 506; water_fill 310; zero_idle 259. Event share is 10,294 / 35,946 = 28.6%.
  - `ds_mix` weights: event 0.4, fault 0.12, routine 0.1, stable 0.08, compound 0.06, real_routine 0.06, water_fill / old_shift / long_drift 0.05 each, recurring 0.04, real_longrange / zero_idle 0.02 each. Train quota per role: 6,500 (air, water, power, hvac) and 5,000 (weather, occupancy). The generator ran in 121.5 s, seed 2026, config `2ec9e0bfad59ff98`.
  - `ds_event_active` (train): true 23,873, false 12,073 (dev 1,294 / 653; test 1,983 / 982).
  - `ds_confidence`: targets are calibrated, not fixed. The largest train bins are 0.7 (7,639), 0.75 (5,149), 0.85 (4,072), 0.95 (3,709), 0.9 (3,647), 0.8 (3,017) and 0.6 (2,518). Low bins: 0.3 (1,886) and 0.35 (935).
  - `ds_patterns` (train rows per role x pattern): air, power, water and weather each use the 12 shared patterns. Largest examples: air gradual_increase 1,071, power stable 1,097, water stable 1,139, weather stable 995. HVAC has 21 patterns of about 241 each, with setback_drift 721, stable 729, pull_down 481 and normal_cycling 473. Occupancy has 6 patterns of about 831-834 each (arrival, departure, intermittent, occupied, off_hours_presence, vacant).
- **How to read it:** "event" is the largest bar but well under half. The hvac and occupancy bars are whole roles that have their own pattern families.
- **Takeaway:** Most of the data teaches the model what is not an alarm, or what kind of trouble it is.
- **Caveats / limits:** The confidence targets come from the current (v1) model's measured accuracy (decision D4). They will be recalibrated in the backend from v2's own placement study, using a mapping table and no retraining.
- **Explain it to a professor:** Only about 29% of rows are classic events. The rest are hard negatives (routines labelled normal), sensor faults, compound shapes, and the long-horizon cases v1 missed. Confidence targets are set to the measured accuracy for each age, size and pattern, so a confidence of 0.7 means about 70% right.
- **Likely follow-up:** "Q: Why is confidence a training target rather than a model output?" / "A: An LLM's stated confidence is uncalibrated unless it is taught one. We teach the measured accuracy for similar cases (Spec #15), then remap in the backend after v2's placement study (D4)."

#### `ds_event_age`: Event age at the window end (folds `ds_event_size`)
- **Claim on the card:** Training events range from fresh (1 h or less) to old (over 3 h), not just 1-3 h.
- **Why it matters:** This is the direct fix for the placement-study finding: 42% pattern accuracy at 40 min, because v1 only saw events 1-3 h old.
- **What is plotted:** Bars by age bucket (readings since onset, 5-min points): 3-12 (1 h or less), 13-36 (1-3 h), over 36 (over 3 h), and none. Folded: event size in multiples of sensor noise.
- **How it was measured:** From `proofs/2026-10-17_retrain_v2/dataset_checks.json`. Onset is uniform from 3 readings before the window end back to the window start, with extra weight on 20-60 min (Spec #6). Size is 1.5-12x noise. Below about 3x, the label stays normal (Spec #11).
- **Result in numbers:**
  - Train age: 1 h or less 8,744; 1-3 h 7,097; over 3 h 10,809; none 9,296. Test: 675 / 679 / 866 / 745.
  - `ds_event_size` (train): under 3 (boundary) 3,135; 3-6 7,856; 6-9 6,346; 9 or more 5,167; none 13,442.
- **How to read it:** The 1 h-or-less bucket is now as large as the 1-3 h bucket. The "under 3 boundary" bar is the set of small events deliberately labelled normal.
- **Takeaway:** Young and small events are now well represented, including boundary cases.
- **Caveats / limits:** The buckets count readings, and window resolution differs by role (HVAC uses 10-min means, D10). Boundary labels are rule-based.
- **Explain it to a professor:** The app asks the agent about 40 minutes after onset, so we place a quarter of events in the first hour. Small events under about 3x noise are labelled normal, so the model learns where the alarm boundary is.
- **Likely follow-up:** "Q: Will this fix the 42%-at-40-min result?" / "A: That is acceptance gate (a): 65% or better at 40 min and 88% or better at 3 h, measured on the NPU after training. Until then it is a data change, not a measured result."

#### `ds_window_lengths`: Window length of each example
- **Claim on the card:** 21 window lengths from 2 h to 12 h (v1: 4 h only).
- **Why it matters:** The run-time window is now dynamic: alert at 4 h, refinements at 8 h or 12 h by severity (Spec #3/5). The model must handle every length.
- **What is plotted:** Bars per length in 5-min points (24 = 2 h ... 144 = 12 h). Train is blue, dev and test are grey.
- **How it was measured:** `dataset_manifest.json`.
- **Result in numbers:** Train is 4 h (48): 12,051; 8 h (96): 6,502; 12 h (144): 4,790. Each other length has 471-1,000 rows (for example 2 h: 1,000, 11 h: 471). Test: 4 h 1,098, 8 h 467, 12 h 327.
- **How to read it:** There are three tall bars at the lengths the app actually uses (4, 8 and 12 h), and a thin spread across the lengths in between.
- **Takeaway:** Heavily weighted to the run-time lengths, with coverage of everything in between.
- **Caveats / limits:** The in-between lengths have under 1,000 rows each, so accuracy there may be lower.
- **Explain it to a professor:** We concentrate data at the three window lengths the app uses, 4, 8 and 12 h, and sprinkle the other 18 lengths so the model is not brittle to window size.
- **Likely follow-up:** "Q: Why weight 4 h so heavily?" / "A: Every early alert uses 4 h for all incidents (Spec #3/5), so it is the most frequent call on the device."

#### `ds_fault_kind`: Sensor-fault kinds (status = sensor_fault)
- **Claim on the card:** Seven sensor-fault kinds, from stuck to quantised readings.
- **Why it matters:** The new `fault_kind` field (Spec #14, D6) tells the operator what to check on the sensor.
- **What is plotted:** Bars per fault kind. Train is blue, dev and test are grey.
- **How it was measured:** Rows with status sensor_fault in `dataset_manifest.json`, n = 5,247 train.
- **Result in numbers (train):** stuck 1,177; dropout 1,010; noise 969; bias 840; quantised 673; saturation 330; drift 248. Test: 108 / 78 / 91 / 63 / 57 / 27 / 21.
- **How to read it:** Common, easy faults (stuck, dropout) dominate. Drift is rarest.
- **Takeaway:** The model can now name the kind of fault, not just say "sensor_fault".
- **Caveats / limits:** Drift has only 248 train and 21 test rows, so its test estimate will be wide. Calibration-drift rules on real windows were tightened (D7).
- **Explain it to a professor:** Every sensor-fault example also carries one of seven fault kinds. This turns "sensor fault" into an actionable instruction such as "stuck" or "biased".
- **Likely follow-up:** "Q: Why so few drift examples?" / "A: Drift is hard to separate from a real slow trend. D7 tightened the real-window drift rules (longer duration, higher r²), so fewer windows qualify."

#### `ds_heldout`: Held-out sensors and test rows seen vs unseen
- **Claim on the card:** 25 sensors are held out entirely, and 1,221 test rows come from them.
- **Why it matters:** It tests generalisation to new sensors, not just new months. v1 used the same sensors in every split.
- **What is plotted:** Bars of held-out sensors per role (blue). Second series: test rows by seen/unseen (grey).
- **How it was measured:** About 15% of sensors per role are excluded from train and dev (Spec #21). Sensor IDs are omitted from the site.
- **Result in numbers:** air_quality 3, water 6, power 2, occupancy 1, weather 0, hvac 13 (total 25). Test rows: unseen 985, seen 1,744, unseen_sepoct 236 (held-out water sensors in Sep-Oct, D8). 985 + 236 = 1,221 unseen.
- **How to read it:** HVAC has the most held-out units (13 of 87). Weather has none.
- **Takeaway:** Acceptance will report seen and unseen sensors separately.
- **Caveats / limits:** Weather is tested on seen stations only (D8). Occupancy has just 1 held-out sensor.
- **Explain it to a professor:** Besides holding out Nov-Dec, we never train on about 15% of sensors, and test rows from them are reported separately. This measures whether the agent works on a sensor it has never seen.
- **Likely follow-up:** "Q: Why no held-out weather station?" / "A: There are too few stations to spare one. It is a stated limit (D8)."

#### `ds_hvac_real_labels`: HVAC real 4 h windows of 87 indoor units (folds `ds_hvac_injection`, `ds_hvac_profile`)
- **Claim on the card:** 98.45% of real HVAC windows are normal, so alarms must be taught by injection.
- **Why it matters:** It justifies how the new HVAC role is built. Real data alone has almost no alarms.
- **What is plotted:** Bars of rule labels on real windows (blue), and a status-share series (grey). Folded: injected examples that passed the labeller, per pattern (bars); share of units running by hour of day (line, 0-23 h).
- **How it was measured:** Per-unit series re-extracted from `SR-AC.csv` (87 units, 2025, D1). The `hvac.py` rules were applied to real windows. Sources: `proofs/2026-10-16_hvac_data/real_label_check.txt`, `realcheck.py`, `MANIFEST.md`, `test_output.txt`, `unit_profile_aggregates.json`, `prof_units.py`. These files hold aggregates only.
- **Result in numbers:**
  - 311,567 windows scanned, 29,393 ambiguous skipped. 73,036 real 4 h labels (non-faulty, non-ambiguous): stable 62,178; setback_drift 7,475; normal_cycling 1,433; pull_down 748; erratic 304; no_cooling_effect 194; stuck_off 151; too_hot 137; stuck_on 132; ... unit_alarm 2.
  - Status share: normal 0.9845, warning 0.0083, sensor_fault 0.0064, critical 0.0008.
  - Faulty units' windows (D11) become real fault examples: unit_alarm 1,090, biased_reading 929, flatline 182, bias_jump 100, erratic 49 (`real_label_check.txt`).
  - `ds_hvac_injection`: 27 patterns injected and accepted, from 73 (calibration_drift) to 200 (unit_alarm, dropout, saturation). 3,432 in total across 24/48/96/144-point windows. All 8 HVAC unit tests pass. Observation words: max 15, mean 10.6. Check failures: 0.
  - `ds_hvac_profile`: share of units on, from 0.037 at 07:00 to a peak of 0.114 at 15:00. Weekday 0.077, weekend 0.064. 9,117 compressor runs, median run 25 buckets.
- **How to read it:** The "stable" bar dwarfs everything else, so without injection the HVAC agent would learn to always say normal.
- **Takeaway:** Real HVAC data is about 98% calm. Alarms are injected, and each injection is verified by the labeller.
- **Caveats / limits:** Injected faults are synthetic. Only the 4 faulty units provide real fault windows. "Running in an empty room" uses synthetic occupancy pairing (D9).
- **Explain it to a professor:** Over 73,000 real 4 h windows from 87 AC units, the rules call 98.45% normal. We therefore inject 27 HVAC behaviours into real bases and keep only those the labeller confirms. Units with known bad sensors become real fault examples.
- **Likely follow-up:** "Q: Does the HVAC agent switch AC off?" / "A: No. D9 adds a `switch_off_ac` recommendation for an empty room, and it still needs human approval in the app. Nothing is switched off automatically."

#### `ds_routine`: Routine hard negatives by kind (folds `ds_label_alarm_rate`)
- **Claim on the card:** Over 20 kinds of normal routine, all labelled normal (hard negatives).
- **Why it matters:** About 31% of v1 false alarms on calm data came from routines (Spec "Why"). Acceptance gate (d) requires fewer.
- **What is plotted:** Bars per routine kind (23 kinds). Train is blue, dev and test are grey. Folded: rate of "status not normal" per role/family, with Wilson 95% CIs.
- **How it was measured:** `dataset_manifest.json`. The label-alarm rate comes from `dataset_checks.json`.
- **Result in numbers:**
  - Train: why_overflow 1,062; why_outdoor_pm 1,044; why_loadcycle 793; why_refill 785; why_drain 572; why_diurnal 448; ... six HVAC routines (night_setback, weekend_off, fan_mode, small_excursion, setpoint_change_ok, continuous_duty) at 240 each; why_hvac_cycle 2.
  - `ds_label_alarm_rate`: all routine and real_routine families have rate 0.0, for example power/routine 0/677 (CI 0-0.0056) and hvac 0/1,440. The exception is water/routine at 0.1809 (112/619, CI 0.1526-0.2132), because abnormal tank fills are deliberately labelled warning or critical (D2). Boundary events: power/long_drift/boundary 0.3673 (36/98); power/event/boundary 0.1353; air 0.0687; weather 0.0051.
- **How to read it:** Each bar is a normal behaviour that looks like trouble. The folded card checks that these are really labelled normal.
- **Takeaway:** The model is shown many routines that look alarming, all labelled normal, except water fills that are genuinely abnormal.
- **Caveats / limits:** "Routine" is defined by our rules. why_hvac_cycle (2 train rows) and why_solar (40) are tiny. The water/routine 18% is by design (D2), not label noise.
- **Explain it to a professor:** To cut false alarms we teach over 20 routines (refills, load cycling, daily CO2 and PM cycles, HVAC setbacks) with a normal label. A label audit confirms that 0% of routine examples are labelled alarming, apart from the deliberate abnormal-fill rule for water.
- **Likely follow-up:** "Q: Why is power/long_drift/boundary 37% alarming if boundary means small?" / "A: Boundary means the event is near the about-3x-noise threshold. For power, a slow drift sustained over a long window can still cross a status rule, so a third are labelled not-normal. That is the boundary the model must learn."

#### `ds_tokens`: Token statistics (Llama 3.2 tokenizer) (folds `ds_tokens_by_window`)
- **Claim on the card:** Prompts are about 733 tokens, and answers are about 76 tokens up to the derived 'action'.
- **Why it matters:** Generated tokens drive NPU latency. Spec #13 targets 55-60 tokens before the new fields.
- **What is plotted:** Bars of prompt mean, completion mean and generated-until-action mean per split. Folded: a line of prompt mean (blue) and generated mean (grey) against window length.
- **How it was measured:** Every row was tokenised with the Llama 3.2 tokenizer (`dataset_manifest.json`). Generation stops at the `"action"` key, which the backend derives.
- **Result in numbers:** Train prompt mean 732.5 (p95 940, max 1,104). Completion 87.6 (p95 107, max 122). Generated until action 75.8 (p95 95, max 109). Dev and test are within about 1%. By window length, prompt mean rises from 634.8 (2 h) to 841.1 (12 h), while generated tokens stay flat at 74.7-76.7.
- **How to read it:** A longer window costs prompt tokens (prefill), not answer tokens (decode).
- **Takeaway:** Answers are about 76 tokens whatever the window. Prompts grow about 200 tokens from 2 h to 12 h.
- **Caveats / limits:** The 75.8 generated tokens exceed the 55-60 target. The new fields (`event_active`, `onset`, `fault_kind`) add tokens. Soft flags: 24,658 rows generate over 70 tokens, and 3,708 prompts exceed 900 (`ds_qa_checks`). Latency is not a training gate (Spec #20c) but will be optimised afterwards.
- **Explain it to a professor:** Each agent call reads about 730 prompt tokens and writes about 76. Window length only adds prompt tokens, which the NPU processes in parallel, so 12 h refinements are cheaper than their length suggests.
- **Likely follow-up:** "Q: Will v2 be slower than v1?" / "A: Possibly at first. The user's policy is accuracy first, then a latency pass until 13 agents take 14.7 s or less and a typical incident 3.8 s or less (Spec, latency policy)."

#### `ds_qa_checks`: Automatic dataset checks
- **Claim on the card:** 11 hard checks across 40,858 rows, with 0 failures.
- **Why it matters:** Labels and wording are generated, so we must show they are internally consistent and that no test data leaks into train.
- **What is plotted:** Stacked bars per check: pass (blue) and fail (grey, all zero).
- **How it was measured:** A script over all splits (35,946 + 1,947 + 2,965 = 40,858). Output: `proofs/2026-10-17_retrain_v2/dataset_checks.json` and `.md`. A 60-sample private review page was also checked by hand (not published).
- **Result in numbers:** json, enums, obs_count, evidence_ids, numbers, leakage, duplicates, amplitude and shape each pass 40,858 / 40,858. rebuild passes 33,459 and v1_equal_48 passes 8,502, both with 0 fails. all_hard_pass = true. Soft flags: generated tokens over 70 on 24,658 rows; prompt tokens over 900 on 3,708; observation words mean 8.0, p95 11, max 14, 0 over 14. False alarm is defined as status != normal (D3).
- **How to read it:** The fail bars are empty everywhere. Bar height shows how many rows each check applies to.
- **Takeaway:** Every hard check passes on every applicable row.
- **Caveats / limits:** The checks prove consistency, not correctness against human judgement (the 60-sample hand review is the only human check). "rebuild" and "v1_equal_48" apply to subsets: v1_equal_48 compares v1 prompts at 48 points. The data does not state exactly why rebuild covers 33,459 rows.
- **Explain it to a professor:** Every one of 40,858 rows is valid JSON, uses legal labels, cites existing evidence ids, quotes numbers that match the evidence, and does not overlap with test windows. The generator also reproduces the rows deterministically.
- **Likely follow-up:** "Q: How do you prevent test leakage with overlapping windows?" / "A: The leakage check verifies that no test window appears in train, on all 40,858 rows, with 0 failures. Test is also separated by month (Nov-Dec) and by held-out sensors."

---

### 4.9 App, stress and UX

Plain language: these cards test the system the way an operator uses it, through the real app API on the QIDK. The tests use random sliders, injected faults, chaos (every sensor failing at once) and killed processes. They also show the operator UI before and after the redesign. Collector: `Website/build/collect/app_ux.py`. Most raw logs are in `proofs/2026-10-16_htpd_*`.

#### `ux_stress_runs`: App stress tests, every run (folds `ux_mode3_latency_runs`, `ux_v6_final_checks`)
- **Claim on the card:** 132/135 on the final htpd build, and every failure is heat.
- **Why it matters:** It is end-to-end evidence that the whole pipeline (event gate, agents, policy, store) works under random and adversarial use.
- **What is plotted:** A line of pass fraction per run (blue) with Wilson CIs. Folded: Mode 3 analysis-time median with min-max per run (boxplot), and final-run pass rate per section.
- **How it was measured:** The harness `Code/smart-city-edge-agent/app/tools/stress_app.py` drives the app API. Logs: `proofs/2026-10-16_htpd_app_chaos.log`, `_app_stress_full.log`, `_v3_app_chaos.log`, `_v4_app.log`, `_v5pc_app_stress.log`, `_v6_app_stress_tail.log`, `_v6_app_stress_report_final.json`, `refined_reanalysis/DEVICE_RESULTS.md`. Earlier runs come from HANDBOOK 2.31 and 2.38. Runs with 34 checks are chaos-only.
- **Result in numbers:**
  | run | passed | rate (CI) | failures | Mode 3 median s |
  |---|---|---|---|---|
  | 10-15 Genie final regression | 238/240 | 0.9917 (0.9701-0.9977) | thermal 2 | 3.5 |
  | 10-16 htpd first (chaos only) | 24/34 | 0.7059 | harness 4, thermal 6 | 35.9 |
  | 10-16 htpd full stress | 225/240 | 0.9375 | harness 9, thermal 6 | 6.6 |
  | htpd v3 (chaos only) | 26/34 | 0.7647 | harness 4, thermal 3, functional 1 | 31.8 |
  | htpd v4 | 128/135 | 0.9481 | harness 4, thermal 3 | 3.8 |
  | htpd v5 + prefix cache | 129/135 | 0.9556 | harness 4, thermal 2 | 4.9 |
  | **htpd v6 (final)** | **132/135** | **0.9778 (0.9367-0.9924)** | thermal 3 | 3.8 |
  | report-page build (v6) | 133/135 | 0.9852 | thermal 2 | - |
  | refinement build (v6, clock resets) | 129/135 | 0.9556 | thermal 6 | - |
  - `ux_v6_final_checks`: baseline 4/4, Mode 3 scenarios 51/51, Mode 2 scenarios 50/50, chaos simultaneous 19/20, chaos staggered 8/10. The failures were "thermal guard not tripped" (twice) and "board below 80 C (96 C)" (the board was at 96 C, so the below-80 C check failed).
  - `ux_mode3_latency_runs`: v6 median 3.8 s (min 2.3, max 20.8, n=13). Genie median 3.5 s, max 53.0.
- **How to read it:** Only the final v6 and later builds matter for the claim. The earlier rows show the path. "Harness" failures were a stale test that looked for genied instead of htpd, and were fixed in the harness, not the app.
- **Takeaway:** On the final build, every functional check passes. The only failures are temperature checks at chaos peaks.
- **Caveats / limits:** The claim "every failure is heat" holds for v6 and later builds only. The v3 run had 1 functional failure. Chaos peaks reach 95-96 C with htpd. The thermal "failures" are the guard behaving differently from the test's expectation, not wrong answers. These are single runs per build.
- **Explain it to a professor:** We drive the real app with random sliders, faults and chaos, using 135 checks per run. The final NPU-daemon build passed 132, and the 3 failures are all thermal checks at 95-96 C chaos peaks. Every Mode 2 and Mode 3 scenario check (101 of them) passed.
- **Likely follow-up:** "Q: Isn't a thermal failure a real problem?" / "A: It is a hardware limit, not a logic bug. The guard queues work instead of dropping it, and the fix for demo and field use is a heatsink or fan (HANDBOOK 2.37)."

#### `ux_chaos_incidents`: Chaos, every sensor failing at once
- **Claim on the card:** 10-12 agents + synthesizer in ~21 s (Genie: 40.8-48.9 s). **Why it matters:** a whole-campus failure still gets one explained report in about 20 s.
- **Why it matters:** This is the worst case for Mode 3, where one agent runs per alarming sensor. It shows why the batched daemon (htpd) was built.
- **What is plotted:** A scatter. X = number of agents. Y = seconds. Blue = htpd builds. Genie points are the comparison.
- **How it was measured:** Chaos incidents in the stress logs (`htpd_app_chaos.log`, `htpd_v4_app.log`, `htpd_v6_app_stress_tail.log`) plus HANDBOOK 2.31 for Genie.
- **Result in numbers:** Genie: 13 agents 48.9 s, 9 agents 40.8 s. htpd first run: 33.9-41.4 s for 10-12 agents. v4: 20.1-22.7 s. v5 + prefix cache: 20.6-21.2 s. v6 final: 20.8 s for 11 agents. One v3 point is 4.8 s for 1 agent (that chaos fired only one agent).
- **How to read it:** At the same agent count, later builds sit lower. v4 roughly halves the time.
- **Takeaway:** A 10-12 agent incident takes about 21 s on htpd, against 41-49 s on Genie.
- **Caveats / limits:** There are 1-3 incidents per build, so the result is not statistically powered. The agent count varies with how many sensors cross thresholds. (Fixed 2026-10-19: the claim used to say "was 41-57 s"; it now quotes the two plotted Genie points.)
- **Explain it to a professor:** When every sensor alarms at once, Mode 3 runs 10-13 agents. With batched decoding on the NPU, htpd does this in about 21 s, against about 41-49 s for sequential Genie calls.
- **Likely follow-up:** "Q: What changed between htpd v3 and v4?" / "A: This dataset shows only the effect (about 32-34 s down to about 20-23 s). The mechanism is in the latency topic and HANDBOOK 2.37."

#### `ux_mode2_vs_mode3_latency`: Mode 2 vs Mode 3 on the same scenarios, htpd v6 (folds `ad_modes_latency`)
- **Claim on the card:** Mode 3 is not slower than one big call: median 3.4 s vs 4.2 s. **Why it matters:** per-sensor agents give checkable evidence at no extra wait.
- **Why it matters:** It answers "is multi-agent too expensive?" On the final build, per-sensor agents cost no more than one all-sensor call.
- **What is plotted:** Paired bars per scenario. Blue = Mode 3, grey = Mode 2. Folded: Genie-era (2026-10-07) Mode 1/2/3 latency bars.
- **How it was measured:** The same 10 scenarios through the app, one run each, from `proofs/2026-10-16_htpd_v6_app_stress_report_final.json`. The folded data comes from HANDBOOK 5 and 2.7.
- **Result in numbers:**
  - Mode 3 vs Mode 2 (s): ventilation_failure 7.426 vs 6.205; pm_spike 4.852 vs 4.602; power_throttling 3.769 vs 3.844; load_surge 2.288 vs 3.758; tank_leak 3.08 vs 4.119; pump_cycling 2.571 vs 4.62; stuck_sensor 2.425 vs 5.899; heat_buildup 3.64 vs 2.989; off_hours_presence 2.426 vs 4.288; crowded_room 7.525 (3 NPU calls, 2 agents) vs 3.561.
  - Mode 3 agents policy-valid: 11/11.
  - Folded Genie era: Mode 1 under 1 ms; Mode 2 9.0 s; Mode 3 fine-tuned 5.6 / 8.9 / 23.5 s for 1 / 2 / 4 calls (base model 5.0 / 18.7 / 27.6); exact-prompt cache rerun 0.003 s.
- **How to read it:** Mode 3 is faster in 7 of 10 scenarios. It is slower when it needs a synthesizer (crowded room) or for some single-agent cases (ventilation, pm_spike, heat).
- **Takeaway:** For single-sensor incidents, the specialised agent is as fast as or faster than one generalist call.
- **Caveats / limits:** One run each, with latency only and no accuracy comparison (the Mode 1/2/3 labelled grid has not been run). The claim now uses the true medians of the 10 values, 3.36 s (Mode 3) and 4.20 s (Mode 2). Until 2026-10-19 it quoted the 6th sorted value (3.6 / 4.3 s).
- **Explain it to a professor:** On ten identical scenarios, Mode 3 had a median of 3.4 s against 4.2 s for Mode 2. A specialised agent prompt is shorter than an all-sensor prompt, and only incidents needing several agents plus a synthesizer cost more.
- **Likely follow-up:** "Q: Is Mode 3 more accurate than Mode 2?" / "A: That is not measured yet. The data explicitly says latency only, and the labelled Mode 1/2/3 grid is listed under next steps in status.json."

#### `ux_scenario_outcomes`: Measured situations through the final app
- **Claim on the card:** 10 measured situations, each producing a completed, policy-checked incident.
- **Why it matters:** It shows what an operator actually receives (diagnosis plus action), not just aggregates.
- **What is plotted:** A table: situation, Mode 3 time, pattern, diagnosis, operator action, agents and NPU calls.
- **How it was measured:** One Mode 3 run per situation on the QIDK, from the same v6 report JSON.
- **Result in numbers:**
  - Ventilation failure: exponential_increase, ventilation_issue, inspect_ventilation, 7.426 s.
  - Outdoor pollution spike: spike, air_pollution_event, inspect_ventilation, 4.852 s.
  - Power throttling: power_load_anomaly, inspect_electrical, 3.769 s.
  - Load surge: spike, power_load_anomaly, 2.288 s.
  - Tank leak: **stable, normal_operation, none**, 3.08 s.
  - Pump cycling: step_decrease, water_leak_or_overuse, monitor, 2.571 s.
  - Stuck sensor: flatline, sensor_fault, check_sensor, 2.425 s.
  - Heat buildup: weather_driven, monitor, 3.64 s.
  - Off-hours presence: occupancy_driven_load, request_facility_review, 2.426 s.
  - Crowded room: step_increase, power_load_anomaly, inspect_electrical, 2 agents, 3 calls, 7.525 s.
- **How to read it:** Read each row as "situation -> what the agent concluded -> what the operator is told to do".
- **Takeaway:** Every situation produced a complete, valid incident in 2.3-7.5 s, but not every diagnosis is right.
- **Caveats / limits:** This is coverage and latency only, not powered accuracy. Two rows are worth noting honestly. The tank-leak run was diagnosed "stable / normal_operation / none", which looks like a miss or a scenario whose slider values did not trigger a leak pattern; the data does not say which. In the crowded-room run, the first agent's diagnosis is power, not occupancy.
- **Explain it to a professor:** These are ten concrete campus situations run through the device, each producing a policy-checked recommendation within 7.5 s. They demonstrate the output format and latency. Accuracy is measured separately on labelled windows.
- **Likely follow-up:** "Q: Why did tank leak return normal?" / "A: In this single run the water agent judged the window stable. It is one sample, and the labelled accuracy evaluation is the right measure. v2 adds water-fill and drain hard cases and abnormal-fill labels (D2)."

#### `ux_fault_injection`: Fault injection on the device (folds `ux_hardening`)
- **Claim on the card:** Killed processes recover: the backend in 8 s, the NPU daemon in 15 s or less.
- **Why it matters:** An edge device in the field will lose power and processes. It must recover without losing incidents.
- **What is plotted:** Bars of recovery time (blue): kill edge-agent -> restarted 8 s; kill genied -> daemon back 15 s; cold boot -> answering 5 s; NPU call completed on CLI after daemon kill 4.9 s. Plus a before/after table, and a folded table of 15 hardening fixes.
- **How it was measured:** `kill -9`, cold reboots, torn log lines and garbage inputs were injected on the QIDK. Sources: HANDBOOK 2.31 and 2.35, `ppt.md`, `proofs/2026-10-16_htpd_app_stress_full.log`.
- **Result in numbers:** 7 injected faults (before -> now). Some examples:
  - Killing the backend mid-analysis used to make the incident vanish. Now it is persisted at creation and reloads as 'failed', approve is refused (409) and rerun is allowed.
  - A stale abort byte used to make the next query return 0 tokens. Now the abort is tied to the query id, and a zero-token query is retried once.
  - Garbage input is rejected (400) or clamped, never a crash (9/9).
  - `ux_hardening`: 15 fixes. Daemon busy-wait (359% idle CPU, 94 C) -> 0% idle. Dashboard about 220% CPU and 75 C -> 5-11% and 43 C. No cap on the number of agents. API token for off-device writes. Never two models resident. Bounded queue: 16 requests (429 beyond), 1 MiB bodies.
- **How to read it:** Short bars are good. The table shows that each fault had a visible bad effect before the fix.
- **Takeaway:** Every injected failure now recovers automatically and keeps the incident history.
- **Caveats / limits:** These are mostly single trials. The fault tests ran in the Genie/genied era (HANDBOOK 2.35). The daemon-kill row names genied, not htpd.
- **Explain it to a professor:** We killed each process mid-work, cut power and corrupted the log. Each now recovers within 15 seconds, and incidents are persisted from creation. Testing through the app found 15 production problems that offline evaluations would never show.
- **Likely follow-up:** "Q: Has the same been done for htpd?" / "A: The htpd builds went through the full stress harness (`ux_stress_runs`, 132/135). The per-fault recovery timings in this card are from the genied build."

#### `ux_screenshots`: Screenshot index, UI before and after, and refinement screens (folds `ux_report_page_checks`, `ux_severity_from_reasoner`)
- **Claim on the card:** The operator UI before and after the report-page and refinement work.
- **Why it matters:** It is the human side of the system. The operator reads, approves or rejects here.
- **What is plotted:** An image gallery (39 files). Before: 13 shots from the DeerFlow-era UI, 2026-10-14 (`_shots/`). After: 13 report-page shots (`proofs/2026-10-16_ux_report_page/`, including a photo of the QIDK screen, `device/d0_current.png`). Refinement: 13 shots (`proofs/2026-10-16_refined_reanalysis/`) showing early, +1.5 h and +3 h states. Folded: page scroll width at a 360 px viewport, and list severity counts.
- **How it was measured:** Screenshots, plus `checks.json` for layout and accessibility (HANDBOOK 2.38).
- **Result in numbers:** `ux_report_page_checks`: document scroll width is 360 on all 5 views (list, list-synthetic, done-detail, sensor-sheet, running-detail), with 0 overflowing elements. Focus moves to the sheet's close button and back, `history.back()` and a backdrop tap close the sheet, and there are no console errors. Severity is shown by bar, glyph and label, not colour alone. `ux_severity_from_reasoner`: after the back-fill, the real stored incidents show Fine 6, Warning 2. Example: INC-0031 went from critical to normal.
- **How to read it:** Compare the before and after galleries. The refinement shots show one incident evolving at +1.5 h and +3 h.
- **Takeaway:** The redesigned report page fits a phone, is accessible, and takes its severity from the AI analysis rather than the first rule hit.
- **Caveats / limits:** The 'after' and refinement shots come from a laptop host backend with mock agents (no NPU). Some show synthetic states, and some show demo slider values. Mock agents answer normal, which is why most rows show Fine.
- **Explain it to a professor:** Severity used to be fixed by the first rule that fired, so an incident the agents called normal still showed critical. Now severity follows the reasoner's analysis. The report page passes phone-width and accessibility checks.
- **Likely follow-up:** "Q: Are these screens from the real board?" / "A: Only `d0_current.png` is a photo of the QIDK. The others are from the laptop host with mock agents, as `notes.txt` states."

---

### 4.10 Operations

Plain language: these cards record every crash, reboot, sleep and thermal problem on both machines (training laptop and QIDK), with cause and fix. The point is that the system's failures were diagnosed and guarded, not hidden. Collector: `Website/build/collect/ops.py`.

#### `ops_incidents`: Every operational incident (folds `ops_disk`, `ops_v1_thermal_fix`)
- **Claim on the card:** Every crash had a plumbing cause, and each now has a guard.
- **Why it matters:** Credibility. The system survives the failures it will meet in the field.
- **What is plotted:** A timeline of 22 incidents by date. QIDK rows are blue, laptop rows are grey. A table gives cause, fix and HANDBOOK section. Folded: disk-space before/after bars, and v1 heat-fix bars.
- **How it was measured:** Compiled from HANDBOOK 2.1b, 2.7, 2.9, 2.24, 2.27, 2.30, 2.34, 2.35, 2.37, 2.40, 4.1 and 5, `proofs/2026-10-17_retrain_v2/` (RESULTS.md, power_events.txt, crash_0xD1_analysis.txt, admin_cleanup.log.txt) and the v1 `train.log`.
- **Result in numbers:** 22 incidents. Laptop: 10-07 1, 10-13 2, 10-17 5, 10-18 2 (total 10). QIDK: 10-07 1, 10-08 2, 10-14 3, 10-15 3, 10-16 3 (total 12). Key QIDK rows:
  - Parallel Genie sessions (about 3.7 GB each) exhausted RAM. Fix: NPU calls strictly sequential.
  - genied busy-wait at 359% CPU and 94 C. Fix: poll off.
  - Base 3B loaded beside the fine-tuned 3B caused a reboot. Fix: never two models resident.
  - USB brownout at chaos peak. Fix: DC adapter.
  - Dashboard at 75 C idle. Fix: solid bars, 5-11% CPU, 43 C.
  - 13-agent chaos at 94 C. Fix: thermal pacing at 88 C or above, giving a peak of about 90 C.
  - GPU tests rebooted Android (unmovable buffers in the 7.26 GB Normal zone).
  - htpd chaos peaks 95-96 C.
  - The 900-window rerun stopped after 39 windows (socket stall at 91 C). **Still to do.**

  Key laptop rows: 21 forced hibernations during v1 (TZ01 at 100 C); C: filled to 0 bytes by the NPU export; wrong-checkpoint export (err 1002); then the v2 events (see `tv2_interruptions`), including the 7.7 h lid standby.
  - `ops_disk` (GB, before -> after): WSL VHDX 171.1 -> 41.0 (10-13); WSL disk 138 -> 51 (10-17); QIDK free 13 -> 33 (10-07); laptop C: free 18 -> 105 (10-17).
  - `ops_v1_thermal_fix`: forced hibernations went from 21 to 0 over the whole v1 run, at a cost of 405 pauses (67.9 min). In the guard test, 5 pauses of 10 s over 6 min made training about 13% slower, with a peak of 86 C.
- **How to read it:** Clusters on 10-14 to 10-16 are QIDK latency and stress work. 10-17 and 10-18 are the v2 training.
- **Takeaway:** 22 incidents, each with a diagnosed cause and a fix. One (the 900-window rerun) is still open.
- **Caveats / limits:** This is a compiled log, not an automated monitor, so incidents not written into the HANDBOOK are absent. Some fixes are operational (keep the lid open, use the DC adapter) rather than code.
- **Explain it to a professor:** We logged every crash on both machines. On the board the causes were memory (two models resident), heat (busy-wait, chaos peaks) and power (USB brownout). On the laptop they were OS-level: hibernation, disk full, a Hyper-V driver crash and lid standby. Each has a specific guard, and one follow-up rerun is still outstanding.
- **Likely follow-up:** "Q: Will the board overheat in the field?" / "A: At chaos peaks htpd reaches 95-96 C. The guard queues work instead of dropping it, and a heatsink or fan is recommended for demo and field use (HANDBOOK 2.37). Ordinary incidents do not trigger it."

#### `ops_power_events`: Windows power events during retrain v2 (folds `ops_ram_guard`)
- **Claim on the card:** 1 blue screen, 1 thermal sleep and 6 lid standbys during training.
- **Why it matters:** It is raw OS evidence behind the training interruptions, not our own narrative.
- **What is plotted:** A timeline of 39 events (reference series). Folded: bars of WSL page-cache drops per day by the supervisor.
- **How it was measured:** A Windows event-log export, `proofs/2026-10-17_retrain_v2/power_events.txt`. Event IDs: 41/6008 unclean shutdown, 1001 bugcheck, 42 sleep, 107 resume, 506/507 Modern Standby enter/exit. Cache drops come from `supervisor.log.txt`.
- **Result in numbers:**
  - 10-17 09:38: unclean reboot plus bugcheck. Event 1001 is written when Windows comes back up; the crash itself was at about 05:31-05:45 per the session log.
  - 10-17 10:25:44: thermal sleep (event 42).
  - 10-17 20:10: unclean reboot with no recorded cause.
  - Lid standbys: 10-17 16:39, 23:08, 23:24; 10-18 01:12 (twice) and 16:18. The longest standby ran from 10-18 01:12:28 to 08:52:46 through repeated 506/507 pairs.
  - `ops_ram_guard`: cache drops 10-17: 5, 10-18: 41, 10-19: 5 (51 in total).
- **How to read it:** Standby enter/exit pairs bracket the frozen periods. The 10-18 night is one long chain.
- **Takeaway:** The OS log independently confirms each interruption the training log shows.
- **Caveats / limits:** The event-log time of the bugcheck is the reboot time, not the crash time. "standby: other" entries are follow-ons with no stated reason. One unclean reboot has no cause.
- **Explain it to a professor:** This is Windows' own power log for the training period. It shows exactly one blue screen, one thermal sleep and six lid-close standbys, matching every gap in the training log. The supervisor also had to free memory 51 times to keep Windows usable.
- **Likely follow-up:** "Q: Why 41 cache drops on 10-18?" / "A: That day had the most background-mode sessions while the user worked. Windows free memory fell below 2.5 GB more often, so the supervisor dropped the WSL page cache."

---

### 4.11 Timeline

#### `tl_milestones`: Project milestones (folds `tl_commits`, `tl_proofs`)
- **Claim on the card:** Spec (17 Sep) -> NPU fine-tune (7 Oct) -> batched NPU daemon (16 Oct) -> v2 training (17 Oct+).
- **Why it matters:** It puts every evidence card in order and shows how much was done after the mid-evaluation.
- **What is plotted:** A timeline of 15 milestones (blue). Folded: commits as files changed per commit (bars over time, 18 commits), and proof folders by date, with file counts and size.
- **How it was measured:** Compiled from PRD.md, plan.md, HANDBOOK.md, ppt.md, Website/SPEC.md, a read-only `git log --shortstat`, and the `proofs/` directory listing. Collector: `Website/build/collect/timeline.py`.
- **Result in numbers (key milestones):**
  - 09-17: PRD v2.0.
  - 09-30: initial commit.
  - 10-01: plan (prove on laptop, then port; Go backend over adb).
  - 10-07: v1 fine-tune trained overnight (94% host pattern accuracy), first NPU export, and the quantisation gap closed to 82.6-85.2% (GPTQ plus a double-BOS fix).
  - 10-08: native app via local adbd, event gate, NPU retries.
  - 10-13: action derived (+3.7 pts).
  - 10-14: latency day (ctx 2048, genied, batch window; LADE, grammar and continuous batching rejected).
  - 10-15: stress testing 238/240, then the mid-evaluation.
  - 10-16: GPU/NPU/hybrid grid; htpd (12-agent chaos about 47 s -> 20.7 s); window study (4 h best); placement study (42% at 40 min); refinements; 12 h checks; AI titles.
  - 10-17: v2 data built (35,946 rows), training started.
  - 10-19: v2 at 60% (step 2,685), best dev loss 0.066.
  - `tl_commits`: 18 commits. The largest are the initial commit (108 files, 131,209 insertions), 10-08 native app (121 files, 112,886) and 10-16 htpd (98 files, 18,690). Last commit: d403c8d on 2026-10-16.
  - `tl_proofs`: 22 proof entries dated 10-16 and 10-17, for example gpu_bringup (55 files, 88.1 MB), refined_reanalysis (59 files, 3.1 MB) and retrain_v2 (14 files, 0.4 MB).
- **How to read it:** The density after 10-15 is the post-mid-evaluation evidence push. Work after 10-16 is in the working tree and `proofs/`, not yet in commits.
- **Takeaway:** In about a month: spec, fine-tune, native NPU app, batched daemon, studies, and the v2 retrain.
- **Caveats / limits:** Milestone dates are compiled by hand from documents. The commit history understates recent work (dirty working tree, per status.json). Raw per-sample proof files stay local, and the site shows aggregates.
- **Explain it to a professor:** We went from spec on 17 September to a fine-tuned model on the NPU on 7 October, an app with an event gate the next day, and a batched NPU daemon on 16 October. Since 17 October we have been retraining with the lessons from the window and placement studies. Each milestone points to a HANDBOOK section and a proof folder.
- **Likely follow-up:** "Q: Why is the newest work not committed?" / "A: The last commit is d403c8d (10-16). The refinements, long-range checks and v2 work are in the working tree and `proofs/`, as the commits data notes. Committing is pending."

#### Current status (short form, from `status.json`)
- **Training position:** v2 running at step 2,685/4,494 (59.75%) at build time. Best dev loss is 0.066 at step 2400. About 22.1 h of GPU time remains at 44.0 s/step, excluding pauses and stops.
- **On the board now:** v1 model on htpd v6. Pattern 0.907 / status 0.944 / cause 0.87 (n=54). Mode 3 median 3.8 s. Stress test 132/135, all failures thermal.
- **Next:** finish v2, then GGUF Q4_0 (imatrix) to htpd, then NPU acceptance on the test months, then a latency pass back to 14.7 s or less / 3.8 s or less, then the cross-domain reasoner, the 900-window rerun and the Mode 1/2/3 labelled grid.

---

## 5. Every decision, and how to defend it

The Decisions page (`#/decisions`) shows 30 ranked decision groups holding 125 dated sub-decisions (D001-D125), so 155 decisions in all. The header line reads "26 kept · 0 replaced · 4 pending · 206 alternatives rejected". The first screen shows the 12 most important groups (rank 1-12). "Show all 30" opens the rest. You can filter by Topic (Use case, Latency, Hardware, Accuracy, Agent design, Refinement, Training, App / UX, Ops), by Status, or by free-text search.

Each card shows its id, topic, date and a status chip, then the title, "Chose ...", and an evidence chart. When a group has several datasets, tabs labelled "Evidence 1/2/..." switch between them. Each rejected option is a button: click it and the chart switches to that option's evidence and highlights the matching bar. Below that, a fold labelled "N related decisions" lists the children with their own status chips and evidence chips (each chip opens that dataset in a modal). A "Log" chip links to the cited HANDBOOK section, and "Link" copies a permalink. An old child id such as `#/decisions/D043` jumps to its group card and opens the child. The status chips mean: **kept** (in the shipped system), **replaced** (was true, later superseded; the newer decision is in the same group), and **pending** (planned or in progress, not yet measured on the device). At group level there are 26 kept and 4 pending. Among the 125 children, 112 are kept, 6 replaced and 7 pending.

Notation below: `[dataset_id]` is the catalog id shown on the evidence card. Numbers are copied from `data/decisions.json`, `data/catalog.json` and the dataset digest.

---

### 5.1 Everything runs on the board's NPU, not in the cloud (G01)

**In one line:** The sensors, the AI, the safety checks and the storage all live on one QIDK board, with no cloud and no laptop.

**What we chose:** The fine-tuned 3B on the Hexagon NPU, started through the board's own adbd, with the Go backend running as the shell user.

**What we rejected and why:**
- Cloud LLM: every incident would ship campus data off-site and stop when the link drops. `[uc_edge_offline]`: bytes leaving campus per incident = 0.
- Laptop driving the board over adb: unplug the laptop and the system dies. `[uc_edge_offline]`

**Evidence:**
- `[uc_edge_offline]`: one agent call on the board takes 2.543 s on the NPU (genied), 1.13 s per agent on the NPU (htpd, 13 in one batch) and 10.01 s on the GPU (Adreno, 1 agent). 0 bytes leave campus.
- `[uc_coverage]`: 174 sensors, 33.2 M readings, 8 domains, 12 months.

**Status:** kept.

**Children:**
- D005 (2026-10-02, **replaced**): Runtime: Qualcomm AI Hub compile to a w4a16 Genie bundle (A8). Rejected: llama.cpp on the CPU (bandwidth-bound and slow), the llama.cpp GGML_QNN fork (abandoned after days), hand-built QNN context binaries (1-3 weeks), and SNPE (superseded by QAIRT). Replaced on 2026-10-16 by htpd (see 5.7).
- D006 (2026-10-08, kept): The APK talks to the board's own adbd on 127.0.0.1:5555 and starts the backend as the shell user (A12). Rejected: running Genie inside the app sandbox (the vendor DSP service refuses apps with err 14001, even in permissive mode), a laptop web app (not edge), and JNI against the Genie C API (the sandbox still cannot open the NPU).
- D007 (2026-10-01, kept): A static Go binary cross-compiled for arm64, with the web dashboard in a WebView. Rejected: a Kotlin APK backend (app SELinux domain, 2 GB of SDK downloads, high risk in 3-4 days) and the laptop FastAPI demo (not on-device).
- D019 (2026-10-07, kept): One bundle for agents, synthesizer and Mode 2. Rejected: alternating two 2.9 GB bundles, because Genie failed with "could not create context from binary". `[hw_board_thermal]`

**How to defend it:** The expected objection is "using adb on the board is a hack and a security hole". Android apps cannot open the NPU at all: the DSP service returns err 14001 even in permissive mode. A shell-user process can, and this is the same technique Shizuku and LADB use. We keep the board off untrusted networks, and off-device writes need an API token (D061). The rule we would not give up is that no campus data leaves the site, and that is measured as 0 bytes per incident.

---

### 5.2 Fine-tune one Llama 3.2 3B for every domain role (G02)

**In one line:** One small model, taught with worked examples, plays every specialist role, and it is far better than prompting the base model.

**What we chose:** One QLoRA multi-role adapter on Llama 3.2 3B, trained on the laptop GPU.

**What we rejected and why:**
- Prompt the base model: 4 in 5 patterns were wrong (20%), and 65% of answers cited invalid evidence. `[acc_v1_host_eval]`: base pattern 0.2 (30/150), evidence valid 0.3467 (52/150).
- A second resident model or separate adapters: two 3B models rebooted the board. `[hw_board_thermal]`

**Evidence:**
- `[acc_v1_host_eval]` (150 held-out Nov-Dec windows, laptop, 4-bit): the fine-tuned model scores pattern 0.94 (141/150, CI 0.8899-0.9681), status 0.9267, cause 0.9333, action 0.9067, evidence valid 1.0 (150/150) and valid JSON 1.0. Base pattern is 0.2 and rules (Mode 1) pattern is 0.68.
- `[acc_v1_output_tokens]`: 84 vs 199 tokens per answer.

**Status:** kept.

**Children:**
- D002 (2026-10-01, kept): A single Llama 3.2 3B with the role in the system prompt. The Qwen reasoner was deferred because two models cannot be resident: the board rebooted.
- D003 (2026-10-01, kept): QLoRA 4-bit on the RTX 4050 in WSL, with Kaggle only for RAM-heavy steps. Rejected: training on the QIDK NPU (HTP is inference-only) and paid cloud GPUs (zero budget, and private data stays on the laptop).
- D004 (2026-10-01, kept): One adapter with the role in the system prompt. Rejected: six separate adapters (six exports and bundles, while the NPU holds one model).
- D009 (2026-10-06, kept): QLoRA fine-tune on 6,480 worked examples. Rejected: prompt + RAG with the base model (pattern 20%, evidence valid 35%, ~199 tokens).
- D013 (2026-10-06, kept): Plan the run from a 24-example pilot at 75% of pilot speed. Plan A (5 roles) finished: 810 steps, best dev loss 0.027. Rejected: a fixed schedule (thermal pauses would blow the deadline).

**How to defend it:** The expected objection is "the 94% is on the laptop, not the board". That is correct, and it is why 5.11 and 5.12 exist. The device figure is lower, 85.2% on Genie and 90.7% on htpd (54 windows). The fine-tune still beats base on every metric, and it also produces shorter answers (84 vs 199 tokens), so it is both more accurate and faster. A second objection is "status/cause/action labels are rule-derived". Lead with pattern accuracy (see 5.13), not cause.

---

### 5.3 Multi-agent incidents (Mode 3) with rules and single-call baselines (G03)

**In one line:** Every alarming sensor gets its own AI specialist, and a synthesizer joins their findings into one root cause. A rules mode and a one-big-call mode are kept to compare against.

**What we chose:** Mode 3: every alarming sensor gets an NPU agent, and a synthesizer names one root cause. Mode 1 (rules) and Mode 2 (one AI call) are kept as baselines.

**What we rejected and why:**
- One call over all sensors (Mode 2) as the main mode: there is no per-sensor evidence to check, and it is not faster on the final build (median 4.2 vs 3.4 s). `[ux_mode2_vs_mode3_latency]`
- Cap the number of agents: alarms beyond the cap were silently dropped. `[ux_stress_runs]`

**Evidence:**
- `[uc_cross_domain]`: all 4 multi-sensor incidents span 2-4 domains (app check 3/3 on the chaos runs). crowded_room: 2 domains, 3 NPU calls, 7.525 s. Chaos incidents: 4 domains each, with 12/10/11 agents in 20.698/20.617/20.752 s, all with report_valid true.
- `[ux_mode2_vs_mode3_latency]` (htpd v6, 10 scenarios, one run each): Mode 3 median 3.4 s vs Mode 2 median 4.2 s. 11/11 Mode 3 agent answers were policy-valid.

**Status:** pending at group level, because the separate reasoner swap (D046) is still a plan and independent cross-domain root-cause ground truth is planned.

**Children:**
- D008 (2026-10-01, kept): Three reasoning modes with the same model and data, so that differences between Modes 2 and 3 come from the architecture. Rejected: building only the multi-agent system (no baseline).
- D046 (2026-10-14, **pending**): Never two models resident. A separate reasoner would load per multi-domain incident (~+1.5 s). Rejected: a second model resident beside the 3B (it rebooted the board with 5.8 GB free).
- D053 (2026-10-15, kept): No cap on NPU agents, so every alarming sensor gets its own agent (chaos: 13 agents + synthesizer). Rejected: a cap of 3 (later 8), because the rest were silently dropped.

**How to defend it:** The expected objection is "multi-agent is just slower and more complex than one prompt". Measured through the app on the final build, Mode 3 is not slower (median 3.4 s vs 4.2 s), and each agent's answer is checked separately against its own sensor's evidence ids. Be honest that the Mode 2 vs Mode 3 comparison is latency only, one run each. There is no accuracy grid for Mode 2 vs 3 yet. That gap is why the group is marked pending.

---

### 5.4 Alert only on persistent abnormal status (event gate) (G04)

**In one line:** The AI is called only when a sensor stays abnormal for 8 readings in a row. This keeps detection the same and cuts false alarms.

**What we chose:** Warning, critical or fault status for 8 consecutive readings opens one incident, and alarms that occur together are batched.

**What we rejected and why:**
- Raise every threshold breach: 20,538 breaches a year, and most do not even last 40 min. `[uc_breaches_need_action]`: 20,538 -> 7,767 persistent -> 2,190 persistent and critical.
- Call the AI immediately: a 20-min-old event is read right only 24% of the time. `[ad_placement_curve]`: 0.236 (49/208) at 20 min.

**Evidence:**
- `[uc_alert_reduction]` (n=364 events, 77 calm windows, held-out months, QIDK NPU): threshold rules detect 0.78 (284/364) with false alarms 0.429 (33/77). Event gate + fine-tuned agents detect 0.775 (282/364) with false alarms 0.273 (21/77). Also: 2,000 calm readings produced 0 incidents.
- `[uc_breaches_need_action]`: as above, per domain.

**Status:** kept.

**Children:**
- D021 (2026-10-07, kept): The event gate. 8 abnormal readings (~16 s in the demo) open one incident, and rules show status instantly. Rejected: calling the AI on every shape change (agents misread events younger than 7 readings) and calling it immediately (a fresh step is called a spike).
- D048 (2026-10-14, kept): Close the batch window after 1 reading when no other sensor is abnormal-but-young. `[lat_batch_window]`: isolated 6.0 -> 2.0 s, crowded_room 6.0 -> 4.0 s. Rejected: always waiting 3 readings.
- D049 (2026-10-14, kept): Keep the 8-reading persistence. Only ~11 ms of the analysis is app overhead, so the gate is deliberate. Rejected: shortening persistence for speed (24% at 20 min).

**How to defend it:** The expected objection is "you delay alerts on purpose". Yes. On the raw 5-min data, 8 readings is 40 min, and only 7,767 of 20,538 breaches last that long. The agent reads an event right only 23.6% of the time at 20 min. Detection stays the same (0.775 vs 0.78) while false alarms fall from 42.9% to 27.3%. The rules still show status instantly. Only the AI explanation waits.

---

### 5.5 Safety: a policy gate on every answer (G05)

**In one line:** Every AI answer is checked for format, allowed labels and real evidence before an operator sees it. The system never acts on its own.

**What we chose:** Validate the JSON, the labels and the evidence ids; record transparent repairs; derive the action from the cause and status; build a fallback report if needed; never actuate.

**What we rejected and why:**
- Trust raw model output: invented labels and evidence ids would reach the operator. `[ad_policy_gate]`
- Use the model's own action: 0.778 vs 0.815, wrong actions from right causes. `[acc_device54_engines]` (acc_action_derived: 2 fixed, 0 made worse)

**Evidence:**
- `[uc_human_in_loop]`: agent answers passing the gate in the app (v6) 1.0 (44/44, CI 0.9197-1.0). Evidence ids valid on the host eval 1.0 (150/150), against base 0.3467. Actions executed without approval: 0.
- `[ad_policy_gate]`: agent pass rate 0.5 (3/6) before repairs and 0.8333 (5/6) with repairs, nothing invented.

**Status:** kept.

**Children:**
- D020 (2026-10-07, kept): The policy gate with transparent repairs. Every repair is recorded (for example, packed evidence ids split, a stray "]" removed), and invented labels are still rejected. Rejected: accepting raw output, and rejecting anything malformed (3/6 pass).
- D030 (2026-10-13, kept): policy.go always derives the action with the same table the labels came from. Result: +3.7 points, 2 fixed, 0 made worse.
- D056 (2026-10-15, kept): A deterministic fallback. If the synthesizer fails the policy check, the report is built from the agents (Mode 3) or the rules (Mode 2) and marked as such, and the rejected text is kept for audit. Rejected: showing "rejected", which leaves the operator with nothing.

**How to defend it:** The expected objection is "repairing model output is cheating". The repairs are mechanical and logged per incident, they never invent a label or an evidence id, and invented labels are still rejected. Note that n=6 for the 3/6 -> 5/6 figure is small. The stronger number is 44/44 in the final app run. Deriving the action is a design choice: the action is a deterministic function of (cause, status), so letting the model generate it can only add errors.

---

### 5.6 Disagreements are shown, decisions stay human (G06)

**In one line:** When the AI and the rules disagree, the report says so and a person decides. Nothing is switched automatically.

**What we chose:** The report states AI-vs-rules conflicts. Even switch_off_ac (v2) needs approval.

**What we rejected and why:**
- Let rules override the AI: the AI was right in 2 of 3 disagreements. `[ad_policy_gate]` (ad_disagreement, 18 calls)
- Automatic actuation: a wrong answer would act on the building. `[uc_human_in_loop]`: 0 actions without approval.

**Evidence:** `[ad_policy_gate]`: the rule was right once (a missed pump oscillation) and the AI was right twice (a CO2 episode that had already cleared). `[uc_human_in_loop]`: 0 automatic actions, and a dismissal needs a note.

**Status:** kept.

**Children:**
- D055 (2026-10-15, kept): The disagreement is surfaced, not resolved. Rejected: rules override the AI (the AI was right 2 of 3 times) and AI overrides the rules (the rule was right once).
- D119 (2026-10-17, kept): AC running in an empty room produces a warning and a switch_off_ac recommendation that needs human approval. Rejected: automatic switch-off (no actuation without a human, ever).

**How to defend it:** The expected objection is "then what is the AI for, if a person decides?". The AI turns 20,538 raw breaches into a few explained, evidence-cited incidents, and the person decides on those. With 3 disagreements, neither side is reliably right, so picking a winner automatically would hide a real error 1 time in 3. Showing both is the honest choice at this sample size.

---

### 5.7 Batched NPU daemon (htpd) for multi-agent incidents (G07)

**In one line:** We moved NPU serving to a llama.cpp Hexagon daemon that runs all agents in one pass over the weights. A 12-agent incident went from about 47 s to 20.7 s with no loss of accuracy.

**What we chose:** The llama.cpp Hexagon daemon: all agents in one weight sweep, with FA streams, an HMX pipe, verified drafting, a prefix cache and NEON argmax.

**What we rejected and why:**
- Stay on Genie: 13 agents take 22-25 s, and Genie drops its batching config. `[lat_route_13_agents]`
- 8-bit KV, synthesizer speculation, runtime knobs: 2x slower or changed answers. `[lat_htpd_levers]`

**Evidence:**
- `[lat_chaos_genie_vs_htpd]` (through the app): 12 agents + synth 47 -> 20.7 s, 10 agents 43.5 -> 20.6 s, 11 staggered 53 -> 20.8 s. The Mode 3 median is unchanged at 3.8 s.
- `[lat_route_13_agents]`: Genie 23.5 s (midpoint of 22-25), htpd v1 28.1, v4 17.5, v5 15.5, v6 14.7 s.
- `[lat_htpd_ab]`: 13 agents 28.1 -> 14.7 s, with identical texts 25/25 vs v5. The noise floor (same binary twice) is 21-24/25.
- `[acc_device54_engines]` (54 windows, paired): pattern Genie 0.8519 (46/54) vs htpd final 0.9074 (49/54), McNemar exact p = 0.453. Valid JSON, evidence and policy pass are all 54/54.

**Status:** kept.

**Children:**
- D074 (2026-10-16, kept): Move to llama.cpp's Hexagon backend (htpd). Decode is bandwidth-bound, so one sweep for all agents is the lever. Rejected: patching Genie's batching (it silently drops the config, and a fix needs Rust plus an AR4/AR8 re-export).
- D075 (2026-10-16, kept): The per-stream flash attention patch (FA_STREAMS). `[hw_htp_batching]`: 13 streams 15.32 -> 75.2 tok/s, and 13-agent wall time 91.8 s before -> 23.8 s. Rejected: flash attention on the CPU.
- D076 (2026-10-16, kept): The pipelined HMX path for decode-sized matmuls. 13 agents 29.5 -> 24.0 s. Rejected: the default matmul path (28-31 s).
- D077 (2026-10-16, kept): Batched, verified n-gram drafting, where a draft is kept only when it equals the greedy output. 13 agents 22 -> 16.4 s, 4 agents 14.9 -> 5.8 s. Rejected: no drafting, and speculation on the synthesizer (it changed outputs).
- D078 (2026-10-16, kept): A prefix cache per role system prompt. 13-agent prefill 8.7 -> 6.8 s. Rejected: re-prefilling the static prefix every time.
- D079 (2026-10-16, kept): NEON argmax with the same first-max tie-break. A/B total 30.3 -> 27.7 s, 25/25 identical. Rejected: scalar argmax.
- D080 (2026-10-16, kept): Keep the legacy prefill order. Rejected: equal-ubatch prefill, which changed ~30% of outputs for no gain.
- D081 (2026-10-16, kept): f16 per-stream KV and default runtime settings. Rejected: 8-bit KV (2x slower) and the FA_SELECT/MM_SELECT/OPPOLL knobs (no gain or 5-10x slower).
- D082 (2026-10-16, kept): Judge output identity against the run-to-run noise floor of 21-24/25. Rejected: requiring 25/25 identical, because batched float sums are not bit-reproducible.
- D083 (2026-10-16, kept): htpd sits behind a file switch (npu_engine = htpd), and htpdclient supervises it and stops genied. Genie is the revert path. Rejected: replacing Genie outright (no quick rollback).

**How to defend it:** The expected objection is "you swapped the vendor runtime for a hacked open-source one, so how do you know the answers did not change?". On the same 54 held-out windows, paired, htpd is no worse: 90.7% vs 85.2%, p = 0.45. Present that as "no worse", not "better". Every speed lever was gated on output identity, and the two that changed answers (synthesizer speculation and equal-ubatch prefill) were dropped. The answer to "why not just tune Genie?" is that the first htpd was slower than Genie (28.1 s vs 23.5 s), and only the FA_STREAMS patch, HMX pipelining and verified drafting made batching pay off. The data shows that whole path.

---

### 5.8 Keep the model resident and stop wasted tokens (G08)

**In one line:** Keep the model loaded between calls and stop generating text the system computes anyway. In the Genie era an agent call went from about 3.9 s to 2.5 s.

**What we chose:** genied, a persistent dialog with poll off; async init; stopping before the derived "action" field; measurement with the profiler only.

**What we rejected and why:**
- A process per call: 687-731 ms of init paid on every call. `[lat_genied]`
- Trim every call: it broke the synthesizer report. `[lat_route_agent_call]`

**Evidence:**
- `[lat_route_agent_call]`: 3947 ms baseline, then allow-async-init 3882 (-65 ms), ctx 2048 3161 (-721 ms), stop before action 2962 (-199 ms), and genied 2543 ms (measured). The intermediate bars are derived, not an additive experiment.
- `[lat_genied]`: 3640 -> 2543 ms per call, first token 1200 -> 312 ms, 28/28 identical.
- `[lat_call_breakdown]`: decode is 70-78% of a call. Init 694.7, prefill 397.0, decode 2646.3 ms (548-token prompt, 3 runs).

**Status:** kept. Genie is now the fallback path behind htpd.

**Children:**
- D028 (2026-10-13, kept): Measure with Genie's profiler only. Rejected: shell `date +%s%N` arithmetic, which reported 1.67 s for a 5.97 s run and led to a wrong 4.2 s "app overhead" conclusion.
- D031 (2026-10-14, kept): allow-async-init: true. Rejected: the shipped default (~65 ms slower init).
- D032 (2026-10-14, kept): Stop at ', "action"' on agent calls only (a []byte buffer with a 16-byte holdback). -199 ms per call, 14/14 clean. Rejected: the first strings.Builder trim (a chunk boundary produced invalid JSON) and trimming the synthesizer too.
- D043 (2026-10-14, **replaced**): genied, the C API via cgo with one dialog per process lifetime. 3640 -> 2543 ms. Superseded by htpd (5.7).
- D044 (2026-10-14, kept): poll off inside the daemon. Rejected: poll=true, which idled at 359% CPU and drove the board to 94 C.

**How to defend it:** The expected objection is "these are tiny micro-optimisations". The profiler showed decode is 70-78% of a call, so the levers are fewer tokens and no repeated init, and each was measured on its own. The bigger lesson is D028. Our first latency diagnosis was wrong because of the measurement tool, and since then only the profiler counts.

---

### 5.9 Smaller context, smarter scheduling (G09)

**In one line:** A smaller context window, batched agents, no idle gaps and a cache for repeats took a 3-call incident from 18.7 s to 11.6 s.

**What we chose:** ctx 2048 (4096 only when needed), batched agents, short gaps, an exact-prompt cache, word limits and sequential NPU sessions.

**What we rejected and why:**
- ctx 4096 for every call: 721 ms per call lost. `[lat_ctx2048]`
- Parallel NPU sessions: 3x slower, and they crashed the board. `[lat_rejected_ideas]`: +224.2% time.

**Evidence:**
- `[lat_route_incident]` (crowded_room, 3 calls): 18691 -> 17726 (batching) -> 17393 (gap 250 ms) -> 14727 (ctx 2048) -> 11570 ms (genied + zero gap).
- `[lat_ctx2048]`: -721 ms per call, 20.7 -> 25.0 tok/s, 14/14 byte-identical. KV 469 MB -> 235 MB.
- `[lat_batch_window]`: -4 s isolated, -2 s cross-domain.

**Status:** kept.

**Children:**
- D023 (2026-10-07, kept): Sequential NPU sessions. Rejected: parallel Genie sessions (76.5 s vs 23.6 s for two calls, and 3.7 GB per session crashed the board).
- D024 (2026-10-07, **replaced**): Genie at 4 threads, cpu-mask 0xf0, use-mmap true. Rejected: use-mmap false (init 3.0 vs 0.65 s) and 3 threads (11.9 vs 11.7 s).
- D025 (2026-10-07, kept): Word limits: root cause <= 20 words and explanation <= 35 words, giving 102-120 tokens (~7-8 s) instead of 184-190 (~11 s).
- D026 (2026-10-07, kept): An exact-prompt cache. Greedy decoding gives identical answers, so Compare reruns cost 0 NPU calls (~3 ms).
- D029 (2026-10-13, **replaced**): poll=true for the per-call CLI. The third-party claim that poll=false is +55% faster measured 7-8% slower here.
- D038 (2026-10-14, **replaced**): genie-app batch (Prefetch). -965 ms, 16/16 identical. Rejected: one CLI process per agent.
- D041 (2026-10-14, kept): Inter-call gap 600 -> 250 ms (0 with a daemon). 17726 -> 17393 ms. Rejected: keeping 600 ms, and 0 ms for the CLI (never measured).
- D042 (2026-10-14, kept): ctx 2048 bundle with the same weights. Rejected: ctx 4096 (we use ~610 slots) and ctx 1024 (generation reaches ~1120 tokens).
- D054 (2026-10-15, kept): Two context windows chosen per call. ctx 4096 is swapped in only when the prompt needs it (~0.9 s swap, chaos-size prompts only), 5/5 identical. Rejected: trimming evidence to fit (it drops evidence the reasoner needs) and 4096 for everything.

**How to defend it:** The expected objection is "a smaller context loses information". The 4096 window held ~610 used slots, the change was 14/14 byte-identical, and large chaos prompts still get 4096 automatically (D054), so no evidence is dropped. Three of these children are marked replaced because htpd superseded the Genie-specific settings. The ideas (smaller KV, batching, zero gaps) carried over.

---

### 5.10 Reject speed-ups that change answers or do not pay (G10)

**In one line:** The two fastest tricks we found gave wrong answers, so every decode change must leave the answers unchanged.

**What we chose:** Gate every decode change on output identity across many prompts.

**What we rejected and why:**
- LADE lookahead decoding: a stuck sensor was reported as normal. `[lat_rejected_ideas]`: -32.5% time, identical 1/14 (0.0714).
- Grammar decoding, multi-graph, RPC knobs, continuous batching: slower, no gain, or truncated answers. `[lat_rejected_ideas]`: grammar +18.1%, 3-graph +14.8%, RPC +1.6% (noise), continuous batching -76.0% but identical 1/12 (0.0833).

**Evidence:** `[lat_rejected_ideas]` as above. `[lat_call_breakdown]`: 2.20 GB per token at 22.4 tok/s = 49.3 GB/s, ~84% of the measured NPU DMA ceiling.

**Status:** kept.

**Children:**
- D033 (2026-10-14, kept): Do not ship multi-graph bundles. Rejected: a 3-graph bundle (4291 vs 3738 ms per call) and a 4-way model split (NUM_SPLITS is hardcoded).
- D034 (2026-10-14, kept): DSP RPC and runtime knobs left at their defaults, because decode is NPU-bound, not RPC-bound.
- D035 (2026-10-14, kept): Stop tuning decode; attack init, token count and the number of calls. Decode is already at ~84% of the DMA ceiling.
- D036 (2026-10-14, kept): No pre-warming of genie-t2t-run (Genie reads the whole prompt first, and SELinux refuses mkfifo). The persistent dialog was used instead.
- D037 (2026-10-14, kept): LADE rejected for good: "a fast wrong answer is worse than a slow right one".
- D039 (2026-10-14, kept): Grammar-constrained decoding rejected (+440 ms init, no tokens saved). The policy gate handles format instead.
- D045 (2026-10-14, kept): Continuous batching on Genie's shared engine rejected (-slots 1). The "76% speedup" was answers stopping early.

**How to defend it:** The expected objection is "you left a 32% speed-up on the table". LADE made only 1 in 14 answers identical, and one of the changed answers called a stuck sensor normal, which is a missed fault. The 76% "speed-up" was truncation, not speed. These negative results are why our latency numbers can be trusted: nothing faster was accepted unless the answers stayed the same.

---

### 5.11 Close the device accuracy gap with GPTQ (G11)

**In one line:** Quantising the model for the NPU first cost a lot of accuracy. GPTQ weights, with the vendor's activation ranges, recovered most of it.

**What we chose:** GPTQ int4 weights, the published activation ranges, w4a16.

**What we rejected and why:**
- Round-to-nearest int4: costs ~15 points (73.9% vs 89.1% on host). `[acc_quant_waterfall]`
- Kaggle-recalibrated activations: no gain once BOS was fixed. `[acc_quant_waterfall]`: 0.8261 both.

**Evidence:** `[acc_quant_waterfall]` (same 46 windows for steps 2-9): first NPU export 0.5435 (25/46), MSE-clipped scales 0.3913, device int4 + fp activations (host) 0.7391, GPTQ fp activations (host) 0.8913, GPTQ + base ranges 0.6739, GPTQ + recalibrated 0.6087, GPTQ + recalibrated + BOS fixed 0.8261, GPTQ + published + BOS fixed (live) 0.8261, and the same live model on 54 windows 0.8519 (46/54).

**Status:** kept.

**Children:**
- D014 (2026-10-07, kept): GPTQ int4 weights calibrated on our train prompts, reproduced exactly on device (0 mismatches over 1,232 tensors). Rejected: plain RTN (stated here as "~20 points"; see the note below) and MSE-clipped scales (39.1% on device).
- D015 (2026-10-07, kept): Qualcomm's published activation ranges. Rejected: ranges recalibrated on 149k tokens (82.6% both, JSON 97.8% vs 100%).
- D017 (2026-10-07, kept): w4a16. Rejected: w4 with fp16 activations, which compiles but does not load on the 8 Gen 3 (err 1002).

**How to defend it:** The expected objection is "the waterfall mixes host and device, and 46 windows". The steps marked host are diagnostics. The device steps (2, 3, 6-9) are all on the same 46 windows, and five steps survive only as HANDBOOK prose because the bundles were overwritten (the notes say so). The key honest point is in 5.12: the biggest single gain was a prompt bug, not quantisation.

Note: the group's rejected line says RTN costs "~15 points", while child D014 says "~20 points". The numbers in the data (73.9% vs 89.1%) give ~15.

---

### 5.12 Prove the device runs exactly what was trained (G12)

**In one line:** We found the device was feeding the model a slightly different prompt than in training. Fixing that, and checking byte-for-byte identity on every change, is what made the device numbers trustworthy.

**What we chose:** Strip our BOS token, force greedy decoding, and validate on the device before switching models.

**What we rejected and why:**
- Trust host accuracy: the first export lost 40 points on the device (94% host vs 54.3% device). `[acc_quant_waterfall]`
- Sampling decoder (the bundle default): no reproducibility, no cache, no identity gates. `[acc_pipeline_parity]`

**Evidence:** `[acc_pipeline_parity]`: 400/400 prompts byte-identical to training, 1232 GPTQ tensors reproduced, 11711 activation encodings matched, verify_batch 16, verify_daemon 28, ctx 2048 vs 4096 14, two-window gate 5. Genie prepends BOS itself (606 host tokens became 607 on device). `[acc_quant_waterfall]`: 0.6739 -> 0.8261 from the BOS fix (67% -> 83%).

**Status:** kept.

**Children:**
- D016 (2026-10-07, kept): Prompts are sent without BOS. Rejected: keeping the training-time BOS (a double BOS the model never saw).
- D018 (2026-10-07, kept): Greedy decoding in every config. Rejected: the bundle default (random sampling, temp 0.8).
- D022 (2026-10-07, kept): A VALIDATED marker is written only after an on-device test; otherwise the app falls back to the base model. Rejected: shipping the fine-tune unconditionally.

**How to defend it:** The expected objection is "greedy decoding is a weaker decoder". For a classifier-like JSON task, determinism matters more. It makes the cache valid and allows byte-identity tests, which is how we proved every later speed change did not alter answers. Owning the BOS bug openly is a strength: it shows we found the real cause rather than blaming quantisation.

---

### 5.13 Honest ground truth and statistics (G13)

**In one line:** We only claim what our labels can prove: pattern accuracy on roles where the rules did not write the answer key. Every number comes with n and a confidence interval.

**What we chose:** Known patterns injected into real calm windows, a temporal split, and n, Wilson CIs and paired tests on every claim.

**What we rejected and why:**
- Claiming cause accuracy as independent: the cause labels come from the same rules as Mode 1. `[acc_v1_rules_vs_llm_fair]`
- All-role averages: occupancy labels are the rules' own logic (rules score 100% by construction). `[acc_v1_host_per_role]`

**Evidence:**
- `[acc_v1_rules_vs_llm_fair]` (4 roles: air, water, power, weather): fine-tuned 0.925 (111/120, CI 0.8636-0.96) vs rules 0.6 (72/120, CI 0.5106-0.6832).
- `[acc_v1_host_per_role]`: fine-tuned 87-100% per role vs rules 53-63%, with occupancy excluded.
- `[acc_device54_engines]`: paired McNemar, p = 0.453.

**Status:** pending at group level. Facility event logs, a second and independent ground truth, have not arrived.

**Children:**
- D010 (2026-10-06, kept): Labels come from injecting known patterns into real calm 4 h windows. Rejected: hand-labelling (slow, subjective) and waiting for facility logs (not available).
- D011 (2026-10-06, **replaced**): The v1 temporal split, train Jan-Aug / dev Sep-Oct / test Nov-Dec 2025. Rejected: a random split (it leaks neighbouring windows). Replaced in v2 by test months plus held-out sensors (5.27).
- D066 (2026-10-16, **pending**): Injected faults now (plus cross-domain injections for root cause), real log events when the raw data arrives.
- D067 (2026-10-16, kept): Lead with pattern accuracy on the 4 non-circular roles: 92.5% vs 60.0%.
- D068 (2026-10-16, kept): Never quote a number without n and a CI. Prefer McNemar on identical cases and save per-sample rows. Rejected: aggregate-only reports (the 54-window set has ~1 case per class, a +-10-point CI).

**How to defend it:** The expected objection is "synthetic injections are not real incidents". The injections sit on real sensor noise from real calm windows, so the noise is real and the label is exact. The limitation is stated, and facility logs are the planned second ground truth (pending). By not claiming cause accuracy as independent, and by excluding the circular occupancy role, we give up flattering numbers to keep the claims defensible. That will hold up better with a professor than a bigger figure would.

---

### 5.14 Keep the 4 h window for the domain agent (G14)

**In one line:** We tried 2, 4, 8 and 12 hour views of the data on the device, and 4 h, the length the model was trained on, reads patterns best.

**What we chose:** 48 x 5-min readings (4 h).

**What we rejected and why:**
- 12 h window: pattern 42%, false alarms 27% -> 46%, +32% cost. `[ad_window_headline]`: pattern 0.425, false alarms 0.455 (35/77). `[ad_window_cost]`: 1.536 vs 1.164 s per agent.
- 2 h window: worst on almost everything (pattern 46%). `[ad_window_headline]`: 0.458.

**Evidence:** `[ad_window_headline]` (2416 NPU calls, 369 labelled cases): pattern 2 h 0.458, 4 h 0.637 (235/369), 8 h 0.558, 12 h 0.425. Detection 0.665/0.775/0.799/0.821 and false alarms 0.351/0.273/0.377/0.455. 4 h beats every other length on pattern, p < 0.0001 (paired). `[ad_window_cost]`: 8 h +18%, 12 h +32% per agent.

**Status:** kept.

**Children:** D084 (2026-10-16, kept): keep 4 h. Rejected 2 h (46%), 8 h (56%, +18% cost, no significant gain on old events) and 12 h (42%, false alarms up, +32% cost).

**How to defend it:** The expected objection is "longer windows obviously see more". They do detect more (12 h detection 0.821 vs 0.775), but they misname what they see, and false alarms rise to 45.5%. The model was trained on 4 h, which is why v2 trains on 2-12 h windows (5.23). The long-range gap is closed separately by cheap 12 h CPU checks (5.16), not by a longer agent window.

---

### 5.15 Early alert, then refined re-reads at 1.5 h and 3 h (G15)

**In one line:** Alert fast, then re-read the same incident later, when the AI is much more likely to name the event correctly.

**What we chose:** The alert stays fast. Every Mode-3 incident is re-analysed at +18 and +36 readings. Early spikes are kept, and the worst severity is kept.

**What we rejected and why:**
- Only the early read: about 6 in 10 young events are misnamed. `[ad_placement_curve]`: 0.423 at 40 min.
- Wait 3 h before the first analysis: alerts would be hours late. `[ad_placement_curve]`

**Evidence:**
- `[ad_placement_curve]` (208 events x 6 onsets, 1248 NPU calls, htpd v6): pattern 0.236 at 20 min, 0.423 at 40 min, 0.572 at 1 h, 0.668 at 1.5 h, 0.76 at 2 h, 0.885 at 3 h (184/208). Paired: at 3 h, 105 events became right and 9 became wrong (p < 0.0001).
- `[ad_placement_heatmap]`: steps are right from 1 h; oscillation and slow rises only at 3 h.
- `[ref_device_runs]` (3 runs, 9 incidents, all reached 3 h): power_throttling goes from early "exponential_increase" to refined "throttling" (correct).

**Status:** kept.

**Children:**
- D087 (2026-10-16, kept): Alert at 8 readings, then re-analyse on windows ending +18 and +36 readings (42% -> 67% -> 88%).
- D088 (2026-10-16, kept): Keep an early spike/dip when the refined read says only "stable" ("event over, not wrong"). Rejected: always replacing it (at 3 h a spike is often called stable, 43%).
- D089 (2026-10-16, kept): Refinements yield to every alert and operator job, never change approval or the gate, and skip Modes 1 and 2. Rejected: running them immediately (that would delay new alerts). `[ref_stage_timing]`: refined reports land 37 s and 74 s after the early one at 2 s demo polls.
- D094 (2026-10-16, kept): A 12 h finding raises a "normal" sensor to warning, and the worst severity is kept. Rejected: severity from the agent only (run 1: tank leak drift found, severity stayed normal; run 2: raised to warning at 1.5 h).

**How to defend it:** The expected objection is "so your early alert is wrong more than half the time". The early alert's pattern name is wrong about 58% of the time at 40 min, but the alert itself fires reliably: 0.769 flagged at 40 min. The refinement exists exactly because we measured this curve. An operator gets a fast warning and then a much more reliable explanation (88% at 3 h) on the same incident. Refinements run at the lowest priority, so they never delay new alerts.

---

### 5.16 12 h CPU checks feed the reasoner (G16)

**In one line:** Two cheap 12-hour statistical checks on the CPU catch old steps and slow drifts that a 4 h view misses, without adding false alarms.

**What we chose:** Level shift + slow drift over 12 h, tuned on dev months and tested once.

**What we rejected and why:**
- A daily "same hours yesterday" baseline: false alarms 20% -> 29%, old steps 86% -> 48%. `[ad_daily_baseline_rejected]`: clean 0.287 vs 0.2, step_old 0.48 vs 0.86.
- A recurring-excursion detector: dev false alarms 2% -> 15%. `[ad_longrange_ablation]`: dev clean 0.15 (18/120) with it vs 0.0167 (2/120) without, with the same test step_old 0.86.

**Evidence:**
- `[ad_longrange_arms]` (test months): agent alone vs agent + 12 h checks gives old step 0.733 -> 0.933 (56/60), slow drift 0.833 -> 0.95 (57/60), false alarms 0.308 -> 0.308 (12/39), and all events 0.775 -> 0.83. Paired: +12 old steps (p=0.0005), +7 drifts (p=0.016), 0 lost.
- `[ad_detector_tuning_frontier]`: at 15% false alarms, raw 12 h catches 64% of old steps vs 23% for the daily baseline.

**Status:** kept.

**Children:**
- D090 (2026-10-16, kept): 12 h CPU checks as evidence lines (E9/E10) for the reasoner instead of a 12 h agent. Rejected: a 12 h agent window (it misnames events, and false alarms rise).
- D091 (2026-10-16, kept): Drop the recurring-excursion detector. Recurring small spikes remain unsolved, and retrain v2 teaches them.
- D092 (2026-10-16, kept): Reject daily-baseline differencing, because yesterday has its own events.
- D093 (2026-10-16, kept): Tune on dev Sep-Oct and evaluate once on Nov-Dec. Rejected: tuning on the test set (optimistic numbers).

**How to defend it:** The expected objection is "you tuned thresholds until the numbers looked good". Tuning used dev months only, the test months were evaluated once, and the paired tests show 0 events lost. We also report what we failed at: recurring small spikes stay at 0.32 detection, which is why that detector was dropped and v2 data now teaches the pattern.

---

### 5.17 Severity, titles and the report follow the AI (G17)

**In one line:** The incident list colour and title now reflect what the AI concluded, not the first rule that fired.

**What we chose:** severity.go and title.go derive from the analysis. A report page with chips and a sensor sheet. Live token streaming.

**What we rejected and why:** Rule severity fixed at creation: the list colours contradicted the analysis. `[ux_screenshots]`

**Evidence:** `[ux_screenshots]`: 39 files, the operator UI before (2026-10-14) and after (2026-10-16), plus refinement screens.

**Status:** kept.

**Children:**
- D050 (2026-10-14, kept): Fix stale UI across app updates (wipe WebView storage per install, no-cache headers, service worker fetch no-cache). Rejected: relying on LOAD_NO_CACHE (the service worker cache survived updates).
- D051 (2026-10-14, kept): Stream live tokens on incident cards, so the first text appears ~1 s after a call starts. Rejected: painting tokens only into an open sheet (answers appeared after ~15 s with no sign of life).
- D085 (2026-10-16, kept): Severity is the reasoner's severity, else the worst final agent status, and old incidents were back-filled.
- D086 (2026-10-16, kept): A "Done in X s" line, chips and a floating sensor sheet. Severity is shown with colour plus bar, glyph and label. No horizontal scroll at 360 px. Rejected: an always-visible step timeline and colour-only severity (not accessible).
- D095 (2026-10-16, kept): title.go rebuilds the title from confirmed agents plus the reasoner label, and keeps the original as rule_title. For example: "All clear: 3 sensors checked".

**How to defend it:** The expected objection is "the AI can downgrade a real alarm". Severity follows the reasoner, but a 12 h finding can raise it (D094), the worst severity across refinements is kept, and the rule's view stays visible: the original title is kept as rule_title, and conflicts are stated (5.6). The evidence here is screenshots, not a metric, so present it as a UX fix, not a measured accuracy gain.

---

### 5.18 Test through the app, the way an operator uses it (G18)

**In one line:** We test by driving the real app with random inputs, faults and chaos, not just offline benchmarks, and the final build passes 132 of 135 checks, with only heat failures.

**What we chose:** stress_app.py: random sliders, faults, chaos and operator actions, with one FIFO queue.

**What we rejected and why:** Offline benchmarks only: they missed un-injectable scenarios, dropped alerts and stale aborts. `[ux_stress_runs]`

**Evidence:**
- `[ux_stress_runs]`: Genie final regression 238/240 (2 thermal). htpd v6 final 132/135 (0.9778, CI 0.9367-0.9924, 3 thermal). Report-page build 133/135. Refinement build 129/135 (6 thermal). Earlier htpd runs had "harness check" failures from a stale genied-alive test, which was fixed in the harness, not the app.
- `[ux_chaos_incidents]`: 10-12 agents + synthesizer in ~21 s (Genie chaos 48.9 s for 13 agents and 40.8 s for 9).

**Status:** kept.

**Children:**
- D040 (2026-10-14, kept): Live fallback nodes for the four un-injectable scenarios, after which crowded_room fanned out to 3 NPU calls. Rejected: leaving 4 of 10 scenarios unable to fire.
- D052 (2026-10-15, kept): One queue, alerts first, at most 16 waiting, duplicates merged, HTTP 429 beyond that. Rejected: each request running its own pipeline (8 interleaved requests took 58 s for 10.8 s of model time).
- D065 (2026-10-15, kept): Test through the app only. 238/240 on the Genie build.

**How to defend it:** The expected objection is "your own tests, your own pass criteria". Every run is listed, including the bad ones (24/34 and 26/34 on early htpd chaos runs), and every failure is classified. The remaining failures are all thermal, at 95-96 C chaos peaks, which is a hardware limit with a stated mitigation (heatsink), not a logic error.

---

### 5.19 Recover from faults; exactly one model on the NPU (G19)

**In one line:** If a process crashes or the NPU hiccups, the system restarts itself and loses no incidents, and it never loads a second model by accident.

**What we chose:** A crash-safe store, incidents persisted at creation, NPU retries, a port lock, an API token, and plausibility rules.

**What we rejected and why:**
- Treat EOF as a normal end: truncated answers were marked "answered". `[ux_fault_injection]`
- A CLI fallback beside a live daemon: it loads a second model and the board reboots. `[ops_incidents]`

**Evidence:**
- `[ux_fault_injection]`: kill edge-agent -> restarted in 8 s; kill genied -> daemon back in 15 s; cold boot -> answering in 5 s; NPU call completed on the CLI after a daemon kill in 4.9 s.
- `[ops_incidents]`: 22 incidents. Every crash had a plumbing cause, and each now has a guard.

**Status:** kept.

**Children:**
- D027 (2026-10-08, kept): Retry after err 1002 at 3, 7 and 15 s, showing "NPU temporarily unavailable". Rejected: a single 4 s retry, which also failed and showed empty output as a safety rejection.
- D059 (2026-10-15, kept): Compaction (temp + fsync + rename), keeping the newest 1000 plus an archive. Rejected: append forever with everything in RAM.
- D060 (2026-10-15, kept): Port as a single-instance lock, no CLI while genied lives, and a wedged daemon is killed (two failed calls or 3 alive-not-listening checks).
- D061 (2026-10-15, kept): POSTs from non-loopback addresses need X-API-Token, and reads stay open. Rejected: an open API on 0.0.0.0 (anyone on the Wi-Fi could approve or inject).
- D063 (2026-10-15, kept): Indoor CO2 < 350 ppm = sensor fault (outside the training rules, documented). Rejected: training-parity rules only (270 ppm was called a harmless step decrease).
- D064 (2026-10-15, kept): Detect truncated answers, persist incidents at creation, watchdog restarts, and re-run interrupted incidents.

**How to defend it:** The expected objection is "edge boards crash, so how is this production-ready?". We killed processes on purpose and measured recovery (8 s and <= 15 s). Every one of the 22 logged operational incidents is listed with its cause and guard. The CO2 rule is openly documented as outside the training rules: it is a physics check, not a hidden override.

---

### 5.20 Keep the board cool and powered (G20)

**In one line:** The dashboard itself was overheating the board, so we redesigned it, paced the AI under heat, and used a proper DC supply.

**What we chose:** Thermal pacing per NPU call, a UI that does not heat the board, and DC power.

**What we rejected and why:**
- Animated, blurred UI: hotter than a 13-agent incident. `[hw_board_thermal]`: idle 75 C before the fix.
- USB power: a brownout rebooted the board at peak load. `[ops_incidents]`

**Evidence:** `[hw_board_thermal]`: idle after the UI power fix 43 C (75 C before). Right after inference 66 C. 13-agent chaos before pacing 94 C. Chaos with thermal pacing (Genie) 90 C. htpd chaos peaks 96 C. Guard: before each NPU call at >= 88 C, wait <= 15 s for 82 C.

**Status:** kept.

**Children:**
- D057 (2026-10-15, kept): A DC adapter (boot reason "reboot" with AC/USB online = false).
- D058 (2026-10-15, kept): Solid bars, stepped animations, 1 Hz sparklines, giving 5-11% CPU and 43 C idle. Rejected: backdrop blurs + 60 fps (~220% CPU at idle).
- D062 (2026-10-15, kept): Thermal pacing inside an incident. Rejected: a guard only between incidents (94 C).

**How to defend it:** The expected objection is "96 C is too hot". Agreed, and we say so. The ~90 C pacing figure is from the Genie era. htpd chaos still peaks at 95-96 C, those peaks are the only remaining stress-test failures, and the stated mitigation is a heatsink or fan for the demo and the field. Typical incidents run far cooler (66 C right after inference).

---

### 5.21 GPU study: decided by data (G21)

**In one line:** We were asked whether the phone's GPU would do better, so we measured GPU-only, NPU-only and hybrid on the same incidents. The NPU wins at every size.

**What we chose:** The full matrix, run on the device's own weights, with a safe memory ladder. The NPU stays in production.

**What we rejected and why:**
- Agents on the Adreno GPU: 10.0 s vs 3.9 s for one agent, and no valid JSON at ctx 4096. `[hw_grid]`: 10.01 vs 3.93 s. `[hw_grid_agreement]`: GPU ctx 4096 valid JSON 0/28.
- Batching agents on the GPU: 8 streams together only 12.4 tok/s. `[hw_gpu_batched]`: 1 stream 16.73 tok/s.

**Evidence:**
- `[hw_grid]` (wall time, 1 rep per cell): Genie NPU 3.93 / 14.35 / 19.37 / 34.94 / 53.62 s for 1 / 2+s / 4+s / 8+s / 13+s. GPU sequential 10.01 / 30.01 / 48.96 / 86.67 / 137.6 s (peaks up to 96.2 C).
- `[hw_grid_agreement]`: llama.cpp HTP agrees with Genie on 22/26 patterns, and the GPU (ctx 1024) on 8/12.

**Status:** kept.

**Children:**
- D070 (2026-10-16, kept): Run the full matrix and decide from data. Rejected: assuming the NPU wins.
- D071 (2026-10-16, kept): Extract the device's int4 weights and repack them exactly to Q4_0/Q8_0, so placement is the only variable. Rejected: stock llama.cpp Q4_0 (different weights).
- D072 (2026-10-16, kept): A safe ladder (oom_score_adj 1000, drop_caches + compact before each load, one rung at a time). Rejected: "load and hope" (the OOM killer picked system processes and Android rebooted).
- D073 (2026-10-16, kept): GPU not used in production. Rejected: GPU only (~8.4 s per agent), hybrid (slower, because both share LPDDR5X bandwidth), and batched GPU (OpenCL matmuls do not batch).

**How to defend it:** The expected objection is "you did not tune the GPU properly". We used the same weights and tried the knobs: dp4a cut prefill to 64 tok/s, and flash attention cut decode to 7.5 tok/s. The structural reason is that GPU and NPU share the same LPDDR5X bandwidth, and OpenCL matmuls do not batch, so a hybrid cannot add throughput. Note that there is 1 rep per cell. The gap (GPU 2.1-2.6x slower per incident size) is far larger than run-to-run noise.

---

### 5.22 Retrain the domain agents (v2) instead of patching (G22)

**In one line:** Rather than piling on more fixes around v1, we are retraining the agents on data that matches how the app actually uses them, and we will accept the result only if it passes on the board.

**What we chose:** A final v2 retrain, deployed as GGUF on htpd. Accuracy first, then bring latency back to today's numbers.

**What we rejected and why:**
- Keep v1 and add more CPU checks: v1 reads 40-min-old events right only 42% of the time. `[ad_placement_curve]`
- Accept on dev loss: dev loss is not accuracy. `[tv2_loss_curve]`

**Evidence:** `[ad_placement_curve]` (0.423 at 40 min, 0.885 at 3 h). `[tv2_loss_curve]`: dev loss 0.1311 -> 0.066, train ~ dev, no overfitting (n=507 points). v1's dev loss of 0.027 is on an easier dataset and is not comparable.

**Status:** pending (training in progress; no device acceptance result yet).

**Children:**
- D096 (2026-10-16, **pending**): Retrain on new data. Rejected: keeping v1 + more CPU checks (42% at 40 min, 4 h only, ~31% false alarms on routines).
- D098 (2026-10-16, **pending**): Merge -> GGUF Q4_0 with an importance matrix from our prompts -> htpd. Rejected: another AI Hub export (fallback only).
- D112 (2026-10-16, **pending**): Acceptance on the QIDK NPU, test months only: pattern >= 65% at 40 min and >= 88% at 3 h, no regression on the 54/900 sets, JSON/policy >= 98%, and fewer false alarms than 31%.
- D114 (2026-10-16, **pending**): Accuracy first, then optimise until the 13-agent batch is <= 14.7 s and a typical incident <= 3.8 s. Rejected: trading accuracy for latency ("user rule: never").

**How to defend it:** The expected objection is "the loss is going down, so it works". We explicitly refuse that argument: acceptance is measured on the NPU, on test months, with fixed numeric thresholds set before the results exist. If v2 misses them, v1 plus refinements remains the shipped system. Present all v2 numbers as in progress.

---

### 5.23 v2 data: events of every age, every window length, 12 h history (G23)

**In one line:** v2 training examples show events at every age and window length, matching what the app will actually ask the model about.

**What we chose:** Onset anywhere (with extra weight at 20-60 min), event sizes 1.5-12x noise, E9/E10 history lines, and the window length shown in the prompt.

**What we rejected and why:** v1 data (4 h only, events 1-3 h old): the agent misreads what the app actually asks about. `[ds_event_age]`

**Evidence:** `[ds_event_age]`: training events range from fresh (<= 1 h) to old (> 3 h), n=35,946. `[ds_window_lengths]`: 21 window lengths from 2 h to 12 h (v1: 4 h only).

**Status:** pending at group level (the run-time window policy D099 depends on v2).

**Children:**
- D099 (2026-10-16, **pending**): Run-time window by severity and stage: early alert 4 h for all; refinements use 4 h for normal, 8 h for warning, and 12 h for critical/fault. Rejected: one fixed window.
- D101 (2026-10-16, kept): Onset uniform from 3 readings before the end back to the window start. Rejected: v1 placement (1-3 h in), because the app asks at ~40 min.
- D102 (2026-10-16, kept): 12 h history lines in the prompt (+40-60 prompt tokens). Rejected: 4 h only (old steps and drifts invisible).
- D103 (2026-10-16, kept): Show "N x 5 min" and hide the stage, so the model reads the data rather than a hint.
- D106 (2026-10-16, kept): Boundary examples below ~3x noise are labelled stable/normal, so the model learns what is too small to alarm.

**How to defend it:** The expected objection is "you are changing the test to suit the model". It is the other way round: the placement study showed the app asks at ~40 min while v1 was trained on 1-3 h-old events, so v2 moves the training distribution to match the real question. Hiding the stage (D103) prevents the model from learning a shortcut.

---

### 5.24 v2 data: teach what v1 missed and what is normal (G24)

**In one line:** v2 adds the patterns v1 never learned, seven kinds of sensor fault, and many routine behaviours labelled "normal" so the model stops raising false alarms on them.

**What we chose:** Recurring spikes, old shifts, long drifts, compound shapes, faults, and routines labelled normal.

**What we rejected and why:** The v1 pattern set: recurring small spikes were caught only 32% of the time, with ~27-31% false alarms on calm data. `[ad_window_old_events]`: recurring small spikes 0.32 (24/75) at 4 h.

**Evidence:** `[ds_families]`: events are 29% of rows, and the rest teach faults, routines, drifts and old shifts. `[ds_routine]`: over 20 kinds of routine labelled normal (n=8,292). `[ds_fault_kind]`: seven fault kinds (n=5,247).

**Status:** kept (the data is built; the training outcome is pending under 5.22).

**Children:**
- D104 (2026-10-16, kept): 12 v1 patterns plus recurring small spikes, old level shifts, long drifts, 7 fault kinds and compound shapes.
- D105 (2026-10-16, kept): Hard negatives (refills, load switching, daily cycles, HVAC cycling, schedules) labelled normal. Rejected: calm windows only (~31% false alarms came from routines).
- D116 (2026-10-17, kept): Recurring small spikes = spike / normal citing E10 (power excluded). Rejected: labelling them warning.
- D117 (2026-10-17, kept): A false alarm is status != normal on a normal window. Rejected: counting any non-stable pattern as an alarm.
- D118 (2026-10-17, kept): Abnormal tank fills (past the high limit, too long, or repeatedly off-hours) are warning/critical, and routine refills stay normal.
- D121 (2026-10-17, kept): fault_kind gains "quantised", and the drift rules are tightened.

**How to defend it:** The expected objection is "labelling spikes 'normal' hides real problems". Only recurring small (sub-threshold) spikes are labelled normal: the agent still names the pattern and cites the E10 evidence line, it just does not alarm on it. Abnormal fills are explicitly taught as warnings (D118). The false-alarm definition (D117) matches what an operator sees.

---

### 5.25 v2 output: short, frozen schema (G25)

**In one line:** v2 answers stay short (~76 tokens) even with three new fields, because output length is decode time.

**What we chose:** At most 2 observations; new fields event_active, onset and fault_kind; calibrated confidence.

**What we rejected and why:** v1 free-length output: more tokens means more decode time. `[ds_tokens]`

**Evidence:** `[ds_tokens]`: prompts ~733 tokens; answers ~76 tokens up to the derived "action". `[ds_families]` for the schema fields.

**Status:** kept.

**Children:**
- D108 (2026-10-16, kept): <= 2 observations of ~14 words.
- D109 (2026-10-16, kept): A frozen v2 schema that the backend already accepts (the old model just omits the new fields). Rejected: changing the schema after training (it forces a second training).
- D110 (2026-10-16, kept): Confidence = the expected accuracy for that age, size and pattern (from the placement study), recalibrated in the backend after training (D4). Rejected: the v1 amplitude formula (not a probability).

**How to defend it:** The expected objection is "shorter answers lose explanation". Decode is 70-78% of a call (5.8), so every token costs time, and the free-text explanation is written by the synthesizer, not the per-sensor agent. Freezing the schema before training means the app and the model cannot drift apart.

---

### 5.26 Add an HVAC agent (G26)

**In one line:** v2 adds a sixth specialist for the 87 indoor AC units, so AC faults and cooling of empty rooms become visible.

**What we chose:** A 6th role per indoor unit, faulty units used as fault examples, and dense "unit on" sampling.

**What we rejected and why:** HVAC only as context: short-cycling and cooling empty rooms stay invisible. `[ds_hvac_real_labels]`

**Evidence:** `[ds_hvac_real_labels]` (73,036 windows kept from 311,567 scanned, 29,393 ambiguous skipped): normal 0.9845, warning 0.0083, sensor_fault 0.0064, critical 0.0008. `[ds_roles]`: 35,946 train / 1,947 dev / 2,965 test rows across 6 roles.

**Status:** kept.

**Children:**
- D100 (2026-10-16, kept): The HVAC agent from SR-AC.csv (87 units) checks room temperature vs setpoint, short-cycling, stuck on/off, and running without cooling.
- D120 (2026-10-17, kept): Faulty units are used as fault examples, with dense "on" sampling. Rejected: all units as normal bases (4 units had bad sensors all year) and natural sampling (98.45% normal, "on" windows rare).

**How to defend it:** The expected objection is "98% of the data is normal, so the model will just say normal". That is exactly why faults are taught by injection plus real faulty units, and why "on" windows are sampled densely. The HVAC agent's accuracy is not yet measured on the device (pending under 5.22).

---

### 5.27 Held-out sensors and data QA before training (G27)

**In one line:** Some sensors are hidden from training entirely, and every training row passes automatic checks before any GPU time is spent.

**What we chose:** Test months plus ~15% held-out sensors, automatic checks plus manual review, all generated from existing data.

**What we rejected and why:**
- Temporal split only: the same sensors appear in every split. `[ds_heldout]`
- Train first, check later: a bad label costs 40+ GPU hours. `[ds_qa_checks]`

**Evidence:** `[ds_heldout]`: 25 sensors held out (air_quality 3, water 6, power 2, occupancy 1, weather 0, hvac 13). Test rows: unseen 985, seen 1744, unseen_sepoct 236. `[ds_qa_checks]`: 11 hard checks x 40,858 rows, 0 failures.

**Status:** kept.

**Children:**
- D107 (2026-10-16, kept): No new raw data; generate from the existing series (35,946 rows generated locally in 121 s). Rejected: waiting for new raw data (not arrived).
- D113 (2026-10-16, kept): Hold out ~15% of sensors and report seen vs unseen (25 sensors; 1,221 test rows from them).
- D115 (2026-10-16, kept): A 60-sample private review page plus automatic checks.
- D122 (2026-10-17, kept): Weather is tested on seen stations only (only 2 stations exist), stated as a limitation.

**How to defend it:** The expected objection is "the model may have memorised each sensor". The held-out sensors answer that: results will be reported seen vs unseen. The weather limitation is stated openly rather than hidden. The 1,221 unseen test rows are 985 unseen in the test months plus 236 held-out water rows from Sep-Oct.

---

### 5.28 Train v2 on the laptop in resumable sessions (G28)

**In one line:** A ~50 h training run on a personal laptop survives crashes, sleeps and heat because it runs in resumable sessions with guards.

**What we chose:** QLoRA r=32, 4,494 steps; a thermal guard; WSL networking off; the lid kept open; a WMI supervisor.

**What we rejected and why:** One uninterrupted 50 h run: a BSOD, a thermal sleep and lid standbys would each have lost the run. `[tv2_interruptions]`: 1 bugcheck (BSOD), 2 unclean reboots, 1 thermal sleep, 6 Modern Standby lid events.

**Evidence:** `[tv2_sessions]`: 12 sessions, every session resumed from a checkpoint. `[tv2_thermal_pauses]`: 1103 pauses, 5.2 h paused, GPU peak 87 C (threshold 81 C, then 76 C). `[tv2_plan]`: v2 35,946 examples, 6 roles, r=32 / 48.6 M trainable (v1: 6,480, 5 roles, r=16 / 24.3 M). `[ops_power_events]`: 1 blue screen, 1 thermal sleep, 6 lid standbys.

**Status:** kept.

**Children:**
- D012 (2026-10-07, kept): v1 laptop heat guard and caps. Rejected: running uncapped (21 forced hibernations at the 100 C limit, 27 -> 36.8 s/step).
- D097 (2026-10-16, kept): run_v2.ps1 sessions with a graceful stop flag, checkpoints every ~10 min, auto-resume. The data says "13 sessions so far"; see the note below.
- D111 (2026-10-16, kept): 35,946 rows, 2 epochs, 4,494 steps, r=32, ~40-50 h of GPU time. Rejected: the v1 size (too small for 6 roles x 21 window lengths).
- D123 (2026-10-17, kept): WSL networking off, GPU pause at 76 C, lid open, launch via WMI, battery and RAM guards. Rejected: defaults (a BSOD in vfpext.sys, thermal sleep, Modern Standby freezes, a dead supervisor).
- D124 (2026-10-18, kept): No GPU duty-cycle throttle (~42-45 s/step). The user chose this; the guard already handles heat.

**How to defend it:** The expected objection is "interrupted training corrupts results". Each stop is a checkpoint resume, and the dev-loss curve is continuous across sessions (5.22). Eight interruption causes were found, and each now has a guard. One unclean reboot (2026-10-17 20:10) has no recorded cause and fell between sessions, which is stated in the evidence notes.

Note: D097 says "13 sessions so far", while `[tv2_sessions]` has n=12.

---

### 5.29 Learn from the operator (G29)

**In one line:** Every operator approval or dismissal, and every automatic repair, is saved as future training data.

**What we chose:** Persist the prompt, raw output, repairs and approval, and export SFT positives and DPO pairs.

**What we rejected and why:** Collect labels later: that loses the free preference pairs. `[uc_human_in_loop]`

**Evidence:** `[uc_human_in_loop]` (folded ad_self_learning): the first approved incident produced 2 SFT positives and 1 DPO pair. A dismissal needs a note.

**Status:** kept.

**Children:** D047 (2026-10-14, kept): capture self-learning data from day one. Rejected: collecting labels later (it loses the policy-repair pairs that need no human labels).

**How to defend it:** The expected objection is "two examples is nothing". It is a pipeline proof, not a training result: the capture works end to end on the device, and each policy repair is automatically a (bad, repaired) preference pair with no labelling cost. No retraining from operator data has been done yet. Say so.

---

### 5.30 Private data, public evidence (G30)

**In one line:** Raw campus data, including room occupancy, never leaves the laptop. The website shows only aggregates and scores, encrypted behind a password.

**What we chose:** A laptop-first build order, private raw data, and a password-only encrypted website.

**What we rejected and why:**
- Publish datasets: room occupancy reveals people's presence. `[uc_coverage]`
- Cloudflare Access login: replaced by a password plus client-side encryption. `[tl_milestones]`

**Evidence:** `[uc_coverage]`: 174 sensors, 33.2 M readings. `[tl_milestones]`: Spec (17 Sep) -> NPU fine-tune (7 Oct) -> batched NPU daemon (16 Oct) -> v2 training (17 Oct+).

**Status:** kept.

**Children:**
- D001 (2026-10-01, kept): Prove the pipeline on the laptop, then port it to the board. Rejected: building the Android app first (nothing to validate against).
- D069 (2026-10-16, kept): Raw CSVs, splits and per-room occupancy never leave the laptop.
- D125 (2026-10-19, kept): A static site with a bcrypt-checked password, AES-256-GCM per file, vendored ECharts, and the deck kept in memory. Rejected: Cloudflare Access (the HANDBOOK 2.36 plan) and plots in the deck (all plots live on the site).

**How to defend it:** The expected objection is "if you cannot show the raw data, how can we verify?". Every chart links to its source file and script, and per-sample scores are published without the inputs. Raw data stays private because occupancy by room and time is personal data. It can be shown locally on request.

---

## 6. The sensors and the raw data

This section explains the "Raw data" page of the evidence website and every sensor behind it. All numbers come from `Website/data/raw/index.json` (generated 2026-10-19 by `Website/build/collect/rawdata.py`), the per-sensor analysis files `Website/data/raw/a/<sensor>.json`, the use-case files `Website/data/use_case/uc_*.json`, and the training code (`Code/smart-city-edge-agent/training/features.py`, `training/v2/*`, `training/RETRAIN_V2_SPEC.md`, `training/v2/HVAC_DATA.md`, `data/sft_v2/manifest.json`).

The data at a glance (from `index.json`, `totals`):

| Quantity | Value |
|---|---|
| Sensors | 174, in 8 domains |
| 5-min readings in 2025 | 33,217,982 |
| Months | 12 (1 Jan 2025 00:00 IST to 1 Jan 2026 00:00 IST) |
| Limit breaches (warning + critical) | 20,538, of which 6,923 critical |
| Real 4 h windows in the data | 2,589,199 |
| Windows used as bases for training/dev/test examples | 48,838 (v1: 7,980, v2: 40,858) |

| Domain (page label) | Sensors | Readings | Breaches (all / critical) | Windows used | Held out in v2 |
|---|---|---|---|---|---|
| Indoor air | 12 | 2,420,597 | 6,628 / 673 | 4,843 | 2 |
| Outdoor air | 10 | 1,385,747 | 3,656 / 126 | 4,151 | 1 |
| Water | 40 | 976,118 | 4,427 / 2,936 | 8,911 | 6 |
| Power | 11 | 591,238 | 3,313 / 1,433 | 8,996 | 2 |
| HVAC units | 87 | 26,328,340 | 1,802 / 1,504 | 7,399 | 13 |
| HVAC floors | 5 | 1,024,376 | 0 / 0 | 0 | 0 |
| Occupancy | 7 | 341,287 | 0 / 0 | 7,290 | 1 |
| Weather | 2 | 150,279 | 712 / 251 | 7,248 | 0 |
| **Total** | **174** | **33,217,982** | **20,538 / 6,923** | **48,838** | **25** |

The source is the cleaned IIIT-H smart-campus (SCRC) data for 2025. `uc_coverage.json` records the original files: 14 CSVs, 4.6 GB, about 37 M rows. A wireless-network file (`WN.csv`, 79 nodes) exists in the source but is not one of the 8 domains on the page.

### 6.0 How to use the Raw data page, and how its numbers are computed

#### What is on the page (top to bottom)

1. **Anchor numbers.** These are the four totals above: 174 sensors (every one browsable), 33.2 M 5-min readings in 2025, 20,538 limit breaches (each with its reason, 6,923 critical) and 48,838 real windows used as training bases (v1 7,980 and v2 40,858).
2. **Picker.**
   - **Domain tabs.** One tab per domain, with its sensor count: Indoor air 12, HVAC floors 5, HVAC units 87, Occupancy 7, Outdoor air 10, Power 11, Water 40, Weather 2. Each tab is drawn in its domain colour.
   - **Search box.** It filters all sensors, across every domain, by ID or description and shows the first 120 matches.
   - **Sensor list.** A small dot next to a sensor ID means the sensor is **held out** (see 6.1).
3. **Main chart for the selected sensor and metric.**
   - **Header.** The title is the sensor ID, plus a "held out · test only" chip when it applies. The subtitle gives the plain-language location, the metric and unit, the share of 2025 covered, and the limits. For example, "limits above 1000 / 1500" or "limits below 0.85 / 0.7". A metric without a fixed limit shows "no fixed limit".
   - **Metric tabs.** One tab per metric of the sensor, such as CO2 / Temperature / Humidity. Hovering a tab shows its coverage.
   - **Zoom buttons.**
     - **Year** shows the whole of 2025.
     - **Week** and **Day** show a 7-day or 1-day span. From the year view they centre on the latest breach of the metric; if there is none, they centre on the middle of the current view.
     - Mouse-wheel or pinch zoom and the slider under the chart also work.
4. **Notes and the "Used for training" legend.** The legend counts the training windows cut from this metric, by pattern. If no window was cut, it says "Held out: never used for training, only for testing." for held-out sensors and "No training window was cut from this metric." for the rest.
5. **Analysis panel.** It holds about ten small charts for the selected sensor and metric, each with an auto-generated one-line insight. They are listed below.
6. **Sankey diagram "From raw windows to training examples".** It shows how real windows flow into training examples (see 6.1).

#### The two time views

- **Year view (hourly).** The line is the **hourly mean**, drawn in the domain colour. The grey band behind it spans the **hourly minimum to maximum**, from the 12 five-minute readings of each hour. The tooltip shows "hour mean · min · max" in IST.
- **Day/week view (5-min).** When the visible span is 8.5 days or less, the page loads the monthly chunk files (`data/raw/c/<sensor>/2025-MM.json`) and replaces the band with the **raw 5-minute readings**. The note then says, for example, "5-min readings: N of M slots in view filled". Zooming out past about a week brings back the hourly band.
- Gaps (no reading) are drawn as breaks, not interpolated.

#### Overlays and colours

| Element | Colour | Meaning |
|---|---|---|
| Mean line | Domain colour: air (indoor and outdoor) `#7cc4f5` light blue, water `#2fc4d8` cyan, power `#f0d24b` yellow, weather `#f0903e` orange, occupancy `#f27bbd` pink, HVAC (units and floors) `#7ee8b8` mint | The reading (hourly mean or 5-min value) |
| Grey band | `rgba(196,198,204,0.16)` | Hourly min-max range (year view only) |
| Dashed amber line "warn N" | `#f2b83d` | Warning limit |
| Dashed red line "crit N" | `#f05a52` | Critical limit |
| Amber dot | `#f2b83d` | A warning breach, placed at the middle of the breach and at its peak value |
| Red dot | `#f05a52` | A critical breach |
| Light blue background, label "train" | `--split-train` (sky blue, 10% opacity) | January to August = training months |
| Light amber background, label "dev" | `--split-dev` (amber, 12%) | September and October = development (validation) months |
| Light violet background, label "test" | `--split-test` (violet, 14%) | November and December = test months |
| Lower lane, row "v1" (label in teal `#2fc9b4`) | bars coloured by pattern | Windows of this metric used in the v1 dataset |
| Lower lane, row "v2" (label in pink `#f27bbd`) | bars coloured by pattern | Windows of this metric used in the v2 dataset |

- **Usage lane bars.** Each bar runs from the window start to the window end. v1 windows are always 48 readings (4 h); v2 windows are 24 to 144 readings (2 to 12 h). Bars are coloured by **pattern**, with up to 16 palette colours given in order of frequency (grey after that), and the legend under the chart lists the patterns with their counts. A bar's tooltip shows the pattern, family, split and version (v1/v2), the start and end time, and the length in 5-min readings.
- **Breach dots.** Click a dot to open a **Breach** dialog. It shows a warning/critical chip, the generated reason sentence, the start and end time (IST), the peak value, and a "Zoom to it (5-min)" button. That button zooms to a view about one day wide, centred on the breach, with at least 3 h of padding on each side.
- **Shareable links.** The URL changes to `#/rawdata?s=<sensor>&m=<metric>`, so a specific view can be linked.
- **Default sensor.** On first load the page opens the indoor-air sensor with the highest "windows used + breaches".

#### The analysis panel (per sensor and metric)

These charts are computed in `rawdata.py` (`_analyse`). Each card has an insight sentence, and every chart can be expanded.

| Card | What it shows (exact computation) |
|---|---|
| Distribution | 30-bin histogram between the 1st and 99th percentile. The insight gives the median, the middle half (p25 to p75), the most common bin, any long tail (skew > 1 or < -1), and the percentage of readings past the warning limit. |
| By month | Box plots per month: whiskers p1 and p99, box p25 to p75, median line. A month needs at least 12 readings. The insight names the months with the highest and lowest median. |
| Hour of day × weekday | Heatmap of mean value by IST hour (0-23) and weekday (Mon-Sun). The insight gives the peak and low hour, their ratio, and weekend vs weekday in %. |
| Daily mean and 7-day rolling mean ± std | Daily means, the 7-day rolling mean, and a ±1 std band. The insight compares the last 30 days with the first 30 and names the most variable week. |
| Coverage per day | Share of the 288 five-minute slots filled each day. Bars are blue when at least 95% are filled, amber when partly filled, red when empty. The insight gives the % of slots filled, full days and empty days. |
| Breaches by month / Breach duration / Breach start hour | Breach counts by month, by duration bucket (<30 min, 30-60 min, 1-2 h, 2-6 h, 6-24 h, >24 h) and by start hour. The insight gives the % under 30 min, the top month, the usual start hour and the longest breach. |
| Autocorrelation of hourly means | Correlation of the hourly series with itself at lags of 1 to 72 h, with dashed markers at 24 h and 48 h. The insight gives "daily cycle explains X% of the variance" (variance of the hour-of-day profile divided by total variance) and r(24 h). It says "strong daily rhythm" when r(24 h) > 0.5 and "weak" when r(24 h) < 0.2. |
| Related sensors, building XX | The 3 sensors in the same building whose hourly means correlate most strongly (Pearson, by absolute value), when the two overlap by at least 14 days. Each is a link to that sensor. |

#### Room codes (occupancy privacy)

- **What the page shows.** Occupancy sensors appear **only as codes**: Room A to Room G, with sensor IDs `room-a` to `room-g`.
- **How codes are assigned.** `rawdata.py` sorts the occupancy CSV file names and gives them letters in that order.
- **Where the real mapping lives.** The code-to-real-ID mapping is written only to `Code/smart-city-edge-agent/data/series/_room_codes.json`, never into `Website/`.
- **When presenting.** Always say "Room E", never a real room or gateway ID.

#### How breaches are computed (`rawdata.py`, function `breaches`)

**Time base.**
- Every series is placed on a fixed grid of 5-min slots from 1 Jan 2025 00:00 IST, with 105,120 slots in the year.
- **Coverage** = filled slots ÷ 105,120. That is the "Coverage" column in the tables below.
- Occupancy values are turned into 0/1 at 0.5. HVAC "on" status is also rounded to 0/1 at 0.5.

**Ordinary metrics.** This covers indoor and outdoor air, water quality, tank level, power factor and weather.
1. A reading **breaches** when it is at or above the warning limit. For power factor, the only "low is bad" metric, it is at or below.
2. Consecutive breaching readings form a run. Two runs separated by a gap of **6 slots or fewer** (the next run starts at most 6 slots after the previous one ended, about 30 min) are **merged** into one breach. So a value that dips below the limit for under half an hour and comes back counts once.
3. The breach's **peak** is the highest reading in it (the lowest for power factor). The breach is **critical** if the peak reaches the critical limit, otherwise **warning**.
4. There is **no minimum duration**: a single 5-min reading at the warning limit is a breach. This is deliberate. The page shows the raw alert flood that a plain threshold system would produce.
5. **The reason sentence** reads, for example: "PM2.5 96.8127 ug/m3 above the 60 ug/m3 warning limit; 10 h 45 min from 01 Jan 00:00."
   - For air, water, power and weather it adds "Rule pattern (4 h window): <pattern>." This is the deterministic Mode-1 rule classifier (`features.rule_pattern`) applied to the 48 readings that end at the breach end, or 4 h after the breach start if that comes first.
   - The rule pattern needs at least 45 of the 48 readings, with both ends present; small gaps are linearly filled.

**pH is two-sided (fixed 2026-10-19).** pH has `dir="both"` in `features.py`. `rawdata.py` now checks both sides, with the same limits the dataset generator uses (`generate_dataset.status_of`): high warning >= 8.5, critical >= 9.0; low warning < 6.5, critical < 6.0. The pH chart shows all four dashed lines. Before this fix only the high side was counted (19,819 breaches in all; now 20,538).

**Water tank level.**
- `features.py` has no fixed limit for tank level, because tanks differ. Instead `rawdata.py` uses per-tank limits from `data/sft_v2/node_limits.json`, computed by `generate_v2.tank_limits` from **training months only** (Jan-Aug):
  - **warning ("high")** = 99th percentile of that tank's readings;
  - **critical ("overflow")** = maximum reading. If the two are equal, the critical limit is set one unit of the last decimal higher.
- So by construction about 1% of training-month readings are above the warning line.
- The direction is "high": the concern on the page is overfilling or overflow.

**HVAC units (per indoor AC unit).** The rule is different here, because idle units read 34-45 C in still air: the thermistor sits in the ceiling unit, not in the room (`HVAC_DATA.md`, quirk 1).
- Only readings **while the AC is on** count.
- **Too hot:** room temperature at or above 30 C while on, lasting **at least 6 readings (30 min)**. Gaps of 2 slots or fewer are merged. The breach is **critical** if the peak reaches 34 C. The reason reads, for example, "Room 41.7 C while the AC runs, above the 34 C critical limit for 2 h 0 min; peak ...".
- **Overcooling:** while on, room temperature below min(setpoint − 4 C, 24 C) for at least 30 min. This is always a **warning**. The 4 C is `band_lo` 3 C + 1.

**HVAC floors (`AC-KH..` aggregates).** These have no limits at all (warn/crit set to None for `AC-` nodes), so they show 0 breaches.

**No fixed limit.** Power (kW), water flow, occupancy, HVAC setpoint and HVAC on/off have no fixed limit. In `features.py` they are "baseline-relative only": the agent judges them by shape (spike, step, drift...), not by a number. They therefore show no limit lines and no breaches.

#### Persistence: which breaches deserve attention

`rawdata.py` itself applies no persistence filter, except the 30 min rule for HVAC units. The use-case chart `uc_breaches_need_action.json` (`use_case.py`) applies the **app's event gate**: a breach must last **at least 8 consecutive readings**, counted as end slot − start slot + 1 of the merged run. On 5-min data that is 40 min; in the demo clock it is about 16 s.

| Domain | All breaches | Critical | Lasting ≥ 8 readings | Critical and lasting |
|---|---|---|---|---|
| Indoor air | 6,628 | 673 | 3,309 | 262 |
| Water | 4,427 | 2,936 | 116 | 17 |
| Outdoor air | 3,656 | 126 | 1,971 | 119 |
| Power | 3,313 | 1,433 | 199 | 157 |
| HVAC units | 1,802 | 1,504 | 1,676 | 1,415 |
| Weather | 712 | 251 | 496 | 220 |
| **Total** | **20,538** | **6,923** | **7,767** | **2,190** |

The claim on the website reads: "20,538 breaches -> 7,767 persistent -> 2,190 persistent and critical". Water and power lose most of their breaches under the gate, because their breaches are mostly single-reading blips (see 6.4 and 6.5).

#### Breaches per month (all / critical), from `uc_breaches_monthly.json`

| Domain | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Indoor air | 469/10 | 366/60 | 496/93 | 601/112 | 683/74 | 482/44 | 700/61 | 520/10 | 669/57 | 795/82 | 497/55 | 350/15 |
| Water | 142/72 | 189/58 | 154/25 | 38/22 | 175/43 | 622/344 | 382/201 | 321/154 | 328/258 | 653/593 | 441/410 | 263/115 |
| Outdoor air | 635/36 | 658/25 | 642/8 | 269/2 | 174/4 | 100/2 | 83/0 | 88/5 | 90/1 | 156/3 | 295/7 | 466/33 |
| Power | 92/27 | 213/52 | 231/86 | 124/70 | 368/102 | 327/121 | 295/119 | 342/139 | 338/127 | 336/164 | 322/206 | 325/220 |
| HVAC units | 37/22 | 181/95 | 201/134 | 266/225 | 214/198 | 168/166 | 157/140 | 143/136 | 135/132 | 156/153 | 111/76 | 33/27 |
| Weather | 13/0 | 0/0 | 0/0 | 0/0 | 20/4 | 78/3 | 57/16 | 239/113 | 211/99 | 86/14 | 6/2 | 2/0 |

#### The table columns used in every domain section below

- **Warn / Crit:** the limits exactly as the page uses them ("none" = no fixed limit; `<=` marks power factor, where low is bad).
- **Coverage:** filled 5-min slots ÷ 105,120.
- **Months with data:** months that have at least one reading of any metric of the sensor.
- **Breaches (warn / crit):** breach counts for that metric over 2025.
- **Windows used:** number of v1 + v2 examples (train, dev and test together) whose base window came from this sensor and metric.
- **Held out (v2):** the sensor was excluded from v2 training and appears only in the v2 test set.

### 6.1 How the sensor data was used in training

The model is never trained on raw readings directly. Each training example is **one window of one metric of one sensor**, turned into a prompt by `features.py`: the series as 10-min means, statistics, and evidence lines E1 to E8 (v2 adds E9, a 12 h summary, and E10, recent episodes). The answer is a JSON label. The labels come from **known injections or deterministic rules**, never from hand labelling. The page's sankey footnote says: "Only calm real windows became bases; every label comes from a known injection or rule."

#### Splits by month (both versions)

| Split | Months (2025, IST) | Page shading |
|---|---|---|
| Train | January to August | light blue "train" |
| Dev | September to October | light amber "dev" |
| Test | November to December | light violet "test" |

- **v1** assigns a window to a split by the month of its **end** (`split_of`: month ≤ 8 train, ≤ 10 dev, else test).
- **v2** requires both the window end **and** the start of its 12 h history to fall in the split.
- So test windows never overlap training months.

#### v1 dataset (`data/sft/`, 7,980 examples)

- **Roles.** Five roles: air_quality (indoor and outdoor air together), water, power, occupancy, weather.
- **Window.** 48 readings × 5 min = 4 h.
- **Quotas.** 1,300 train / 120 dev / 180 test per role, rounded down to a multiple of the pattern count. Actual counts: **6,480 train, 600 dev, 900 test** (1,296 / 120 / 180 per role).
- **Base windows** (`generate_dataset.py`) for continuous metrics:
  - Windows are taken at an hourly stride. A window needs at least 45 of 48 readings (weather: at least 24), with the first and last present; gaps are linearly filled.
  - A window becomes a base only if it is **calm**: |slope| × 4 h ≤ 3·s0, range ≤ 8·s0, longest flat run < 10, and noise > 0. Here s0 = max(metric floor, 1.5 × noise).
  - All-zero windows are kept separately and partly used as "flatline" examples.
- **Injection.** One of 12 patterns is added to a calm base: stable, spike, dip, gradual_increase, gradual_decrease, step_increase, step_decrease, exponential_increase, oscillation, throttling, flatline, erratic.
  - Amplitude A = s0 × U(4, 10); spikes and dips use U(5, 12).
  - Patterns are balanced (quota ÷ 12 each).
- **Occupancy.** Real 0/1 windows at a 30-min stride, labelled by rule into 6 patterns: vacant, occupied, arrival, departure, intermittent, off_hours_presence. Quota ÷ 6 each.
- **Held-out sensors.** v1 has none: the split is by month only.

#### v2 dataset (`data/sft_v2/`, manifest v2.0, seed 2026, created 2026-10-17, 40,858 examples)

**Size.** **35,946 train, 1,947 dev, 2,965 test** (9 duplicates dropped in train).

**Per-role quota and actual counts:**

| Role | Train quota (actual) | Dev quota (actual) | Test quota (actual) |
|---|---|---|---|
| air_quality | 6,500 (6,498) | 360 (360) | 540 (540) |
| water | 6,500 (6,455) | 360 (355) | 540 (505) |
| power | 6,500 (6,500) | 360 (360) | 540 (540) |
| weather | 5,000 (4,999) | 280 (233) | 420 (420) |
| occupancy | 5,000 (4,995) | 280 (279) | 420 (420) |
| hvac (new) | 6,500 (6,499) | 360 (360) | 540 (540) |

**Bases and window lengths.**
- A base is a **real** window from `data/series`, with up to 144 readings (12 h) of history.
- The agent sees the last N readings, where N is 24 to 144 in steps of 6 (2 to 12 h).
- Sampling weights: N = 48 (4 h) 25%, N = 96 (8 h) 20%, N = 144 (12 h) 20%; the remaining 35% is spread uniformly over the other lengths.
- This matches the run-time policy in the spec: early alert at 4 h, refinement at 8 h for warnings and 12 h for critical or fault.

**Event age (onset).**
- 35% of events start 4 to 12 readings (20 to 60 min) before the window end.
- The rest start uniformly anywhere from 3 readings before the end back to the window start.
- Why: the v1 study found pattern accuracy was 42% at 40 min but 88% at 3 h, because v1 placed events 1 to 3 h into the window.

**Event size.**
- 1.5 to 12 × noise (spec #11).
- With probability 0.20 (0.15 in some families) the size is a "small" uniform 1.5 to 3 ×. Otherwise it is log-uniform between 3 (or 4) and 12 ×.
- Below about 3 × the label stays stable/normal with an observation, so the model learns the boundary.

**Family mix per continuous role** (`MIX`): event 0.40, fault 0.12, routine 0.10, stable 0.08, compound 0.06, real_routine 0.06, water_fill 0.05, old_shift 0.05, long_drift 0.05, recurring 0.04, real_longrange 0.02, zero_idle 0.02.

**Actual train family counts:**

| Family | Train | Dev | Test | What it is |
|---|---|---|---|---|
| event | 10,294 | 614 | 862 | v1's 10 event patterns injected at any age and size |
| hvac | 6,499 | 360 | 540 | per-unit HVAC windows labelled by `hvac.py` rules |
| occupancy | 4,995 | 279 | 420 | real 0/1 windows plus edited top-ups; flapping = sensor_fault |
| fault | 3,033 | 168 | 252 | injected sensor faults: stuck, bias, calib_drift, noise_increase, dropout, saturation, quantised (weights 3 / 1.5 / 1 / 2 / 1.5 / 1 / 1.5) |
| stable | 2,023 | 109 | 167 | calm base, normal |
| routine | 1,959 | 109 | 162 | **synthetic hard negatives** (normal routines that look like trouble) |
| compound | 1,516 | 74 | 120 | dominant pattern plus a second feature |
| real_routine | 1,513 | 71 | 98 | **real** windows whose shape matches a routine rule (hard negatives from real data) |
| old_shift | 1,265 | 54 | 94 | level shift that happened earlier in the 12 h history |
| long_drift | 1,265 | 55 | 102 | slow drift over the history |
| recurring | 509 | 23 | 62 | recurring small spikes (spike / normal, cites E10; power excluded) |
| real_longrange | 506 | 17 | 39 | real calm windows with a 12 h (E9) finding |
| water_fill | 310 | 7 | 26 | abnormal tank fills: overflow_fill, valve_stuck (fill ≥ 2 × usual), night_refills |
| zero_idle | 259 | 7 | 21 | all-zero idle windows |

**Hard negatives (spec #10, `ROUTINES`).** These are labelled normal, to cut the 31% false-alarm rate that v1 showed on calm data.
- Water level and flow: refill_fast, refill_slow, drain_day, pump_cycle, short_cycle.
- Power kW (not the solar/LT `SL-` meters): load_cycle, startup, shutdown.
- Air: co2_occupancy and co2_decay (CO2), hvac_cycle (indoor temperature), outdoor_pm (outdoor PM2.5/PM10).
- Weather: no synthetic routine; its daily cycles come in through real_routine.

**Held-out sensors (spec #21).**
- **Rule.** About 15% of the sensors in each role: round(0.15 × n), and at least 1 if the role has at least 4 sensors. They are chosen by a seeded hash among sensors with at least 2,000 test-month window ends.
- **Use.** They are **never used in v2 training or dev**. They appear only in the v2 test set, tagged "unseen". About 35% of test examples come from held-out sensors (60% for water, whose test-month data is thin).
- **Total.** 25 sensors are held out:
  - Indoor air (2): SR-AQ-KH95-00, SR-AQ-TH04-00.
  - Outdoor air (1): AQ-VN90-00.
  - Power (2): SR-EM-KH04-01, SR-EM-KH04-02.
  - Water (6): WM-WF-KH95-40, WM-WF-KH98-40, WM-WF-PH03-01, WM-WF-PH03-02, WM-WF-PH04-70, WM-WF-VN04-70.
  - Occupancy (1): Room E.
  - Weather (0): only 2 stations exist, so weather is tested on seen stations only (decision D8, a stated limit).
  - HVAC units (13): SR-AC-KH00-00, KH00-02, KH01-03, KH01-10, KH01-19, KH02-09, KH02-17, KH02-18, KH03-02, KH03-05, KH03-07, KH03-21, KH95-01.
- **Important nuance.** "Held out" is a **v2** property. v1 had no held-out sensors, so some of these sensors do have **v1** training windows. For example, SR-EM-KH04-01 has 321 v1-train windows and 189 v2-test windows; Room E has 386 v1-train and 155 v2-test windows. In v2 every one of their windows is a test window. The page's "held out · test only" chip refers to v2.

**From real windows to examples (the sankey on the page).**
- **Real windows.** The page counts every real 4 h window at an hourly stride whose first and last readings exist, for every metric except the HVAC floor aggregates: **2,589,199**.
- **Used.** Of these, **48,838** (1.9%) were used as bases for v1 or v2 examples. The rest are "Not used", which is left out of the drawn sankey.
- **Groups.** Used windows flow into these groups (v1 + v2 together):

| Group | Examples | Train | Dev | Test |
|---|---|---|---|---|
| Injected pattern (v1 injected; v2 event, compound, recurring, old_shift, long_drift) | 22,761 | 19,601 | 1,260 | 1,900 |
| HVAC rule-labelled | 7,399 | 6,499 | 360 | 540 |
| Real occupancy | 7,290 | 6,291 | 399 | 600 |
| Routine (routine, real_routine, water_fill) | 4,255 | 3,782 | 187 | 286 |
| Calm, untouched (v1/v2 stable, real_longrange, zero_idle) | 3,680 | 3,220 | 173 | 287 |
| Injected fault | 3,453 | 3,033 | 168 | 252 |
| **Total** | **48,838** | **42,426** | **2,547** | **3,865** |

**Teaching point.** The training set is mostly real campus data with a known, controlled change added on top, plus real windows labelled by transparent rules. That is why every label can be traced and checked.

---

### 6.2 Indoor air (12 sensors, `SR-AQ-*`)

**What it measures.**
- **Sensors.** Wall-mounted room sensors inside buildings KH, KN, TH and VN. Every sensor has temperature (C) and relative humidity (%). Nine also report CO2 (ppm) and four report PM2.5 (ug/m3).
- **Node ID format.** `SR-AQ-<building><level>-<sensor>`, for example SR-AQ-KH03-02 = KH building, level 03, indoor air sensor 02. Level codes such as 90, 95, 96 and 98 are copied from the source node IDs and shown unchanged. Their physical meaning (for example, roof or plant room) is not documented in these files.
- **Agent.** Indoor air is handled by the **Air Quality agent** (role `air_quality`), the same agent as outdoor air.

| Node | Metric | Unit | Warn | Crit | Coverage | Months with data | Breaches (warn / crit) | Windows used | Held out (v2) |
|---|---|---|---|---|---|---|---|---|---|
| SR-AQ-KH00-01 | CO2 | ppm | >= 1000 | >= 1500 | 43.4% | 1-7 | 140 / 0 | 312 |  |
| SR-AQ-KH00-01 | Temperature | C | >= 30 | >= 34 | 43.4% | 1-7 | 240 / 3 | 232 |  |
| SR-AQ-KH00-01 | Humidity | % | >= 70 | >= 85 | 43.4% | 1-7 | 7 / 0 | 235 |  |
| SR-AQ-KH00-02 | CO2 | ppm | >= 1000 | >= 1500 | 6.1% | 1-12 | 0 / 0 | 3 |  |
| SR-AQ-KH00-02 | Temperature | C | >= 30 | >= 34 | 99.0% | 1-12 | 353 / 27 | 61 |  |
| SR-AQ-KH00-02 | Humidity | % | >= 70 | >= 85 | 99.0% | 1-12 | 0 / 0 | 252 |  |
| SR-AQ-KH03-00 | CO2 | ppm | >= 1000 | >= 1500 | 0.2% | 1-12 | 0 / 0 | 0 |  |
| SR-AQ-KH03-00 | Temperature | C | >= 30 | >= 34 | 1.4% | 1-12 | 828 / 341 | 0 |  |
| SR-AQ-KH03-00 | Humidity | % | >= 70 | >= 85 | 1.4% | 1-12 | 0 / 0 | 0 |  |
| SR-AQ-KH03-01 | Temperature | C | >= 30 | >= 34 | 85.9% | 1-12 | 597 / 0 | 81 |  |
| SR-AQ-KH03-01 | Humidity | % | >= 70 | >= 85 | 85.9% | 1-12 | 47 / 0 | 211 |  |
| SR-AQ-KH03-02 | Temperature | C | >= 30 | >= 34 | 99.9% | 1-12 | 815 / 1 | 49 |  |
| SR-AQ-KH03-02 | Humidity | % | >= 70 | >= 85 | 99.9% | 1-12 | 8 / 0 | 320 |  |
| SR-AQ-KH03-03 | CO2 | ppm | >= 1000 | >= 1500 | 86.0% | 1-12 | 0 / 0 | 332 |  |
| SR-AQ-KH03-03 | Temperature | C | >= 30 | >= 34 | 86.2% | 1-12 | 254 / 0 | 45 |  |
| SR-AQ-KH03-03 | Humidity | % | >= 70 | >= 85 | 86.2% | 1-12 | 84 / 0 | 224 |  |
| SR-AQ-KH95-00 | CO2 | ppm | >= 1000 | >= 1500 | 61.9% | 1-12 | 0 / 0 | 64 | yes |
| SR-AQ-KH95-00 | Temperature | C | >= 30 | >= 34 | 78.0% | 1-12 | 129 / 0 | 21 | yes |
| SR-AQ-KH95-00 | Humidity | % | >= 70 | >= 85 | 78.0% | 1-12 | 97 / 2 | 98 | yes |
| SR-AQ-KH95-03 | Temperature | C | >= 30 | >= 34 | 1.5% | 1-12 | 20 / 0 | 0 |  |
| SR-AQ-KH95-03 | Humidity | % | >= 70 | >= 85 | 1.5% | 1-12 | 583 / 0 | 0 |  |
| SR-AQ-KN00-00 | CO2 | ppm | >= 1000 | >= 1500 | 66.4% | 3-12 | 1 / 0 | 342 |  |
| SR-AQ-KN00-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 66.4% | 3-12 | 0 / 0 | 220 |  |
| SR-AQ-KN00-00 | Temperature | C | >= 30 | >= 34 | 66.4% | 3-12 | 164 / 14 | 8 |  |
| SR-AQ-KN00-00 | Humidity | % | >= 70 | >= 85 | 66.4% | 3-12 | 85 / 6 | 162 |  |
| SR-AQ-TH04-00 | CO2 | ppm | >= 1000 | >= 1500 | 61.6% | 1-7,9-12 | 185 / 117 | 69 | yes |
| SR-AQ-TH04-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 61.6% | 1-7,9-12 | 59 / 75 | 28 | yes |
| SR-AQ-TH04-00 | Temperature | C | >= 30 | >= 34 | 61.6% | 1-7,9-12 | 127 / 0 | 1 | yes |
| SR-AQ-TH04-00 | Humidity | % | >= 70 | >= 85 | 61.6% | 1-7,9-12 | 59 / 0 | 23 | yes |
| SR-AQ-TH04-01 | CO2 | ppm | >= 1000 | >= 1500 | 77.1% | 1-12 | 119 / 64 | 419 |  |
| SR-AQ-TH04-01 | PM2.5 | ug/m3 | >= 60 | >= 120 | 77.1% | 1-12 | 0 / 0 | 108 |  |
| SR-AQ-TH04-01 | Temperature | C | >= 30 | >= 34 | 77.1% | 1-12 | 230 / 16 | 28 |  |
| SR-AQ-TH04-01 | Humidity | % | >= 70 | >= 85 | 77.1% | 1-12 | 35 / 0 | 149 |  |
| SR-AQ-VN90-00 | CO2 | ppm | >= 1000 | >= 1500 | 73.6% | 3-12 | 100 / 7 | 293 |  |
| SR-AQ-VN90-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 73.5% | 3-12 | 89 / 0 | 240 |  |
| SR-AQ-VN90-00 | Temperature | C | >= 30 | >= 34 | 73.6% | 3-12 | 500 / 0 | 44 |  |
| SR-AQ-VN90-00 | Humidity | % | >= 70 | >= 85 | 73.6% | 3-12 | 0 / 0 | 169 |  |

**Totals by metric:**

| Metric | Sensors | Warn breaches | Crit breaches | Windows used |
|---|---|---|---|---|
| CO2 | 9 | 545 | 188 | 1,834 |
| Temperature | 12 | 4,257 | 402 | 570 |
| Humidity | 12 | 1,005 | 8 | 1,843 |
| PM2.5 | 4 | 148 | 75 | 596 |

**Normal range** (medians and middle half from the page's Distribution cards):
- **CO2:** about 414-506 ppm median. Examples: SR-AQ-KH03-03 median 414 ppm (middle half 358-478); SR-AQ-KN00-00 506 ppm; SR-AQ-VN90-00 480 ppm.
- **Indoor PM2.5:** median 6.0-11.9 ug/m3 on the sensors checked (TH04-01, KN00-00, VN90-00).
- **Temperature:** median 27.8-30.2 C on most rooms. SR-AQ-KH00-02 (31.2 C) and SR-AQ-KH03-00 (32.5 C) run hotter. SR-AQ-KN00-00 has a median of 30.2 C, with 55.6% of readings past 30 C.
- **Humidity:** median 43.8-55.9% on the sensors checked.

**Thresholds and why.**
- **The values** (`features.py`, `METRICS`):
  - CO2: warn 1000 / crit 1500 ppm.
  - PM2.5: warn 60 / crit 120 ug/m3.
  - Temperature: warn 30 / crit 34 C.
  - Humidity: warn 70 / crit 85%.
  - All are "high is bad".
- **What `features.py` says.** It states no reason for these values. The project's planning documents do cite sources:
  - `PRD.md` lists CO2 1000/1500 ppm as "ASHRAE 62.1-2019", and `plan.md` says "CO2 1000/1500 ppm (ASHRAE)".
  - The PRD drafts had different values for the others (indoor PM2.5 25/75 "WHO AQG 2021", temperature 28/35 "ASHRAE 55", humidity 70/80 "ASHRAE 55 — mold risk above 70%"). The final code uses the values above.
- **General background (not stated in the code).**
  - 1000 ppm CO2 is the widely used indoor ventilation indicator associated with ASHRAE 62 (roughly 700 ppm above outdoor air).
  - 60 ug/m3 PM2.5 equals India's 24-hour NAAQS limit (CPCB).
  - Relative humidity above about 70% is commonly cited as a mould risk.
  - No standard sets 30/34 C. These are project choices for a hot-climate campus without full air conditioning.
- **Floors.** The noise floors used to scale patterns are CO2 40 ppm, PM2.5 6.0, temperature 0.6 C, humidity 3.0%.

**What a breach means operationally.**
- **CO2:** too many people for the ventilation, so open windows or check the fresh-air supply. The agent's causes include `occupancy_load` and `ventilation_insufficient`.
- **Indoor PM2.5:** an indoor source, or outdoor smoke and dust getting in.
- **Temperature:** a cooling issue (`hvac_cooling_issue`).
- **Humidity:** `humidity_control_issue`.
- **What the agent may do.** The agent can only recommend an inspection, such as `inspect_ventilation` or `inspect_hvac`. It never actuates anything.

**Typical patterns.**
- **Daily cycles are strong.** CO2 on SR-AQ-KH03-03 peaks at 16:00 (500 ppm) and is lowest at 08:00 (346 ppm); the daily cycle explains 32% of its variance, and weekends are 8% lower. Humidity peaks around 07:00 and dips mid-afternoon on most rooms, with r(24 h) between 0.74 and 0.92.
- **Season.**
  - Temperature is highest in April-July (SR-AQ-KN00-00 April median 34.45 C, SR-AQ-TH04-01 May 31.5 C) and lowest in December.
  - Humidity is highest in August-September (monsoon) and lowest in March or December.
- **Monthly breaches.** Indoor-air breaches run 350-795 a month, highest in October (795) and July (700). Critical breaches peak in April (112).
- **Long episodes.** Temperature breaches can last days: SR-AQ-KN00-00 has one of 360 h 20 min from 25 March, SR-AQ-TH04-01 one of 97 h 25 min.
- **Persistence.** Half of the indoor-air breaches (3,309 of 6,628) last at least 40 min.
- **Data caution: low-coverage sensors.**
  - SR-AQ-KH03-00 has 1,169 temperature breaches from only 1.4% coverage. Its median is 32.5 C, with 89.9% of readings over 30 C and 98% of breaches under 30 min.
  - SR-AQ-KH95-03 has 583 humidity breaches at 1.5% coverage.
  - These two sensors contribute many breaches but **no training windows** (too sparse for 4 h bases).
- **Data caution: CO2 coverage.** CO2 on SR-AQ-KH00-02 and SR-AQ-KH03-00 is almost empty (6.1% and 0.2%).

**Training use.**
- **Windows.** 4,843 windows (v1 1,004, v2 3,839), mostly CO2 and humidity bases. Temperature has fewer (570), because it is often not "calm" or is above the limit.
- **Held out.** SR-AQ-KH95-00 and SR-AQ-TH04-00 are held out in v2.
- **Hard negatives.** co2_occupancy and co2_decay on CO2, hvac_cycle on indoor temperature.

### 6.3 Outdoor air (10 stations, `AQ-*`)

**What it measures.**
- **Sensors.** Outdoor particulate-matter stations at 10 building sites, measuring PM2.5 and PM10 in ug/m3: fine and coarse dust and smoke. PM2.5 is particles under 2.5 micrometres, which reach deep into the lungs.
- **Agent.** Also handled by the Air Quality agent.

| Node | Metric | Unit | Warn | Crit | Coverage | Months with data | Breaches (warn / crit) | Windows used | Held out (v2) |
|---|---|---|---|---|---|---|---|---|---|
| AQ-AN00-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 97.3% | 1-12 | 193 / 0 | 299 |  |
| AQ-AN00-00 | PM10 | ug/m3 | >= 100 | >= 250 | 97.1% | 1-12 | 116 / 0 | 342 |  |
| AQ-FG00-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 0.0% | 2,12 | 2 / 0 | 0 |  |
| AQ-FG00-00 | PM10 | ug/m3 | >= 100 | >= 250 | 0.0% | 2,12 | 0 / 0 | 0 |  |
| AQ-KN00-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 82.0% | 1-12 | 214 / 25 | 307 |  |
| AQ-KN00-00 | PM10 | ug/m3 | >= 100 | >= 250 | 82.0% | 1-12 | 159 / 0 | 299 |  |
| AQ-MG00-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 65.5% | 1-7,9-10,12 | 331 / 10 | 261 |  |
| AQ-MG00-00 | PM10 | ug/m3 | >= 100 | >= 250 | 65.5% | 1-7,9-10,12 | 131 / 0 | 275 |  |
| AQ-PH03-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 51.9% | 1-7,9-12 | 172 / 0 | 211 |  |
| AQ-PH03-00 | PM10 | ug/m3 | >= 100 | >= 250 | 52.1% | 1-7,9-12 | 88 / 0 | 210 |  |
| AQ-PH04-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 87.0% | 1-12 | 397 / 34 | 208 |  |
| AQ-PH04-00 | PM10 | ug/m3 | >= 100 | >= 250 | 87.0% | 1-12 | 284 / 0 | 238 |  |
| AQ-PL00-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 94.9% | 1-12 | 258 / 0 | 273 |  |
| AQ-PL00-00 | PM10 | ug/m3 | >= 100 | >= 250 | 94.9% | 1-12 | 148 / 0 | 346 |  |
| AQ-SN00-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 49.1% | 2-8,12 | 218 / 23 | 220 |  |
| AQ-SN00-00 | PM10 | ug/m3 | >= 100 | >= 250 | 49.3% | 2-8,12 | 155 / 0 | 223 |  |
| AQ-TH00-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 53.1% | 1-7,11-12 | 94 / 34 | 143 |  |
| AQ-TH00-00 | PM10 | ug/m3 | >= 100 | >= 250 | 53.1% | 1-7,11-12 | 173 / 0 | 175 |  |
| AQ-VN90-00 | PM2.5 | ug/m3 | >= 60 | >= 120 | 78.2% | 1-12 | 245 / 0 | 59 | yes |
| AQ-VN90-00 | PM10 | ug/m3 | >= 100 | >= 250 | 78.2% | 1-12 | 152 / 0 | 62 | yes |

**Totals.**
- PM2.5: 2,124 warning + 126 critical breaches, 1,981 windows used.
- PM10: 1,406 warning + 0 critical breaches, 2,170 windows used.

**Normal range.**
- **PM2.5:** median 17.7 ug/m3 at AQ-AN00-00 (middle half 7.8-34.4) and 33.9 at AQ-PH04-00 (middle half 16.8-55.7).
- **PM10:** median 25.4 ug/m3 at AQ-AN00-00 and 43.8 at AQ-PH04-00.
- **Long upper tail.** Distributions have a long upper tail: AQ-PH04-00 PM2.5 has a p95 of 93.5 ug/m3.

**Thresholds and why.**
- **The values** (`features.py`): PM2.5 warn 60 / crit 120 ug/m3; PM10 warn 100 / crit 250 ug/m3. Floors are 6.0 and 10.0.
- **What the code says.** No reason is stated. `plan.md` mentions "PM2.5 indoor/outdoor (WHO/NAAQS India)" as the intended source.
- **General background.** India's NAAQS 24-hour limits (CPCB) are 60 ug/m3 for PM2.5 and 100 ug/m3 for PM10. In India's AQI bands, PM2.5 above 120 ug/m3 is "very poor" and PM10 above 250 ug/m3 is "poor". That is consistent with the 120 and 250 critical limits, but the code does not say this.

**What a breach means operationally.**
- **Polluted outside air.** Keep windows shut, limit outdoor activity and ventilation intake.
- **Cross-domain context.** It also explains indoor PM rises (`outdoor_pollution_ingress`).
- **Facilities cannot fix the source.** A breach is information and advice, not a fault.

**Typical patterns.**
- **Strong winter season.** Monthly breaches are 635 / 658 / 642 in January to March and 466 in December, falling to 83-100 in June to September during the monsoon. Rain washes particulates out.
- **Monthly medians.** AQ-AN00-00 PM2.5 is highest in January (61.63 ug/m3) and lowest in August (5.96).
- **Daily cycle.** PM peaks in early morning, around 06:00-07:00, when the boundary layer is low and traffic starts. It is lowest around 14:00-16:00: AQ-PH04-00 PM2.5 is 49.2 at 06:00 vs 29.8 at 14:00 (1.7×). r(24 h) is 0.73-0.79.
- **Long episodes.** Winter episodes can last days: AQ-PH04-00 has 110 h 15 min from 15 January, AQ-TH00-00 150 h 30 min from 11 January.
- **Persistence.** 1,971 of 3,656 breaches last at least 40 min.
- **Data caution.** AQ-FG00-00 has only 9 readings in the year (0.0% coverage) and was never used.

**Training use.**
- **Windows.** 4,151 windows (v1 592, v2 3,559).
- **Held out.** AQ-VN90-00 is held out in v2.
- **Hard negative.** The "outdoor_pm" routine (normal daily PM cycle) applies to these stations.

### 6.4 Water (40 sensors: 7 quality, 24 flow, 9 tank level)

**What it measures.**
- **Water quality (`WM-WD-*`).** TDS (total dissolved solids, ppm) on 7 sensors and pH on 3. These measure how much is dissolved in the water and its acidity.
- **Water flow (`WM-WF-*`).** Flow in m3/h through 24 pipe meters.
- **Tank level (`WM-WL-*`).** How full 9 storage tanks are. The unit is recorded only as "level" (the source does not say cm or %), and each tank has its own scale.
- **Agent.** All three types are handled by the **Water agent**.

**Water quality:**

| Node | Metric | Unit | Warn | Crit | Coverage | Months with data | Breaches (warn / crit) | Windows used | Held out (v2) |
|---|---|---|---|---|---|---|---|---|---|
| WM-WD-KH04-00 | TDS | ppm | >= 500 | >= 1000 | 3.4% | 6-12 | 0 / 0 | 0 |  |
| WM-WD-KH95-00 | TDS | ppm | >= 500 | >= 1000 | 6.5% | 1-9,11-12 | 0 / 0 | 0 |  |
| WM-WD-KH96-00 | TDS | ppm | >= 500 | >= 1000 | 3.4% | 1-12 | 0 / 0 | 0 |  |
| WM-WD-KH96-00 | pH | pH | >= 8.5 or < 6.5 | >= 9 or < 6 | 3.3% | 1-12 | 644 / 662 | 0 |  |
| WM-WD-KH96-01 | TDS | ppm | >= 500 | >= 1000 | 0.5% | 6-12 | 0 / 0 | 0 |  |
| WM-WD-KH96-01 | pH | pH | >= 8.5 or < 6.5 | >= 9 or < 6 | 1.3% | 6-12 | 0 / 1276 | 0 |  |
| WM-WD-KH96-02 | TDS | ppm | >= 500 | >= 1000 | 1.0% | 6-12 | 148 / 0 | 0 |  |
| WM-WD-KH98-00 | TDS | ppm | >= 500 | >= 1000 | 0.6% | 6-7,9-12 | 0 / 0 | 0 |  |
| WM-WD-KH98-00 | pH | pH | >= 8.5 or < 6.5 | >= 9 or < 6 | 0.9% | 6-7,9-12 | 0 / 965 | 0 |  |
| WM-WD-PR00-00 | TDS | ppm | >= 500 | >= 1000 | 2.6% | 1-3,5-7,11-12 | 2 / 0 | 0 |  |

**Tank level:**

| Node | Metric | Unit | Warn | Crit | Coverage | Months with data | Breaches (warn / crit) | Windows used | Held out (v2) |
|---|---|---|---|---|---|---|---|---|---|
| WM-WL-AN00-00 | Tank level | level | >= 75 | >= 87 | 26.6% | 2-3,5-9 | 161 / 1 | 973 |  |
| WM-WL-BK00-00 | Tank level | level | >= 206 | >= 222 | 43.1% | 1-3,5-9 | 174 / 12 | 1553 |  |
| WM-WL-BK00-02 | Tank level | level | >= 78 | >= 88 | 7.8% | 1 | 3 / 1 | 256 |  |
| WM-WL-KH00-00 | Tank level | level | >= 83 | >= 95 | 36.8% | 1-3,5-8,11 | 10 / 1 | 1443 |  |
| WM-WL-KH98-00 | Tank level | level | >= 186.5 | >= 235 | 19.8% | 1-3,5-6,8 | 16 / 1 | 614 |  |
| WM-WL-PH03-00 | Tank level | level | >= 209 | >= 252 | 16.3% | 1-3,5-6 | 8 / 1 | 349 |  |
| WM-WL-PH03-01 | Tank level | level | >= 422 | >= 448 | 37.3% | 1-3,5-9 | 266 / 1 | 1799 |  |
| WM-WL-PL00-00 | Tank level | level | >= 110.5 | >= 126 | 24.0% | 2-3,5-7 | 17 / 8 | 247 |  |
| WM-WL-VN00-00 | Tank level | level | >= 85 | >= 101 | 16.2% | 1-3,5 | 42 / 7 | 1039 |  |

**Water flow** (no fixed limit, so 0 breaches on every meter):

| Node | Coverage | Months with data | Windows used | Held out (v2) |
|---|---|---|---|---|
| WM-WF-BB04-70 | 12.5% | 1-2,6-7,10 | 28 |  |
| WM-WF-BB04-71 | 53.8% | 1-9 | 0 |  |
| WM-WF-KB04-70 | 45.8% | 1-6 | 68 |  |
| WM-WF-KB04-71 | 64.5% | 1-8 | 41 |  |
| WM-WF-KB04-72 | 12.2% | 1-3 | 0 |  |
| WM-WF-KB04-73 | 0.0% | 1,3 | 0 |  |
| WM-WF-KH95-40 | 8.9% | 3,9-12 | 29 | yes |
| WM-WF-KH98-40 | 22.8% | 3,6,9-12 | 349 | yes |
| WM-WF-KH98-70 | 11.1% | 9-12 | 0 |  |
| WM-WF-PH01-00 | 33.9% | 1,3-12 | 27 |  |
| WM-WF-PH01-01 | 10.6% | 3,7-12 | 11 |  |
| WM-WF-PH02-70 | 0.7% | 8 | 0 |  |
| WM-WF-PH03-00 | 47.7% | 1-9 | 74 |  |
| WM-WF-PH03-01 | 56.8% | 3-5,7-12 | 4 | yes |
| WM-WF-PH03-02 | 97.1% | 1-12 | 7 | yes |
| WM-WF-PH03-03 | 68.1% | 1-12 | 0 |  |
| WM-WF-PH03-70 | 12.7% | 6,9-12 | 0 |  |
| WM-WF-PH04-50 | 13.5% | 1-9 | 0 |  |
| WM-WF-PH04-70 | 49.6% | 1-5,8-11 | 0 | yes |
| WM-WF-PL00-50 | 6.6% | 1-4,6-8 | 0 |  |
| WM-WF-PL00-70 | 24.6% | 1-2,9-12 | 0 |  |
| WM-WF-PR00-50 | 2.8% | 1-2,6-7 | 0 |  |
| WM-WF-PR00-70 | 6.9% | 1-6 | 0 |  |
| WM-WF-VN04-70 | 13.9% | 9-12 | 0 | yes |

**Totals.**
- TDS: 150 warning, 0 critical.
- pH: 644 warning, 2,903 critical (both sides).
- Tank level: 697 warning, 33 critical.
- Flow: 0.
- Windows used: level 8,273, flow 638, quality 0.

**Normal range.**
- **TDS:** low single digits to a few hundred ppm. WM-WD-KH96-00 median 5 ppm; WM-WD-KH96-02 median 232 ppm.
- **Tank level:** depends on the tank. WM-WL-PH03-01 median 257 (middle half 101-342); WM-WL-BK00-00 median 73.5.
- **Flow:** many meters sit near a constant. WM-WF-PH03-02 has p5, median and p95 all 0.10 m3/h.

**Thresholds and why.**
- **TDS** warn 500 / crit 1000 ppm and **pH** warn 8.5 / crit 9.0, from `features.py`.
  - No reason is stated in the code. `plan.md` names "turbidity/pH (IS 10500)" as the intended source, and `PRD.md` lists pH "6.5 low / 8.5 high" warning and "6.0 / 9.0" critical (IS 10500:2012).
  - General background: Indian drinking-water standard IS 10500 (BIS) gives an acceptable pH range of 6.5-8.5 and a TDS acceptable limit of 500 mg/L (2000 mg/L permissible without an alternative source).
  - The page checks both sides of pH (see 6.0).
- **Tank level** has no fixed limit in `features.py` (`warn=None`), because each tank has its own scale. The page uses per-tank limits from training months (warning = p99, critical = training maximum):

| Tank | Warn (p99) | Crit (max) | Usual fill time (p90) | Fills seen in train months |
|---|---|---|---|---|
| WM-WL-AN00-00 | 75 | 87 | 80 min | 1 |
| WM-WL-BK00-00 | 206 | 222 | 35 min | 1,117 |
| WM-WL-BK00-02 | 78 | 88 | 30 min | 0 |
| WM-WL-KH00-00 | 83 | 95 | 30 min | 31 |
| WM-WL-KH98-00 | 186.5 | 235 | 125 min | 211 |
| WM-WL-PH03-00 | 209 | 252 | 35 min | 56 |
| WM-WL-PH03-01 | 422 | 448 | 30 min | 2,976 |
| WM-WL-PL00-00 | 110.5 | 126 | 120 min | 291 |
| WM-WL-VN00-00 | 85 | 101 | 30 min | 96 |

  These limits also feed the v2 prompt's TANK line and the abnormal-fill rules (decision D2): a fill past the high mark, a fill longer than 2 × the usual time, or repeated off-hours refills.
- **Flow** has no fixed limit ("baseline-relative only"). The agent judges it by shape: a sudden rise could be a leak or a burst, a flatline a stuck meter.

**What a breach means operationally.**
- **High pH or TDS:** a possible water-quality problem (`water_quality_issue`), so test the water.
- **Tank level above its p99 or maximum:** an overfill or overflow risk (`tank_overflow_risk`). If the fill runs long: `fill_valve_stuck`.
- **Repeated night refills:** `possible_leak`.

**Typical patterns.**
- **pH breaches are mostly sensor artefacts, not water.**
  - WM-WD-KH96-01 reads pH 14.00 almost all the time (median and p95 = 14.00, 99.4% of readings past the limit). That is a saturated sensor; it produces 1,276 critical breaches.
  - WM-WD-KH98-00 alternates between about 5.0 and 11+ (median 10.51); 965 critical breaches, now that the readings near 5.0 count as low-side breaches too.
  - WM-WD-KH96-00 has 1,306.
  - These three sensors give 3,547 of the 4,427 water breaches and 2,903 of its 2,936 critical ones.
  - They are why water breaches jump in **June** (630), **October** (660) and **December** (704). WM-WD-KH96-01 and KH98-00 start reporting in June.
  - **Almost all are single blips.** Only 115 water breaches last at least 40 min, and 16 are critical and lasting. When presenting, call this out as an example of a threshold flood that the agent and its sensor-fault class are meant to filter.
- **Tank level.** It follows fill and drain cycles: for example, WM-WL-PH03-01 had 2,976 fills in training months. Most level breaches are brief (91% under 30 min on PH03-01) and happen at the top of a fill.
- **Coverage.** Coverage is low for water: quality 0.5-6.5%, level 7.8-43.1%, flow 0.04-97.1%. April is missing on every tank-level sensor.

**Training use.**
- **Windows.** 8,911 windows (v1 1,596, v2 7,315). Almost all are tank level (8,273): these are the richest calm bases and the hard negatives (refill_fast, refill_slow, drain_day, pump_cycle, short_cycle, plus real refills).
- **Flow and quality.** Flow gives 638 windows. Water-quality sensors give **0** windows: they are too sparse to form 4 h bases.
- **Held out.** 6 flow meters are held out in v2. The water test set leans on them (60% unseen), because water test-month data is thin (decision D8: the water test also draws from held-out sensors in September-October).

### 6.5 Power (11 meters)

**What it measures.**
- **EM-CR-SB00-00.** The **11 kV feeder meter** at substation SB00, the campus main supply. It reports power (kW) and **power factor** (PF, 0-1: how efficiently current is turned into useful work; low PF means wasted reactive current and possible tariff penalties).
- **SL-* (7 meters).** LT / solar panel meters, power in kW.
- **SR-EM-KH04-00/01/02.** Room energy meters on KH level 04, power in kW.
- **Agent.** All are handled by the **Power agent**.

| Node | Metric | Unit | Warn | Crit | Coverage | Months with data | Breaches (warn / crit) | Windows used | Held out (v2) |
|---|---|---|---|---|---|---|---|---|---|
| EM-CR-SB00-00 | Power | kW | none | none | 83.3% | 1-12 | 0 / 0 | 1125 |  |
| EM-CR-SB00-00 | Power factor | (ratio) | <= 0.85 | <= 0.7 | 83.0% | 1-12 | 1880 / 1433 | 3011 |  |
| SL-NI01-00 | Power | kW | none | none | 19.7% | 1-12 | 0 / 0 | 139 |  |
| SL-NI03-00 | Power | kW | none | none | 8.1% | 1-12 | 0 / 0 | 0 |  |
| SL-NI03-01 | Power | kW | none | none | 8.7% | 1-12 | 0 / 0 | 3 |  |
| SL-PL00-00 | Power | kW | none | none | 2.4% | 1-12 | 0 / 0 | 0 |  |
| SL-PL96-00 | Power | kW | none | none | 4.5% | 6-9,11-12 | 0 / 0 | 47 |  |
| SL-VN02-01 | Power | kW | none | none | 9.0% | 1-12 | 0 / 0 | 1 |  |
| SL-VN95-00 | Power | kW | none | none | 96.5% | 1-12 | 0 / 0 | 438 |  |
| SR-EM-KH04-00 | Power | kW | none | none | 82.5% | 1-12 | 0 / 0 | 3002 |  |
| SR-EM-KH04-01 | Power | kW | none | none | 82.4% | 1-12 | 0 / 0 | 596 | yes |
| SR-EM-KH04-02 | Power | kW | none | none | 82.4% | 1-12 | 0 / 0 | 634 | yes |

**Normal range.**
- **Feeder load:** median 435.90 kW, middle half 358.37-559.13 kW, p95 707.73 kW.
- **Power factor:** median 0.998 (middle half 0.994-0.999), with a long lower tail (p5 0.6637).
- **Room meter SR-EM-KH04-00:** median 5.08 kW.
- **Solar/LT meter SL-VN95-00:** median 1.43 kW.

**Thresholds and why.**
- **Power factor:** warn ≤ 0.85, crit ≤ 0.7 ("low is bad", the only such metric), from `features.py`.
  - No reason is stated in the code. `plan.md` lists "feeder PF/voltage" as a threshold to fill.
  - General background: Indian electricity tariffs commonly penalise an average PF below about 0.9 (some use 0.85), and a PF below 0.7 indicates a serious reactive load or a measurement problem.
- **Power in kW:** no fixed limit ("baseline-relative only"), because a normal load for one meter is abnormal for another. The agent judges load surges, drops and outages by shape.

**What a breach means operationally.** Low PF means a `power_quality_issue`: inspect capacitor banks or inductive loads (`inspect_electrical`).

**Typical patterns.**
- **Feeder load has a strong office rhythm.** It peaks at 17:00 (605.67 kW) and is lowest at 07:00 (340.30 kW, 1.8×); weekends are 16% lower. The daily cycle explains 41% of the variance.
- **Season.** Load is highest in April (median 561.485 kW) and lowest in December.
- **Solar.** SL-VN95-00 shows a pure solar curve: peak at 12:00, a 14× day/night ratio, and 85% of the variance explained by the daily cycle.
- **PF breaches.** All 3,313 power breaches are PF breaches on the one feeder.
  - **Short.** 2,866 of them (87%) last under 30 min, so only 199 pass the 40-min gate.
  - **One long episode.** It lasted 180 h 30 min from 11 April. April's monthly PF median is 0.3274, against 0.96-0.999 in the other months: a data or meter anomaly worth naming as such.
  - **By month.** PF breaches rise from 92 in January to 368 in May, then stay at 295-342 a month. The critical share grows towards December (220 of 325).
- **Coverage.** Coverage of the SL meters is low (2.4-19.7%), except SL-VN95-00 (96.5%).

**Training use.**
- **Windows.** 8,996 windows (v1 1,596, v2 7,400).
- **By meter.** The feeder gives 4,136 windows (PF 3,011, kW 1,125) and the room meters 4,232. The SL meters give 628, and synthetic routines are not applied to `SL-` meters.
- **Held out.** SR-EM-KH04-01 and SR-EM-KH04-02 are held out in v2.
- **Hard negatives.** load_cycle, startup, shutdown.

### 6.6 HVAC units (87 indoor AC units, `SR-AC-KH<floor>-<unit>`, new in v2)

**What it measures.**
- **Units.** Each indoor air-conditioning unit in the KH building. The 5 floors have 19 / 20 / 22 / 22 / 4 units: KH00, KH01, KH02, KH03, KH95.
- **Metrics.** Three per unit:
  - **Room temp (C):** the unit's own thermistor, in the ceiling unit.
  - **Setpoint (C):** the temperature the user set.
  - **AC on (0/1):** whether the unit is running.
- **Source.** Re-extracted per unit from `SR-AC.csv` (1.57 GB, 11.46 M rows; decision D1), by `training/v2/extract_hvac_units.py`.
- **Agent.** The new **HVAC agent**.

**Per-floor summary** (room-temperature metric; setpoint and on/off have no limits and no breaches):

| Floor | Units | Readings (all 3 metrics) | Breaches (warn / crit) | Windows used | Held out |
|---|---|---|---|---|---|
| KH00 | 19 | 5,784,581 | 7 / 0 | 1,581 | 2 |
| KH01 | 20 | 6,020,091 | 230 / 713 | 1,515 | 3 |
| KH02 | 22 | 6,689,548 | 13 / 791 | 1,907 | 3 |
| KH03 | 22 | 6,617,187 | 47 / 0 | 1,996 | 4 |
| KH95 | 4 | 1,216,933 | 1 / 0 | 400 | 1 |
| **All** | **87** | **26,328,340** | **298 / 1,504** | **7,399** | **13** |

**Coverage.**
- Room temp: min 54.6% (SR-AC-KH03-10), median 96.8%, max 96.8%.
- Setpoint: 90.4-96.8%.
- On/off: 96.7-96.8%.
- All 87 units have data in all 12 months.

**Limits (identical on every unit).**
- Room temp: warn 30 C, crit 34 C, applied **only while the unit is on**.
- Overcooling: a warning below min(setpoint − 4, 24 C) while on.
- Setpoint and on/off: none.

**Notable units (examples):**

| Unit | Room temp coverage | Breaches (warn / crit) | Windows used | Held out | Median room temp | Mean on-share | Median setpoint | Note |
|---|---|---|---|---|---|---|---|---|
| SR-AC-KH02-10 | 96.0% | 0 / 786 | 38 | | 41.7 C | 0.22 | 26 C | hot thermistor: reads 39-45 C even while cooling |
| SR-AC-KH01-04 | 91.8% | 0 / 491 | 62 | | 42.1 C | 0.143 | 26 C | hot thermistor |
| SR-AC-KH01-10 | 69.6% | 0 / 222 | 0 | yes | 42.9 C | 0.132 | 22 C | hot thermistor |
| SR-AC-KH01-15 | 58.8% | 207 / 0 | 26 | | 15.2 C | 0.354 | 20 C | malfunction code 37 for 26,858 buckets, reads about 15 C (faulty unit) |
| SR-AC-KH03-02 | 96.8% | 33 / 0 | 117 | yes | 25 C | 0.662 | 26 C | near-continuous unit (on 66%) |
| SR-AC-KH03-14 | 96.8% | 4 / 0 | 463 | | 23.5 C | 0.674 | 24 C | near-continuous unit (on 67%) |
| SR-AC-KH95-02 | 96.7% | 1 / 0 | 291 | | 25 C | 0.888 | 24 C | near-continuous (on 89%); noisy sensor (median step 0.4 C) |
| SR-AC-KH02-02 | 96.7% | 5 / 0 | 36 | | 29.3 C | 0.111 | 25 C | genuine short-cycler: 246 of its 780 runs are 2 readings or fewer |
| SR-AC-KH03-10 | 54.6% | 0 / 0 | 0 | | 43 C | 0 | 24 C | never runs; lowest coverage |

**Normal range** (from `HVAC_DATA.md`, 5-min buckets):
- **Who runs.** Only **21 of 87 units ever run**: 18 office-hours units and 3 near-continuous ones. 66 never run, but still log room temperature. Units are on in 7.2% of raw readings.
- **Healthy running.** Room minus setpoint after at least 30 min running: p25 −1.0, median +0.1, p75 +1.2 C. Healthy units sit at about −1.6 to +1.3 C (p10-p90).
- **Pull-down.** In the first 30 min after a start: median −3.2 C/h.
- **Runs.** Median run 25 buckets (about 2 h).
- **Setpoints.** Most common setpoints are 22, 24, 25 and 26 C.
- **Week.** **Saturday is a working day**: floor on-share is Sunday 0.10, Saturday 0.35, Mon-Fri 0.41-0.46. On-share by hour is 3.7% at 07:00, peaking at 11.4% at 15:00.

**Thresholds and why** (stated in `training/v2/hvac.py` comments):
- **Hot limits.** 30 C (`HOT_OCC`) is "the v1 indoor temperature warning limit"; 34 C (`CRIT_T`) is "the same as the v1 indoor temp critical limit".
- **Comfort band.** `BAND_HI` = 2.0 C above setpoint is "too warm", because normal running error p10..p90 is about −1.6..+1.3 C. `BAND_LO` = 3.0 C below is "too cold", because normal units' running error p10 reaches −2.3..−2.9 C.
- **Cold limits.** `COLD_ABS` = 24 C: too cold also needs the room under 24 C, because "a unit set to 30-32 C (seen in data) is not overcooling". `COLD_HARD` = 20 C: below that while cooling is overcooling regardless of setpoint.
- **Durations.** A condition must hold at least 3 readings (15 min, `MIN_PTS`) to be a pattern and at least 6 readings (30 min, `WARN_PTS`) to be a warning.
- **AC-off rooms.** They are **never** labelled too hot, unless occupancy says the room is occupied. Idle units read 34-45 C in still air, because the thermistor is in the ceiling unit.
- **Other rules.** Short cycling: at least 4 starts per 4 h with median run ≤ 15 min (critical at 8 or more). Bias: at least 36 C after at least 1 h of cooling. Calibration drift (tightened, D7): at least 150 min, r² ≥ 0.85, at least 0.8 C/h, at least 2 C drop.

**What a breach means operationally.**
- **Too hot while running:** the unit is not cooling (`ac_not_cooling`, `high_heat_load`), so inspect the HVAC.
- **Overcooling:** wasted energy and discomfort.
- **The 1,802 breaches are mostly sensor faults.** The four faulty units above produce **1,706** of them (786 + 491 + 222 + 207). For three of those units a "critical 41 C room" is really a hot-reading thermistor. That is why the v2 agent has fault classes such as `biased_reading`.
- **AC running in an empty room** is a new warning with action `switch_off_ac` (D9). It is a recommendation that needs human approval; nothing is switched off automatically.

**Typical patterns.**
- **Monthly breaches.** Highest from March to May (201 / 266 / 214), lowest in January and December (37, 33).
- **Persistence.** Because of the 30-min rule, nearly all HVAC breaches persist: 1,676 of 1,802 last at least 40 min, and 1,415 are critical and lasting.
- **Running units.** They show cycling and pull-down. Idle rooms sit exactly flat for 1-2 h at a time (0.1 C resolution).

**Training use.**
- **Windows.** 7,399 v2 windows (6,499 train / 360 dev / 540 test) from 84 of the 87 units, all rule-labelled by `hvac.py` into 21 patterns:
  - normal: stable, normal_cycling, pull_down, setback_drift;
  - events: too_hot, too_cold, slow_recovery, no_cooling_effect, short_cycling, stuck_on, stuck_off, running_empty_room, unit_alarm;
  - faults: flatline, erratic, bias_jump, biased_reading, calibration_drift, dropout, saturation, quantised.
- **Train counts.** About 241 per event or fault pattern; stable 729, setback_drift 721, pull_down 481, normal_cycling 473.
- **Faulty units.** The four faulty units are never normal bases, only real fault examples (D11).
- **Sampling.** "Unit on" windows are sampled densely (D12: stride 2 on vs 12 off; 257,639 running vs 427,900 off window ends in train months at 4 h).
- **Label rates on real data.** On real 4 h windows of non-faulty units, the rules give normal 98.45%, warning 0.83%, critical 0.08%, sensor_fault 0.64%.
- **Held out.** 13 units are held out.

### 6.7 HVAC floors (5 aggregates, `AC-KH00/01/02/03/95`)

**What it measures.** One series per KH floor:
- **Room temp:** the floor-mean room temperature.
- **Units on:** how many AC units are running.

These are the v1-era aggregates that the current app uses (for example, `AC-KH03` in `sensors.json`).

| Node | Metric | Unit | Warn | Crit | Coverage | Months with data | Breaches (warn / crit) | Windows used | Held out (v2) |
|---|---|---|---|---|---|---|---|---|---|
| AC-KH00 | Room temp | C | none | none | 98.4% | 1-12 | 0 / 0 | 0 |  |
| AC-KH00 | Units on | units | none | none | 98.4% | 1-12 | 0 / 0 | 0 |  |
| AC-KH01 | Room temp | C | none | none | 97.3% | 1-12 | 0 / 0 | 0 |  |
| AC-KH01 | Units on | units | none | none | 97.3% | 1-12 | 0 / 0 | 0 |  |
| AC-KH02 | Room temp | C | none | none | 97.4% | 1-12 | 0 / 0 | 0 |  |
| AC-KH02 | Units on | units | none | none | 97.4% | 1-12 | 0 / 0 | 0 |  |
| AC-KH03 | Room temp | C | none | none | 97.3% | 1-12 | 0 / 0 | 0 |  |
| AC-KH03 | Units on | units | none | none | 97.3% | 1-12 | 0 / 0 | 0 |  |
| AC-KH95 | Room temp | C | none | none | 96.9% | 1-12 | 0 / 0 | 0 |  |
| AC-KH95 | Units on | units | none | none | 96.9% | 1-12 | 0 / 0 | 0 |  |

**Normal range.** AC-KH03: room temp median 28.7 C (middle half 28.0-29.5), highest in April (30.22 C); units on median 2.0, peak at 17:00 (2.4) and low at 07:00 (0.9).

**Thresholds.** None. `rawdata.py` removes the 30/34 C limits for `AC-` nodes, because a floor mean mixes running and idle units (and idle thermistors read hot).

**Training use.** None (0 windows). Decision D1 keeps the floor aggregate only as a **CPU context signal** in the app; the HVAC agent is trained per unit. Their windows are also excluded from the "real windows" count.

### 6.8 Occupancy (7 rooms, shown as Room A to Room G)

**What it measures.** A binary presence sensor per room: 1 = someone present, 0 = empty, sampled into 5-min slots and thresholded at 0.5. The rooms are shown only as codes (see 6.0).

| Node | Metric | Unit | Warn | Crit | Coverage | Months with data | Breaches (warn / crit) | Windows used | Held out (v2) |
|---|---|---|---|---|---|---|---|---|---|
| room-a | Occupied | 0/1 | none | none | 26.3% | 1-12 | 0 / 0 | 556 |  |
| room-b | Occupied | 0/1 | none | none | 26.3% | 1-12 | 0 / 0 | 607 |  |
| room-c | Occupied | 0/1 | none | none | 26.3% | 1-12 | 0 / 0 | 560 |  |
| room-d | Occupied | 0/1 | none | none | 20.6% | 1-8 | 0 / 0 | 514 |  |
| room-e | Occupied | 0/1 | none | none | 75.1% | 1-12 | 0 / 0 | 630 | yes |
| room-f | Occupied | 0/1 | none | none | 75.1% | 1-12 | 0 / 0 | 2212 |  |
| room-g | Occupied | 0/1 | none | none | 75.1% | 1-12 | 0 / 0 | 2211 |  |

**Normal range.** Mostly vacant: the mean occupied fraction is 0.0-0.1 for every room. `HVAC_DATA.md` gives 0-11% occupied.
- **Weekends.** 29% to 48% less occupancy than weekdays (Room A −48%, Room C −44%, Room B −38%, Room G −36%, Rooms E and F −29%).
- **Peak hours.** Around 11:00-16:00.

**Coverage.**
- Rooms A-C: 26.3% (11 full days, 159 empty days).
- Room D: 20.6%, January to August only.
- Rooms E-G: 75.1% (163 full days, 52 empty days).

**Thresholds.** None (`features.py`: occupancy has `warn=None`). Occupancy is not "bad" by value. What matters is the pattern: arrival, departure, intermittent, and especially **off_hours_presence** (presence between 22:00 and 06:00 IST, per `is_off_hours`), which can point to a security or schedule issue (`review_schedule`).

**What an alert means operationally.** Off-hours presence or unexpected activity means reviewing the schedule. Rapid flapping is treated as a sensor fault in v2.

**Typical patterns.** Weekday daytime presence with a weak daily rhythm (r(24 h) 0.27-0.46).

**Cross-domain limit.** P(occupied | AC on) is 0.09-0.22 against 0.05-0.11 when off, for every unit and sensor pair: only a time-of-day effect. The occupancy sensors are **not mapped to AC rooms**. "AC running in an empty room" is therefore trained by attaching a real vacant sequence to a running window (synthetic pairing). Without an occupancy feed the prompt says "occupancy n/a" and that rule cannot fire.

**Training use.**
- **Windows.** 7,290 windows of **real** occupancy (v1 1,596; v2 5,694: 4,995 train, 279 dev, 420 test).
- **Labels.** The six patterns, balanced: about 831-834 each in v2 train.
- **By room.** Rooms F and G give the most (2,212 and 2,211).
- **Held out.** Room E is held out in v2 (155 v2-test windows; it had 475 v1 windows).

### 6.9 Weather (2 rooftop stations)

**What it measures.** Rooftop weather stations on the BN and VN buildings (level 04): air temperature (C), relative humidity (%) and wind speed (m/s). Handled by the **Weather agent**.

| Node | Metric | Unit | Warn | Crit | Coverage | Months with data | Breaches (warn / crit) | Windows used | Held out (v2) |
|---|---|---|---|---|---|---|---|---|---|
| WE-BN04-00 | Temperature | C | >= 38 | >= 42 | 21.4% | 1-3,5-10,12 | 0 / 0 | 695 |  |
| WE-BN04-00 | Humidity | % | >= 90 | >= 97 | 21.4% | 1-3,5-10,12 | 226 / 86 | 1189 |  |
| WE-BN04-00 | Wind | m/s | >= 10 | >= 15 | 21.4% | 1-3,5-10,12 | 59 / 0 | 2005 |  |
| WE-VN04-00 | Temperature | C | >= 38 | >= 42 | 26.3% | 1-2,5-12 | 0 / 0 | 584 |  |
| WE-VN04-00 | Humidity | % | >= 90 | >= 97 | 26.3% | 1-2,5-12 | 176 / 165 | 1045 |  |
| WE-VN04-00 | Wind | m/s | >= 10 | >= 15 | 26.3% | 1-2,5-12 | 0 / 0 | 1730 |  |

**Normal range.**
- **Temperature:** median 24.6 C (WE-BN04-00) and 24.7 C (WE-VN04-00). p5-p95 is 19.84-30.75 and 18.97-32.04 C.
- **Humidity:** median 69.1% and 73.4%.
- **Wind:** median 3.05 m/s and 1.37 m/s.

**Thresholds and why.**
- **The values:** temperature warn 38 / crit 42 C; humidity warn 90 / crit 97%; wind warn 10 / crit 15 m/s (`features.py`, no reason stated).
- **Planning documents.** `PRD.md` lists outdoor temperature 35/42 C as "IMD heat wave alert thresholds"; the final warning limit is 38 C.
- **General background.**
  - IMD declares a heatwave in the plains when the maximum temperature is at least 40 C and well above normal, or at least 45 C outright.
  - 10 m/s is about Beaufort 5 (fresh breeze), and 15 m/s is about Beaufort 7 (near gale).
  - Humidity above 90-97% means near-saturated air: fog, rain, condensation.

**What a breach means operationally.**
- Heat build-up means heat-stress advisories and extra cooling load.
- Gusty wind means securing loose rooftop items.
- Very high humidity gives context for indoor humidity and dampness.
- Weather is mainly **context** for the other agents (cooling load, ingress).

**Typical patterns.**
- **Temperature.** The clearest daily cycle in the dataset: peak at 13:00-14:00 (28.9 / 30.2 C), low at 06:00. The daily cycle explains 57% and 64% of the variance, with r(24 h) of 0.967 and 0.968.
- **Humidity.** Mirrors temperature: peak at 05:00-06:00, low at 14:00-15:00. Highest medians in August (90.3% and 92.3%).
- **No temperature breach in 2025.** The stations never reached 38 C within their recorded coverage.
- **Humidity and wind breaches.** All weather breaches (712) are humidity (653) or wind (59). They cluster in the **monsoon**: 239 in August and 211 in September, but 0 from February to April.
- **Persistence.** 496 of them last at least 40 min.

**Coverage.** Coverage is only 21.4% and 26.3% of the year. The v1 weather bases therefore accept windows with at least 24 of 48 readings present (other roles need 45).

**Training use.**
- **Windows.** 7,248 windows (v1 1,596; v2 5,652). Wind provides the most (3,735), then humidity (2,234) and temperature (1,279).
- **Held out.** No weather station is held out (D8). Weather is tested on seen stations in unseen months only.
- **Hard negatives.** Weather has no synthetic routine family. Daily-cycle hard negatives come from real_routine windows (340 in v2 train).

### 6.10 Points a professor may probe

- **"Why so many breaches?"**
  - The page counts every crossing of a fixed limit, with no minimum duration.
  - Applying the app's 8-reading gate cuts 20,538 to 7,767, and requiring critical as well cuts it to 2,190.
  - Much of the rest is sensor trouble, which the agent is trained to label `sensor_fault`: saturated pH probes, hot HVAC thermistors, a unit stuck on alarm code 37.
- **"Were the test sensors seen in training?"**
  - Test months (November-December) were never used for training.
  - v2 also holds out 25 whole sensors (test only), and results for seen and unseen sensors are reported separately (spec #21).
  - Weather has no held-out station, because only two exist.
- **"Are the labels real?"**
  - The bases are real 2025 readings.
  - Labels come either from a known injected change (pattern, size and onset recorded) or from deterministic rules on real windows (HVAC, occupancy, routines).
  - Only 48,838 of 2,589,199 real 4 h windows (1.9%) were used.
- **"Where do the thresholds come from?"**
  - `features.py` defines them but does not justify them.
  - The planning documents cite ASHRAE 62.1 (CO2), WHO/NAAQS India (PM), IS 10500 (pH/TDS) and IMD (heat).
  - The HVAC limits are justified in `hvac.py` from the data's own distribution.
  - Tank limits are data-driven (p99 and maximum of the training months).

---

## 7. Use case and measured situations

This section explains what the system is for, and then goes through every demo scenario: what happens physically, what the board does, and what the operator sees. Every number comes from a website dataset (id in brackets) or from the raw stress report `proofs/2026-10-16_htpd_v6_app_stress_report_final.json`, which most scenario datasets are built from.

Where these appear on the website:
- **Proofs > Use case** tab: the `uc_*` cards.
- **Proofs > App / UX** tab: `ux_scenario_outcomes`, rendered as a table (the "Measured situations" table; `proofs.js` lists it in `AS_TABLE`), plus `ux_mode2_vs_mode3_latency` and `ux_chaos_incidents`.
- **Proofs > Refinement** tab: `ref_device_runs` and `ref_stage_timing`.
- **Q&A page**, top: a "Situations: What happens when...?" picker. It reads `data/situations_index.json` and `data/situations/sit_*.json`, one story card per scenario with a sensor trace and a stage timeline (start, alert, agents done, refined 1.5 h, refined 3 h).

### 7.1 The use case in one paragraph

The IIIT-H campus has **174 sensors** in 8 domains that produced **33.2 M readings** in 2025 (`uc_coverage`). A plain threshold system on that data fires **20,538 warning/critical breaches in a year, 6,923 of them critical** (`uc_breaches_monthly`). Each one says only that a line was crossed, never why. Our system runs on one Qualcomm QIDK board (Snapdragon 8 Gen 3, Hexagon NPU) and does four things:
- **Waits** until a sensor has been abnormal for 8 readings in a row (the event gate). On the yearly data this cuts the breaches to **7,767 persistent** ones, of which **2,190 are persistent and critical** (`uc_breaches_need_action`).
- **Batches** every sensor alarming at about the same time into one incident.
- **Sends** each alarming sensor to a fine-tuned Llama 3.2 3B "domain agent" on the NPU. When several sensors are involved, a synthesizer call then names one root cause.
- **Checks** every answer with a policy gate and hands the operator one explained, evidence-cited report to approve or dismiss.

At the same detection rate as the threshold rules (**78.0% vs 77.5%**, 284/364 vs 282/364 injected events), false alarms on calm windows fall from **42.9% (33/77) to 27.3% (21/77)** (`uc_alert_reduction`). Nothing leaves the board: **0 bytes per incident leave campus** (`uc_edge_offline`). Nothing is switched automatically: **44/44 agent answers passed the policy gate in the final app run, and 0 actions ran without approval** (`uc_human_in_loop`).

### 7.2 Vocabulary you need for the scenarios

| term | meaning |
|---|---|
| **Demo clock** | The app replays and injects sensor data. One poll every 2 s equals one 5-minute sensor reading, so 8 readings are about 16 s of wall time and 40 min of sensor time (`uc_breaches_need_action` notes; `ad_event_gate` inside `uc_alert_reduction`). The refinement device runs used 1 s polls (`ref_device_runs`). |
| **Event gate** | Only a warning, critical or fault status that lasts **8 readings** calls the AI. It re-arms only after the sensor returns to normal (one report per abnormal episode). **2,000 calm readings produced 0 incidents**, and a 90 s random drift in the stress test raised none (`uc_alert_reduction`). |
| **Batch window** | After the gate fires, the app waits for other sensors that are also waking up. It closes after **1 reading (2 s)** when no other sensor is abnormal-but-young, otherwise later. Crowded room took **2 readings (4 s)**. Before this fix it always waited about 6 s (`lat_batch_window`). |
| **Mode 1 / 2 / 3** | Mode 1: rules only, no AI. Mode 2: one AI call reads every sensor. Mode 3: one NPU agent per alarming sensor, plus a synthesizer for the cross-domain report. All scenario numbers below are Mode 3 unless stated. |
| **Single-sensor Mode 3** | Only one sensor is alarming, so only **1 NPU call** is made. The report is assembled deterministically from that agent's finding, after the related domains have been checked and found steady. The stress report marks it `"deterministic (related domains verified steady)"`. |
| **Multi-sensor Mode 3** | N agents run in **one batched NPU sweep** (htpd), then one synthesizer call, so N + 1 NPU calls. |
| **Policy gate** | Checks valid JSON, whitelisted labels, real evidence ids (`S1.E7` style) and no actuation. Repairs are recorded. If the synthesizer fails, a fallback report is built from the agents' validated findings and marked as such (`ad_policy_gate`). |
| **Refinement** | Every Mode 3 incident is automatically re-analysed when its window ends **+1.5 h (18 readings)** and **+3 h (36 readings)** after the original window, through the same pipeline. At 2 s polls these re-reads land **37 s and 74 s** after the early report (`ref_stage_timing`). An early spike or dip is kept if the re-read only says "stable" (the event is over, not wrong). In run 3 the worst severity is kept. |
| **12 h checks** | CPU detectors for level shift and slow drift over the last 12 h of each flagged sensor. They add evidence lines `S#.E9` / `S#.E10`. Since refinement run 2, a 12 h finding can raise severity (`ref_device_runs`). |
| **Human decision** | Every incident has `requires_human_approval: true`. The operator approves or dismisses, and a dismissal needs a note. Both verdicts are logged as training data. The first approved incident produced **2 SFT positives and 1 DPO pair** (`uc_human_in_loop`). |

### 7.3 The scenario catalogue (what each one does physically)

Scenarios are defined in `app/backend/server.go` (`var Scenarios`). Each one injects a shape into one or more live sensors through `POST /api/inject`. Demo events hold until cleared, the way a real fault does; spikes are transient by nature.

| scenario | physical story | sensor(s) and metric | injected shape |
|---|---|---|---|
| `ventilation_failure` | Ventilation stops in a room, so CO2 builds up | KH level 03 indoor air `SR-AQ-KH03-03`, CO2 | exponential rise, held |
| `pm_spike` | Short burst of outdoor PM2.5 (e.g. nearby burning) | outdoor air station (VN, fallback KN `AQ-KN00-00`), PM2.5 | spike, transient |
| `power_throttling` | Room load climbs, then flat-lines at a cap | KH level 04 room energy meter `SR-EM-KH04-01`, kW | throttle, held |
| `load_surge` | Short spike on a room energy meter | KH level 04 energy meter, kW | spike, transient |
| `tank_leak` | Tank drains steadily without refill | KH tank `WM-WL-KH98-00`, level | slow ramp down over 36 readings, held |
| `pump_cycling` | Tank level swings as the pump cycles on and off | KH tank level | oscillation, held |
| `stuck_sensor` | Indoor temperature freezes at one value | indoor air (fallback `SR-AQ-KH03-03`), temperature | flatline, held |
| `heat_buildup` | Outdoor temperature climbs steadily on the roof | VN rooftop weather station `WE-VN04-00`, temperature | ramp up, held |
| `off_hours_presence` | A room reports occupancy at night | KH room occupancy (gateway KH95) | occupancy set to 1 |
| `crowded_room` | Room fills: occupancy on, CO2 climbs, power steps up together | occupancy + CO2 + room power (3 targets, 3 domains) | set + ramp up + step up |
| chaos (stress test) | "Every sensor haywire": many sensors in all domains fail at once (simultaneous or staggered) | 10 to 13 sensors | random faults from `stress_app.py` |

Background worth knowing: on 2026-10-14, **4 of 10 scenarios could not fire** because they targeted sensors that did not exist in the live topology. That is also why Mode 3 had looked single-agent. Live fallbacks (`Alt`) fixed it (HANDBOOK 2.17; `ux_fault_injection` hardening list).

### 7.4 Measured situations through the final app (one table)

Source: `ux_scenario_outcomes`, built from the final htpd v6 app stress run (2026-10-16, QIDK). The Mode 2 columns come from `ux_mode2_vs_mode3_latency`, which uses the same report. There is **one run per situation**. This is scenario coverage and latency, not a statistically powered accuracy comparison (dataset notes).

| situation (incident) | agent pattern | diagnosis label | operator action | agents / NPU calls | Mode 3 time | Mode 2 time / label |
|---|---|---|---|---|---|---|
| Ventilation failure (INC-0530) | exponential_increase | ventilation_issue | inspect_ventilation | 1 / 1 | **7.426 s** | 6.205 s / ventilation_issue |
| Outdoor pollution spike (INC-0531) | spike | air_pollution_event | inspect_ventilation | 1 / 1 | **4.852 s** | 4.602 s / air_pollution_event |
| Power throttling (INC-0532) | exponential_increase | power_load_anomaly | inspect_electrical | 1 / 1 | **3.769 s** | 3.844 s / hvac_or_thermal_issue |
| Power load surge (INC-0533) | spike | power_load_anomaly | inspect_electrical | 1 / 1 | **2.288 s** | 3.758 s / power_load_anomaly |
| Tank leak (INC-0534) | stable | normal_operation | none | 1 / 1 | **3.080 s** | 4.119 s / water_supply_issue |
| Pump cycling (INC-0535) | step_decrease | water_leak_or_overuse | monitor | 1 / 1 | **2.571 s** | 4.620 s / water_leak_or_overuse |
| Stuck sensor (INC-0536) | flatline | sensor_fault | check_sensor | 1 / 1 | **2.425 s** | 5.899 s / sensor_fault |
| Heat buildup (INC-0537) | exponential_increase | weather_driven | monitor | 1 / 1 | **3.640 s** | 2.989 s / ventilation_issue |
| Off-hours presence (INC-0538) | off_hours_presence | occupancy_driven_load | request_facility_review | 1 / 1 | **2.426 s** | 4.288 s / ventilation_issue |
| Crowded room (INC-0539) | step_increase + exponential_increase | power_load_anomaly | inspect_electrical | 2 / 3 | **7.525 s** | 3.561 s / weather_driven |

Totals: Mode 3 median **3.6 s** vs Mode 2 median **4.3 s**, and **11/11** Mode 3 agent answers were policy-valid (`ux_mode2_vs_mode3_latency`). The time is the analysis only (agents + report). The event gate and batch window come before it.

How to read this table honestly:
- Mode 3 got the expected label in most rows. The tank leak and crowded room rows need the explanations below.
- Mode 2 mislabelled power throttling, heat buildup, off-hours presence and crowded room (see the Mode 2 column). It also mislabelled tank leak as `water_supply_issue`.
- There is **no labelled Mode 2 vs Mode 3 accuracy grid yet** (Q40 in section 10). Say "on these single runs" and do not claim Mode 3 is more accurate.

### 7.5 Scenario by scenario

#### Ventilation failure
- **Physically:** a room's ventilation fails, so CO2 rises slowly and then sharply.
- **Abnormal sensor:** CO2 at KH level 03, indoor air sensor 03. Limits are warning 1000 ppm and critical 1500 ppm (`sit_ventilation_failure`).
- **Event gate:** the first abnormal-looking reading came 65 min before the alert. The gate fired after 8 abnormal readings, and the batch window closed after 1 reading because nothing else was waking up (2 s instead of 6 s, `lat_batch_window`).
- **Final app (INC-0530):**
  - 1 agent, 1 NPU call, **7.426 s**.
  - The agent read exponential_increase, warning, cause ventilation_insufficient, action inspect_ventilation, citing evidence such as "+66.8 ppm/h; most of the rise is in the last hour (EMA 683 vs SMA 4h 507) [E4,E6]".
  - The deterministic report checked the related domains (occupancy vacant, power stable, temperature stable) and concluded "the cause is local to this domain".
  - Label **ventilation_issue**, action **inspect_ventilation**.
- **Refinement (run 3, INC-0616, `ref_device_runs` / `sit_ventilation_failure`):**

| stage | severity | pattern | time | 12 h check |
|---|---|---|---|---|
| early | **warning** | exponential_increase | 4.870 s | level shifted +177 ppm |
| +1.5 h | **critical** | exponential_increase | 3.365 s | +1.29e+03 ppm shift |
| +3 h | **critical** | throttling | 2.889 s | (kept) |

  The CO2 peak was 1747.991 ppm, 2.33 h after the alert. Severity follows the event as it grows and never silently drops.
- **Human decision:** approval pending. The operator decides whether to send someone to inspect the ventilation.
- **Caveat to know:** one agent observation in INC-0530 reads "863 ppm exceeds the warning limit of 1000 ppm". The number is true but the comparison is wrong. The policy gate checks that evidence ids are real, not that the prose arithmetic is right. The label and action were still correct.

#### Outdoor PM2.5 spike
- **Physically:** a short burst of outdoor particulate, e.g. something burning nearby.
- **Abnormal sensor:** PM2.5 at the KN outdoor air station. Limits are warning 60 and critical 120 ug/m3.
- **Final app (INC-0531):**
  - 1 agent, 1 NPU call, **4.852 s**.
  - Spike, critical, cause outdoor_pollution_ingress. The peak was 145.4 ug/m3 and the largest 5-min change +118.8 ug/m3.
  - Related domains (wind, humidity) were steady.
  - Label **air_pollution_event**, action **inspect_ventilation**.
- **Refinement (run 1, INC-0611):**
  - Critical/spike at every stage: early 3.418 s, refined 2.434 s and 2.429 s.
  - No 12 h finding fired.
  - This is the "spike kept when the event is over" rule in action: the later windows no longer contain an active spike, but the report does not get rewritten to "stable" (`sit_pm_spike`).
- **Human decision:** inspect ventilation intake or monitor. Approval pending.

#### Power throttling
- **Physically:** a room's load climbs and then hits a ceiling (a cap or breaker limit).
- **Abnormal sensor:** room energy meter at KH level 04.
- **Final app (INC-0532):**
  - 1 agent, 1 NPU call, **3.769 s**.
  - The agent read exponential_increase, critical: "now 20.97 kW", "+2.51 kW/h".
  - Label **power_load_anomaly**, action **inspect_electrical**.
- **Refinement (run 3, INC-0615):** this is the headline refinement result (`ref_device_runs` claim).

| stage | pattern | severity | time | 12 h check |
|---|---|---|---|---|
| early | exponential_increase | critical | 7.478 s | level shift +7.24 kW |
| +1.5 h | **throttling** (correct) | critical | 2.897 s | +18 kW |
| +3 h | **throttling** | critical | 1.507 s | |

  In run 2 (INC-0614) the 3 h read drifted to step_decrease. Run 3 held throttling.
- **Why it matters:** the early alert reads a young event poorly. At about 40 min after onset, pattern accuracy is 42% (`ad_placement_curve`). The re-read with more of the event in the window names the real shape.
- **Human decision:** inspect the electrical panel. Approval pending.

#### Power load surge
- **Physically:** a brief spike on a room energy meter.
- **Final app (INC-0533):**
  - 1 agent, 1 NPU call, **2.288 s**, the fastest scenario.
  - Spike, critical: peak 33.04 kW, +30.07 kW in 5 min.
  - Label **power_load_anomaly**, action **inspect_electrical**.
- **Refinement:** not measured for this scenario.

#### Tank leak (the honest-limit scenario)
- **Physically:** a tank drains slowly with no refill. A slow leak never crosses a fixed limit fast.
- **Final app (INC-0534):**
  - The rules raised it as "Tank level spike".
  - The 4 h agent said **stable / normal**: "Tank level steady around 261.6 level, ranging only 254.6-283.0".
  - 1 NPU call, **3.080 s**. Label **normal_operation**, action **none**.
  - The report surfaced the conflict: "AI and rules disagree: Tank level (S1): the AI judged this stable/normal, but the deterministic rule that raised this incident found spike/warning - review before deciding". Neither side overrides (`ad_policy_gate`, HANDBOOK 2.33).
- **Refinement and 12 h checks (`ref_device_runs`, `sit_tank_leak`):**

| run | early | +1.5 h | +3 h | what changed |
|---|---|---|---|---|
| run 1, before the fix (INC-0610) | normal | normal | normal | the 12 h drift check fired at 1.5 h and 3 h but **did not raise severity**. This gap was found by the test. |
| run 2, after the fix (INC-0612) | **normal** (4.899 s) | **warning** (1.594 s), titled "Tank level slow drift (12 h view)" | **warning** (1.758 s) | the 12 h finding, "slow drift -64.5 level over 12 h (r2 0.85, 32.3x normal variation)", raised severity (`longRangeRaise`) |

  The label stayed normal_operation / none. Only severity and title changed, so the operator sees a warning to review.
- **What to say:** "The immediate 4-hour read called the slow leak normal. The 12 h check is what surfaces it, at the 1.5 h refinement." This is Q14 in section 10.
- **Requirement:** 12 h checks need at least 8 h of history (`ref_device_runs` notes).
- **Mode 2 comparison:** on the same scenario, Mode 2 said **water_supply_issue / inspect_water_system** (4.119 s).

#### Pump cycling
- **Physically:** the tank level oscillates as the pump turns on and off.
- **Final app (INC-0535):**
  - 1 NPU call, **2.571 s**.
  - The agent read **step_decrease**, warning: "stepped down at 10:05 (300.0 -> 269.0 level)". The injected shape was an oscillation, so the agent only caught one leg of it.
  - Label **water_leak_or_overuse**, action **monitor**.
- **Related evidence:** in the Genie-era stress tests, the one time the rule was right in an AI/rule disagreement was "a missed pump oscillation" (`ad_policy_gate`, folded `ad_disagreement`).
- **Refinement:** not measured.

#### Stuck sensor
- **Physically:** an indoor temperature sensor freezes at one value.
- **Final app (INC-0536):**
  - 1 NPU call, **2.425 s**.
  - Flatline, status sensor_fault: "Temperature frozen at exactly 25.0 C for 24 consecutive samples".
  - Label **sensor_fault**, action **check_sensor**.
- **Refinement (runs 1 and 3, INC-0609 / INC-0617):**
  - sensor_fault / flatline at all three stages (run 3: 2.590 s, 1.435 s, 1.445 s). No 12 h finding.
  - The story card counts 23 readings from the first abnormal-looking reading to the alert (`sit_stuck_sensor`).
- **Why it matters:** "A frozen reading is a sensor fault, not an emergency": a technician goes to the sensor, nobody evacuates a room (`sit_stuck_sensor`). The rejected LADE speed-up turned a stuck sensor into "normal", which is why speed-ups are gated on identical answers (`lat_rejected_ideas`). See Q16 in section 10.

#### Heat buildup
- **Physically:** outdoor temperature climbs steadily at the rooftop weather station.
- **Final app (INC-0537):**
  - 1 NPU call, **3.640 s**.
  - Exponential increase, warning, cause heat_buildup: "to 33.8 C", "+0.8 C/h".
  - Label **weather_driven**, action **monitor**.
- **Caveat:** the same comparison error as ventilation appears here ("33.8 C exceeds the warning limit of 38 C").
- **Mode 2:** said ventilation_issue.

#### Off-hours presence
- **Physically:** a room reports occupancy at night (fraction 0.19, last occupied 23:50).
- **Final app (INC-0538):**
  - 1 NPU call, **2.426 s**.
  - Pattern off_hours_presence, warning.
  - Label **occupancy_driven_load**, action **request_facility_review**.
- **Why it matters:** this is a privacy-sensitive signal and a reason the system stays on the edge (`uc_edge_offline`: no occupancy data leaves the site).

#### Crowded room (the cross-domain scenario)
- **Physically:** a room fills up. Occupancy turns on, CO2 climbs, and room power steps up as AC and equipment start.
- **Abnormal sensors:**
  - Power at KH level 04 went **critical**: it stepped from about 3 kW to about 9 kW.
  - CO2 at KH level 03 went **warning**: it rose from about 450 to 758.5 ppm.
  - The occupancy sensor stayed status normal, so the incident is "2 sensors alarming: Power critical, CO2 warning" (`sit_crowded_room`).
- **Event gate and batching:** the batch window took **2 readings (4 s)** so that both sensors joined **one** incident (`lat_batch_window`).
- **Final app (INC-0539, htpd v6):**
  - **2 agents + synthesizer = 3 NPU calls, 7.525 s**, across 2 domains (`uc_cross_domain`).
  - Power agent: step_increase, "+5.98 kW at 10:15 and stayed there", cause equipment_startup.
  - Air agent: exponential_increase, cause ventilation_insufficient.
  - The synthesizer (fine-tuned Llama, w4a16) chose label **power_load_anomaly**, action **inspect_electrical**.
  - Policy repairs: affected_domains was completed with air_quality, and evidence entries were reduced to S#.E# ids.
- **Same scenario on the older Genie path (INC-0392, hw_grid run):** 14.4 s, label **ventilation_issue**, action inspect_ventilation (`sit_crowded_room`).
- **Phase breakdown, Genie/genied era (`uc_example_incident`, HANDBOOK 2.29):**

| phase | seconds |
|---|---|
| abnormal for 8 readings (event gate) | 16 |
| batch window (2 sensors) | 4 |
| 2 NPU domain agents | 7.112 |
| synthesizer root cause | 4.457 |
| app overhead | 0.011 |
| **total, first abnormal reading to report** | **about 32 s of demo time** |

- **Honest note:** neither run's synthesizer said "crowding" in words. The Genie run picked ventilation and the htpd run picked power. Both are domains that really were abnormal. Independent root-cause ground truth (cross-domain injections) is still **planned** (`uc_cross_domain` notes).
- **Mode 2:** one call in 3.561 s said weather_driven / none, which is a worse answer.
- **Refinement:** not measured for this scenario.
- **Human decision:** approval pending. The operator sees both domains' findings and decides.

#### Chaos: several systems fail together
- **Physically:** a stress round that drives many sensors in every domain out of range at once (PM, CO2, humidity, temperature, wind, power, pH, TDS, flow, tank level). This is the worst case for latency and heat.
- **Final app, htpd v6 (`uc_cross_domain`, `ux_chaos_incidents`, stress report):**

| incident | agents / NPU calls | domains | time | report |
|---|---|---|---|---|
| chaos simultaneous #1 (INC-0550) | 12 / 13 | 4 | **20.698 s** | Llama synthesizer: **weather_driven**, monitor. Disagreement on humidity (S10) surfaced. |
| chaos simultaneous #2 (INC-0551) | 10 / 11 | 4 | **20.617 s** | The synthesizer's own report **was rejected by policy**. A fallback was built from the agents that passed: **hvac_or_thermal_issue**, inspect_hvac, marked "synthesizer output rejected by policy". |
| chaos staggered #1 (INC-0552) | 11 / 12 | 4 | **20.752 s** | **weather_driven**, monitor. Disagreement on CO2 (S7) surfaced. |

- **Before htpd:**
  - Genie took 48.9 s (13 agents) and 40.8 s (9 agents) for chaos incidents (`ux_chaos_incidents`).
  - The 13-agent hw_grid trace INC-0401 took 53.6 s (`sit_chaos`).
  - Claim: "10-12 agents + synthesizer in ~21 s (Genie: 40.8-48.9 s)".
- **What it shows:**
  - There is no agent cap: every alarming sensor gets its own NPU agent.
  - One incident, not 13 alarms.
  - Every answer is gated, and the operator always gets a report, even when the synthesizer fails.
- **Heat:** chaos peaks reach 95-96 C on htpd, and back-to-back chaos rounds trip the thermal guard. All 3 failures in the final 132/135 stress run were thermal (`ux_stress_runs`, `hw_board_thermal`). Use a heatsink.
- **Refinement:** not measured for chaos.

#### Not yet measured: AC running in an empty room
`situations_index.json` lists "What happens when the AC runs in an empty room?" as **not yet measured**. The `switch_off_ac` recommendation is part of the v2 retrain (D119). It still needs operator approval, and no measured QIDK run exists yet. If asked, say so plainly (Q17 in section 10).

### 7.6 What refinement adds, in summary (`ref_device_runs`)
- **Coverage:** 3 device runs, 9 incidents. **9/9 reached the 3 h stage**. Stages are about 15-18 s apart at 1 s polls.
- **Corrects the pattern:** power throttling went from exponential_increase to throttling at 1.5 h.
- **Escalates severity as the event grows:** ventilation went from warning to critical at 1.5 h.
- **Surfaces what the 4 h agent misses, via the 12 h checks:** tank leak went from normal to warning (after the run 2 fix).
- **Keeps what is right:** the PM spike stayed a spike, and the stuck sensor stayed sensor_fault.
- **Never touches the approval or the event gate.** It queues behind new alerts, and its unit tests pass 5/5 (`ref_go_tests`, folded in `ref_device_runs`).
- **Displays correctly:** at 360 px phone width there is no overflow on any screen. The EARLY -> REFINED 1.5 h -> REFINED 3 h badges appear live over SSE (`ref_ui_checks`).

### 7.7 A day in the life of one incident (plain language)

The ventilation failure case (INC-0616, refinement run 3) is used here because it is the one with every stage measured.

1. **14:15 sensor time, KH building level 03.** A room's ventilation has stopped. The CO2 sensor first looked abnormal about 65 min earlier at 493.7 ppm and has been climbing. No alarm has gone off yet, because one high reading on its own is not an incident.
2. **The event gate decides it is real.** CO2 has now been abnormal for 8 readings in a row (40 min of sensor time, about 16 s on the 2 s demo clock). The gate opens a batch window, sees no other sensor waking up, and closes it after one reading.
3. **The AI looks.** The board sends the last 4 h of this sensor to one fine-tuned Llama 3.2 3B agent on the Hexagon NPU. **4.9 s later** it answers in checked JSON: pattern exponential_increase, status **warning**, cause ventilation_insufficient, action inspect_ventilation. Each observation cites evidence ids. A 12 h CPU check adds "level shifted +177 ppm about 0.6 h ago".
4. **The policy gate checks the answer.** Valid JSON, whitelisted labels, real evidence ids, no actuation. It passes. The report also notes that occupancy, power and temperature are steady, so the cause is local to this room.
5. **The operator's phone shows one card**, badged EARLY: "CO2 exponential increase: KH building, level 03, indoor air sensor 03", severity warning, recommended action **inspect ventilation**, with the evidence underneath. Nothing has been switched on or off.
6. **+1.5 h of sensor time (about 37 s of demo time).** The board re-reads the sensor automatically. Now the window holds more of the event, and the agent says **critical** (3.4 s). The card's badge changes to REFINED 1.5 h and the History fold keeps the early answer.
7. **+3 h.** A second re-read stays **critical** (2.9 s). CO2 peaked near 1748 ppm. Severity never silently drops.
8. **A person decides.** The operator taps **Approve**, and someone goes to check the air handler. Or they tap **Dismiss** with a note, e.g. "planned maintenance". Either way the verdict is stored. Approved answers become SFT examples and policy-corrected answers become DPO pairs for the next fine-tune.

The same flow with two sensors (crowded room) adds a second agent and one synthesizer call. That run took **7.5 s** on the final build, against about 32 s first-reading-to-report on the older Genie trace. With 10-12 sensors (chaos) it takes about **21 s**.

---

## 8. Statistics primer (with worked examples from our data)

**The rule of thumb.** Every number on the site is a count out of n, or a time. Look first at n, then at the CI, then at the paired test.

- **Accuracy and false alarms are proportions** (k right out of n). We report them with **Wilson 95% CIs**. Two systems are compared on the *same* cases with an **exact McNemar test**.
- **Times are means of a few runs.** We report them with a **t-based 95% CI** where we have repeats. Where the source logged only a range, we use the midpoint and say so.

### 8.1 Proportion and its 95% CI (Wilson)
- **What it is.** An accuracy is k/n. The 95% CI is the range of true accuracies compatible with what we saw.
- **Why Wilson.** The textbook "p ± 1.96·√(p(1−p)/n)" breaks near 0% and 100%: it can give a CI above 100% or of zero width. Wilson's formula does not. Most site datasets use `ci_method: "wilson95"` (289 points tagged in the data).
- **Formula.** With z = 1.96:
  - centre = (p + z²/2n) / (1 + z²/n)
  - half-width = z·√(p(1−p)/n + z²/4n²) / (1 + z²/n)
- **Worked example** (`acc_v1_host_eval`). The fine-tuned model got the pattern right on 141 of 150 held-out windows.
  - p = 0.94, centre = 0.9290, half-width = 0.0391, so the CI is **0.8899 - 0.9681**. That is exactly the whisker on the chart.
  - Base model: 30/150 = 0.20, CI 0.1438 - 0.2711. The two CIs are far apart, so the difference is unmistakable.
- **Edge case.** 150/150 valid JSON gives CI 0.975 - 1.0, not "exactly 100%". With 150 samples we can only say the true rate is at least 97.5%.
- **Small n** (`acc_device54_engines`). htpd pattern 90.7% on n = 54 has CI roughly 80-96%, as the Route anchor says. A few points of difference at n = 54 is noise.

### 8.2 Mean time and its 95% CI (Student t)
- **What it is.** For a handful of timed runs, CI = mean ± t(0.975, n−1)·s/√n. With n = 3, t = 4.303 (much wider than 1.96, because 3 runs say little about spread).
- **Worked example** (`lat_call_breakdown`). Model init over 3 runs: mean **694.7 ms**, CI **677.76 - 711.58 ms**.
  - The half-width of 16.9 ms implies a run-to-run standard deviation of about 6.8 ms (16.9·√3 / 4.303).
  - Decode: 2646.3 ms, CI 2574.57 - 2718.09.
  - Takeaway: decode dominates, and the CIs do not overlap.
- **Most latency numbers have no CI.** They are single measured runs, or the second of two repetitions (`lat_htpd_ab`: "total = rep 2 of 2", board cooled below 55 °C before each config). When the Analysis line says "no spread recorded, so no test", that is the reason.
- **What to say about latency without a CI.** We guard against noise in two ways:
  - **Order effects.** We repeat A/B/A runs, e.g. `v5 + prefix cache (after v6)` re-measured 15.9 s.
  - **Correctness.** We report text identity against the run-to-run noise floor of 21-24/25.

### 8.3 Paired vs unpaired: why McNemar
- **Paired data.** When two systems answer the *same* cases, the data are paired. Cases both get right, or both get wrong, carry no information about which is better. Only the **discordant** cases count:
  - b = cases only A got right;
  - c = cases only B got right.
- **Exact McNemar test.** Under "no difference", each discordant case is a fair coin flip. So p = 2·P(Binomial(b + c, 0.5) ≤ min(b, c)), capped at 1.
- **Worked example 1: no evidence of a difference** (`acc_device54_engines`, paired_tests). Genie vs htpd final, pattern, n = 54.
  - only Genie right = 2, only htpd right = 5;
  - p = 2·P(X ≤ 2 | 7 flips) = 2·(1 + 7 + 21)/128 = **0.453**.
  - So "90.7% vs 85.2%" is **not significant (n.s.)**. We claim "htpd is no worse", not "htpd is better".
  - The same holds for status (2 vs 6, p = 0.289), cause (1 vs 4, p = 0.375) and derived action (1 vs 5, p = 0.219).
- **Worked example 2: a clear win** (`ad_longrange_arms`, folded `ad_longrange_paired`). Agent alone vs agent + 12 h checks on old steps, n = 60.
  - Caught only with the checks: 12. Caught only without them: 0.
  - p = 2·(1/2)¹² = **0.0005**.
  - Drifts: 7 vs 0, so p = 2/128 = **0.016**. Recurring small spikes: 0 vs 0, so p = 1.0 (no change).
- **Worked example 3: big n, big effect** (`ad_placement_curve`, folded `ad_placement_paired`). The same 208 events read at 40 min and at 3 h.
  - 105 events were right at 3 h but wrong at 40 min; only 9 went the other way.
  - p < 0.0001.
- **Worked example 4: one test per window length** (`ad_window_headline`, folded `ad_window_paired`, n = 169 classic cases). 4 h vs 2 h on pattern: 53 cases only 4 h got right, 2 only 2 h, p = 8.55e-14.

### 8.4 Two-proportion z-test (what the Proofs "Analysis" line computes)
- **What it is.** For two independent rates p₁ = k₁/n₁ and p₂ = k₂/n₂:
  - pooled p = (k₁ + k₂)/(n₁ + n₂);
  - z = (p₂ − p₁) / √(pooled·(1−pooled)·(1/n₁ + 1/n₂));
  - two-sided p-value from the normal distribution.
- **The CI of the difference** uses the unpooled standard error: (p₂ − p₁) ± 1.96·√(p₁(1−p₁)/n₁ + p₂(1−p₂)/n₂).
- **Worked example** (`uc_alert_reduction`). False alarms on 77 calm windows: rules 33/77 = 42.9%, agents 21/77 = 27.3%.
  - Difference −15.6 pp, z = −2.03, **p ≈ 0.043**: significant at 5%, but only just.
  - Detection: 284/364 vs 282/364, z = −0.18, p ≈ 0.86. That is why the claim says "same detection".
- **Caveat to state.** These are the *same* windows, so a paired McNemar is the more appropriate test. The automatic Analysis line is a quick unpaired check. Where a dataset carries its own McNemar result (`acc_device54_engines`, `ad_window_headline`, `ad_longrange_arms`, `ad_placement_curve`), quote that one.
- **If no k/n is available** but both CIs are, the page approximates each standard error as (hi − lo)/3.92 and runs a z-test on the difference ("z-test from the two 95% CIs").

### 8.5 p-value: what it is and is not
- **What it is.** p is the chance of a difference at least this large *if there were really no difference*.
  - p < 0.05: we call it significant.
  - p ≥ 0.05: **n.s.** The data cannot tell the two apart.
- **What it is not.** It is *not* the probability that the result is wrong, and it is not a size of effect. p = 0.45 does not mean "the systems are equal". It means "no evidence of a difference at n = 54". That is why we say **"no worse"**.
- **Multiple comparisons.** `ad_window_paired` runs 15 tests. At 5% each, about 0.75 false "significant" results are expected by chance.
  - With a Bonferroni-strict threshold (0.05/15 ≈ 0.0033), the pattern results (all p < 0.0001) and step_old vs 12 h (p = 3.05e-05) survive.
  - "step_old flag vs 2 h" (p = 0.0386) would not.
  - Say this honestly if asked: the headline claim (4 h best on pattern) survives any correction.

### 8.6 Effect size: Cohen's h
- **Why.** A large n makes tiny differences significant, so we also report how *big* the difference is.
- **Formula.** For proportions, h = 2·asin(√p₂) − 2·asin(√p₁). |h| < 0.2 is negligible, < 0.5 small, < 0.8 medium, ≥ 0.8 large.
- **Worked example** (`uc_alert_reduction` false alarms, 0.429 → 0.273): h = **−0.33, small**. A real but modest reduction, and that is how to describe it.
- **Contrast** (`acc_v1_host_eval` pattern, base 0.20 → fine-tuned 0.94): h = 2·asin(0.970) − 2·asin(0.447) ≈ 2.65 − 0.93 = **1.72, very large**.

### 8.7 Dev/test discipline, Pareto fronts and ablations
- **Tuning.** Every threshold or detector parameter was tuned on **dev months (Sep-Oct)** and tested **once** on **test months (Nov-Dec)**. Training used Jan-Aug.
- **Pareto front** (`ad_detector_tuning_frontier`). Each grid tries 7,680 parameter settings. For each false-alarm rate on calm dev windows, the chart plots the best old-step catch rate.
  - At 15% false alarms, the raw 12 h check catches 64% of old steps; the daily baseline catches 23%.
  - That is a fair, tuning-independent comparison: each method at its best.
- **Ablation** (`ad_longrange_ablation`). Remove one detector and re-measure, on dev and on test. That is how the recurring-excursion detector was shown to add false alarms without enough gain.

### 8.8 Noise floors for "identical outputs"
- **The problem.** Batched floating-point sums on the NPU are not bit-reproducible, so the same htpd binary run twice gives **21-24 of 25** identical texts (`lat_htpd_ab`).
- **The test.** A latency change is accepted as "does not change answers" when its identity score sits inside that floor, e.g. v6 vs v5 25/25. Only lossless changes count, e.g. drafting, which keeps a draft only when it equals greedy.
- **What failed it.** Changes that fall far below the floor were rejected: LADE 1/14, continuous batching 1/12, equal-ubatch prefill (~30% of outputs changed).

### 8.9 Ground truth: where labels come from
- **Injection.** A known pattern or fault is added to a real calm window, so the true label is exact. This is used for pattern, detection, the window study and the placement study.
- **Calm windows** give the "truth = normal" cases for false alarms. Real calm data can still contain real events, so false alarms are **over-counted**. On a strict clean subset (n = 19), 4 h false alarms are 5% (`ad_window_headline` notes).
- **Teacher rules** label status, cause and action. Comparing the AI with Mode 1 on those is therefore circular, and only the pattern comparison is independent (`acc_v1_rules_vs_llm_fair`).

---

## 9. Honest limits and unmeasured items (and what we say)

| Limit | What is true | What we say if asked |
|---|---|---|
| **Small device test set** | Device accuracy is n = 54 windows (about 1 per class); htpd vs Genie is n.s. (p = 0.45). A 900-window rerun stopped after 39 windows on a thermal stall at 91 °C (`acc_device54_engines` notes). | "At n = 54 we can claim *no worse*, not *better*. The 900-window rerun is scheduled, and the 2,416-call window study and 1,248-call placement study on the same NPU give large-n support." |
| **Host vs device gap** | 94% on the laptop (NF4) vs 85.2-90.7% on the NPU. The first export was 54.3%. | "Most of the gap was a double-BOS prompt bug, plus int4 rounding. GPTQ and the BOS fix recovered it. Every step is in `acc_quant_waterfall`." |
| **Circular labels** | Status, cause and action labels come from the teacher rules that Mode 1 runs. | "So we compare to rules on *pattern* only (`acc_v1_rules_vs_llm_fair`). Injected ground truth is independent of the rules." |
| **Mode 2 vs Mode 3 accuracy** | Not measured on a labelled grid yet (a 600-incident grid is planned). | "We do not claim Mode 3 is more accurate. We claim it is cross-domain and evidence-cited. The labelled grid is next." |
| **Cross-domain root cause** | All 4 multi-sensor incidents span 2-4 domains, but there is no independent root-cause ground truth yet (`uc_cross_domain`). | "Cross-domain injections with known root causes are planned. Today we show coverage, not root-cause accuracy." |
| **Young events** | At alert time (40 min) pattern accuracy is 42%. | "That is why the alert is labelled EARLY and refined at 1.5 h (67%) and 3 h (88%). v2 trains on young events, with acceptance at ≥ 65% at 40 min." |
| **Recurring small spikes** | No window length or detector catches them reliably (32-52%). | "Unsolved in v1. v2 teaches them explicitly." |
| **False alarms** | 27% on calm windows at 4 h, over-counted. v1 calls about 31% of routines alarms. | "Lower than the rules' 43% at equal detection. v2 adds 8,292 routine hard negatives (`ds_routine`), and its acceptance requires fewer false alarms." |
| **Synthetic injections** | Patterns are injected, not real labelled incidents. | "They ride on real calm windows from real sensors. A real-event set from facility logs is planned as a second ground truth." |
| **Weather generalisation** | Weather is tested on seen stations only (2 stations). | A stated limit (spec D8). |
| **Heat** | Chaos peaks reach 95-96 °C. The 3 stress failures out of 135 are thermal. | "A heatsink or fan is required in the field. The thermal guard pauses work instead of crashing." |
| **Energy** | Joules per incident are not measured (no free power rail). USB power browned out at peak, so the evaluation uses the DC adapter. | "Not measured; we will not guess." |
| **Latency CIs** | Most timings are single runs or rep 2 of 2. Genie values are midpoints of logged ranges. | "Differences are large compared with run-to-run spread (e.g. 47 → 20.7 s). Small ones (3.8 vs 3.8 s) we call equal." |
| **Refinement cost** | Up to 3× the NPU work per incident, spread over 3 h of sensor time. After a backend restart, pending refinements are dropped. | "Refinements queue behind new alerts and wait when the board is hot." |
| **12 h checks warm-up** | They need ≥ 8 h of history, so they are silent for about 8 min of demo after a restart. | A stated behaviour. |
| **v2 not finished** | 60% of the steps are done (build of 2026-10-19 20:13). No v2 accuracy exists yet. | "Every v2 number on the site is about data and training progress, not results. The acceptance gate is fixed in advance (RETRAIN_V2_SPEC #20)." |
| **Screens** | Most after-screens come from a laptop backend with mock agents, and some states are synthetic. | Labelled in the gallery. |
| **Reasoner** | Severity and titles come from a stub (`severity.go`, `title.go`) until the cross-domain reasoner is trained. | "Next after v2." |

### 9.1 Inconsistencies found in the site data, and their status (re-checked 2026-10-19)
These were found when checking every card against its data. None changed a headline conclusion. **Fixed** items are corrected on the site (build of 2026-10-19 20:13); **explain** items remain true and you should be ready to say why.

- **Fixed: chaos "was 41-57 s"** (`ux_chaos_incidents`). The claim now reads "~21 s (Genie: 40.8-48.9 s)", the two plotted Genie points. (57 s was the top of HANDBOOK's staggered-run range, 49-57 s.)
- **Fixed: Mode 2 vs Mode 3 "median"** (`ux_mode2_vs_mode3_latency`). The collector now uses the true median of the 10 scenarios: 3.4 s (Mode 3) vs 4.2 s (Mode 2) (3.36 / 4.20). Decision G03 and the Q&A answer use the same numbers.
- **Fixed: `uc_cross_domain` "3/3".** The claim is now "All 4 multi-sensor incidents span 2-4 domains in one report"; the notes say the app check "names several domains" passed 3/3 on the chaos runs only.
- **Fixed: pH low side** (raw data). `rawdata.py` now counts pH below 6.5 (warning) and 6.0 (critical) as in `generate_dataset.status_of`. Breaches rose from 19,819 to **20,538** (critical 6,282 → **6,923**); water from 3,708 to 4,427. The 3 faulty pH sensors now give 3,547 of 4,427 water breaches; most HVAC-unit breaches still come from 4 faulty units (1,706 of 1,802). Q&A answers with breach counts are now filled from the data, not typed.
- **Fixed (flagged honestly): agent text arithmetic.** Some passed answers state a wrong comparison, e.g. "863 ppm exceeds the warning limit of 1000 ppm". The site does not quote agent free text as correct anywhere; the Q&A "not measured yet" card and the new question "Is every answer that passes the gate correct?" call it "model text, numerically wrong". The gate checks labels and evidence ids, not prose arithmetic; v2 shortens free text to at most 2 observations.
- **Fixed: readings vs rows** (`uc_coverage`). The card notes now explain that a reading is one metric value per 5-min slot after cleaning, so 33.2 M readings differ from ~37 M CSV rows.
- **Fixed: LADE −32.5 % vs −20 %** (`lat_rejected_ideas`). The notes now say −32.5 % is one prompt and about −20 % decode over 14 prompts. Either way it was rejected because answers changed.
- **Explain: "every failure is heat"** (`ux_stress_runs`). The claim says "on the final htpd build"; it is true for v6 and later only. The v3 run had 1 functional failure.
- **Explain: GPU agreement** (`hw_grid_agreement`). 8/12 pattern agreement with Genie in the saved grid; HANDBOOK 2.37's 82 % is from a wider check whose per-sample file was not kept (the notes say so).
- **Explain: label quirk** (`lat_route_13_agents`). The first bar is "≈ Genie, 13 agents", the midpoint of 22-25 s, not one run.
- **Explain: 12 h-check false alarms.** 8.75 % (7/80) in `ad_longrange_ablation` vs 2.6 % (1/39) in `ad_longrange_arms`: different case sets and calm-window definitions.
- **Explain: typical incident 3.8 s vs 3.4 s.** 3.8 s (status and Q&A "How fast") is the median over the stress run's incidents (`lat_chaos_genie_vs_htpd` notes); 3.4 s is the median of the 10 paired Mode 2/3 scenarios. Different sets, same order of magnitude.
- **Explain: synthesizer drafting.** HANDBOOK 2.37 rejects *speculation* on the synthesizer, but the backend uses *verified drafting* for the synthesizer and Mode 2. Drafting is lossless against greedy on the same batch, but wording can differ slightly from Genie's. Do not claim "no speculative decoding anywhere".
- **Explain: "held out" means held out in v2.** Some v2-held-out sensors had v1 training windows.
- **Explain: missing paired test.** Agent vs rules false alarms (27 % vs 43 %, n = 77) have no paired test in the data. The unpaired z-test gives p ≈ 0.043 (section 8.4).
- **Explain: numbers that move.** Training step, s/step, ETA, thermal pauses and session counts are read from the live log at each build; quote the site, not this guide, for them.

---

## 10. Q&A cheat sheet

The website's **Q&A page** (`src/pages/qa.js`) loads all 81 questions in 17 topics from `data/qa.json` (generated 2026-10-19T18:56:55). The page is laid out top to bottom as follows:
- A "Situations: What happens when...?" picker, with one trace card per scenario (section 7).
- A use-case block.
- A search box with typo-tolerant synonym matching, topic chips, and a "Likely first questions" list.

Opening a question shows:
- the one-line answer;
- a "See decision G.." link;
- an "Honest limit" chip when the answer admits a gap;
- a "Situation card" link for scenario questions;
- the first 2 evidence charts, with "+ more" for the rest.

Deep links use a 0-based index, so **Q<n> here is `#/qa?q=<n-1>`**.

How to use this sheet:
- The **bold line** is the question.
- The first plain line under it is the site's short answer, **verbatim**. Say this first.
- The expansion after it is for follow-up questions.
- Numbers come from the dataset ids in the "Evidence" line (`data/catalog.json`, or `data/situations/` for `sit_*`).

Questions are grouped by `category`, in qa.json order: use case, situations, accuracy, status quo, hardware, model, agent design, false alarms, latency, data, training, thermals, safety, robustness, limits, next, status.

### Use case (12)

**Q1. What is the system for?**

It watches a campus's sensors (174 sensors, 33.2 M readings a year across 8 domains), notices real problems and explains why, on one small board.

Coverage (`uc_coverage`): 174 sensors and 33,217,982 readings over 12 months in 8 domains. The largest domain is HVAC units: 87 sensors and 26.33 M readings. The raw source is 14 CSVs, 4.6 GB, about 37 M rows (folded `ds_source_data`). "Notices real problems" means the event gate plus the domain agents. "Explains why" means each report cites evidence ids from the sensor window. "On one small board" means the QIDK (Snapdragon 8 Gen 3, Hexagon NPU), with no cloud.

Evidence: `uc_coverage`. Decision: G01 ("Everything runs on the board's NPU, not in the cloud").

**Q2. Who uses it?**

Facility operators: they get one explained incident instead of a flood of threshold alarms, and approve or dismiss each recommendation.

The operator sees one incident card with a diagnosis, an action and the cited evidence. Every incident requires human approval, and a dismissal needs a note (`uc_human_in_loop`). Measured gain over plain thresholds on the same windows: detection 77.5% vs 78.0%, false alarms 27.3% (21/77) vs 42.9% (33/77) (`uc_alert_reduction`). Verdicts feed training: the first approved incident gave 2 SFT positives and 1 DPO pair.

Evidence: `uc_human_in_loop`, `uc_alert_reduction`. Decision: G06 ("Disagreements are shown, decisions stay human").

**Q3. What problem does it solve?**

Threshold alarms fire 20,538 times a year on this campus and say what crossed a line, never why.

The 20,538 breaches come from real 2025 data across 6 alarm-raising domains, and 6,923 of them are critical (`uc_breaches_monthly`). By domain: indoor air 6,628, water 4,427, outdoor air 3,656, power 3,313, HVAC units 1,802, weather 712 (`uc_breaches_need_action`). A breach is one contiguous run above a warning or critical limit on one metric. A threshold system tells the operator which line was crossed. It cannot say whether the cause is crowding, a leak or a stuck sensor.

Evidence: `uc_breaches_monthly`, `uc_breaches_need_action`. Decision: G04 ("Alert only on persistent abnormal status (event gate)").

**Q4. How many of those alarms actually need attention?**

7,767 breaches last at least 40 min (the event-gate rule) and 2,190 are both persistent and critical.

The app's own event gate (8 consecutive abnormal readings, which is 40 min on the 5-min raw data) applied to the year's breaches: 20,538 -> 7,767 persistent -> 2,190 persistent and critical (`uc_breaches_need_action`). The gate cuts water hardest: 4,427 breaches, but only 116 last 8 readings and 17 are also critical. HVAC units barely change (1,802 -> 1,676 -> 1,415), because AC faults tend to persist.

Evidence: `uc_breaches_need_action`. Decision: G04 ("Alert only on persistent abnormal status (event gate)").

**Q5. Which domains raise the most alarms?**

Indoor air 6,628, Water 4,427, Outdoor air 3,656, Power 3,313, HVAC units 1,802, Weather 712.

These are raw counts per domain for 2025 (`uc_breaches_need_action`). After the gate, indoor air (3,309) and outdoor air (1,971) lead, with HVAC units at 1,676. The monthly view (`uc_breaches_monthly`) shows seasonality: water peaks in Jun (630), Oct (660) and Dec (704), and outdoor air is highest Jan-Mar (635-658) and lowest in summer (83-100).

Evidence: `uc_breaches_monthly`, `uc_breaches_need_action`.

**Q6. What improves over the status quo?**

At the same detection rate as threshold rules (78%), false alarms drop from 43% to 27%, and each alert comes with a cited explanation.

Measured on 4 h windows from the held-out test months, on the QIDK NPU (`uc_alert_reduction`).
- Detection: rules 284/364 (78.0%) vs our system 282/364 (77.5%).
- False alarms on 77 calm windows: 33 (42.9%) vs 21 (27.3%).
- The 95% CIs on false alarms (0.324-0.54 vs 0.186-0.381) overlap slightly, so present this as "same detection, fewer false alarms", not as a large significant gap.
- Each alert also carries an explanation with evidence ids. Rules give none.

Evidence: `uc_alert_reduction`. Decision: G04 ("Alert only on persistent abnormal status (event gate)").

**Q7. How quickly does an operator get an explanation?**

About 4 s for a typical incident and 20.7 s when 12 sensors fail at once (was ~47 s); refined re-reads follow at +1.5 h and +3 h.

Typical incident: median 3.8 s on both Genie and htpd. 12-sensor chaos incident: about 47 s on Genie (midpoint of 46-48 s) vs 20.7 s on htpd v6. A 13-agent A/B run: 23.5 s -> 14.7 s (`uc_time_to_insight`). Rules alert in about 1 ms but explain nothing. Refined re-reads land at +1.5 h and +3 h of sensor time: about 37 s and 74 s at 2 s demo polls, or 15-18 s apart at 1 s polls in the device runs, where 9/9 incidents reached the 3 h stage (`ref_device_runs`).

Evidence: `uc_time_to_insight`, `ref_device_runs`. Decision: G07 ("Batched NPU daemon (htpd) for multi-agent incidents").

**Q8. Does it need the internet or a server?**

No: inference, statistics, safety checks and storage all run on the QIDK; no campus data leaves the site.

Everything runs on the board (`uc_edge_offline`): sensor data, inference, statistics, the policy gate and the incident store. 0 bytes leave campus per incident. One agent call takes 2.543 s on the genied NPU path, or 1.13 s per agent when 13 run in one htpd batch. The Android app reaches the NPU through the board's own adbd on 127.0.0.1:5555, because apps cannot open the NPU directly. Energy per incident has not been measured: there is no free power rail.

Evidence: `uc_edge_offline`. Decision: G01 ("Everything runs on the board's NPU, not in the cloud").

**Q9. Can it explain problems that span several systems?**

Yes: in multi-sensor incidents NPU agents examine up to 4 domains and one report names a single root cause; all 4 multi-sensor incidents spanned 2-4 domains.

From the final app stress run (`uc_cross_domain`):
- Crowded room: 2 agents, 3 NPU calls, 2 domains, 7.525 s.
- Three chaos incidents: 4 domains each, with 12/13, 10/11 and 11/12 agents/NPU calls, about 20.6-20.8 s.
- Every report was policy-valid, and each names one root-cause label.
The 4 incidents are the crowded room (2 domains) and three chaos runs (4 domains each); the app check "names several domains" passed 3/3 on the chaos runs. Caveat: independent root-cause ground truth (cross-domain injections) is planned, not done. So this shows the system produces cross-domain reports, not that their causes are correct.

Evidence: `uc_cross_domain`. Decision: G03 ("Multi-agent incidents (Mode 3) with rules and single-call baselines").

**Q10. Walk me through one incident.**

Crowded room: CO2 and power abnormal for 8 readings, 4 s batch window, 2 domain agents (7.1 s), synthesizer (4.5 s), then the operator decides.

Phases from the Genie/genied-era trace (`uc_example_incident`): gate 16 s, batch window 4 s, 2 domain agents 7.112 s, synthesizer 4.457 s, app overhead 0.011 s. That is about 32 s from the first abnormal reading to an approval-ready report. On htpd v6 the same scenario's analysis took 7.525 s (3 NPU calls). After that the operator approves or dismisses, and refinements re-read at +1.5 h and +3 h. See section 7.5 (crowded room).

Evidence: `uc_example_incident`. Decision: G03 ("Multi-agent incidents (Mode 3) with rules and single-call baselines").

**Q11. Will it ever switch something off by itself?**

Never: the policy gate forbids actuation; 100% of agent answers passed the gate in the final app test and every action waits for a person.

The policy gate rejects any actuation. Only advisory actions such as inspect_ventilation or check_sensor are whitelisted (`uc_human_in_loop`). Final app: 44/44 agent answers passed the gate, with 0 actions executed without approval. On the host eval, evidence ids were valid 150/150 for the fine-tune vs 52/150 for the base model. The approval state is stored per incident, and a refinement never changes it.

Evidence: `uc_human_in_loop`. Decision: G05 ("Safety: a policy gate on every answer").

**Q12. What does it take to run in the field?**

One QIDK board on DC power with a heatsink; it idles at ~43 C and peaks ~95 C only when every sensor fails at once.

Thermals (`hw_board_thermal`): idle is 43 C after the UI power fix, against 75 C with the earlier dashboard and 50 C on any tab before that. It reaches 63-69 C right after inference and 96 C at htpd chaos peaks. Guard: pause above 88 C NPU / 60 C skin, and before an NPU call at 88 C or more, wait up to 15 s for 82 C. Power: use the DC adapter, because USB power browned out at peak (`ops_incidents`). Energy per incident is not measured (`uc_edge_offline`).

Evidence: `uc_edge_offline`, `hw_board_thermal`. Decision: G20 ("Keep the board cool and powered").

### Situations (5)

**Q13. What does the system do for a ventilation failure?**

It raises one air-quality incident, identifies insufficient ventilation, and recommends an inspection; the final on-board run completed it in 7.4 s.

Final app, INC-0530 (`ux_scenario_outcomes`): 1 agent, 1 NPU call, 7.426 s, pattern exponential_increase, label ventilation_issue, action inspect_ventilation. Mode 2 gave the same label in 6.205 s (`ux_mode2_vs_mode3_latency`). The refinement run (`ref_device_runs`, INC-0616) went from warning early to critical at 1.5 h and 3 h. Full story in section 7.5.

Evidence: `sit_ventilation_failure`, `ux_scenario_outcomes`, `ux_mode2_vs_mode3_latency`. Situation card: `ventilation_failure`.

**Q14. What does it do when a water tank is leaking?**

The immediate 4-hour run completed in 3.1 s but called the slow leak normal with no action; the 12-hour check found the slow drift (-65 over 12 h) and raised it to warning at the 1.5 h re-read on the board.

This is an honest-limit answer: the 4 h agent misses it and the 12 h check catches it.
- Final app INC-0534: the agent saw "stable", label normal_operation, action none, in 3.080 s (`ux_scenario_outcomes`). The report surfaced the rule/AI disagreement.
- Refinement run 1 (INC-0610): the 12 h drift check fired but did not raise severity.
- After the fix, run 2 (INC-0612, `sit_tank_leak`): early normal (4.899 s). At 1.5 h, warning with "slow drift -64.5 level over 12 h (r2 0.85, 32.3x normal variation)" (1.594 s). At 3 h, warning with -65.1 (1.758 s). The "-65" in the short answer is the 3 h value. The label stayed normal_operation; only severity and title changed (`ref_device_runs`).
- Mode 2 said water_supply_issue in 4.119 s.
- The 12 h checks need at least 8 h of history.

Evidence: `sit_tank_leak`, `ux_scenario_outcomes`, `ux_mode2_vs_mode3_latency`, `ref_device_runs`. Situation card: `tank_leak`.

**Q15. What happens when several systems fail together?**

It groups the incident, sends one agent per affected domain, and gives the operator one safety-checked report; 10–12 agents plus synthesis completed in about 21 s.

Chaos results on htpd v6 (`uc_cross_domain`, `ux_chaos_incidents`):
- 12 agents / 13 calls: 20.698 s.
- 10 / 11: 20.617 s. Here the synthesizer was rejected by policy and a fallback report was built from the agents.
- 11 / 12 staggered: 20.752 s.
- Genie needed 48.9 s (13 agents) and 40.8 s (9 agents).
- There is no agent cap. AI/rule disagreements are written into the report.
- Heat is the limit: chaos peaks are 95-96 C.

Evidence: `sit_chaos`, `ux_scenario_outcomes`, `ux_chaos_incidents`, `uc_cross_domain`. Situation card: `chaos`.

**Q16. What happens when a sensor gets stuck?**

The agent calls the frozen reading a flatline and a sensor fault (not an emergency) and recommends checking the sensor; 2.6 s on the board, unchanged at 1.5 h and 3 h.

Measured stuck-sensor runs:
- Final app INC-0536: flatline, sensor_fault, "Temperature frozen at exactly 25.0 C for 24 consecutive samples", label sensor_fault, action check_sensor, 2.425 s (`ux_scenario_outcomes`).
- Refinement run 3, INC-0617 (`sit_stuck_sensor`): early 2.590 s, refined 1.435 s and 1.445 s, sensor_fault/flatline at every stage, no 12 h finding.
The point for the operator: send a technician to the sensor, not an evacuation. Contrast: the rejected LADE speed-up turned a stuck sensor into "normal" (`lat_rejected_ideas`).

Evidence: `sit_stuck_sensor`, `ux_scenario_outcomes`. Situation card: `stuck_sensor`. Decision: G17 ("Severity, titles and the report follow the AI").

**Q17. What happens when the AC runs in an empty room?**

Not yet measured: the switch_off_ac recommendation is part of the v2 retrain and will need operator approval like every action.

There is no evidence chart for this question; it has no dataset id. `situations_index.json` marks it measured: false, "Not yet measured on the board". The switch_off_ac recommendation (AC on, room empty) is part of the v2 retrain (D119). Like every action it is advisory and needs operator approval (policy gate, G06). Do not quote a timing or accuracy for it.

Evidence: none (no measured dataset). Situation card: `ac_empty_room`. Decision: G06 ("Disagreements are shown, decisions stay human").

### Accuracy (10)

**Q18. Against what did you measure accuracy?**

Exact labels from known patterns injected into real calm sensor windows of held-out months (Nov-Dec 2025), plus rules (Mode 1) and the base model on the same windows.

Ground truth is known patterns (step, spike, drift and so on) injected into real calm windows of held-out months.
- v1 eval: 150 windows (`acc_v1_host_eval`).
- Window study: 604 cases x 4 lengths (`ad_window_headline`).
- v2 adds about 15% of sensors held out entirely (`ds_roles`).
- Baselines on the same windows: rules (Mode 1, pattern 68%) and the base model (20%).
- Status, cause and action labels come from the same teacher rules, so only pattern is an independent comparison.

Evidence: `acc_v1_host_eval`, `ds_roles`, `ad_window_headline`. Decision: G13 ("Honest ground truth and statistics"), D010.

**Q19. What is the headline accuracy?**

Pattern accuracy 94% fine-tuned vs 20% base vs 68% rules on 150 held-out windows (laptop); 90.7% on the QIDK NPU (n=54).

Laptop, 4-bit, 150 windows (`acc_v1_host_eval`): pattern fine-tuned 0.94 (141/150, CI 0.89-0.968), base 0.20 (30/150), rules 0.68 (102/150). The fine-tune also scores status 0.927, cause 0.933, action 0.907, and 100% valid JSON and evidence. On the QIDK NPU, 54 windows (`acc_device54_engines`): htpd final pattern 0.907 (49/54, CI 0.80-0.96), status 0.944, cause 0.870, and JSON/evidence/policy 54/54.

Evidence: `acc_v1_host_eval`, `acc_device54_engines`. Decision: G02 ("Fine-tune one Llama 3.2 3B for every domain role"), D009.

**Q20. Is the comparison with the rules fair?**

For pattern on air, water, power and weather yes (92.5% vs 60.0%); occupancy labels and status/cause/action are circular, so we lead with pattern.

On air, water, power and weather (120 windows) pattern accuracy is 92.5% (111/120) vs 60.0% (72/120) for the rules (`acc_v1_rules_vs_llm_fair`). Per role the fine-tune scores 87-100% and the rules 53-63% (`acc_v1_host_per_role`). Occupancy is excluded because its labels come from the same logic as the rules, so the rules score 100% by construction. HANDBOOK 2.36 also quotes the rules at 68.6% on all 900 test windows (prose only, no per-sample file).

Evidence: `acc_v1_rules_vs_llm_fair`, `acc_v1_host_per_role`. Decision: G13 ("Honest ground truth and statistics"), D067.

**Q21. Is your 93% cause accuracy independent reasoning?**

No: cause labels come from the same teacher rules Mode 1 runs, so it shows the model imitates the taxonomy; independent 'why' truth needs cross-domain injections or facility logs.

The cause label is produced by the teacher rules that generated the training data, the same rules Mode 1 runs (`acc_v1_rules_vs_llm_fair` notes). So 93.3% cause accuracy (`acc_v1_host_eval`) means the model reproduces the taxonomy from the window, not that it independently discovered why something happened. Independent "why" ground truth would need cross-domain injections or facility maintenance logs. Both are planned.

Evidence: `acc_v1_rules_vs_llm_fair`. Decision: G13 ("Honest ground truth and statistics"), D066.

**Q22. Why does accuracy matter here?**

A wrong pattern drives the wrong cause and action: LADE turned a stuck sensor into 'normal', which an operator would ignore.

LADE lookahead decoding cut time by 32.5%, but answers changed (1 in 14 identical) and a stuck sensor became "normal" (`lat_rejected_ideas`). A wrong pattern propagates into the cause and the action, and "normal" means no action at all. That is why every speed-up is gated on output identity and accuracy is measured on device (`acc_device54_engines`). This is the policy "never trade accuracy for latency".

Evidence: `lat_rejected_ideas`, `acc_device54_engines`. Decision: G10 ("Reject speed-ups that change answers or do not pay"), D037.

**Q23. Why is the device lower than the laptop?**

4-bit quantisation on the NPU plus a double-BOS prompt bug; GPTQ and the BOS fix took the device from 54% to 85%, and htpd to 91%.

Waterfall on the same 46 windows (`acc_quant_waterfall`):
- Laptop NF4: 0.94.
- First NPU export (w4a16): 0.543.
- MSE-clipped scales: 0.391.
- GPTQ + base ranges: 0.674.
- Recalibrated ranges: 0.609.
- BOS fixed: 0.826.
The double-BOS bug happened because Genie adds BOS itself (606 host tokens became 607); fixing it alone took 67% -> 83% (`acc_pipeline_parity`). On the 54-window set: Genie 0.852 and htpd final 0.907 (`acc_device54_engines`).

Evidence: `acc_quant_waterfall`, `acc_device54_engines`. Decision: G12 ("Prove the device runs exactly what was trained"), D016.

**Q24. How big are your test sets and how wide are the CIs?**

150 windows on the laptop (+-~4 points), 54 on the device (+-~8-10), 604 cases x 4 lengths in the window study and 208 x 6 in the placement study; every chart shows Wilson 95% CIs.

The CIs are Wilson 95%.
- Host 150: pattern 0.94 has CI 0.89-0.968 (`acc_v1_host_eval`).
- Device 54: 0.907 has CI 0.80-0.96, about 1 window per class (`acc_device54_engines`).
- Window study: 369 labelled cases, 364 injected events, 77 calm windows, 2,416 NPU calls (`ad_window_headline`).
- Placement study: 208 events x 6 onsets = 1,248 NPU calls (`ad_placement_curve`).
Paired comparisons use McNemar tests.

Evidence: `acc_v1_host_eval`, `acc_device54_engines`, `ad_window_headline`, `ad_placement_curve`. Decision: G13 ("Honest ground truth and statistics"), D068.

**Q25. Is htpd really better than Genie, 90.7% vs 85.2%?**

Not significantly: paired McNemar p=0.45 on 54 windows; the claim is 'no worse while twice as fast'.

Paired on the same 54 windows (`acc_device54_engines`): htpd final got 5 windows right that Genie got wrong, and Genie got 2 that htpd got wrong, exact p = 0.453. Status p = 0.289. Wall time for all 54: htpd v1 136 s, final 78.6 s. Both reach 54/54 on JSON, evidence and policy. Say "no worse, and about twice as fast on big incidents", not "more accurate".

Evidence: `acc_device54_engines`. Decision: G07 ("Batched NPU daemon (htpd) for multi-agent incidents"), D083.

**Q26. What happened to the 900-window device rerun?**

It stopped after 39 windows on a one-off socket stall at 91 C; the full rerun is still to do.

The folded `acc_test900_partial` in `acc_device54_engines`: the run stopped after 3 batches of 13 (39 windows) on a one-off socket TimeoutError at 91 C. It is shown only for completeness, with wide CIs. The full 900-window rerun is still to do.

Evidence: `acc_device54_engines`.

**Q27. Do you have per-sample predictions?**

Yes for the device sets, window and placement studies (scores and labels, no inputs) in the data packs; the original laptop eval kept only aggregates.

Per-sample rows exist for the 54-window device sets (Genie and htpd, `acc_device54_engines`), the window study (`ad_window_headline`) and the placement study (`ad_placement_curve`). They are published as scores and labels without raw sensor inputs, because the data stays private. The original v1 laptop eval (`eval_agents.py`) kept only aggregates. That is why `acc_v1_host_eval` has no McNemar test and reconstructs k as round(rate x 150).

Evidence: `acc_device54_engines`, `ad_window_headline`, `ad_placement_curve`. Decision: G13 ("Honest ground truth and statistics"), D068.

### Status quo (3)

**Q28. Why is this better than the status quo (threshold alarms)?**

At the same detection rate (78% vs 78% at 4 h) the agent raises fewer false alarms (27% vs 43%) and explains each alert with cited evidence.

On the same 4 h windows (`ad_window_rules_vs_agent`): agent detection 0.775 vs rules 0.78. Agent false alarms 0.273 (21/77) vs rules 0.429 (33/77). At 8 h and 12 h the rules' false alarms climb to 0.636 and 0.701. Each agent answer passes the policy gate with real evidence ids (`ad_policy_gate`). The rules give a threshold crossing only.

Evidence: `ad_window_rules_vs_agent`, `ad_policy_gate`.

**Q29. What do rules miss that the AI catches?**

Shape: rules name the pattern correctly 60% of the time on the fair roles vs 92.5% for the agent; with 12 h checks old steps 73% -> 93%.

Pattern on the four fair roles: 92.5% vs 60.0% (`acc_v1_rules_vs_llm_fair`). Old steps (2.5-8 h ago): the 4 h agent alone catches 73.3% (44/60). Adding the 12 h CPU checks brings it to 93.3% (56/60), and slow drift goes from 83.3% to 95% (57/60), with no new false alarms (`ad_longrange_arms`). The rules see a crossing. The agent names the shape (step, exponential, flatline...), and the shape decides the cause and action.

Evidence: `acc_v1_rules_vs_llm_fair`, `ad_longrange_arms`.

**Q30. Why not send everything to a cloud LLM?**

Privacy (occupancy reveals presence), bandwidth, and it fails when the link does; everything here runs on the board with no internet.

Occupancy reveals presence, and the campus has 7 occupancy sensors (`uc_coverage`). Sending 33.2 M readings a year off site costs bandwidth, and a cloud path fails when the link does. On the board, 0 bytes leave campus per incident (`uc_edge_offline`), and one agent call is 1.13-2.543 s on the NPU. Raw data stays private by policy (G30), and only aggregates are published.

Evidence: `uc_coverage`, `uc_edge_offline`. Decision: G30 ("Private data, public evidence"), D069.

### Hardware (5)

**Q31. Why the NPU and not the GPU?**

Same weights on the Adreno GPU: ~8.4 s per agent, no batching gain, slower than the NPU at every incident size.

Placement grid, same incidents (`hw_grid`):
- 1 agent: GPU 10.01 s vs Genie NPU 3.93 s.
- 13 agents + synthesizer: GPU 137.6 s vs NPU 53.62 s.
- GPU peaks are 87-96 C.
Batching does not help the GPU (`hw_gpu_batched`): 1 stream decodes 16.7 tok/s, and 8 streams together only 12.4 tok/s. Prefill is about 195 tok/s on the GPU vs about 970 on HTP and 1,380 in Genie.

Evidence: `hw_grid`, `hw_gpu_batched`. Decision: G21 ("GPU study: decided by data"), D073.

**Q32. Did you try GPU + NPU together (hybrid)?**

Yes; hybrid placements were slower too, because both engines share the same LPDDR5X bandwidth.

Hybrid placements (agents on GPU, synthesizer on NPU) were also slower (`hw_grid` notes, HANDBOOK 2.37). The reason is memory bandwidth: decode streams 2.20 GB of weights per token, and at 22.4 tok/s that is 49.3 GB/s. That is about 84% of the 59 GB/s NPU DMA ceiling, and the whole-device practical peak is 68 GB/s (`lat_call_breakdown`, folded `lat_bandwidth_roof`). Two engines sharing that bus cannot add throughput.

Evidence: `hw_grid`, `lat_call_breakdown`. Decision: G21 ("GPU study: decided by data"), D073.

**Q33. Do GPU answers match NPU answers?**

At ctx 4096 the GPU produced no valid JSON; at ctx 1024 pattern agreed in 8/12 agent calls; llama.cpp HTP agreed 22/26.

Agreement with the Genie answer for the same agent prompt (`hw_grid_agreement`), not accuracy against ground truth:
- GPU at ctx 4096: 0/28 valid JSON.
- GPU at ctx 1024: pattern 8/12, status 9/12, cause 9/12.
- llama.cpp HTP (13 streams or sequential): pattern 22/26, status 23/26, cause 21/26, valid JSON 27/27.
HANDBOOK 2.37 quotes 82% GPU agreement from a wider check.

Evidence: `hw_grid_agreement`. Decision: G21 ("GPU study: decided by data"), D071.

**Q34. Why did the board reboot during GPU tests?**

GPU and NPU buffers are unmovable and must fit a 7.26 GB zone; the OOM killer picked system processes; the ladder now protects them.

GPU (kgsl) and NPU buffers cannot be moved and must fit in the 7.26 GB Normal memory zone. Genie alone holds about 3.1 GB (`hw_grid` folded `hw_gpu_bringup_failures`). The first GPU runs were killed by the out-of-memory killer, which picked system processes and rebooted the board. A "ladder" bring-up script now protects them. `ops_incidents` lists every crash with its cause and fix.

Evidence: `hw_grid`, `ops_incidents`. Decision: G21 ("GPU study: decided by data"), D072.

**Q35. Can the Android app use the NPU directly?**

No on this firmware (err 14001 in the sandbox); the app starts the backend as the shell user through the board's own adbd.

Paths tried (`uc_edge_offline`, folded `hw_platform_paths`):
- A11, an APK running Genie in the app sandbox, FAILED with error 14001: the vendor DSP service refuses apps, also in permissive mode.
- A12, shipped: the app asks the board's own adbd (127.0.0.1:5555) to start the backend as the shell user.
- A13, JNI against the Genie C API, was deferred because the sandbox still cannot open the NPU.
Note for the safety question: adb has no auth on this dev kit.

Evidence: `uc_edge_offline`. Decision: G01 ("Everything runs on the board's NPU, not in the cloud"), D006.

### Model (3)

**Q36. Why fine-tune instead of prompting?**

The base model is 20% on pattern, cites invalid evidence 65% of the time and writes ~199 tokens; fine-tuned: 94%, 100% valid, 84 tokens.

On 150 held-out windows (`acc_v1_host_eval`):

| metric | base | fine-tuned |
|---|---|---|
| pattern | 0.20 | 0.94 |
| cause | 0.18 | 0.933 |
| evidence ids valid | 0.347 (52/150) | 1.0 |

Answer length (`acc_v1_output_tokens`): 198.7 tokens for the base vs 83.8 for the fine-tune. Decode is about 70% of a call, so shorter answers are also faster.

Evidence: `acc_v1_host_eval`, `acc_v1_output_tokens`. Decision: G02 ("Fine-tune one Llama 3.2 3B for every domain role"), D009.

**Q37. Why Llama 3.2 3B?**

It fits the NPU memory budget with one resident model, has a Qualcomm reference export, and decodes ~22-25 tok/s on V75.

Memory: one Genie session of the 3B is about 3.7 GB resident, inside a 7.26 GB Normal zone (`hw_board_thermal`, folded `hw_memory`). Speed: decode runs at about 22-23 tok/s in the profiler (`lat_call_breakdown`) and 24.5-26.5 tok/s per agent in the Genie reference runs (`hw_grid`). A Qualcomm AI Hub export path exists for Llama 3.2 3B (path A8 in `hw_platform_paths`).

Evidence: `hw_board_thermal`, `lat_call_breakdown`. Decision: G02 ("Fine-tune one Llama 3.2 3B for every domain role"), D002.

**Q38. Why one model for all roles?**

Two full models cannot be resident: loading a second 3B rebooted the board with 5.8 GB free.

Loading the base 3B beside the resident fine-tune (genied) rebooted the board with 5.8 GB free (`hw_board_thermal`, folded `hw_memory`, HANDBOOK 2.27). So all roles (5 in v1, plus HVAC in v2) share one fine-tuned model with role-specific prompts. A separate cross-domain reasoner is parked: it would have to be swapped in per incident (about +1.5 s), and LoRA adapters inside one context binary are the recommended route (folded `ad_reasoner_plan`).

Evidence: `hw_board_thermal`. Decision: G03 ("Multi-agent incidents (Mode 3) with rules and single-call baselines"), D046.

### Agent design (7)

**Q39. Why multi-agent (Mode 3) instead of one call (Mode 2)?**

Each sensor gets a specialist reading of its own window with evidence ids the gate can check; on the final build Mode 3 is also not slower (median 3.4 s vs 4.2 s).

Final build, the same 10 scenarios run once each (`ux_mode2_vs_mode3_latency`):
- Mode 3 median 3.4 s vs Mode 2 median 4.2 s.
- 11/11 Mode 3 agent answers were policy-valid.
- In the earlier Genie era, Mode 2 took about 9 s for one all-sensor call (folded `ad_modes_latency`).
Mode 3 keeps each prompt to one sensor's 4 h window, which is the format the model was trained on. That is also why the gate can check each evidence id.

Evidence: `ux_mode2_vs_mode3_latency`. Decision: G03 ("Multi-agent incidents (Mode 3) with rules and single-call baselines"), D008.

**Q40. Is Mode 3 more accurate than Mode 2?**

Not measured yet on a labelled grid; that comparison (600-incident grid) is planned, so we do not claim it.

Honest-limit answer. `ux_mode2_vs_mode3_latency` is latency only, one run each. On those single runs Mode 2 gave different labels on several scenarios: hvac_or_thermal_issue for power throttling, weather_driven for crowded room, and ventilation_issue for heat buildup and off-hours presence. That is anecdotal. A labelled grid of about 600 incidents is planned (HANDBOOK 2.36 plan B).

Evidence: `ux_mode2_vs_mode3_latency`. Decision: G13 ("Honest ground truth and statistics"), D066.

**Q41. Why a 4-hour window?**

Measured: 4 h gives the best pattern accuracy (64% vs 46/56/42% at 2/8/12 h, p<0.0001) for the model trained on it.

Window study, 604 cases x 4 lengths = 2,416 NPU calls (`ad_window_headline`). Pattern accuracy: 2 h 0.458, 4 h 0.637, 8 h 0.558, 12 h 0.425. Status and cause also peak at 4 h (0.699 and 0.675). Paired McNemar: 4 h beats every other length on classic patterns, p < 0.0001 (folded `ad_window_paired`). The model was trained on 4 h windows, so other lengths are out of distribution.

Evidence: `ad_window_headline`. Decision: G14 ("Keep the 4 h window for the domain agent"), D084.

**Q42. But longer windows catch old changes, why not 12 h?**

12 h catches old steps (100%) but misnames them, raises false alarms 27% -> 46% and costs +32%; cheap 12 h CPU checks give 93% without that.

From `ad_window_old_events`: at 12 h the agent catches 100% (60/60) of old steps but often misnames them. Of 39 sub-threshold "detections", 25 are the agent calling the window flatline. False alarms at 12 h are 0.455 vs 0.273 at 4 h (`ad_window_headline`). The 12 h CPU detectors on top of the 4 h agent give old steps 93.3% and drifts 95%, with false alarms unchanged at 12/39 (`ad_longrange_arms`). The +32% cost is quoted from the short answer.

Evidence: `ad_window_old_events`, `ad_longrange_arms`. Decision: G16 ("12 h CPU checks feed the reasoner"), D090.

**Q43. When is the AI called?**

Only after a warning/critical/fault status lasts 8 readings (~16 s); 2,000 calm readings produced 0 incidents.

Gate rules (`uc_alert_reduction`, folded `ad_event_gate`):
- Persist 8 readings, because agents were trained on events at least 7 readings old.
- Re-arm only after the sensor returns to normal.
- No agent cap (it was 3, then 8).
- The batch window closes after 1 reading if no other sensor is abnormal-but-young.
Measured: 2,000 calm readings gave 0 incidents, and a 90 s random drift in the stress test gave none.

Evidence: `uc_alert_reduction`. Decision: G04 ("Alert only on persistent abnormal status (event gate)"), D021.

**Q44. Why re-analyse at 1.5 h and 3 h?**

At alert time the event is ~40 min old and pattern accuracy is 42%; it rises to 67% at 1.5 h and 88% at 3 h on the same events.

Placement study, 208 events x 6 onsets, 1,248 NPU calls (`ad_placement_curve`). Pattern accuracy: 20 min 0.236, 40 min 0.423, 1 h 0.572, 1.5 h 0.668, 2 h 0.76, 3 h 0.885. Paired: 105 events right at 3 h that were wrong at 40 min, 9 the other way (p < 0.0001). On device (`ref_device_runs`): power throttling went from exponential_increase to throttling at 1.5 h, and ventilation from warning to critical. 9/9 incidents reached 3 h.

Evidence: `ad_placement_curve`, `ref_device_runs`. Decision: G15 ("Early alert, then refined re-reads at 1.5 h and 3 h"), D087.

**Q45. What if the AI and the rules disagree?**

The report states the conflict; neither overrides. In stress tests the AI was right 2 of 3 times.

Policy rule (HANDBOOK 2.33): if an agent says normal while the rule view of the same sensor is warning/critical, the report says so explicitly ("AI and rules disagree ... review before deciding"). In stress tests (`ad_policy_gate`, folded `ad_disagreement`) there were 3 disagreements in 18 calls. The rule was right once (a missed pump oscillation) and the AI was right twice (a CO2 episode that had already cleared). The tank leak in section 7 is a live example.

Evidence: `ad_policy_gate`. Decision: G06 ("Disagreements are shown, decisions stay human"), D055.

### False alarms (4)

**Q46. How many false alarms?**

On real calm test windows the 4 h agent flags 27% (rules 43%); a strict-clean subset gives 5%, because real 'calm' data contains real events.

Window study, 77 calm windows (`ad_window_rules_vs_agent`): the 4 h agent flags 21 (0.273), the rules 33 (0.429). On a strict-clean subset of 19 windows the agent flags 1/19 (0.053) at 2 h and 4 h, and 0/19 at 8 h and 12 h (`ad_window_headline`). "Calm" real data contains real events, so 27% over-counts true false alarms.

Evidence: `ad_window_rules_vs_agent`, `ad_window_headline`.

**Q47. Do the 12 h checks add false alarms?**

No: on piecewise-calm windows the combination stays at 31% (12/39) with 0 new alarms.

On piecewise-calm test windows (`ad_longrange_arms`), the 4 h agent alone and agent + 12 h detectors both flag 0.308 (12/39). The detectors alone flag 1/39. Gains: +12 old steps (p = 0.0005) and +7 drifts (p = 0.016), with 0 lost. They were tuned on dev months (Sep-Oct) and tested once on Nov-Dec. They fire on 10% (16/160) of random real windows.

Evidence: `ad_longrange_arms`. Decision: G16 ("12 h CPU checks feed the reasoner"), D090.

**Q48. Why did you drop the daily baseline?**

It raised more false alarms (29% vs 20%) and caught half the old steps (48% vs 86%): yesterday has its own events.

Test months (`ad_daily_baseline_rejected`): the "same hours yesterday" baseline raised false alarms on clean windows to 0.287 (23/80) vs 0.20 (16/80) for the raw 12 h detectors, and caught 0.48 of old steps vs 0.86. On the dev-month tuning frontier at 15% false alarms, raw 12 h catches 64% of old steps and the daily baseline 22.7% (`ad_detector_tuning_frontier`). Yesterday has its own events, so subtracting it adds noise instead of cancelling routine.

Evidence: `ad_daily_baseline_rejected`, `ad_detector_tuning_frontier`. Decision: G16 ("12 h CPU checks feed the reasoner"), D092.

**Q49. How will v2 reduce false alarms?**

It is trained on routines that look like alarms (refills, load switching, daily cycles) labelled normal; acceptance requires fewer than today's 31%.

The v2 data has 8,292 routine "hard negative" rows (`ds_routine`) across 23 kinds, all labelled normal. The largest kinds are overflow 1,062, outdoor PM 1,044, load cycling 793, refills 785 and draining 572, plus night setback, weekend off, short-cycling and others. Acceptance needs a false-alarm rate below today's 31% on the same calm windows.

Evidence: `ds_routine`. Decision: G24 ("v2 data: teach what v1 missed and what is normal"), D105.

### Latency (7)

**Q50. Where does the time go in one AI call?**

Decode ~70%, init ~18%, prefill ~11%; decode is at ~84% of the NPU's memory-bandwidth ceiling.

Genie profiler, 548-token prompt, 59 tokens out, 3 runs (`lat_call_breakdown`): init 694.7 ms, prefill 397.0 ms, decode 2,646.3 ms. That is decode about 71%, init about 19%, prefill about 11%. Prefill runs at about 1,380-1,481 tok/s and decode at about 22-23 tok/s. Measured read bandwidth during decode is 49.3 GB/s vs the 59 GB/s DMA ceiling (folded `lat_bandwidth_roof`), so configuration knobs can save about 440 ms at most.

Evidence: `lat_call_breakdown`. Decision: G10 ("Reject speed-ups that change answers or do not pay"), D035.

**Q51. How fast is an incident now?**

Typical Mode 3 incident median 3.8 s; a 12-agent chaos incident 20.7 s (was ~47 s on Genie).

Through the app (`lat_chaos_genie_vs_htpd`): 12 agents + synthesizer 47 -> 20.7 s, 10 agents 43.5 -> 20.6 s, 11 staggered 53 -> 20.8 s. The Mode 3 median is 3.8 s on both engines. The final htpd v6 stress run passed 132/135 checks with a Mode 3 median of 3.8 s. The Genie final regression passed 238/240 with a median of 3.5 s (`ux_stress_runs`).

Evidence: `lat_chaos_genie_vs_htpd`, `ux_stress_runs`. Decision: G07 ("Batched NPU daemon (htpd) for multi-agent incidents"), D074.

**Q52. What were the biggest latency wins?**

Batching all agents in one weight sweep (htpd), drafting, ctx 2048 (-721 ms/call), the persistent daemon (3.6 -> 2.5 s/call) and the batch window (-4 s).

Measured wins:
- htpd route for 13 agents: 23.5 s (Genie) -> 28.1 s (htpd v1) -> 17.5 s (v4: HMX pipe + drafting) -> 15.5 s (v5 prefix cache) -> 14.7 s (v6) (`lat_route_13_agents`).
- ctx 2048: 20.7 -> 25.0 tok/s, 14/14 identical (`lat_ctx2048`).
- genied: 3,640 -> 2,543 ms per call, first token 1.2 s -> 0.31 s (`lat_genied`).
- Batch window: 6 -> 2 s isolated, 6 -> 4 s cross-domain (`lat_batch_window`).

Evidence: `lat_route_13_agents`, `lat_ctx2048`, `lat_genied`, `lat_batch_window`.

**Q53. What did you try that failed?**

LADE (fast but 1/14 identical), grammar decoding (+440 ms), continuous batching (truncated answers), parallel sessions (3x slower), GPU (slower).

From `lat_rejected_ideas` (time change vs shipped):

| idea | time change | why rejected |
|---|---|---|
| LADE | -32.5% | answers changed |
| continuous batching | -76% | the speed-up was truncated answers |
| grammar decoding | +18.1% | +440 ms init, 0 tokens saved |
| 3-graph bundle | +14.8% | slower on every call |
| two parallel NPU sessions | +224.2% | |
| DSP RPC knobs | +1.6% | within noise |

GPU: slower at every incident size (`hw_grid`).

Evidence: `lat_rejected_ideas`, `hw_grid`. Decision: G10 ("Reject speed-ups that change answers or do not pay"), D037.

**Q54. Did any speed-up change the answers?**

Every shipped change was gated on output identity (14/14, 28/28, 16/16, 25/25) against the run-to-run noise floor; ones that changed answers were rejected.

Identity gates (`acc_pipeline_parity`):
- 400/400 prompts byte-identical to training.
- 1,232 GPTQ tensors reproduced.
- 11,711 activation encodings matched.
- verify_batch 16/16, daemon 28/28, ctx 2048 vs 4096 14/14, two-window gate 5/5.
htpd v6 vs v5 was 25/25 identical, against a run-to-run noise floor of 21-24/25 for the same binary (`lat_htpd_ab`). LADE and continuous batching were rejected for changing answers.

Evidence: `acc_pipeline_parity`, `lat_htpd_ab`. Decision: G07 ("Batched NPU daemon (htpd) for multi-agent incidents"), D082.

**Q55. How much of the incident time is your app, not the model?**

About 11 ms in a 11.6 s three-call incident.

Phase trace of a real 3-call crowded_room incident (`lat_route_incident`, folded `lat_phase_trace`): agents 7,112 ms, synthesizer 4,457 ms, total 11,570 ms, of which about 11 ms is non-model time. The same incident's route: 18,691 ms (Genie CLI, no batching) -> 17,726 ms -> 17,393 ms -> 14,727 ms (ctx 2048) -> 11,570 ms (genied, zero gap).

Evidence: `lat_route_incident`. Decision: G04 ("Alert only on persistent abnormal status (event gate)"), D048.

**Q56. Will v2 be slower?**

Possibly at first (+40-60 prompt tokens); the policy is accuracy first, then a latency pass back to <= 14.7 s (13 agents) and <= 3.8 s typical.

v2 prompts average 732.5 tokens (train) and generation stops at about 76 tokens before the derived action (`ds_tokens`). The 548-token prompt in the v1 profile (`lat_call_breakdown`) is not the same population as the v2 means, so do not subtract one from the other. The extra 40-60 tokens is the figure quoted in the short answer. Targets: 13 agents at or below 14.7 s (`lat_route_13_agents`) and a typical incident at or below 3.8 s. Accuracy first, then latency.

Evidence: `lat_route_13_agents`, `ds_tokens`. Decision: G22 ("Retrain the domain agents (v2) instead of patching"), D114.

### Data (7)

**Q57. What data did you use?**

IIIT-H campus sensor data for 2025: 14 CSVs, 4.6 GB, ~37 M rows across air, water, power, occupancy, weather and HVAC.

`uc_coverage` and folded `ds_source_data`. Rows (M) per file:

| file | rows (M) | nodes |
|---|---|---|
| SR-AC (HVAC) | 11.5 | 87 |
| outdoor air | 9.5 | |
| SR-AQ (indoor air) | 7 | |
| solar / LT panels | 1.8 | |
| water flow | 1.7 | |
| main energy meters | 1.2 | |
| wireless network | 0.9 | |
| room energy | 0.7 | |
| tank level | 0.37 | |
| occupancy | 0.3 | |
| weather | 0.1 | |
| water quality | 0.03 | |

Data stays private on the laptop. Timestamps mix +00:00 and +05:30.

Evidence: `uc_coverage`. Decision: G27 ("Held-out sensors and data QA before training"), D107.

**Q58. How did you avoid leakage?**

Temporal split (train Jan-Aug, dev Sep-Oct, test Nov-Dec), a leakage check on every v2 row, and in v2 ~15% of sensors held out entirely.

v2 split (`ds_roles`): 35,946 train / 1,947 dev / 2,965 test rows, with duplicates dropped (9/2/1). Held-out sensors (`ds_heldout`): 25 sensors never seen in training (air 3, water 6, power 2, occupancy 1, HVAC 13; weather has only seen stations). That gives 1,221 test rows from unseen sensors (985 + 236 in Sep-Oct). The leakage check passes on all 40,858 rows (`ds_qa_checks`).

Evidence: `ds_qa_checks`, `ds_heldout`, `ds_roles`. Decision: G27 ("Held-out sensors and data QA before training"), D113.

**Q59. Are synthetic injections realistic?**

They ride on real calm windows from real sensors; a real-event set from facility logs is planned as a second ground truth.

Injections are added on top of real calm windows from real sensors, so noise and daily cycles are real (`ds_roles`). The limit is that the label comes from the injector, and status and cause come from the teacher rules (`acc_v1_rules_vs_llm_fair` notes). A second ground truth from real events in facility logs is planned.

Evidence: `ds_roles`, `acc_v1_rules_vs_llm_fair`. Decision: G13 ("Honest ground truth and statistics"), D066.

**Q60. Can we see the test cases?**

Yes as labels and per-sample scores (data packs); raw sensor windows stay private by policy.

`ad_window_per_family` gives detection and pattern accuracy per case family and window length. At 4 h, 83-100% of classic patterns are flagged, against 32% of recurring small spikes. `ad_placement_heatmap` gives pattern accuracy per pattern and onset age. Steps are right from 1 h; oscillation and gradual rises only at 3 h (gradual_increase is 0/21 at 40 min and 18/21 at 3 h). Raw sensor windows are not published (G30).

Evidence: `ad_window_per_family`, `ad_placement_heatmap`. Decision: G30 ("Private data, public evidence"), D069.

**Q61. What is in the v2 training data?**

35,946 rows over 6 roles, 21 window lengths (2-12 h), events of every age and size, 7 fault kinds, routines labelled normal, HVAC per unit.

Composition (`ds_roles`, `ds_families`, `ds_window_lengths`, `ds_event_age`, `ds_fault_kind`):
- Roles: air 6,498, water 6,455, power 6,500, occupancy 4,995, weather 4,999, HVAC 6,499.
- Families: event 10,294 (about 29%), fault 3,033, routine 1,959 + real routine 1,513, old shift 1,265, long drift 1,265, recurring 509, among others.
- Window lengths: 21, from 24 to 144 points (2-12 h).
- Event age: 8,744 rows at 1 h or less, 7,097 at 1-3 h, 10,809 over 3 h.
- Fault kinds: stuck 1,177, dropout 1,010, noise 969, bias 840, quantised 673, saturation 330, drift 248.

Evidence: `ds_roles`, `ds_families`, `ds_window_lengths`, `ds_event_age`, `ds_fault_kind`. Decision: G24 ("v2 data: teach what v1 missed and what is normal"), D104.

**Q62. How do you know the v2 data is correct?**

11 hard checks on 40,858 rows (JSON, enums, evidence ids, numbers, rebuild, leakage, duplicates...) with 0 failures, plus a 60-sample manual review.

From `ds_qa_checks`: the hard checks are json, enums, observation count, evidence ids, numbers matching the evidence, rebuild from the generator (33,459 rows), v1 prompt equality at 48 points (8,502), leakage, duplicates, amplitude and shape. There were 0 failures. Soft flags (generated tokens over 70: 24,658 rows) are tracked, not failed. A private 60-sample review page was also checked by hand.

Evidence: `ds_qa_checks`. Decision: G27 ("Held-out sensors and data QA before training"), D115.

**Q63. Why add HVAC?**

87 indoor AC units are the largest data source; faults like short-cycling or cooling an empty room were invisible to the other agents.

HVAC units are 87 sensors with 26.33 M readings, the largest source (`uc_coverage`). The rules call 98.45% of real 4 h HVAC windows normal: 73,036 windows labelled, 311,567 scanned (`ds_hvac_real_labels`). Real fault examples are rare (short_cycling 25, stuck_on 132, no_cooling_effect 194), so alarms are taught by injection. The HVAC unit tests pass 8/8.

Evidence: `ds_hvac_real_labels`. Decision: G26 ("Add an HVAC agent"), D100.

### Training (3)

**Q64. How is v2 trained?**

QLoRA on Llama 3.2 3B, r=32, 2 epochs = 4,494 steps, ~44 s/step recently on a 6 GB laptop GPU, in resumable sessions.

Setup (`tv2_plan`): Llama-3.2-3B-Instruct, QLoRA nf4, r=32 (48.6 M trainable; v1 was r=16 / 24.3 M), 2 epochs = 4,494 optimizer steps, grad accumulation 16, lr 0.0002, max length 1,280. That is 29,477,242 train tokens, 411 tok/s in the pilot at 4.58 GiB peak VRAM, and an estimated 39.8 h. Sessions resume from checkpoints (`tv2_sessions`).

Evidence: `tv2_plan`, `tv2_sessions`. Decision: G28 ("Train v2 on the laptop in resumable sessions"), D111.

**Q65. Is it overfitting?**

No sign so far: dev loss falls 0.131 -> 0.066 (best, step 2400) and train loss per token tracks it; the best checkpoint, not the last, is kept.

Dev loss every 300 steps (`tv2_loss_curve`): 0.1311 (step 300), 0.0985, 0.0923, 0.0809, 0.0772, 0.0685, 0.0682, 0.066 (step 2,400, epoch 1.07). The train loss per token is the logged loss divided by the 16 grad-accumulation steps, and it tracks dev. Dev loss is not accuracy: acceptance runs on the QIDK NPU afterwards. v1's 0.027 was on an easier dataset and is not comparable.

Evidence: `tv2_loss_curve`. Decision: G22 ("Retrain the domain agents (v2) instead of patching"), D112.

**Q66. Why did training take so long?**

Thermal pauses (5+ h), a blue screen, a thermal sleep, lid standby and supervisor deaths; each now has a guard.

Thermal guard (`tv2_thermal_pauses`): 1,181 pauses, about 5.6 h paused (build of 2026-10-19 20:13), GPU peak 87 C. The pause threshold dropped from 81 to 76 C after a thermal sleep. Power events (`ops_power_events`): 1 BSOD (0xD1 in the Hyper-V switch used by WSL), 1 thermal sleep, 6 lid standbys, 2 unclean reboots. All 8 interruption causes now have a guard (`tv2_interruptions`).

Evidence: `tv2_interruptions`, `tv2_thermal_pauses`, `ops_power_events`. Decision: G28 ("Train v2 on the laptop in resumable sessions"), D123.

### Thermals (3)

**Q67. How hot does the board get?**

Idle ~43-50 C; htpd chaos peaks 95-96 C, where the guard pauses work; a heatsink is needed in the field.

Measured (`hw_board_thermal`):

| state | temperature |
|---|---|
| idle, after the UI fix | 43 C |
| idle, any tab before that | 50 C |
| right after inference | 63-69 C |
| genied busy-wait, before its fix | 94 C |
| 13-agent Genie chaos, before pacing | 94 C |
| with pacing | 90 C |
| htpd chaos peaks | 96 C |

All failures in the final stress run were thermal: 3 of 135 (`ux_stress_runs`).

Evidence: `hw_board_thermal`, `ux_stress_runs`. Decision: G20 ("Keep the board cool and powered"), D062.

**Q68. Did the UI really heat the board?**

Yes: the redesigned dashboard used ~220% CPU and held the board at 75 C; after the fix 5-11% and 43 C.

Cause: 22 px backdrop blurs re-rasterised every frame under 60 fps infinite animations (`hw_board_thermal`, folded `hw_ui_cpu`, HANDBOOK 2.35). That held the board at 75 C idle, hotter than a 13-agent incident. Fix: solid bars, indicators stepping at 2 fps, sparklines at 1 Hz. CPU fell to 5-11% on every tab and the board to 43 C idle.

Evidence: `hw_board_thermal`. Decision: G20 ("Keep the board cool and powered"), D058.

**Q69. What about power?**

Not yet measured in joules (no free power rail); USB power browned out at peak, so the evaluation uses the DC adapter.

`ops_incidents`: the board rebooted during chaos with boot reason "reboot" and AC/USB online = false, which is a USB brownout. Fix: the DC adapter for the evaluation, and an incident store that survives torn writes. Energy per incident is not measured because there is no free power rail to probe (`uc_edge_offline`).

Evidence: `ops_incidents`. Decision: G20 ("Keep the board cool and powered"), D057.

### Safety (5)

**Q70. Can the AI switch anything off?**

No. The policy gate forbids actuation; every recommendation (even switch_off_ac in v2) needs a human approval.

The policy gate forbids actuation for every role (`ad_policy_gate`). v2 adds HVAC recommendations such as switch_off_ac (AC on in an empty room, `ds_hvac_real_labels`). These remain advisory and require approval (decision D119). This scenario is not yet measured on the board (section 7.5).

Evidence: `ad_policy_gate`, `ds_hvac_real_labels`. Decision: G06 ("Disagreements are shown, decisions stay human"), D119.

**Q71. What stops hallucinated evidence?**

The policy gate accepts only real evidence ids, whitelisted labels and valid JSON; repairs are recorded, invented labels rejected.

`ad_policy_gate`: transparent repairs raised the agent pass rate on the demo scenarios from 3/6 to 5/6, with nothing invented. Repairs include deriving the action from the stated cause, splitting packed evidence ids, salvaging malformed JSON from the model's own fields, and removing a stray "]". On device, htpd final passed policy 54/54 with evidence valid 54/54 (`acc_device54_engines`). The base model had only 52/150 valid evidence.

Evidence: `ad_policy_gate`, `acc_device54_engines`. Decision: G05 ("Safety: a policy gate on every answer"), D020.

**Q72. What if the synthesizer's answer fails policy?**

The operator still gets a report built from the agents' findings (Mode 3) or the rules (Mode 2), marked as such.

HANDBOOK 2.33 and `ad_policy_gate` notes. Live example: chaos INC-0551, where the report is marked "deterministic (synthesizer output rejected by policy)", label hvac_or_thermal_issue, assembled from the agents that passed (section 7.5). The rejected text is kept in the record for audit, and nothing is invented.

Evidence: `ad_policy_gate`. Decision: G05 ("Safety: a policy gate on every answer"), D056.

**Q82. Is every answer that passes the gate correct?** (new 2026-10-19)

No: the gate checks JSON, labels and evidence ids, not arithmetic in free text. One passed answer said '863 ppm exceeds the 1000 ppm warning limit' (model text, numerically wrong); v2 caps free text at 2 short observations.

Where it happened: ventilation incident INC-0530 (section 7.5), and the same kind of slip in heat build-up ("33.8 C exceeds the warning limit of 38 C"). In both, the label, status and action were right; only the prose comparison was wrong. The site does not quote such text as correct: the Q&A "What we have not measured yet" card names it as "model text, numerically wrong". The fix path is v2's shorter observations (max 2, ~14 words) built from templates with numbers taken only from the evidence, plus an arithmetic check in the gate as a possible follow-up.

Evidence: `ad_policy_gate`, `uc_human_in_loop`. Decision: G05, D020.

**Q73. Is the board secure on a network?**

Off-device writes need an API token; adb has no auth on this dev kit, so the board stays off untrusted networks.

Off-device writes require an API token. adb has no authentication on this dev kit (the app itself uses local adbd on 127.0.0.1:5555, `uc_edge_offline`), so anyone on the network could reach it. The board must stay off untrusted networks. Garbage input (NaN, strings, absurd values) is rejected (400) or clamped, never a crash (9/9 checks, `ux_fault_injection`).

Evidence: `ux_fault_injection`, `uc_edge_offline`. Decision: G19 ("Recover from faults; exactly one model on the NPU"), D061.

### Robustness (2)

**Q74. How did you test robustness?**

Through the app: random sliders, faults, chaos, operator actions, killed processes and reboots; final build 132/135, all failures thermal.

`stress_app.py` drives only the app's own API: random sliders, sensor faults, scenarios, chaos rounds, approve/dismiss/rerun, mode switches. After each phase it checks the board. Results (`ux_stress_runs`): Genie final 238/240; htpd v6 final 132/135; report-page build 133/135. Every failure in the final runs was thermal. Fault injection (`ux_fault_injection`) covers killed processes, torn store lines, cold reboots and stale abort bytes.

Evidence: `ux_stress_runs`, `ux_fault_injection`. Decision: G18 ("Test through the app, the way an operator uses it"), D065.

**Q75. What happens if a process crashes mid-analysis?**

The backend is back in 8 s, the NPU daemon in <= 15 s, and the interrupted incident reloads as 'rerun'.

From `ux_fault_injection`:
- Kill edge-agent: the watchdog restarts it in 8 s, incidents intact.
- Kill genied mid-answer: the error is detected and the call re-run (valid answer, 4.9 s); the daemon is back in 15 s or less.
- Kill the backend mid-analysis: the incident was persisted at creation and reloads as failed. Approve is refused (409) and rerun is allowed.
- Cold boot: answering about 5 s after boot completes.

Evidence: `ux_fault_injection`. Decision: G19 ("Recover from faults; exactly one model on the NPU"), D064.

### Limits (2)

**Q76. What are the honest limits?**

Small device sets (n=54), no labelled Mode 2 vs 3 grid yet, circular cause labels, recurring small spikes unsolved, heat at chaos peaks, power not measured.

Each limit has a dataset:
- Device n = 54 (CIs about +-8-10 points; the 900-window rerun stopped at 39) (`acc_device54_engines`).
- No labelled Mode 2 vs Mode 3 grid.
- Circular status/cause labels.
- Recurring sub-threshold spikes: 32% at 4 h (`ad_window_old_events`).
- Chaos peaks at 96 C (`hw_board_thermal`).
- Energy not measured.
- Cross-domain root cause has no independent ground truth (`uc_cross_domain`).

Evidence: `acc_device54_engines`, `ad_window_old_events`, `hw_board_thermal`.

**Q77. What is still unsolved?**

Recurring sub-threshold spikes: no window length or detector catches them reliably (32-52%); v2 teaches them explicitly.

Window study (`ad_window_old_events`): recurring small spikes are detected at 0.44 (2 h), 0.32 (4 h), 0.467 (8 h) and 0.52 (12 h), mostly called "stable". The recurring-excursion detector was tried and dropped: removing it cut dev false alarms from 0.15 to 0.0167 at the same old-step catch (`ad_longrange_ablation`). v2 training data has 509 "recurring" rows (`ds_families`).

Evidence: `ad_window_old_events`, `ad_longrange_ablation`. Decision: G16 ("12 h CPU checks feed the reasoner"), D091.

### Next (4)

**Q78. What is next?**

Finish v2 training, deploy it on htpd, run the NPU acceptance test, then the latency pass and the cross-domain reasoner.

v2 training status (`tv2_loss_curve`): best dev loss 0.066 at step 2,400 of 4,494. Then: export to the NPU, the acceptance test (Q77), a latency pass back to 14.7 s or below for 13 agents (`tv2_plan`, `lat_route_13_agents`), and the parked cross-domain reasoner (`ad_reasoner_plan`).

Evidence: `tv2_loss_curve`, `tv2_plan`. Decision: G22 ("Retrain the domain agents (v2) instead of patching"), D112.

**Q79. How will you know v2 is better than v1?** (was "What will decide whether v2 ships?"; merged 2026-10-19)

Fixed in advance, on the QIDK, test months, paired against v1: pattern >= 65% at 40 min (v1 42%) and >= 88% at 3 h, no regression on the 54/900 sets, JSON/policy >= 98%, fewer false alarms than v1's 31%.

The bar comes from the placement curve (`ad_placement_curve`): v1 is 0.423 at 40 min and 0.885 at 3 h, so v2 must beat 40 min and hold 3 h. No regression is allowed against the 54-window (htpd final 0.907) or 900-window sets (`acc_device54_engines`). JSON and policy validity must be at least 98%, against today's 100%. False alarms must come in below 31%.

Paired means the same windows go through v1 and v2 on the same NPU, so McNemar applies (section 8.3). Dev loss is not used as proof: v1's 0.027 was on an easier set.

Evidence: `ad_placement_curve`, `acc_device54_engines`, `uc_alert_reduction`. Decision: G22 ("Retrain the domain agents (v2) instead of patching"), D112.

**Q83. What happens after training finishes?** (new 2026-10-19)

Merge the best adapter, export GGUF Q4_0 for htpd, run the acceptance tests on the QIDK (test months), then a latency pass back to <= 14.7 s for 13 agents.

Order (Route > Training v2, "After the last step"): keep the best dev-loss checkpoint, merge, export GGUF Q4_0 with an importance matrix from our own prompts, load into htpd, run the acceptance test (Q79), then the latency pass (accuracy first, RETRAIN_V2_SPEC latency policy), then recalibrate confidence from v2's placement results (D4) and start the cross-domain reasoner.

Evidence: `tv2_plan`, `tv2_loss_curve`, `lat_route_13_agents`. Decision: G22, D112.

**Q84. What if v2 fails the acceptance test?** (new 2026-10-19)

v1 stays deployed (it is the revert); we report the failed criteria and fix data or training, never lower the bar after the fact.

Evidence: `acc_device54_engines`, `tv2_plan`. Decision: G22, D112.

### Status (2)

**Q80. What runs on the QIDK today?**

The v1 fine-tuned Llama 3.2 3B on htpd (llama.cpp Hexagon), Mode 3 agents with refinements and 12 h checks, policy gate, native app.

Running today:
- Model: v1 fine-tune, device pattern 0.907 (`acc_device54_engines`).
- NPU engine: htpd (llama.cpp Hexagon backend) is current, with Genie as the fallback via a file switch (`hw_platform_paths`).
- Pipeline: event gate, Mode 3 agents, synthesizer, policy gate, refinements at +1.5 h / +3 h with 12 h checks (9/9 reached 3 h, `ref_device_runs`), AI-derived titles, and a native APK launching the backend via local adbd.
v2 is not deployed yet.

Evidence: `acc_device54_engines`, `ref_device_runs`. Decision: G07 ("Batched NPU daemon (htpd) for multi-agent incidents"), D083.

**Q81. Where is training right now?**

Step 2,685 of 4,494 (60%) at build time, best dev loss 0.066; about 22 h of training left, plus pauses.

The answer is filled from the training log at build time (numbers above are from the build of 2026-10-19 20:13). The Q&A page also shows a status strip for this question (`ui.statusStrip(status)`, from `data/status.json`, built from the training log). Latest values in the datasets:
- Dev loss: 0.066 at step 2,400 (2026-10-19 09:47) (`tv2_loss_curve`).
- Last session listed: started 2026-10-19 10:01 (`tv2_sessions`).
Read the strip live rather than quoting a step number from memory.

Evidence: `tv2_sessions`, `tv2_loss_curve`.
