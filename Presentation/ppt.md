# Agentic Edge AI for Smart Cities — PPT Script & Slide Guide

**Project:** Agentic Edge AI for Smart Cities  
**Platform:** Qualcomm QIDK (Snapdragon 8 Gen 3 / SM8650 / HTP V75)  
**Institution:** IIIT Hyderabad · Embedded Systems & Wireless Lab  
**Advisor:** Prof. Anuradha Vattem | TA: Lokabhiram Chintada

---

## SLIDE 1 — Title Slide

**Title:** Agentic Edge AI for Smart Cities  
**Subtitle:** Multi-Agent On-Device LLM Inference for Real-Time Infrastructure Monitoring  

**Visuals:**
- QIDK device photo (physical board)
- Smart city grid/circuit overlay image
- IIITH logo

**Speaker note:** This project deploys a multi-layered AI agent system entirely on-device on the Qualcomm QIDK — no cloud, no network dependency. We'll show it working live today.

---

## SLIDE 2 — The Problem: Smart Cities Are Blind to Root Causes

**Title:** Current Monitoring is Siloed — It Tells You *What*, Not *Why*

**Content (3 bullet points):**
- 🏙️ Urban infrastructure (energy, water, air, HVAC, occupancy) runs in isolated data silos
- ⚠️ Rule-based systems fire 3 separate alerts for what is actually 1 cascading failure
- 🌐 Real root causes are almost always **cross-domain** — invisible to any single-domain monitor

**Example (show as a diagram):**

```
[High Energy Draw] + [CO2 Spike] + [High Temp]
      Rule Engine → 3 separate alerts ❌

        Cross-Domain AI → 
  "HVAC overcooling due to outdoor heat surge,
   causing ventilation block + energy spike" ✅
```

**Speaker note:** A rule engine fires "energy threshold exceeded." An AI agent knows the outdoor temp spiked, which forced HVAC into overdrive, which blocked airflow, which caused CO2 to rise. One root cause, three symptoms.

---

## SLIDE 3 — Why On-Device? The Edge Constraint

**Title:** Cloud AI Is Not an Option for Critical Infrastructure

**Three-column layout:**

| ☁️ Cloud AI | 📡 Connectivity | 🔒 Privacy |
|---|---|---|
| Round-trip latency: 2–5s minimum | Monitoring must work offline | Campus occupancy & energy data cannot leave premises |
| Unacceptable for real-time decisions | Network outages during emergencies | Institutional data governance policies |

**Bottom line (bold):** The system must reason fully on-device, air-gap-capable, in real-time.

**Visuals:** QIDK board, Qualcomm Hexagon NPU logo

---

## SLIDE 4 — Research Thesis

**Title:** Our Central Research Question

**Thesis (large, centered quote block):**

> *"Does a multi-agent architecture of domain-specialized Llama 3.2 3B Instruct agents + a cross-domain Qwen reasoning model outperform (a) a rule-based baseline and (b) a single-SLM baseline — in root-cause diagnostic accuracy — while maintaining acceptable latency on a Snapdragon 8 Gen 3 edge device?"*

**Three evaluation modes we test:**
1. **Mode 1 — Rules Baseline:** Threshold engine only. No LLM. `< 10ms`
2. **Mode 2 — Single-SLM:** One model gets all sensor data at once. `~7s`
3. **Mode 3 — Multi-Agent Pipeline:** Orchestrator → Domain Agents → Cross-Domain Synthesis. `~7s (optimized)`

---

## SLIDE 5 — System Architecture (The Three-Tier Stack)

**Title:** Three Vertically Stacked AI Tiers — All On-Device

**Diagram (top to bottom):**

```
┌──────────────────────────────────────────────────────┐
│  TIER 3: Cross-Domain Reasoning                      │
│  Llama 3.2 3B · Qualcomm Genie · HTP V75 NPU        │
│  → Synthesizes root cause from domain agent reports  │
├──────────────────────────────────────────────────────┤
│  TIER 2: Multi-Agent Domain Orchestration            │
│  Llama 3.2 3B · Qualcomm Genie · HTP V75 NPU        │
│  → 5 specialized agents: Energy, Air, Water,         │
│    Weather, Occupancy                                │
├──────────────────────────────────────────────────────┤
│  TIER 1: Always-On Anomaly Detection                 │
│  Rule Engine + Denoising Autoencoder · CPU           │
│  → <5ms · Monitors 10 channels continuously         │
└──────────────────────────────────────────────────────┘
         ↑ Sensor Telemetry (10 channels, 5 domains)
```

