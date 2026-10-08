# plan.md — Smart City Edge Agent on QIDK (Android App + On-Device LLM)

> Written 2026-10-01. Companion to `context.md` (repo review) and `PRD.md` (long-term spec).
> This plan is the **working plan**: what we build next, in what order, who does what, and how we know each step is done.
> "Me" = Claude (code, scripts, docs, analysis). "You" = Rishit (device, Android Studio, accounts, decisions, human review).

---

## 0. TL;DR

**Goal:** An Android app that runs **entirely on the QIDK**. It polls sensor values every few seconds/minutes, runs cheap always-on checks (data-quality → rules → anomaly model), and **only when something is wrong** calls the on-device LLM. Domain agents (Energy, HVAC, Air, Water, Weather) say *what they notice*, a synthesizer says *what the problem probably is*. Every claim cites an **evidence ID** that you can tap to see the raw reading. Three modes (Rules / Single-LLM / Multi-Agent) are switchable in the app for comparison.

**How we get there (8 phases):**

| # | Phase | Output | Rough size |
|---|---|---|---|
| 0 | Decisions + device sanity | Scope locked, Genie bundle verified on device | 1–2 days |
| 1 | Data pipeline | Clean, time-aligned, per-building Parquet/SQLite from the 4.6 GB CSVs | ~1 week |
| 2 | Detection + guardrails | Data-quality gate, rules, seasonal anomaly model, evidence IDs, event gate | ~1 week |
| 3 | Labelled scenarios | Fault-injected + real events with known causes (train / eval split) | ~1 week |
| 4 | LLM layer (prompt + RAG first) | Domain agents + synthesizer, JSON contracts, policy gate, 3 modes — on laptop | ~1 week |
| 5 | Fine-tune (only if Phase 4 isn't good enough) | One multi-role LoRA → merged → re-exported Genie bundle | 1–2 weeks, risky |
| 6 | Android app | Kotlin app: poller service, detection, Genie via JNI, store, UI | ~2 weeks |
| 7 | Evaluate + demo | Mode 1/2/3 numbers on device, latency/RAM, demo video | ~1 week |

**The order matters.** Prove the brain on the laptop (Phases 1–4) with the *same* code paths and prompts the phone will use, then port. Fine-tuning is a fallback, not step one.

### Decisions locked (2026-10-01)

| Question | Answer | Effect on plan |
|---|---|---|
| Deadline | Soon | **Critical path = 0 → 1 → 2 → 4 → 6 → 7.** Phase 3 shrinks to fault injection only (~1–2 days). Phase 5 (fine-tune) becomes **stretch**. Phases 1–2 overlap with Phase 0 |
| Qwen | Deferred until app + basic agents run | One Llama 3.2 3B, many roles |
| Live SCRC feed | Later, at integration | v1 polls replay; `SensorSource` interface keeps the live swap cheap |
| Building codes | Building names | UI shows codes for now (optional code → full-name table later) |
| Teacher model | Not needed unless Phase 5 happens | Revisit only if prompt + RAG quality is insufficient |
| UI | Whatever works best on QIDK | **Kotlin backend service + embedded localhost HTTP API + existing HTML/JS dashboard in a WebView** (see Phase 6) |

**Compressed schedule (critical path):**

| Week | Work |
|---|---|
| 1 | Phase 0 (device + Genie sample app) ∥ Phase 1 (data pipeline, replay pack) |
| 2 | Phase 2 (guardrails, evidence) + Phase 3-lite (fault injection) + start Phase 4 |
| 3 | Phase 4 (agents, RAG, policy, eval on laptop) ∥ Phase 6 skeleton (service, Genie JNI, WebView) |
| 4 | Phase 6 port + Phase 7 demo/eval. Phase 5 only if time remains |

---

## 1. What the new dataset actually contains

I streamed all 14 files in `ihub-clean-datasets/` (4.6 GB, ~37 M rows) and read `meta data.xlsx` from the zip (units, ranges per parameter). Full-year coverage: **2025-01-01 → 2025-12-31**.

### 1.1 Files, cadence, coverage

| File | Domain | Rows | Nodes | Approx. cadence/node | Useful columns |
|---|---|---|---|---|---|
| `SR-AC.csv` | HVAC (room AC units) | 11.5 M | 87 | ~4 min | Room Temp, Temp Adjust (setpoint), Start/Stop, Compressor, Fan, Alarm, Malfunction Code, Filter Sign, Mode |
| `air_qulaity.csv` | Outdoor air | 9.5 M | 10 | ~30 s | PM2.5/PM10 (raw + calibrated), Temp, RH, Noise, AQI |
| `SR-AQ.csv` | Indoor air | 7.0 M | 12 | ~1 min | **CO2**, Temp, RH, PM2.5/PM10, Noise, AQI |
| `SL.csv` | Solar / LT panel power | 1.8 M | 9 | ~1–2 min | 3-phase V/I/PF/kW, frequency, energy import/export |
| `WM-WF.csv` | Water flow | 1.7 M | 25 | ~15 min | Flowrate (m³/h), Total Flow, Pressure (bar) |
| `EM.csv` | Main energy meters | 1.2 M | 3 | varies | 11 kV feeder / transformer V, I, kW, PF, kWh |
| `WN.csv` | Wireless network | 0.9 M | 79 | ~10 min | RSSI, latency, ETX, MAC tx failures |
| `SR-EM.csv` | Room energy | 0.7 M | 3 | 2 min | Energy (Wh), Power (kW), Current |
| `WM-WL.csv` / `WL.csv` | Water tank level | 0.37 M | 9 | ~3 min | Water Level, Temp (two near-identical copies) |
| `SR-OC.csv` | Occupancy | 0.3 M | 2 | — | **All occupancy/temp/RH values are empty** |
| `we.csv` | Weather | 0.1 M | 2 | 5 min | Temp, RH, wind, gust, solar radiation, rain, pressure |
| `WM_WD.csv` | Water quality | 30 K | 9 | ~2 h | TDS, turbidity, pH, temp |
| `cm.csv` | ? (KH95 only) | 2 K | 3 | — | Mostly zeros — ignore |

### 1.2 The most important finding: where domains overlap

Node IDs encode a building + floor code (e.g. `SR-AQ-**KH03**-01`). Cross-domain reasoning only makes sense where several domains exist **in the same building**. Only one building qualifies:

```
KH (Kohli block, floors 00–04, 95/96/98 = roof/plant/tank levels — to confirm with you)
 ├── HVAC       SR-AC  KH00, KH01, KH02, KH03, KH95   (87 AC units)
 ├── Indoor air SR-AQ  KH00, KH03, KH95              (CO2, PM, temp, RH)
 ├── Energy     SR-EM  KH04 (3 meters), EM KH95
 ├── Water      WM-WL  KH00, KH98 · WM-WF KH95, KH98 · WM-WD KH95/96/98/04
 └── Occupancy  SR-OC  KH00, KH95 → EMPTY
Campus-wide (broadcast to every building): Weather WE-VN04 / WE-BN04, Outdoor AQ (nearest node)
```

**Decision this forces:** our app monitors the **KH building** (room/floor level) with campus weather + outdoor air as context. Other buildings get single-domain monitoring only (water/solar/outdoor-air), no cross-domain claims.

### 1.3 "Clean" data still has problems we must handle

| Problem | Example | What we do |
|---|---|---|
| Occupancy is empty | `SR-OC.csv` 0 non-empty values in 298,796 rows | Drop Occupancy as a sensor domain. Add an **inferred occupancy** signal (CO2 rise rate + AC units on + room power), always labelled "inferred" |
| Sentinel / overflow values | SR-AQ CO2 max 4,294,965 (uint32 overflow); AQI 86,099; AQL ±1e67; WD temp −40/125; weather pressure 0/600 (spec 660–1070 mbar) | Data-quality gate using the ranges in `meta data.xlsx` → mark as `SENSOR_FAULT`, never as an anomaly |
| Columns shift between nodes/firmware | `EM-CR-KH95-00` puts line voltage in `GDVLL` and frequency in `T1VLL`; `SR-EM` Frequency ≈ 0.03 and Power Factor ≈ 50 (swapped) | Per-node / per-version column maps in a config file |
| Physically impossible values | WM-WF Flowrate up to 5.6 M m³/h and negatives (spec 0.1–31.25); EM T1Current 4.2 M A | Clamp/flag by physical range |
| Mostly-zero channels | EM 70 % zeros; SR-AC Gas/Elec Total Power, Heater, Forced Thermo always 0; WF Pressure 76 % zero | Exclude dead channels from models; treat "zero for hours" as stuck/offline |
| Rows not time-sorted | WM-WF and WE rows out of order | Sort per node during ingest |
| Mixed timezones | Most files `+00:00`; WL, WD, cm `+05:30` | Normalise to UTC on ingest; show IST in UI |
| Duplicate file | `WL.csv` ≈ `WM-WL.csv` (same row count, tiny diff) | Use one, note the diff |
| Missing building codes | Most WN nodes are `WN-L001-03` style (no building) | Need a node → location map from you / SCRC (`latest.json` topology) |

### 1.4 No ground truth

There are **no incident labels** anywhere. This is the single biggest problem for "properly training" agents and for proving Mode 3 > Mode 1. Phase 3 solves it with fault injection + a small human-reviewed set.

---

## 2. Target architecture

### 2.1 What runs where

Everything runs on the QIDK in production. The laptop is only for training, data prep and evaluation.

```
┌──────────────────────────── QIDK (Android 14, SM8650) ────────────────────────────┐
│                                                                                    │
│  Android App (Kotlin)                                                              │
│  ┌──────────────────────────────── UI (Jetpack Compose) ───────────────────────┐   │
│  │ Live dashboard · Incident detail (agents + evidence) · Mode switch · Settings│   │
│  └──────────────────────────────────────▲──────────────────────────────────────┘   │
│                                         │ StateFlow                                │
│  ┌──────────────── EdgeService (foreground service = "backend") ───────────────┐   │
│  │  1 SensorSource      replay DB  |  HTTP (laptop/SCRC)    ← polled every N s  │   │
│  │  2 WindowBuilder     per-node rolling stats + evidence IDs                   │   │
│  │  3 QualityGate       ranges/sentinels/stuck/stale → SENSOR_FAULT             │   │
│  │  4 Detectors         rules (YAML) + seasonal baseline + ONNX autoencoder     │   │
│  │  5 EventGate         dedup, cooldown, LLM rate limit, thermal check          │   │
│  │  6 Reasoner          Mode 1 | Mode 2 | Mode 3 (agents → synthesizer)         │   │
│  │       └── Retriever  topology, sensor specs, thresholds, past incidents      │   │
│  │  7 PolicyGate        schema, evidence ⊆ known, action whitelist              │   │
│  │  8 IncidentStore     Room/SQLite + append-only audit log                     │   │
│  └───────────────┬──────────────────────────────────────────────────────────────┘   │
│                  │ JNI                                                              │
│  ┌───────────────▼──────────────┐   ┌───────────────────────────┐                   │
│  │ Genie (QAIRT) — Llama 3.2 3B │   │ ONNX Runtime (CPU)        │                   │
│  │ loaded ONCE, kept warm, HTP  │   │ anomaly autoencoders      │                   │
│  └──────────────────────────────┘   └───────────────────────────┘                   │
└────────────────────────────────────────────────────────────────────────────────────┘
```

Key choices and why:

- **"Backend" = a foreground Service inside the app**, not a separate server. No Python on the phone, no laptop dependency, survives screen-off.
- **Genie loaded once via JNI and kept resident.** The current `adb shell genie-t2t-run` path pays ~4 s of HTP init per call. Multi-agent mode makes 3–6 calls per event, so a resident model is the difference between ~8 s and ~30 s per incident. Qualcomm's reference is in `qidk/GenAI-Solutions/AI-Assistant` (Genie C++ + JNI).
- **One LLM (Llama 3.2 3B, already exported and on the device), many roles.** Each domain agent and the synthesizer are different prompts on the same loaded model. The PRD's Qwen and model-swap work stays deferred. Swapping 2–3 GB models per event would kill latency.
- **Polling source is pluggable.** We have no live SCRC feed, so v1 polls a **replay source**: a curated SQLite slice of the real data (KH building + weather + outdoor air), played back on a sped-up clock with optional injected faults. The same interface can later point at a live HTTP endpoint (laptop replay server or the SCRC API if we get access).

### 2.2 The three modes inside the app

| Mode | When LLM is called | What it produces |
|---|---|---|
| **1 Rules** | Never | Rule violations + template text. Baseline. |
| **2 Single-LLM** | Once per event | One prompt with all domains' evidence → RootCauseReport |
| **3 Multi-Agent** | 1 call per *affected* domain + 1 synthesis | Per-domain `DomainFinding` ("what I notice") → synthesizer `RootCauseReport` ("what the problem is") |

Detection (quality gate, rules, anomaly model) is identical in all modes, so the comparison is fair. A shadow setting can run Mode 1 alongside 2/3 for side-by-side display.

### 2.3 Agents (adjusted to the real data)

| Agent | Sees | Example findings |
|---|---|---|
| **HVAC** | SR-AC per unit/floor: on/off, compressor, setpoint vs room temp, alarm, malfunction code, filter sign | "12 units on KH02 running compressor but room temp rising → cooling not effective"; "Filter sign active on 5 units" |
| **Indoor Air** | SR-AQ: CO2, PM, temp, RH, noise | "CO2 1,450 ppm and rising 300 ppm/h on KH03 → ventilation insufficient for inferred occupancy" |
| **Energy** | SR-EM, EM, (SL for solar) | "Room power 2.3× seasonal baseline for this hour-of-week" |
| **Water** | WM-WL, WM-WF, WM-WD | "Tank KH98 level falling 8 %/h with no inflow → possible leak or pump fault"; "Turbidity above limit" |
| **Weather/Outdoor** (context agent) | WE + nearest outdoor AQ | "Outdoor 38 °C, solar 850 W/m² → high cooling load expected"; "Outdoor PM2.5 spike → ingress likely" |
| **Synthesizer** | Only the agents' JSON findings + evidence table + retrieved context | Root cause, causal chain, confidence, uncertainties, recommended *inspection* action |

Inferred occupancy is a derived feature given to HVAC/Air/Energy agents, not its own agent.

---

## 3. Contracts (fixed early, shared by laptop and app)

### 3.1 Evidence IDs

Generated deterministically by the WindowBuilder, one per **(node, metric, statistic, window)**. They are not per raw row, which would be too many for the LLM context.

```
ev:{node_id}:{metric}:{stat}:{window_end_epoch_s}
ev:SR-AQ-KH03-01:co2:last:1751012400
ev:SR-AC-KH02-07:compressor:on_frac:1751012400
ev:WE-VN04-00:temp:max:1751012400
```

Each ID maps to a row in an `evidence` table (value, unit, window, quality flag, raw sample IDs), so the UI can show the reading and chart behind any claim. The LLM only sees IDs that exist for this event, and the PolicyGate rejects any other.

### 3.2 LLM outputs (JSON, validated)

```jsonc
// DomainFinding — one per agent call
{ "domain": "hvac", "status": "abnormal|normal|insufficient_data",
  "observations": [ {"text": "...", "evidence": ["ev:..."]} ],   // what I notice (1–4)
  "suspected_cause": "HVAC_FAULT",                                // from taxonomy
  "confidence": 0.0-1.0, "missing_data": ["..."] }

// RootCauseReport — synthesizer
{ "root_cause_label": "HVAC_OVERLOAD",                           // taxonomy enum (scorable)
  "summary": "...", "causal_chain": ["...", "..."],
  "evidence": ["ev:..."], "confidence": 0.0-1.0,
  "recommended_action": "inspect_hvac",                          // enum, never free-form actuation
  "note": "...", "uncertainties": ["..."], "requires_human_approval": true }
```

- **Taxonomy (revised for this data):** HVAC_OVERLOAD, HVAC_FAULT, HVAC_FILTER, VENTILATION_INSUFFICIENT, OUTDOOR_AIR_INGRESS, ENERGY_ABNORMAL_LOAD, POWER_QUALITY, WATER_LEAK_OR_DRAIN, WATER_SUPPLY_LOW, WATER_QUALITY, WEATHER_HEAT_LOAD, SENSOR_FAULT, UNKNOWN.
- **Actions:** `inspect_hvac`, `clean_or_replace_filter`, `inspect_ventilation`, `inspect_water_system`, `check_sensor`, `review_energy_schedule`, `request_facility_review`. The model picks from this list; a free-text `note` is allowed but is never executed.

These go into `schemas.py` (Python) and mirror 1:1 into Kotlin data classes, plus a shared JSON-Schema file used by both.

---

## 4. Phases in detail

### Phase 0 — Decisions & device sanity (1–2 days)

| Task | Who |
|---|---|
| Answer §6 open questions (scope, deadline, live data access, building codes) | **You** |
| Verify the Llama bundle on disk: `part_2_of_3.bin` is 561 MB but there is a 901 MB `part_2_of_3.recovered.bin`, so one is likely a broken download. Re-download or check hashes against AI Hub | Me (script) + **You** (run) |
| Measure on device: cold load time, per-call latency for 100/300 output tokens, RAM (`dumpsys meminfo`), thermal after 20 calls | Me (script) + **You** (run, device plugged in) |
| Install Android Studio + NDK; clone/build Qualcomm's AI-Assistant / ChatApp Genie sample and get it chatting on the QIDK | **You** (I guide step by step) |
| Find out where that sample loads model files from (app-private dir vs `/sdcard/Android/data/<pkg>`). SELinux blocks app access to `/data/local/tmp` | **You** + me |

**Done when:** a Qualcomm sample app chats with Llama 3.2 3B on the QIDK, and we have real numbers for load time, tokens/s and RAM.
**Why first:** if the Android Genie path doesn't work, everything after Phase 4 changes. This is the biggest technical risk.

### Phase 1 — Data pipeline (≈1 week)

| Task | Who |
|---|---|
| `configs/sensors.yaml`: per-file/per-node column maps, units, valid ranges (from `meta data.xlsx`), sentinel values, dead channels | Me |
| Streaming ingest → **Parquet per domain, partitioned by month** (needs `pyarrow`/`polars` in WSL venv): UTC timestamps, sorted per node, quality flags (not deletions) | Me |
| Topology table: node → building → floor → domain, built from node codes. **You** confirm what KH, 95/96/98, VN, PH… mean and supply WN locations if available | Me + **You** |
| Resample to **5-min buckets per node** (energy/water are 2–15 min; 1-min buckets would be mostly forward-fill), forward-fill with TTL, staleness flag | Me |
| Seasonal baselines per node/metric: median + MAD by **hour-of-week** (AC and CO2 follow strong weekly cycles) | Me |
| Data report (HTML): coverage heatmaps per node per day, gaps, fault rates | Me |
| Export a **replay pack** (SQLite, KH + weather + outdoor AQ, a few representative weeks) for the app | Me |

**Done when:** one command rebuilds clean Parquet + baselines + replay pack from the CSVs, and the data report shows per-node coverage.

### Phase 2 — Detection & guardrails (≈1 week)

Detection runs in layers. Each layer can stop the event before it costs an LLM call.

```
reading → QualityGate ──fault──► SENSOR_FAULT event (no LLM unless many sensors fail at once)
            │ok
            ▼
        Rules (thresholds.yaml, duration + hysteresis)  ┐
        Seasonal z-score (|x − median_how| / MAD > k)   ├─► Candidate anomaly (domain, node, score, evidence)
        Per-domain autoencoder (ONNX)                   ┘
            ▼
        EventGate: group by building+15 min · dedup · cooldown · max K LLM events/hour · thermal OK?
            ▼
        AnomalyEvent → Reasoner (Mode 1/2/3)
```

| Task | Who |
|---|---|
| Fill `thresholds.yaml` with real values: CO2 1000/1500 ppm (ASHRAE), PM2.5 indoor/outdoor (WHO/NAAQS India), room temp vs setpoint delta, tank-level drop rate, turbidity/pH (IS 10500), feeder PF/voltage | Me (draft) + **You** (approve) |
| Rule engine v2: nested YAML, duration, hysteresis, warning/critical | Me |
| QualityGate: range, sentinel, stuck (flat for > N buckets), stale, jump rate | Me |
| Per-domain autoencoders retrained on clean 5-min features with seasonal inputs (hour, weekday). Threshold from **validation** month, not test. ONNX export (opset 17) + parity test vs PyTorch | Me (code) + **You** (run in WSL with GPU, or CPU is fine — models are tiny) |
| Evidence builder + evidence table (§3.1) | Me |
| Unit tests for every gate, plus replay tests on chosen weeks | Me |

**Done when:** replaying a full month gives a sane event rate (target: a handful of LLM-worthy events per day for KH, not hundreds), every event carries valid evidence IDs, and known sentinel values never produce anomalies.

### Phase 3 — Labelled scenarios (≈1 week)

We need examples with **known answers** both to train (if we fine-tune) and to prove the modes work.

| Source | How | Use |
|---|---|---|
| **Fault injection** on real KH traces | Scripts that modify real windows in physically consistent, multi-domain ways, e.g. HVAC fault (compressor on, room temp climbs, power up), filter clog (cooling efficiency drops slowly), ventilation failure (CO2 ramps with occupancy), leak (tank drains at night with no flow-in), heat wave (outdoor temp up → all floors load up), sensor fault (stuck/spike) | Train + eval with exact labels |
| **Real events** found by Phase 2 | I cluster detected events; **you** review ~100–200 with a small labelling page (pick a taxonomy label, or "don't know") | Eval only (the honest test) |
| **Negatives** | Normal windows and single-domain noise | Teach "normal / insufficient data" |

- Split by **time** (e.g. Jan–Aug train, Sep–Oct dev, Nov–Dec test) and by injected-fault seed. No window appears in two splits.
- Target: ~2,000 injected train scenarios, ~300 injected test, ~150 human-labelled real test events.

**Done when:** `data/scenarios/{train,dev,test}.jsonl` exist with event, evidence table, label, and a labelling README describing the protocol.

### Phase 4 — LLM layer, prompt + RAG first (≈1 week, laptop)

Build the reasoner in Python first so we can iterate fast. The laptop calls the **same Llama 3.2 3B** on the QIDK via the existing ADB runner, or a local llama.cpp copy of Llama 3.2 3B for fast iteration. The prompts must be the exact strings the app will send.

| Task | Who |
|---|---|
| Fix prompt format: use **Llama 3 chat template** (the bundle's `chat_template.jinja`), not ChatML `<|im_start|>` | Me |
| Raise output budget: genie `max-num-tokens` ≈ 350–400 (current 60–100 truncates JSON) | Me |
| Agent prompts per domain: role, allowed evidence (only that domain's IDs + context), compact table of stats, JSON schema, 1–2 few-shot examples | Me |
| **Retriever (RAG) — structured first, no embedding model needed:** (1) sensor specs/units/ranges from metadata, (2) topology (which floor, which units), (3) threshold rationale snippets, (4) **similar past incidents** from the store (same building + same domains + label, last N approved), (5) short runbook per taxonomy label. Selected by keys plus BM25, capped at ~600 tokens | Me |
| JSON robustness: strict parser, one auto-repair retry with the validator error, then fail closed | Me |
| PolicyGate v2: schema, evidence ⊆ event IDs, per-agent evidence ownership, action enum, confidence sanity, audit log with hash chain | Me |
| Evaluation harness: accuracy + macro-F1 on taxonomy, evidence validity before gate (= hallucination rate), JSON failure rate, latency p50/p95, tokens. **McNemar** test Mode 3 vs 2 vs 1. Ablation: Mode 3 without RAG | Me |
| Review ~30 outputs by hand for "is this explanation actually useful?" | **You** |

**Done when:** on the test split, Mode 3 output is valid JSON ≥ 95 % of the time with ≥ 98 % grounded evidence, and we have Mode 1/2/3 accuracy numbers. Then decide: **good enough → skip to Phase 6; not good enough → Phase 5.**

### Phase 5 — Fine-tuning (now the current focus — full detail in `training_plan.md`)

> Update 2026-10-01: you asked to focus on training first, with Claude as the teacher model. `training_plan.md` covers where to train (laptop RTX 4050, Kaggle overflow; NPU is inference-only), the export round trip back to the HTP, data sizes and time estimates. The table below is the original sketch.

| Task | Who |
|---|---|
| Build SFT data from Phase 3 *train* split. Targets come from a stronger **teacher** model (larger local model or a cloud API, if allowed for this data) that sees the label + evidence and writes the findings/report. Each target passes the PolicyGate before use; you spot-check ~50 | Me + **You** (approve teacher use, spot-check) |
| **One** multi-role QLoRA on Llama 3.2 3B (role given in the system prompt) instead of 5 adapters. Reuse `train_llama_lora.py` on the RTX 4050 | Me (config) + **You** (run in WSL) |
| Merge adapter → full weights → **re-export via Qualcomm AI Hub** to a Genie bundle for SM8650 (w4a16). **Spike this in week 1 with the un-tuned model** so we know export of custom weights works before investing in training | Me (scripts) + **You** (AI Hub account, run jobs) |
| Re-run Phase 4 eval with the tuned bundle; keep it only if it beats prompt + RAG | Me |

Fallback if export of custom weights fails: stay with base model + RAG + few-shot, and report fine-tuning as host-only results.

### Phase 6 — Android app (≈2 weeks)

| Task | Who |
|---|---|
| New project `android/SmartCityEdge` (Kotlin, minSdk 34, arm64-v8a). Start from the working Genie sample from Phase 0 | **You** (create/build) + me (code) |
| **UI approach (decided):** the EdgeService runs a small embedded HTTP server (Ktor/NanoHTTPD) on `127.0.0.1:8000` exposing the same `/api/...` endpoints as today's FastAPI app. The UI is the existing `index.html/main.js/styles.css`, packaged as app assets and shown in a full-screen WebView. Why: reuses the dashboard we already have (fastest for the deadline); WebView on the 8 Gen 3 is smooth; the same UI also opens in a laptop browser via `adb forward tcp:8000 tcp:8000` for demos/debugging; the UI talks to the backend over a clean API instead of JS bridges. Native Compose only if time remains | Me |
| `GenieEngine` JNI wrapper: load once, `generate(prompt, maxTokens)` with streaming, reset KV between calls, timeout, cancel | Me + **You** (build/test on device) |
| Port detection to Kotlin: QualityGate, rules (YAML via snakeyaml-engine), seasonal baselines (JSON), ONNX Runtime Android for autoencoders, EventGate, evidence builder. **Golden tests:** the same replay week must give the same events in Python and Kotlin | Me |
| `SensorSource`: replay from the bundled SQLite pack on an accelerated clock; optional HTTP source (laptop replay server via `adb reverse`) | Me |
| Reasoner + Retriever + PolicyGate in Kotlin using the same prompt templates (shared `prompts/` asset files) | Me |
| `IncidentStore`: Room DB (incidents, findings, evidence, audit) + approve/dismiss with note | Me |
| UI (extend the existing HTML dashboard): (1) Live — building/floor cards per domain, sparklines, status; (2) Incidents list; (3) Incident detail — synthesizer summary, causal chain, agent cards "what I notice", tappable evidence chips → chart; (4) Settings — mode 1/2/3, poll interval, replay speed, LLM rate limit, thresholds view, model info | Me (code) + **You** (feedback on look/flow) |
| Foreground service + notification on new incident; thermal guard (pause LLM calls if throttling) | Me |
| Model files: push the bundle to the app-accessible directory found in Phase 0; startup hash check | **You** (push) + me (check code) |

**Done when:** unplug the laptop, open the app on the QIDK, start replay, and within minutes an injected fault shows up as an incident with agent findings, evidence and a synthesizer report, all generated on the device.

### Phase 7 — Evaluate & demo (≈1 week)

| Task | Who |
|---|---|
| On-device benchmark run (test split, all 3 modes): accuracy, macro-F1, grounding, JSON failures, latency p50/p95, RAM, thermal | Me (harness) + **You** (run, keep device cool/plugged) |
| Compare Python vs Android outputs on the same events (parity) | Me |
| Results write-up; update PRD "status vs target"; align README/ppt with what really exists | Me |
| Demo script + screen recording (into `Demos/`) | **You** + me |

---

## 5. Repo changes this plan implies

```
Code/smart-city-edge-agent/
├── configs/sensors.yaml           NEW  column maps, units, ranges, sentinels
├── configs/thresholds.yaml        FILL real values (nested format)
├── configs/taxonomy.yaml          NEW  labels + allowed actions
├── prompts/                       NEW  shared prompt templates (Python + Android assets)
├── schemas/*.schema.json          NEW  shared JSON schemas
├── src/smart_city_edge/
│   ├── ingest/                    NEW  streaming CSV → Parquet, quality flags
│   ├── features/                  NEW  5-min windows, baselines, evidence builder
│   ├── detect/                    REWRITE rules v2, quality gate, AE scorer, event gate
│   ├── reason/                    NEW  agents, synthesizer, retriever, JSON repair
│   ├── policy.py                  UPGRADE
│   └── eval/                      REWRITE harness + stats
├── scripts/inject_faults.py       NEW
├── scripts/build_replay_pack.py   NEW
├── webapp/                        KEEP as laptop debug UI — but show REAL LLM output (fix §3 of context.md)
└── android/SmartCityEdge/         NEW  real app
```

The fake parts of the current web demo (hardcoded root cause, "warm-state" label, always-passing gate) get fixed in Phase 4, since the web UI becomes our debug view of the real pipeline.

---

## 6. Open questions for you (answered 2026-10-01 — see "Decisions locked" in §0; kept for reference)

1. **Deadline / evaluation date?** This decides whether Phase 5 (fine-tuning) is realistic.
2. **Is Qwen required** by the advisor/PRD, or is "one Llama, many roles" acceptable? (Strongly recommended for this timeline.)
3. **Live data:** do we have (or can we get) access to the SCRC live API/oneM2M feed? If not, replay is the polling source for the demo.
4. **Building codes:** what do KH, VN, PH, PL, AN, BN, KN, TH, MG, SN and floor codes 95/96/98 mean? Is there a `latest.json` or node map with locations (especially for WN nodes)?
5. **Cloud teacher model:** may we send *derived, non-personal* sensor windows to a cloud LLM to generate training explanations (Phase 5)? If not, we use a local larger model.
6. **Android UI style:** native Compose (recommended) or reuse the existing HTML dashboard inside a WebView (faster, less native)?
7. Who else works on this? Splitting Phase 6 (app) from Phases 2–4 (brain) would let both run in parallel.

---

## 7. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Genie inside an Android app can't access the model or fails to load (SELinux, paths, libs) | Blocks the "runs on QIDK" goal | Phase 0 spike with Qualcomm's own sample first. Fallback: app UI on QIDK + `genie-t2t-run` started over ADB from the laptop (not standalone) |
| Custom-weight re-export via AI Hub fails | No fine-tuned model on device | Prompt + RAG path is the main plan; fine-tune is optional |
| 3B model gives shallow or wrong reasoning | Weak results | Strong structure: agents get pre-computed stats + baselines, not raw rows; taxonomy enum; few-shot; retrieval of similar past incidents; honest "UNKNOWN" allowed |
| Latency of Mode 3 too high | Poor UX | Resident model; only call agents for affected domains; short outputs; streaming UI; cap agents at 3 + synthesizer |
| Fault injection teaches the model our own simulator | Inflated scores | Keep a human-labelled *real* test set and report it separately |
| Thermal throttling in long runs | Latency spikes, invalid benchmark | Thermal guard, LLM rate limit, cool-down between benchmark batches |
| Data quirks (column shifts, sentinels) cause false alarms | Alarm fatigue | QualityGate + per-node column maps + data report reviewed by you |

---

## 8. What I can start on immediately (once you say go)

1. `configs/sensors.yaml` from `meta data.xlsx` + the profiling results.
2. Streaming ingest → Parquet + the data-quality HTML report (needs a WSL venv with `polars`/`pyarrow`; I'll give you the exact commands).
3. Device benchmark script for Phase 0 (load time, tokens/s, RAM, thermal) for you to run with the QIDK plugged in.
4. Fix prompt template + token budget in the existing runner, so even the current web demo shows real model output.

---

## Appendix A — Profiling notes (2026-10-01)

- Buildings per file: SR-AC {KH00 2.5 M, KH01 2.6 M, KH02 2.9 M, KH03 2.9 M, KH95 0.5 M}; SR-AQ {KH00, KH03, KH95, KN00, TH04, VN90}; AQ outdoor {AN00, FG00, KN00, MG00, PH03, PH04, PL00, SN00, TH00, VN90}; SL {NI01, NI03, PL00, PL96, VN02, VN03, VN95}; WF {BB04, KB04, KH95, KH98, PH01–04, PL00, PR00, VN04}; WL {AN00, BK00, KH00, KH98, PH03, PL00, VN00}; WD {KH04, KH95, KH96, KH98, PR00, PR96, VN01}; SR-EM {KH04 ×3}; EM {KH95, SB00 ×2}; WE {VN04, BN04}.
- SR-AC: Gas/Elec Total Power, Forced Thermo OFF, Energy Efficiency, Heater are 100 % zero (dead). Start/Stop on 7 % of samples, Compressor on 27 %, Filter Sign active 32 %, Alarm 0.3 %, Malfunction codes up to 154.
- SR-AQ: CO2 non-null 89.5 %, PM fields 72 % (older firmware lacks PM). Temp 20.8–39.2 °C, RH 15–96 %.
- Outdoor AQ: calibrated PM2.5 mean 34 µg/m³, max 213; AQL column is corrupt (±1e67).
- WE: Pressure 20 % zeros and capped at 600 (bad); Rain 99.7 % zero.
- WM-WF: Pressure present 78 % but 76 % zeros → only a few nodes have real pressure.
- EM: `EM-CR-SB00-00` looks like the 11 kV feeder (VLL ≈ 10.8 kV, ~470 kW); `EM-CR-SB00-01` mostly zeros; `EM-CR-KH95-00` uses a different column layout.
- Profiling scripts and JSON outputs are in the session scratchpad (not committed).