**Hardware:** Snapdragon 8 Gen 3 · HTP V75 (Hexagon Tensor Processor) · 12GB LPDDR5X

---

## SLIDE 6 — The Hardware: Qualcomm QIDK

**Title:** Deployed on Qualcomm QIDK — Snapdragon 8 Gen 3

**Two-column layout:**

**Left — Hardware Specs:**
| Component | Spec |
|---|---|
| SoC | Snapdragon 8 Gen 3 (SM8650) |
| AI Accelerator | Hexagon Tensor Processor V75 |
| Memory | 12 GB LPDDR5X |
| OS | Android 14 (arm64-v8a) |
| Runtime | Qualcomm QAIRT 2.50 / Genie |

**Right — What's Deployed on It:**
| File | Size |
|---|---|
| Llama 3.2 3B (Part 1/3) | 752 MB |
| Llama 3.2 3B (Part 2/3) | 860 MB |
| Llama 3.2 3B (Part 3/3) | 1.2 GB |
| Genie Runtime Binary | 5.3 MB |
| QAIRT 2.50 Libraries | ~180 MB |
| **Total on device** | **~2.8 GB** |

**Visuals:** Photo of QIDK board. Qualcomm logo.

---

## SLIDE 7 — The Dataset: Real Campus Telemetry

**Title:** SCRC-IHub Dataset — Real IoT Sensor Data, IIIT Hyderabad Campus

**Content:**
- Source: Smart Campus Research Center, IIITH — real sensor deployment
- 12 CSV files across 5 domains: Air Quality, Energy, Water, Weather, Occupancy
- ~3.5 GB total. 1-minute resolution time-series

**5 Monitored Domains:**

| Domain | Sensors | Thresholds (WHO/ASHRAE/IS) |
|---|---|---|
| 🌬️ Air Quality | CO2, PM2.5, Temp, Humidity | CO2 > 1000 ppm (ASHRAE 62.1) |
| ⚡ Energy | Power (kW), Voltage, Current | Load > 80 kW (campus baseline) |
| 💧 Water | Flow (L/min), Pressure, pH | Flow > 50 L/min |
| 🌡️ Weather | Outdoor Temp, Wind, RH | Temp > 35°C (IMD heat alert) |
| 👥 Occupancy | People count, Room state | > 80 people (fire code) |

---

## SLIDE 8 — What We Built: End-to-End Pipeline

**Title:** Complete Agentic Edge AI Pipeline

**Step-by-step flow (horizontal or vertical diagram):**

```
Sensor Input (10 telemetry channels)
        ↓
[1] Rule Engine + Anomaly Scorer    ← <5ms, CPU
        ↓ (if anomaly detected)
[2] Domain Router (Python)          ← <2ms, determines which domains triggered
        ↓
[3] Domain Analysis (Python)        ← <2ms, per-domain structured analysis
        ↓
[4] Cross-Domain NPU Synthesis      ← ~7s, Llama 3.2 3B on Qualcomm HTP V75
        ↓
[5] Safety Policy Gate              ← <1ms, validates evidence & actions
        ↓
Root Cause Report + Recommendation  → Dashboard
```

**Key optimization:** Collapsed 4 sequential LLM calls (29s) → 1 single NPU synthesis call (~7s).

---

## SLIDE 9 — Key Technical Decisions & Findings

**Title:** Analysis: What We Learned Building This

**Three key findings:**

**Finding 1 — Cold-Start Penalty is the Bottleneck**
- Each `genie-t2t-run-2.50` CLI call incurs ~4s HTP initialization + ~3s generation = ~7s
- 4 sequential calls → 29s total
- Fix: collapsed to 1 synthesis call → ~7s (4× faster)

**Finding 2 — Domain Routing Doesn't Need an LLM**
- The "Orchestrator" LLM call was redundant — the rule engine already knows which domains triggered
- Replaced with pure Python deterministic routing: saves ~7s with zero accuracy loss

**Finding 3 — Prompt-File vs. Shell Arg**
- Passing prompts as shell args causes escaping issues on Windows/WSL ADB
- Using `--prompt_file` (write via `cat > file` + ADB stdin) is reliable across all platforms

---

## SLIDE 10 — Live Demo: The Web Dashboard

**Title:** Live Demo — Edge AI Dashboard

**Show on screen (live):**
1. Open http://localhost:8000
2. Header shows: ⚡ **NPU Active — 1-Call Mode** (green badge)
3. Select preset: **"🌐 Full Multi-Domain Crisis"**
4. Click **"Evaluate Sensors"**
5. Watch in real time:
   - Anomaly score badge → 🔴 ANOMALY DETECTED
   - Orchestrator plan → 3 domains flagged
   - Domain agent outputs → Air Quality, Energy, Occupancy
   - Root Cause Report → cross-domain causal explanation
   - Execution Trace → per-step timing (< 8s total)

**Screenshot to include (if live not possible):**
- Dashboard with red anomaly card
- Domain agent output cards
- Execution trace timeline with timing

---

## SLIDE 11 — QIDK: Live Inference

**Title:** NPU Inference Running on Qualcomm QIDK

**Show (live or as screenshot):**
```powershell
# Step 1: Verify device
C:\Users\hp\Desktop\qidk\platform-tools\adb.exe devices
# → 3ce9a4e2   device

# Step 2: Confirm model on device
adb shell ls -lh /data/local/tmp/genie_bundle/*.bin
# → llama_v3_2_3b_instruct_part_*.bin  (752MB + 860MB + 1.2GB)

# Step 3: Direct NPU inference (raw)
adb shell "cd /data/local/tmp/genie_bundle && \
  LD_LIBRARY_PATH=./qairt_2_50_libs:./aarch64-android \
  ./genie-t2t-run-2.50 -c llama3.2-3b-sm8650-genie.json -p 'Hi'"
```

**Output shows:**
```
Using libGenie.so version 1.20.0
[INFO] Using create From Binary List Async
[INFO] Allocated 270MB across 5 HTP buffers
[PROMPT]: Hi
[BEGIN]: Hello! How can I help you today?[END]
```

**Key point:** The model is running entirely on the Snapdragon 8 Gen 3 HTP V75 — no cloud, no GPU on the laptop.

---

## SLIDE 12 — Results & Performance

**Title:** Performance Results

**Latency Comparison:**

| Mode | Description | Latency |
|---|---|---|
| Mode 1 — Rules | No LLM | < 5 ms |
| Mode 2 — Single-SLM | 1 NPU call | ~7 s |
| Mode 3 — Multi-Agent (before opt.) | 4 sequential NPU calls | ~29 s |
| **Mode 3 — Optimized (current)** | **1 NPU call + Python analysis** | **~7 s** |

**Resource Usage on Device:**
| Metric | Value |
|---|---|
| Model storage on device | 2.8 GB |
| HTP NPU Allocation | ~270 MB across 5 buffers |
| Total inference latency | ~7s per anomaly event |
| Thermal state | Nominal (no throttling) |
| PRD target (Mode 3 p95) | ≤ 20 seconds ✅ |

---

## SLIDE 13 — Zero-Trust Safety Policy Gate

**Title:** Safety by Design — Policy Gate Before Every Action

**Three policy checks enforced on every AI output:**

1. **Evidence Grounding** — Every cited evidence ID must exist in the actual sensor window. Hallucinated evidence is rejected.
2. **Action Whitelist** — Only pre-approved actions (`inspect_hvac`, `isolate_water_valve`, `recalibrate_sensors`, `shed_energy_load`) are permitted.
3. **Human Approval Required** — `requires_human_approval: True` is immutable. No action is taken autonomously.

**Visual:** ✅ Evidence validated → ✅ Actions safe → ✅ Human approval enforced → Report committed

**Speaker note:** This is what makes the system safe enough to route recommendations to actual infrastructure operators. The AI advises; humans decide.

---

## SLIDE 14 — What Works Today vs. What's Next

**Title:** Current State vs. Roadmap

**What's Working NOW (Demo-Ready):**
- ✅ Llama 3.2 3B deployed on QIDK HTP V75 via Qualcomm Genie QAIRT 2.50
- ✅ End-to-end pipeline: sensor input → anomaly detection → NPU synthesis → root cause report
- ✅ Web dashboard with live NPU inference over ADB
- ✅ Safety Policy Gate with evidence grounding
- ✅ 5 preset anomaly scenarios (Air Crisis, Energy Surge, Water Leak, Multi-Domain Crisis)
- ✅ Per-step execution trace with timing

**Pending / Next Steps:**
- 🔲 LoRA domain adapter fine-tuning (per-domain specialized agents)
- 🔲 Formal 3-mode benchmark on 1,000-event SCRC-IHub evaluation set
- 🔲 Qwen 1.5B deployment on device for cross-domain reasoning (2-model swap protocol)
- 🔲 Android native dashboard (Java/Kotlin + JNI bridge to Genie C++ API)
- 🔲 Fog/cloud persistence layer (JSONL incident store + REST query API)
- 🔲 Conversational interface with tool calls on past incidents

---

## SLIDE 15 — Future Research Roadmap

**Title:** Future Extensions

**Six research directions (icons + one-line each):**

1. **🔬 LoRA Fine-Tuning** — Domain-specialized agents via LoRA adapters trained on SCRC events, increasing root-cause accuracy vs. zero-shot baseline

2. **🤝 Federated Edge Mesh** — Multiple QIDK nodes across building clusters sharing incident alerts without raw data leaving devices

3. **🪞 Digital Twin Integration** — Campus physical simulation for counterfactual reasoning ("What if we pre-cooled Zone 3 at 11 AM?")

4. **🗣️ Voice Interface** — Whisper Small (already on QIDK) + Melo TTS → full voice monitoring assistant

5. **🔮 Predictive Alerting** — LSTM/Transformer time-series predictor issuing alerts 15–30 min before anomaly (proactive vs. reactive)

6. **📊 Formal Benchmark** — 3-mode comparison (Rules vs. Single-SLM vs. Multi-Agent) on 1,000 labeled SCRC events with paired t-test, p < 0.05

---

## SLIDE 16 — Thank You / Q&A

**Title:** Agentic Edge AI for Smart Cities  
**Subtitle:** Running Llama 3.2 3B Instruct On-Device · Qualcomm QIDK · HTP V75 NPU

**Contact / Links:**
- Dashboard: http://localhost:8000 (live during demo)
- Codebase: `C:\Users\hp\Desktop\qidk\smart-city-edge-agent\`
- Deploy guide: `C:\Users\hp\Desktop\qidk\deploy.md`
- PRD: `C:\Users\hp\Desktop\qidk\PRD.md`

**Questions?**

---

## Presenter Notes — Demo Checklist

Run through this before the presentation:

```
□ QIDK connected via USB
  → adb devices shows "3ce9a4e2  device"

□ WSL terminal open, server running:
  cd /mnt/c/Users/hp/Desktop/qidk/smart-city-edge-agent
  source .venv/bin/activate
  uvicorn src.smart_city_edge.webapp.app:app --host 0.0.0.0 --port 8000

□ Browser open at http://localhost:8000
  → Header badge shows ⚡ "NPU Active — 1-Call Mode" (green)

□ Preset ready: select "🌐 Full Multi-Domain Crisis"

□ Demo sequence:
  1. Show the sliders (sensor telemetry inputs)
  2. Click "Evaluate Sensors" 
  3. Wait ~7s for NPU inference
  4. Walk through the results cards top-to-bottom
  5. Scroll to Execution Trace — point out per-step latency
  6. Show QIDK board physically — "this is what ran that inference"
```

---

## Slide Count: 16 slides

| # | Slide | Type |
|---|---|---|
| 1 | Title | Cover |
| 2 | Problem | Context |
| 3 | Why On-Device | Motivation |
| 4 | Research Thesis | Research |
| 5 | Architecture | Technical |
| 6 | Hardware (QIDK) | Technical |
| 7 | Dataset | Research |
| 8 | What We Built | Technical |
| 9 | Key Findings | Analysis |
| 10 | Live Dashboard | **Live Demo** |
| 11 | QIDK Live Inference | **Live Demo** |
| 12 | Performance Results | Analysis |
| 13 | Safety Policy Gate | Technical |
| 14 | Current vs Next | Status |
| 15 | Future Roadmap | Future |
| 16 | Thank You / Q&A | Closing |
