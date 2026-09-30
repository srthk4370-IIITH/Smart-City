# Agentic Edge AI for Smart Cities — Product Requirements Document (PRD)

**Version:** 2.0 (Authoritative)  
**Date:** 2026-09-17  
**Institution:** IIIT Hyderabad · Embedded Systems & Wireless Lab  
**Platform:** Qualcomm QIDK (Snapdragon 8 Gen 3 / SM8650 / HTP V75)  
**Advisor:** Prof. Anuradha Vattem | TA: Lokabhiram Chintada  
**Classification:** Internal Research Document

> **Note:** This document supersedes all previous `.md` handover files, partial plans, and preliminary designs. It represents the authoritative product specification for the Agentic Edge AI for Smart Cities project. Any prior implementation that contradicts this specification must be revised to align with this document.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement & Research Thesis](#2-problem-statement--research-thesis)
3. [System Architecture Overview](#3-system-architecture-overview)
4. [Hardware & Deployment Environment](#4-hardware--deployment-environment)
5. [Data Layer — Ingestion, Ontology & Temporal Join](#5-data-layer--ingestion-ontology--temporal-join)
6. [Layer 1 — Always-On Anomaly Detection (Edge, CPU)](#6-layer-1--always-on-anomaly-detection-edge-cpu)
7. [Layer 2 — Multi-Agent Orchestration (Llama 3.2 3B, Genie)](#7-layer-2--multi-agent-orchestration-llama-32-3b-genie)
8. [Layer 3 — Cross-Domain Reasoning Engine (Qwen)](#8-layer-3--cross-domain-reasoning-engine-qwen)
9. [Safety, Grounding & Policy Gate](#9-safety-grounding--policy-gate)
10. [Fog/Cloud Storage Layer](#10-fogcloud-storage-layer)
11. [Conversational Interface with Tool Calls](#11-conversational-interface-with-tool-calls)
12. [Android Dashboard Application](#12-android-dashboard-application)
13. [Model Training & Deployment Pipeline](#13-model-training--deployment-pipeline)
14. [Evaluation & Benchmarking Framework](#14-evaluation--benchmarking-framework)
15. [Security, Privacy & Compliance](#15-security-privacy--compliance)
16. [Performance Targets & Success Criteria](#16-performance-targets--success-criteria)
17. [Risk Analysis & Mitigations](#17-risk-analysis--mitigations)
18. [Future Extensions & Research Roadmap](#18-future-extensions--research-roadmap)
19. [Appendix A — Data Schema Reference](#19-appendix-a--data-schema-reference)
20. [Appendix B — Threshold Reference Table](#20-appendix-b--threshold-reference-table)

---

## 1. Executive Summary

The **Agentic Edge AI for Smart Cities** project designs, builds, and evaluates a complete on-device, multi-layered intelligent agent system for real-time infrastructure monitoring of a smart urban campus. It is deployed natively on the **Qualcomm QIDK development platform** (Snapdragon 8 Gen 3, SM8650), exploiting the Hexagon Tensor Processor (HTP V75) and Qualcomm AI Runtime (QAIRT/Genie) for efficient on-device inference.

The system is built on three vertically stacked AI tiers:

1. **Always-On Detection Tier (CPU):** A lightweight, always-running non-LLM anomaly detector (denoising autoencoder + configurable rule engine) continuously monitors five infrastructure domains — Energy, Air Quality, Water, Weather, and Occupancy — consuming negligible power in the idle state.

2. **Multi-Agent Specialization Tier (Llama 3.2 3B, On-Device):** Upon anomaly detection, domain-specialized agents — fine-tuned LoRA role adapters on Llama 3.2 3B Instruct — are invoked for the domains flagged by the trigger. Each agent performs deep domain-specific analysis and produces a structured JSON hypothesis object.

3. **Cross-Domain Reasoning Tier (Qwen, On-Device):** The domain agent hypotheses are federated and passed to **Qwen**, a second, larger reasoning-capable SLM deployed on the same QIDK device, which synthesizes cross-domain evidence to declare a unified root cause, explains the causal chain, and issues a human-reviewable recommendation.

Additionally, the system incorporates:
- A **fog/cloud storage** layer where every incident, evidence snapshot, and Qwen report is persisted.
- A **conversational interface** powered by Qwen with tool calls, allowing users to query past incidents by natural language, retrieve and analyze historical data dynamically.
- An **Android foreground dashboard** providing live visualization of sensor streams, alert timelines, and AI-generated reasoning reports.

The core research contribution is empirically answering: *"Does a multi-agent cross-domain edge SLM architecture (Llama domain specialists + Qwen reasoner) outperform a single-SLM baseline and a rule-based baseline in root-cause diagnostic accuracy, while remaining within acceptable edge resource constraints on QIDK?"*

---

## 2. Problem Statement & Research Thesis

### 2.1 The Smart City Monitoring Gap

Modern urban infrastructure — energy grids, water distribution networks, HVAC systems, environmental quality sensors, and occupancy tracking — is typically monitored in isolated data silos. Each domain operates independently, producing threshold-based alerts that describe *what* happened, but not *why* it happened.

This siloed monitoring paradigm has a fundamental limitation: **the real root causes of infrastructure anomalies are almost always cross-domain**. Consider:

- **Scenario A:** An energy spike is observed. In isolation, the rule engine fires "Energy threshold exceeded." But the actual cause is that unusually high outdoor temperatures forced HVAC into overcooling, which also changed indoor air quality metrics and increased occupancy discomfort. A rule system fires three independent alerts; a cross-domain agent identifies a single root cause.

- **Scenario B:** Water pressure drops in a specific zone. The rule engine fires a water alert. But the root cause is that a network node cluster in that building lost connectivity (occupancy domain), causing a scheduled irrigation system to misfire. These are physically coupled events invisible to any single-domain monitor.

### 2.2 The Edge Deployment Constraint

Cloud-based AI solutions exist for building management, but they introduce:
- **Latency:** Round-trip cloud inference is unacceptable for time-sensitive infrastructure decisions.
- **Privacy Risk:** Sending raw building occupancy, water usage, and energy data to external servers violates institutional data governance policies.
- **Connectivity Dependency:** Critical facility monitoring must remain operational during network outages.

The project therefore requires **fully on-device, air-gap-capable reasoning** on the QIDK hardware.

### 2.3 The Challenge of Efficient Edge Reasoning

Small Language Models (SLMs) available for edge deployment (1B–7B parameters) have limited context windows and reasoning capability compared to frontier cloud models. The central hypothesis is that **specialization through multi-agent role decomposition** compensates for the capability gap:

- Each domain agent (Llama 3.2 3B + LoRA) specializes in one domain, reducing reasoning complexity.
- A larger, more capable model (Qwen) performs cross-domain synthesis after receiving compact, pre-analyzed JSON hypotheses from domain agents, rather than raw multi-domain sensor data.

### 2.4 Formal Research Thesis

> *"A multi-agent edge SLM architecture consisting of domain-specialized Llama 3.2 3B Instruct role agents (fine-tuned via LoRA) and a cross-domain Qwen reasoning model achieves significantly higher root-cause diagnostic accuracy and evidence grounding than (a) a rule-based threshold system and (b) a single-SLM architecture receiving all domains simultaneously, while maintaining acceptable latency (< 15 seconds total end-to-end) and memory footprint on a Snapdragon 8 Gen 3 (SM8650 / HTP V75) edge device."*

### 2.5 What the System Builds

The project delivers:
1. A production-quality edge inference pipeline for smart city infrastructure monitoring.
2. An empirical benchmark comparing three evaluation modes under identical conditions.
3. A persistent fog/cloud incident store with a conversational historical query interface.
4. An Android native dashboard for live monitoring and interaction.

---

## 3. System Architecture Overview

### 3.1 High-Level Architecture

The system consists of six layers:

```
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 6: CONVERSATIONAL INTERFACE (Qwen + Tool Calls)              │
│  Natural-language query → cloud fetch → analysis → response         │
├─────────────────────────────────────────────────────────────────────┤
│  LAYER 5: ANDROID FOREGROUND DASHBOARD                              │
│  Live sensor visualization · Alert timeline · AI report viewer      │
├─────────────────────────────────────────────────────────────────────┤
│  LAYER 4: FOG/CLOUD STORAGE                                         │
│  Incident tabulation · Evidence snapshots · Historical query API     │
├─────────────────────────────────────────────────────────────────────┤
│  LAYER 3: CROSS-DOMAIN REASONING (Qwen, On-Device, QAIRT)           │
│  Domain hypothesis synthesis · Root cause · Recommendation          │
├─────────────────────────────────────────────────────────────────────┤
│  LAYER 2: MULTI-AGENT ORCHESTRATION (Llama 3.2 3B + LoRA, On-Device)│
│  Orchestrator selects agents · Domain agents analyze domains         │
├─────────────────────────────────────────────────────────────────────┤
│  LAYER 1: ALWAYS-ON ANOMALY DETECTION (CPU, Non-LLM)               │
│  Denoising Autoencoder · Rule Engine · Trigger Gateway              │
└─────────────────────────────────────────────────────────────────────┘
        ↑                              ↓
┌───────────────┐           ┌──────────────────────────┐
│ IoT Sensor    │           │  Sensor Streams (5 domains)│
│ CSV Replay /  │           │  Energy · AQ · Water ·    │
│ Live MQTT     │           │  Weather · Occupancy      │
└───────────────┘           └──────────────────────────┘
```

### 3.2 End-to-End Event Flow

The following describes the complete lifecycle of an anomaly event, from raw sensor data to a persisted, queryable report:

**Step 1 — Continuous Sensor Ingestion:**  
The `SensorStreamManager` reads the SCRC-IHub dataset as a sliding-window replay (emulating live IoT streams). Each domain's CSV is read chunk-by-chunk. A `TemporalJoinEngine` synchronizes the five domain streams to a common 1-minute resolution `FeatureWindow` using forward-fill imputation and sparse masking.

**Step 2 — Always-On Detection (Layer 1):**  
Every `FeatureWindow` is evaluated by two parallel detectors:
- The `RuleEngine` checks all domain features against configurable thresholds loaded from `thresholds.yaml`. Any threshold breach fires a `RuleAlert`.
- The `AnomalyScorer` passes the normalized feature vector through the ONNX denoising autoencoder. If reconstruction loss > threshold, it fires an `AutoencoderAlert`.

Either type of alert produces an `AnomalyEvent` carrying the triggered domain list, severity, evidence IDs, and anomaly score.

**Step 3 — Orchestrator Activation (Layer 2):**  
The `OrchestratorAgent` (Llama 3.2 3B + orchestrator LoRA, executed via Genie on-device) receives a compact anomaly summary. It outputs a JSON routing decision: which domain agents must be consulted, in which order, and what evidence fields each agent is allowed to reference. This prevents agents from contaminating each other's analysis.

**Step 4 — Domain Agent Invocation (Layer 2):**  
For each domain selected by the Orchestrator, the corresponding `DomainAgent` (Llama 3.2 3B + domain-specific LoRA) is invoked sequentially via the Genie runtime. Each agent receives only its permitted slice of the feature window and evidence IDs. Each returns a strictly-typed `DomainAnalysis` JSON:
```json
{
  "event_id": "evt_20260917_001",
  "domain": "energy",
  "hypothesis": "Spike in consumption attributed to HVAC overcooling during peak outdoor heat",
  "evidence": ["ev_energy_kw_peak_01", "ev_hvac_state_cooling_01"],
  "confidence": 0.91,
  "uncertainty": "Occupancy not confirmed for the affected zone",
  "recommendation": "Inspect HVAC actuator in Zone 3"
}
```

**Step 5 — Cross-Domain Synthesis (Layer 3):**  
All `DomainAnalysis` objects, along with the original evidence window, are passed to the **Qwen reasoning model** (also on-device, QAIRT). Qwen produces the final `RootCauseReport`:
```json
{
  "event_id": "evt_20260917_001",
  "root_cause": "Outdoor temperature surge (38°C) caused HVAC compressor overload in Zone 3, drawing excess energy...",
  "evidence": ["ev_energy_kw_peak_01", "ev_outdoor_temp_01", "ev_hvac_state_cooling_01"],
  "confidence": 0.88,
  "recommendation": "Inspect compressor unit in Zone 3 HVAC. Schedule pre-cooling before peak hours.",
  "requires_human_approval": true,
  "uncertainties": ["Sensor calibration drift in water pressure may mask secondary leak"]
}
```

**Step 6 — Policy Validation:**  
The `PolicyGate` validates the `RootCauseReport` against the evidence whitelist, schema, and safety rules. Invalid reports are rejected and logged. Valid reports proceed.

**Step 7 — Fog/Cloud Persistence:**  
The validated `IncidentRecord` (event + analyses + Qwen report) is serialized and pushed asynchronously to the cloud storage layer (JSONL append log + REST API). The Android dashboard is notified.

**Step 8 — Dashboard Display:**  
The Android app updates in real time, showing the sensor trace, the anomaly alert, the Qwen-generated root cause, the cited evidence, and the human approval action.

**Step 9 — Conversational Query (On Demand):**  
At any time, a user types a natural-language query into the conversational interface. Qwen (via a separate conversational context) decides whether to call a tool to fetch historical data from the cloud, analyzes the retrieved data, and responds.

---

## 4. Hardware & Deployment Environment

### 4.1 Target Device

| Property | Value |
|---|---|
| Device | Qualcomm QIDK Development Kit |
| SoC | Snapdragon 8 Gen 3 (SM8650) |
| AI Accelerator | Hexagon Tensor Processor (HTP V75) |
| OS | Android 14 (arm64-v8a) |
| Device Serial | `3ce9a4e2` |
| /data Free Space | 19 GB (verified 2026-08-20) |
| Thermal Status | Nominal at baseline |
| SELinux | Enforcing |

### 4.2 Host Development Environment

| Property | Value |
|---|---|
| Host OS | Windows 11 (WSL2 for training) |
| WSL Python | Python 3.11 (training only) |
| Windows Python | Python 3.14 (host scripts) |
| GPU | NVIDIA RTX 4050 (6 GB VRAM) — Training only |
| ADB Path | `C:\Android\platform-tools\adb.exe` |
| QAIRT SDK | `2.47.0.260601` or compatible |

### 4.3 Model Memory Budget

Both Llama 3.2 3B and Qwen must coexist on the QIDK device. The Snapdragon 8 Gen 3 uses unified memory shared between CPU, GPU, and HTP. The following allocation is required:

| Component | Estimated Size | Quantization | Notes |
|---|---|---|---|
| Llama 3.2 3B (Genie Bundle) | ~1.8 GB | 4-bit | Primary agent model |
| Qwen 1.5B / 2B (Genie Bundle) | ~1.0–1.5 GB | 4-bit or 8-bit | Cross-domain reasoning model |
| Anomaly ONNX Model | < 5 MB | FP32 | Always-on detector |
| Bootstrap ONNX Models | < 10 MB | FP32 | Fast routing fallback |
| Sensor Ring Buffer | < 200 MB | N/A | Sliding window state |
| App Runtime | < 200 MB | N/A | Android process |
| **Total Peak** | **~3.5 GB** | | Within LPDDR5X budget |

> **Design Decision:** Both models should not be loaded into HTP memory simultaneously. The system must implement a model-swap protocol: Llama is loaded and executed for domain agents, then swapped out before Qwen is loaded for cross-domain synthesis. This swap is orchestrated by the `ModelManager` service.

### 4.4 Inference Engine Strategy

| Component | Target Processor | Runtime | Fallback |
|---|---|---|---|
| Denoising Autoencoder | CPU (via ONNX Runtime) | ONNX Runtime | None — must always run |
| Bootstrap Routing Models | CPU | ONNX Runtime | None |
| Llama 3.2 3B Domain Agents | HTP V75 (preferred) / GPU | Qualcomm Genie | CPU if HTP busy |
| Qwen Reasoning Model | HTP V75 (preferred) / GPU | Qualcomm Genie | CPU if HTP busy |
| Conversational Qwen | HTP V75 / CPU | Qualcomm Genie | CPU |

The Genie runtime natively manages HTP vs. GPU vs. CPU fallback. The application layer must set the appropriate priority and timeout on each inference call.

### 4.5 QIDK Repository & SDK Integration

The `qidk/` checkout (commit `175e8d4`, master) provides:
- **QAIRT (QNN/SNPE):** Model quantization and on-device execution API.
- **Genie C++ APIs:** LLM-specific runtime with tokenizer, context bin management, and streaming output.
- **JNI Bridge:** C++ native bindings called from the Android Java/Kotlin UI layer.
- **CMake Build System:** For compiling the native inference bridge.

---

## 5. Data Layer — Ingestion, Ontology & Temporal Join

### 5.1 SCRC-IHub Dataset Overview

The dataset originates from the IIIT Hyderabad Smart Campus Research Center (SCRC) and contains real IoT sensor telemetry:

| File | Domain | Key Fields | Size |
|---|---|---|---|
| `aq.csv` | Outdoor Air Quality | PM2.5, PM10, CO2 (derived), Temp, Humidity, Noise | ~1.1 GB |
| `em.csv` | Energy Meters | Voltage, Current, Power Factor, kW, kWh | ~266 MB |
| `sr-aq.csv` | Smart Room Air Quality | Indoor PM2.5, CO2, Temp, Humidity | ~680 MB |
| `sr_ac.csv` | Smart Room AC | HVAC state, setpoint, mode | ~1.1 GB |
| `sr_oc.csv` | Smart Room Occupancy | People count, room state | ~44 MB |
| `sr-em.csv` | Smart Room Energy | Zone-level power consumption | ~64 MB |
| `we.csv` | Weather Station | Outdoor Temp, RH, Wind Speed, Gust | ~12 MB |
| `wm-wf.csv` | Water Flow | Flowrate m³/h, Pressure bar | ~138 MB |
| `wm-wd.csv` | Water Quality | pH, Turbidity, TDS, Temp | ~3 MB |
| `wm-wl.csv` | Water Level | Tank/reservoir level | ~23 MB |
| `wn.csv` | Wireless Network | Node density, signal quality | ~113 MB |
| `cm.csv` | Campus Map | Building/zone metadata | ~207 KB |

**Total dataset on host:** `C:\Users\hp\Desktop\dataset\` (~3.5 GB compressed subset)

### 5.2 Topology Registry

The campus topology maps raw sensor node codes to human-readable locations, GPS coordinates, and domain assignments. The `TopologyRegistry` class reads `data/raw/latest.json` and exposes lookups like:
- `"WM-WF-PL00-70"` → `{"location": "Palash Nivas Hostel", "lat": 17.445, "lon": 78.349, "domain": "water_flow"}`

> **Requirement:** The topology registry must support **dynamic sensor registration**. New sensor nodes can be added at runtime without restarting the application, by issuing a registry update over the Android dashboard UI or via an ADB push of an updated `latest.json`. The system must detect changes and reload the registry hot.

### 5.3 Canonical Feature Vector

The system maintains a fixed-order canonical feature vector `F` of dimension 16 for the autoencoder. This order is immutable and must match exactly between training and on-device inference:

```
F = [
  energy_kw,               # [0]
  indoor_pm25,             # [1]
  indoor_co2,              # [2]  (Derived: proxy from ventilation & pm10 correlation)
  indoor_temp_c,           # [3]
  indoor_humidity,         # [4]
  water_flow_lpm,          # [5]
  water_pressure_kpa,      # [6]
  water_level_m,           # [7]
  outdoor_temp_c,          # [8]
  outdoor_humidity,        # [9]
  wind_mps,                # [10]
  occupancy_count,         # [11]
  hvac_state_encoded,      # [12]  (off=0, heating=1, cooling=2, ventilating=3)
  ventilation_state_enc,   # [13]  (off=0, on=1)
  network_node_density,    # [14]
  water_turbidity_ntu      # [15]
]
```

> **Important Note on CO2:** The outdoor `aq.csv` does not contain a direct CO2 sensor. The indoor CO2 proxy is computed from the indoor air quality data (`sr-aq.csv`). The previously implemented hack of computing CO2 as `PM10 * 10` is explicitly forbidden. The correct approach is to use the CO2 column from `sr-aq.csv` directly for indoor zones that have it, and mark CO2 as absent (masked) for outdoor zones.

### 5.4 Temporal Synchronization & Multi-Domain Join

The five domains have different sampling rates and timestamps:

| Domain Source | Typical Sampling Rate |
|---|---|
| Energy Meters (`em.csv`) | Every 15 minutes |
| Outdoor Air Quality (`aq.csv`) | Every 5 minutes |
| Smart Room AQ (`sr-aq.csv`) | Every 1 minute |
| Weather (`we.csv`) | Every 10 minutes |
| Water Flow (`wm-wf.csv`) | Every 5 minutes |
| Water Quality (`wm-wd.csv`) | Every 30 minutes |
| Occupancy (`sr_oc.csv`) | Every 1–5 minutes |
| Network (`wn.csv`) | Every 1–5 minutes |

**Join Strategy — Asof Join with Resolution Bucket:**

The `TemporalJoinEngine` operates as follows:
1. **Resolution:** All streams are resampled to a common **1-minute resolution bucket**. Each bucket represents a 1-minute interval.
2. **Forward Fill:** For low-frequency streams (energy at 15 min, water quality at 30 min), the last observed value is forward-filled until a new observation arrives, up to a maximum of **60 minutes** (1 TTL bucket). If no observation is available within 60 minutes, the value is marked as **masked**.
3. **Masked Features:** Masked features are represented in the feature vector as `NaN` or a domain-specific sentinel value. The autoencoder is trained to handle masked inputs with mean imputation at inference time. Masked features are flagged in the evidence metadata.
4. **Clock Skew Handling:** Timestamps from different sensor nodes may have clock skew up to ±2 minutes. The join engine uses a ±2 minute tolerance window when matching timestamps to a bucket.
5. **Spatial Grouping:** Joins are performed per building/zone pair. Records with mismatching building or zone IDs are not joined.

**FeatureWindow Construction:**  
Once a 1-minute bucket is fully populated (or TTL expired for slow streams), it becomes a `FeatureWindow` with a 60-minute rolling history. Each feature in the window includes:
- `mean`, `min`, `max` over the 60-minute window
- `last_value` (most recent observation)
- `trend` (linear regression slope over the window)

This produces a compact statistics object rather than 60 raw rows, keeping the context fed to domain agents small and well-structured.

### 5.5 Missing Data & Anomalous Record Handling

| Situation | Handling |
|---|---|
| Single missing value | Forward fill from prior bucket |
| Missing > 60 min | Mark as masked in feature vector |
| Negative sensor value | Quarantine record — do not forward-fill; log warning |
| Timestamp out of order | Accept if within ±5 min; discard otherwise; log |
| Parsing failure | Quarantine and log with raw line content |
| Out-of-physical-range | Clamp to physical range but flag as suspect |

> **Requirement:** All quarantine decisions must be logged to an immutable `data_quality.log` with the raw sensor record, reason code, and timestamp. This log feeds the cloud audit trail.

### 5.6 Evidence ID Generation

Every unique sensor observation that enters a `FeatureWindow` is assigned an `evidence_id` with the format:
```
ev_{domain}_{sensor_tag}_{timestamp_epoch_ms}
```
Example: `ev_energy_EM-BH01_1757891340000`

Evidence IDs are immutable once assigned. They serve as the grounding mechanism for the policy gate — every claim made by any AI agent must cite at least one valid evidence ID from the current event's evidence set.

---

## 6. Layer 1 — Always-On Anomaly Detection (Edge, CPU)

### 6.1 Design Rationale

Layer 1 must run **continuously, 24/7, at negligible power cost**. It is intentionally a non-LLM pipeline. Invoking any SLM for every sensor tick would consume unacceptable power and thermal budget. Layer 1 acts as the precise, low-latency gatekeeper that decides when to wake up the expensive AI reasoning layers.

The Layer 1 pipeline runs entirely on the **CPU** of the QIDK device. The ONNX Runtime is used for model inference, which maps directly to Qualcomm's SNPE/QNN acceleration for small models while maintaining CPU fallback.

### 6.2 Rule Engine (Mode 1 Baseline)

The `RuleEngine` evaluates hard threshold rules from `configs/thresholds.yaml`. The threshold configuration is fully externalized and configurable without code changes.

**Threshold Configuration Schema (`thresholds.yaml` — Full Specification):**

```yaml
version: 1.0
window_seconds: 3600          # 60-minute evaluation window
minimum_duration_seconds: 300 # Anomaly must persist for at least 5 min to fire
hysteresis_seconds: 120       # After alert clears, hold for 2 min before re-alerting

domains:
  energy:
    energy_kw:
      low_warning: 10.0       # Below normal load
      high_warning: 80.0      # Moderate load warning
      high_critical: 120.0    # Critical overload
      unit: kW
      policy_source: "IIITH Campus Operations Manual v2.1"
  
  air_quality:
    indoor_pm25:
      high_warning: 25.0      # WHO guideline 24h mean
      high_critical: 75.0
      unit: µg/m³
      policy_source: "WHO AQG 2021"
    indoor_co2:
      high_warning: 1000.0    # ASHRAE 62.1 comfortable occupancy
      high_critical: 1500.0   # ASHRAE 62.1 action required
      unit: ppm
      policy_source: "ASHRAE 62.1-2019"
    indoor_temp_c:
      low_warning: 18.0
      high_warning: 28.0
      high_critical: 35.0
      unit: °C
  
  water:
    water_pressure_kpa:
      low_warning: 150.0      # Below normal mains pressure
      high_warning: 400.0     # Elevated — potential pipe stress
      high_critical: 600.0    # Critical — risk of rupture
      unit: kPa
    water_turbidity_ntu:
      high_warning: 1.0       # WHO drinking water limit
      high_critical: 4.0
      unit: NTU
  
  weather:
    outdoor_temp_c:
      high_warning: 35.0      # Heat stress threshold for campus operations
      high_critical: 42.0
      unit: °C
  
  occupancy:
    occupancy_count:
      high_warning: 80        # 80% capacity — monitor HVAC
      high_critical: 100      # At or above rated capacity
      unit: persons
```

**Rule Evaluation Logic:**
1. For each feature in the current `FeatureWindow`, check `last_value` against configured thresholds.
2. If any threshold is breached, check minimum duration (the breach must have persisted for `minimum_duration_seconds` within the window).
3. If duration met and hysteresis period has elapsed since last alert, fire a `RuleAlert`.
4. Severity is determined by the breached threshold level: `warning` → `medium`, `critical` → `high`.

### 6.3 Denoising Autoencoder (Non-LLM ML Trigger)

The autoencoder is trained on normal-state sensor data and flags anomalies by high reconstruction error.

**Architecture:**
```
Input F(16) → Linear(64) → ReLU → Linear(16) → ReLU → Linear(64) → ReLU → Linear(16) → Output F(16)
```

**Training Protocol:**
- **Data:** 80% of the SCRC-IHub dataset chronologically sorted (not shuffled) to avoid temporal leakage.
- **Normal Training Distribution:** Only records not already flagged by the rule engine are used as "normal" training examples. This ensures the model learns the normal operating envelope.
- **Test Split:** Final 20% chronologically held out. Anomaly threshold = 99th percentile of reconstruction loss on the test split.
- **Normalization:** Mean and standard deviation computed from the training split only. Stored in `models/anomaly/norm_params.json`.
- **Export:** ONNX exported with opset 17. Verified lossless compared to PyTorch output.

**On-Device Scoring:**
- The `AnomalyScorer` loads `model.onnx` and `norm_params.json` at startup.
- Every `FeatureWindow`'s mean feature vector is normalized, passed through the model, and compared to threshold.
- If `reconstruction_loss > threshold`, a `AutoencoderAlert` is created with the reconstruction loss as the `anomaly_score`.

**Trigger Combination Logic:**
- If only the rule engine fires → `trigger_sources = ["rule"]`
- If only the autoencoder fires → `trigger_sources = ["anomaly_model"]`
- If both fire → `trigger_sources = ["rule", "anomaly_model"]` — highest severity
- Either trigger alone is sufficient to create an `AnomalyEvent`.

### 6.4 Event Gating & Deduplication

To prevent alert storms, the trigger gateway enforces:
- **Cooldown:** After an `AnomalyEvent` is fired for a given building/zone, another event for the same building/zone cannot be fired until the previous one has been resolved (Qwen report received) or a 15-minute timeout has elapsed.
- **Domain Deduplication:** If an active event already covers domain X and a new trigger fires only on domain X, it updates the existing event's evidence instead of creating a new one.

---

## 7. Layer 2 — Multi-Agent Orchestration (Llama 3.2 3B, Genie)

### 7.1 Design Rationale

Layer 2 introduces domain-specialized reasoning. The key architectural decision is to use **one shared Llama 3.2 3B model file** with multiple LoRA adapters, rather than separate model files per domain. This keeps the storage and memory footprint manageable on the QIDK device.

The role of Layer 2 is:
1. **Orchestration:** Decide which domain agents to call and in what order.
2. **Domain Analysis:** For each selected domain, produce a structured JSON hypothesis.

Layer 2 does **not** produce the final root cause. That is Layer 3's responsibility.

### 7.2 Orchestrator Agent

**Purpose:** Given the `AnomalyEvent` summary (triggered domains, severity, anomaly score, building/zone), decide the optimal agent call sequence.

**Model:** Llama 3.2 3B Instruct + Orchestrator LoRA adapter (`models/llama-lora/agent-orchestrator-3b/`)

**Input Prompt Structure:**
```json
{
  "role": "orchestrator",
  "event_id": "evt_20260917_001",
  "triggered_domains": ["energy", "air_quality", "occupancy"],
  "severity": "high",
  "anomaly_score": 0.91,
  "building_id": "BH-01",
  "zone_id": "3A",
  "available_agents": ["energy", "air_quality", "water", "weather", "occupancy"],
  "instruction": "Decide which domain agents to call and in what order to best diagnose the root cause. Return JSON only."
}
```

**Expected Output:**
```json
{
  "agents_in_order": ["energy", "air_quality", "occupancy"],
  "evidence_budget_per_agent": {
    "energy": ["ev_energy_kw_*", "ev_hvac_state_*"],
    "air_quality": ["ev_indoor_co2_*", "ev_indoor_pm25_*"],
    "occupancy": ["ev_occupancy_count_*"]
  },
  "orchestration_rationale": "High energy spike with AQ deviation likely HVAC-driven; occupancy needed to assess load cause",
  "root_cause": null,
  "requires_human_approval": true
}
```

> **Note:** The Orchestrator explicitly outputs `"root_cause": null`. It is not responsible for root cause determination. This constraint is enforced at the schema level to prevent the Orchestrator from overstepping its role.

**Routing Logic:**
- The Orchestrator may call a **subset** of the 5 agents. For example, a pure water pressure drop may only require the Water and Weather agents (to check if weather affects pipe pressure).
- The Orchestrator may decide **sequentially**: call Energy first, pass its output context hint to Air Quality, etc.
- The maximum number of agents the Orchestrator may select is **5** (all domains). The minimum is **2** (for cross-domain validity).

### 7.3 Domain Agents

Five domain agents, each implemented as a prompt over the shared Llama 3.2 3B model with a domain-specific LoRA adapter:

| Agent | LoRA Adapter | Domain Focus |
|---|---|---|
| Energy Agent | `models/llama-lora/energy-agent-3b/` | Power consumption, HVAC loads, grid events |
| Air Quality Agent | `models/llama-lora/aq-agent-3b/` | CO2, PM2.5, ventilation, indoor climate |
| Water Agent | `models/llama-lora/water-agent-3b/` | Flow, pressure, quality, leaks, demand |
| Weather Agent | `models/llama-lora/weather-agent-3b/` | Outdoor temp, wind, humidity, heat stress |
| Occupancy Agent | `models/llama-lora/occupancy-agent-3b/` | People count, room state, network density |

> **Current Status:** Only the Orchestrator + Air Quality LoRA adapter has been trained (`models/llama-lora/agent-orchestrator-3b/`, checkpoints at 200 and 250 steps). The remaining 4 adapters must be trained as per the training pipeline in Section 13.

**Domain Agent Prompt Contract:**  
Each domain agent receives:
- Its specific domain's feature window statistics (mean, min, max, trend over 60 min).
- The evidence IDs it is permitted to cite (as constrained by the Orchestrator's `evidence_budget`).
- A system prompt defining its role, constraints, and output schema.

**Domain Agent Output Contract (`DomainAnalysis`):**
```json
{
  "event_id": "evt_20260917_001",
  "domain": "energy",
  "hypothesis": "Free-text causal hypothesis for this domain (max 500 chars)",
  "evidence": ["ev_energy_kw_peak_01"],
  "confidence": 0.91,
  "uncertainty": "Cannot confirm whether occupancy-triggered load or HVAC fault",
  "recommendation": "Domain-specific action suggestion (max 500 chars)"
}
```

### 7.4 Model Swapping Protocol

Since Llama 3.2 3B is too large to keep in HTP memory alongside Qwen, the `ModelManager` implements adapter hot-swapping:

1. Load Llama 3.2 3B base weights into HTP memory.
2. Load Orchestrator LoRA adapter → run Orchestrator inference.
3. Hot-swap to domain agent LoRA adapter 1 → run domain agent 1.
4. Hot-swap to domain agent LoRA adapter N → run domain agent N.
5. Unload Llama 3.2 3B from HTP.
6. Load Qwen from storage into HTP → run cross-domain synthesis.
7. Unload Qwen.

LoRA adapters are small (typically 10–50 MB each) and swap in milliseconds. The base model weights remain in HTP memory across adapter swaps.

### 7.5 Sequential Execution & Latency Management

Domain agents run **sequentially** (not in parallel) on the QIDK to avoid memory overflow. The total latency for Layer 2 is approximately:
```
L_layer2 = L_orchestrator + N_agents × L_per_agent
```
Where:
- `L_orchestrator` ≈ 1–2 seconds (short routing output, ~100 tokens)
- `L_per_agent` ≈ 2–4 seconds per agent (structured JSON output, ~200 tokens each)
- `N_agents` = typically 2–4 (the Orchestrator will not always call all 5)

Estimated Layer 2 latency: **5–12 seconds** for 3 agents.

---

## 8. Layer 3 — Cross-Domain Reasoning Engine (Qwen)

### 8.1 Design Rationale

Qwen is the **synthesis and reasoning** model. It receives compact, structured `DomainAnalysis` JSON objects (not raw sensor data) from Layer 2, and its job is to:
1. **Integrate** competing or supporting hypotheses across domains.
2. **Identify causal chains** that connect domain-level observations into a single root cause.
3. **Generate** a human-readable explanation, a root cause statement, and a concrete recommendation.
4. **Quantify** uncertainty honestly, listing what is unknown or ambiguous.

Qwen is chosen over using a second Llama instance because:
- Qwen 1.5B/2B variants offer strong reasoning-per-parameter ratios.
- A separate model provides architectural separation: domain agents specialize, the reasoner generalizes.
- Qwen's multilingual and instruction-following capabilities are well-documented.

### 8.2 Qwen Model Selection & Quantization

| Variant | Params | 4-bit Size | Notes |
|---|---|---|---|
| Qwen2-1.5B-Instruct | 1.5B | ~0.9 GB | Minimal footprint, adequate for synthesis |
| Qwen2-2B-Instruct | 2B | ~1.2 GB | Better reasoning, preferred if memory allows |
| Qwen2.5-1.5B-Instruct | 1.5B | ~0.9 GB | Latest generation, recommended |

**Decision:** Begin with **Qwen2.5-1.5B-Instruct** quantized to 4-bit via QAIRT toolchain. If reasoning quality is insufficient in evaluation, upgrade to Qwen2-2B-Instruct. Do not fine-tune Qwen initially — use zero-shot prompting. The compact `DomainAnalysis` JSON inputs from domain agents serve as effective in-context structure.

### 8.3 Qwen Input Prompt — Cross-Domain Synthesis

**System Prompt:**
> "You are a Smart City Cross-Domain Root Cause Reasoning Engine. You receive structured domain hypotheses from 2–5 specialist agents. Your task is to synthesize them into a single coherent root cause explanation, identifying the primary cause, secondary effects, and the causal chain. Ground every claim in the provided evidence IDs. Output only valid JSON. Do not invoke any external API or perform actuation."

**User Input:**
```json
{
  "event_id": "evt_20260917_001",
  "timestamp": "2026-09-17T13:45:00Z",
  "building_id": "BH-01",
  "zone_id": "3A",
  "severity": "high",
  "all_evidence_ids": ["ev_energy_kw_peak_01", "ev_hvac_state_cooling_01", ...],
  "domain_analyses": [
    {
      "domain": "energy",
      "hypothesis": "Energy spike 35% above baseline during cooling cycle",
      "evidence": ["ev_energy_kw_peak_01"],
      "confidence": 0.91
    },
    {
      "domain": "air_quality",
      "hypothesis": "CO2 elevated despite ventilation active — potential HVAC inefficiency",
      "evidence": ["ev_indoor_co2_01", "ev_hvac_state_cooling_01"],
      "confidence": 0.78
    },
    {
      "domain": "occupancy",
      "hypothesis": "Zone occupancy 95 persons — above comfortable HVAC design load of 80",
      "evidence": ["ev_occupancy_count_01"],
      "confidence": 0.94
    }
  ]
}
```

**Expected Qwen Output (`RootCauseReport`):**
```json
{
  "event_id": "evt_20260917_001",
  "root_cause": "Zone BH-01/3A experienced a compounding thermal event: occupancy exceeded the HVAC design load (95 > 80 persons), causing the cooling system to operate at full capacity. This drove energy consumption 35% above baseline and simultaneously reduced effective ventilation efficiency, elevating indoor CO2. The primary root cause is occupancy overload triggering HVAC saturation.",
  "causal_chain": [
    "High occupancy (95 persons) exceeds HVAC design capacity (80)",
    "HVAC enters sustained cooling overload state",
    "Energy consumption spikes 35% above baseline",
    "Ventilation efficiency drops → CO2 elevation despite ventilation being active"
  ],
  "evidence": ["ev_occupancy_count_01", "ev_energy_kw_peak_01", "ev_hvac_state_cooling_01", "ev_indoor_co2_01"],
  "confidence": 0.87,
  "recommendation": "Reduce zone occupancy below 80 persons or schedule HVAC pre-cooling before peak occupancy hours. Inspect compressor efficiency in Zone 3A.",
  "requires_human_approval": true,
  "uncertainties": [
    "Outdoor temperature data not available for this time window — heat load contribution uncertain",
    "HVAC compressor age/efficiency not known — degradation may amplify effect"
  ]
}
```

### 8.4 Qwen Inference via Genie

Qwen is bundled and deployed via the Qualcomm QAIRT/Genie pipeline (same as Llama). A separate `QwenRunner` class (analogous to `GenieRunner`) manages Qwen's Genie bundle:

```
models/genie_bundle/qwen2_5-1_5b-instruct/sm8650-v75/
├── qwen_quantized.json        # Genie config
├── qnn_context_qwen.bin       # QNN context binary
├── tokenizer/                 # Qwen tokenizer
└── libqwen_genie.so           # Backend library
```

### 8.5 Qwen for Conversational Interface (Dual Mode)

Qwen serves two distinct operational modes:

| Mode | Trigger | Context | Output |
|---|---|---|---|
| **Synthesis Mode** | New anomaly event → domain analyses ready | Domain analysis JSON + evidence window | `RootCauseReport` JSON |
| **Conversational Mode** | User types query in Android dashboard | Conversation history + available tool definitions | Natural language response + optional tool calls |

The two modes share the same Qwen model file but use **distinct system prompts** and **context management**. In Conversational Mode, Qwen is given tool definitions for fetching historical incident data from the cloud storage API.

---

## 9. Safety, Grounding & Policy Gate

### 9.1 Design Philosophy

The system must be trusted. Smart infrastructure recommendations have real-world consequences. The policy gate is the last line of defense before any AI output reaches a human operator or gets persisted. It must **fail closed** — reject anything that is ambiguous or cannot be validated.

### 9.2 Evidence Grounding Validation

Every `evidence_id` cited in a `DomainAnalysis` or `RootCauseReport` must:
1. Exist in the `known_evidence_ids` set of the current event's feature window.
2. Belong to the correct domain (energy evidence can only be cited by the Energy agent or Qwen).
3. Fall within the event's time window (within the 60-minute rolling window).

Any hallucinated `evidence_id` causes immediate rejection of the entire report.

### 9.3 Human Approval Enforcement

`requires_human_approval: true` is a **Pydantic Literal constraint** at the schema level. The `RootCauseReport` class will reject any deserialization where this field is false or absent. The system structurally cannot produce an output that bypasses human approval.

### 9.4 Action Safety Gate

Recommendations are free-text but pass through a keyword filter. The following action patterns are **blocked** at the policy gate:

| Blocked Pattern | Reason |
|---|---|
| "shut off", "disable", "cut power to" | Autonomous actuation — requires human |
| "override", "bypass", "force close" | System override — requires authorization |
| "evacuate" | Safety-critical — escalate to emergency response |
| Any action with "immediately" + infrastructure verb | Urgency bypass attempt |

Blocked recommendations cause the report to be rejected with reason `"Action restriction violation"`. A sanitized fallback recommendation (`"Contact facility management for immediate inspection"`) is substituted.

### 9.5 Prompt Injection Defense

Domain agents receive structured JSON inputs, not free-text from users. However, the Conversational interface exposes Qwen to user-provided text. The following defenses apply:

1. **Conversation Prefix Locking:** The Qwen system prompt is locked and cannot be modified by user input.
2. **Tool Call Whitelist:** Only pre-defined tool functions (e.g., `query_incident_history`, `get_sensor_stats`) can be invoked. No arbitrary code execution.
3. **Output Sanitization:** Qwen conversational output is stripped of any patterns matching infrastructure commands.

### 9.6 Audit Logging

Every interaction with the Policy Gate — valid or rejected — is appended to an immutable audit log:
```
reports/audit_log.jsonl
```

Each entry contains:
- Timestamp and event ID
- Input raw output from the LLM
- Validation result (valid/rejected)
- Rejection reasons (if any)
- Model version and configuration version hash

The audit log is also synchronized to the cloud storage layer for retrospective review.

### 9.7 Schema Versioning

The `SensorRecord`, `FeatureWindow`, `AnomalyEvent`, `DomainAnalysis`, and `RootCauseReport` schemas are versioned with a `schema_version` field. Any mismatch between the runtime schema version and a stored record version triggers an explicit upgrade path or rejection. This prevents silent data corruption across software updates.

---

## 10. Fog/Cloud Storage Layer

### 10.1 Architecture Decision

Every anomaly event processed by the full pipeline (Layers 1–3) must be persisted. The user's stated preference is for **Qwen on-device with tool calls** to serve historical queries, rather than a separate cloud AI service. This document formalizes that choice.

The fog/cloud layer has two responsibilities:
1. **Write path:** Edge device writes every `IncidentRecord` to the cloud immediately after the Qwen report is validated.
2. **Read path:** The conversational Qwen issues a tool call to the cloud REST API to fetch historical data on demand.

### 10.2 Incident Record Schema

The `IncidentRecord` is the top-level persistent document for each anomaly event:

```json
{
  "incident_id": "INC-20260917-001",
  "event_id": "evt_20260917_001",
  "timestamp": "2026-09-17T13:45:00Z",
  "building_id": "BH-01",
  "zone_id": "3A",
  "severity": "high",
  "triggered_domains": ["energy", "air_quality", "occupancy"],
  "trigger_sources": ["rule", "anomaly_model"],
  "anomaly_score": 0.91,
  "feature_window_summary": { ... },
  "evidence_ids": ["ev_energy_kw_peak_01", ...],
  "domain_analyses": [ {...}, {...} ],
  "root_cause_report": { ... },
  "human_approved": false,
  "human_approved_by": null,
  "human_approval_timestamp": null,
  "human_notes": null,
  "device_id": "qidk_3ce9a4e2",
  "model_versions": {
    "autoencoder": "1.0",
    "llama_lora": "agent-orchestrator-3b-ckpt250",
    "qwen": "qwen2.5-1.5b-instruct-4bit"
  },
  "audit_log_entry": { ... }
}
```

### 10.3 Cloud Storage Backend Options

Given the research/prototype nature of the project, the cloud storage should be lightweight but functional:

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| Firebase Realtime DB | Free tier, easy Android SDK, real-time sync | Proprietary, noSQL | ✅ **Recommended for prototype** |
| Supabase (Postgres + REST) | Open-source, SQL queryable, REST API | Slightly more setup | Good alternative |
| Self-hosted FastAPI + SQLite | Full control, offline-capable | Requires always-on server | For production |
| Azure IoT Hub | Enterprise-grade | Overkill and paid | Not recommended |

**Chosen for prototype:** **Firebase Realtime Database** or **Firestore**, with the Android SDK for write path and a REST API for Qwen tool calls (read path).

### 10.4 Data Flow — Write Path

```
PolicyGate (QIDK)
  → IncidentRecord JSON serialization
  → WiFi/LTE network check (non-blocking)
  → Async POST to Firebase REST API
  → Local JSONL buffer (if offline, write to /data/local/tmp/incident_buffer.jsonl)
  → Background sync on reconnect
```

The write path is **non-blocking and asynchronous**. The Android dashboard displays the incident immediately; cloud persistence happens in the background. If offline, incidents buffer locally and sync when connectivity is restored.

### 10.5 Data Flow — Read Path (Tool Calls)

The `query_incident_history` tool available to Qwen in conversational mode:

```python
def query_incident_history(
    building_id: str | None = None,
    zone_id: str | None = None,
    domain: str | None = None,
    severity: str | None = None,
    start_time: str | None = None,  # ISO8601
    end_time: str | None = None,
    limit: int = 10
) -> list[IncidentRecord]:
    """Query the cloud storage for historical incident records matching the filters."""
    ...
```

Example tool call flow:
```
User: "How many energy anomalies happened in Block BH this week?"
Qwen decides: call query_incident_history(building_id="BH-01", domain="energy", start_time="2026-09-11T00:00:00Z")
Tool returns: [list of IncidentRecords]
Qwen synthesizes: "There were 7 energy anomalies in Block BH-01 this week, peaking on Wednesday..."
```

### 10.6 Local Offline Mode

The system must remain functional when the cloud is unreachable:
- Incidents are stored locally in `/data/local/tmp/smart_city_edge/incidents/` as JSONL files, partitioned by date.
- Conversational queries during offline mode search the local JSONL files instead of the cloud API.
- A sync daemon (`IncidentSyncService`) runs as a background thread in the Android app, uploading buffered incidents when connectivity returns.

---

## 11. Conversational Interface with Tool Calls

### 11.1 Overview

The conversational interface allows operators and researchers to query the system in natural language. It is surfaced in the Android dashboard as a chat-style panel alongside the live sensor view. All conversational intelligence is provided by Qwen in Conversational Mode.

### 11.2 Conversational System Prompt

```
You are the Smart City Assistant for the IIIT Hyderabad campus monitoring system.
You help operators understand anomaly events, query historical incidents, and interpret sensor data.

You have access to the following tools:
1. query_incident_history — Retrieve historical anomaly incidents from cloud storage
2. get_sensor_stats — Get current or historical statistics for a specific sensor/domain
3. get_topology_info — Look up building/zone information

Rules:
- Only use tools when the user asks about data you cannot answer from context.
- Always cite incident IDs and evidence IDs when discussing specific events.
- Do not recommend physical actuation. Always recommend human follow-up.
- If a query is outside your knowledge, say so clearly.
- Respond concisely. Maximum 3 paragraphs per response unless the user asks for detail.
```

### 11.3 Tool Definitions

**Tool 1: `query_incident_history`**  
Parameters: `building_id`, `zone_id`, `domain`, `severity`, `start_time`, `end_time`, `limit`  
Returns: List of `IncidentRecord` summaries (without full feature windows to conserve context)

**Tool 2: `get_sensor_stats`**  
Parameters: `sensor_tag`, `metric`, `start_time`, `end_time`, `aggregation` (mean/max/min/trend)  
Returns: Aggregated sensor statistics over the requested period

**Tool 3: `get_topology_info`**  
Parameters: `building_id`, `zone_id`, `sensor_tag`  
Returns: Location name, GPS coordinates, domain, connected sensors

### 11.4 Conversation Examples

**Example 1 — Historical Summary:**
```
User: "What were the top 3 anomalies last week?"
Qwen: [calls query_incident_history(start_time=..., end_time=..., limit=3)]
Qwen: "Last week's top 3 anomalies were:
1. INC-20260910-004 — High energy + CO2 spike in BH-01 Zone 3A (Sep 10, severity: high). Root cause: HVAC saturation due to occupancy overload.
2. INC-20260912-001 — Water pressure drop in Lab Block Zone 2 (Sep 12, severity: medium). Root cause: Night-time irrigation system misconfiguration.
3. INC-20260914-002 — Outdoor PM2.5 surge in Zone 5 (Sep 14, severity: medium). Root cause: Likely construction activity upwind."
```

**Example 2 — Trend Query:**
```
User: "Is energy consumption trending up in the hostel blocks?"
Qwen: [calls get_sensor_stats(sensor_tag="EM-BH*", metric="energy_kw", start_time="-30d", aggregation="trend")]
Qwen: "Yes. Energy consumption across BH hostel blocks shows a +12% upward trend over the past 30 days. Notable spikes occurred on Sep 10, Sep 14, and Sep 17. This aligns with rising outdoor temperatures increasing HVAC load."
```

**Example 3 — Incident Deep-Dive:**
```
User: "Tell me more about the water issue on Sep 12"
Qwen: [calls query_incident_history(domain="water", start_time="2026-09-12", end_time="2026-09-12")]
Qwen: "On Sep 12 at 02:30 AM, incident INC-20260912-001 was detected in the Lab Block Zone 2. Water pressure dropped from 320 kPa to 85 kPa over 20 minutes — well below the 150 kPa warning threshold. The Water Agent hypothesized a demand surge event. The Qwen reasoning engine identified a scheduled irrigation batch job that was incorrectly configured to run at 02:00 AM with full-open valves. The incident was resolved at 03:15 AM. Human approval was granted by operator ID OPS-07."
```

### 11.5 Context Window Management

Qwen's context window is finite (~4K–8K tokens depending on quantization). The conversational interface implements:
- **Conversation truncation:** Keep only the last 8 turns in context.
- **Incident summary compression:** When tool calls return incident data, compress to key fields only (id, timestamp, domain, severity, root_cause summary) before inserting into context.
- **Tool response limit:** Tool results are capped at 2000 tokens max. If exceeded, they are summarized before injection.

---

## 12. Android Dashboard Application

### 12.1 Overview

The Android dashboard is the primary human interface. It runs as a **foreground application** on the QIDK device (or optionally on a companion Android device connected over ADB). It is built with Kotlin/Java and uses JNI C++ bindings to interface with the Genie AI backend.

### 12.2 Architecture

```
Android App (Kotlin/Java UI)
  ↕ JNI (CMake / C++)
Native Layer (Genie C++ APIs)
  ├── LlamaRunner.so  (Llama agent invocation)
  ├── QwenRunner.so   (Qwen synthesis + chat)
  └── AnomalyScorer.so (ONNX autoencoder)
  ↕ ADB / direct on-device
QIDK Hardware (NPU/HTP/CPU)
```

### 12.3 UI Screens

**Screen 1 — Live Dashboard (Home)**
- Five domain status cards (Energy, AQ, Water, Weather, Occupancy) showing current readings and status (Normal / Warning / Alert).
- A timeline view showing the last 60 minutes of multi-domain sensor data as a sparkline chart.
- A global alert banner with the most recent unresolved incident.

**Screen 2 — Incident Detail View**
- Triggered by tapping an alert. Shows:
  - The full `RootCauseReport` from Qwen (root cause text, causal chain, confidence).
  - Cited evidence IDs (tappable — shows raw sensor reading).
  - Domain-agent hypotheses in collapsed accordion views.
  - A **Human Approval Panel:** "Approve" (timestamp + user ID) or "Dismiss" (with required note).
  - An "Uncertainty" section listing Qwen's stated unknowns.

**Screen 3 — Conversational Chat**
- A chat interface with Qwen in conversational mode.
- Message history persisted locally across sessions.
- A microphone button for optional voice input (via Whisper Small, if available in QIDK).
- Tool call responses displayed as compact data cards embedded in the conversation.

**Screen 4 — Sensor Explorer**
- Browse all sensor streams by domain, building, or zone.
- Plot historical data from the local JSONL store or cloud API.
- Export data as CSV for external analysis.

**Screen 5 — Settings & Configuration**
- Threshold editor (YAML editor UI that modifies `thresholds.yaml` and hot-reloads the rule engine).
- Topology viewer (map of campus buildings and sensor nodes).
- Model version display (Llama LoRA checkpoint, Qwen bundle version, Autoencoder hash).
- Cloud sync status and manual sync trigger.

### 12.4 Human Approval Mechanism

When a `RootCauseReport` arrives with `requires_human_approval: true`:
1. The app displays a push notification (foreground service) with the root cause summary.
2. The Incident Detail View is accessible for full review.
3. The operator can **Approve** (accepts the report — it is marked as human-reviewed and pushed to cloud) or **Dismiss** (reject the recommendation — recorded with mandatory dismissal note).
4. An unapproved incident older than 30 minutes escalates to a persistent alert state.

### 12.5 Mode Selection for Benchmarking

For the research evaluation, the app includes a **Mode Selector** in Settings:
- **Mode 1:** Rule-Based Only
- **Mode 2:** Single-SLM (Qwen receives raw multi-domain window directly, bypassing domain agents)
- **Mode 3:** Multi-Agent (full Llama domain agents + Qwen synthesis — the proposed architecture)

This allows live side-by-side comparison during the evaluation phase.

### 12.6 Native Android Components

The JNI layer exposes:
```cpp
// LlamaRunner.cpp
std::string runOrchestrator(const std::string& event_json);
std::string runDomainAgent(const std::string& domain, const std::string& window_json);

// QwenRunner.cpp
std::string runCrossDomainSynthesis(const std::string& analyses_json);
std::string runConversationalTurn(const std::string& history_json, const std::string& user_message);

// AnomalyScorer.cpp
float scoreFeatureWindow(const float* features, int dim);
```

---

## 13. Model Training & Deployment Pipeline

### 13.1 Stage 0 — Data Preparation

**Step 0.1 — Dataset Manifest:**
```bash
cd smart-city-edge-agent
python scripts/build_dataset_manifest.py --dataset-dir "C:\Users\hp\Desktop\dataset"
```
Outputs a verified manifest (`data/dataset_manifest.json`) with file hashes, row counts, column schemas, and basic statistics.

**Step 0.2 — Temporal Join & Feature Window Generation:**
```bash
python scripts/prepare_sft_dataset.py --manifest data/dataset_manifest.json --output data/processed/
```
Outputs:
- `data/processed/feature_windows.jsonl` — all 1-minute feature windows
- `data/processed/scrc_events.jsonl` — 1,000 anomaly evaluation windows (balanced across domains)

### 13.2 Stage 1 — Anomaly Autoencoder Training

```bash
# WSL or Windows Python 3.11 venv
python scripts/train_anomaly.py \
  --data data/processed/feature_windows.jsonl \
  --output models/anomaly/ \
  --epochs 50 \
  --hidden 64 \
  --bottleneck 16 \
  --seed 42 \
  --test-split 0.2
```

Outputs:
- `models/anomaly/model.onnx` — exported ONNX model
- `models/anomaly/norm_params.json` — per-feature mean, std, threshold
- `models/anomaly/training_log.json` — loss curve, threshold value, test metrics

**Validation Gates:**
- Test reconstruction loss < 0.35
- Overfitting gap (train - test) < 0.05
- False positive rate on normal data < 2%

### 13.3 Stage 2 — Bootstrap Routing Model Training

Already completed and verified (`models/bootstrap/`). This creates initial routing labels for Llama LoRA training.

### 13.4 Stage 3 — Llama LoRA Adapter Training (All Agents)

The Orchestrator + Air Quality adapters are done. The remaining 4 adapters (Energy, Water, Weather, Occupancy) need SFT datasets and training.

**Step 3.1 — Generate domain SFT datasets:**
```bash
# WSL Python 3.11
source .venv/bin/activate
python scripts/prepare_llama_agent_orchestrator_sft.py \
  --routing-corpus models/bootstrap/bootstrap_air_routing_corpus.jsonl \
  --output data/processed/sft/
```
Outputs per-domain SFT JSONL: `agent_energy.jsonl`, `agent_water.jsonl`, etc.

**Step 3.2 — Train each domain adapter:**
```bash
# Repeat for energy, water, weather, occupancy
make train-llama-roles DOMAIN=energy
make train-llama-roles DOMAIN=water
make train-llama-roles DOMAIN=weather
make train-llama-roles DOMAIN=occupancy
```

Each adapter trains in `models/llama-lora/{domain}-agent-3b/`.

**Training Config (QLoRA, RTX 4050 6GB):**
```yaml
base_model: meta-llama/Llama-3.2-3B-Instruct
max_train_examples: 2000
max_val_examples: 200
epochs: 1
max_sequence_length: 256
batch_size: 1
gradient_accumulation_steps: 8
lora_rank: 16
lora_alpha: 32
quantization: 4bit (bitsandbytes NF4)
```

### 13.5 Stage 4 — Merge & Export Llama Adapters

Each adapter must be merged into the base model and exported as a standalone Genie bundle:

```bash
# Per adapter
python scripts/merge_llama_adapter.py \
  --base models/base/llama-3.2-3b-instruct/ \
  --adapter models/llama-lora/energy-agent-3b/ \
  --output models/merged/llama-energy-agent/

# Then: Qualcomm AI Hub export pipeline for SM8650/V75
# (Requires QAIRT SDK and AI Hub account)
qairt-export --model models/merged/llama-energy-agent/ \
             --target sm8650 --htp V75 \
             --output models/genie_bundle/llama-energy-agent/sm8650-v75/
```

> **Note:** The Qualcomm export pipeline is the most uncertain step and may require 40–80 GB temporary storage. It should be attempted on a machine with sufficient disk space and tested incrementally, starting with the already-trained Orchestrator adapter.

### 13.6 Stage 5 — Qwen Bundle Preparation

```bash
# Download Qwen2.5-1.5B-Instruct
python scripts/download_qwen.py --model Qwen/Qwen2.5-1.5B-Instruct --output models/base/qwen2.5-1.5b/

# Export to Genie bundle
qairt-export --model models/base/qwen2.5-1.5b/ \
             --target sm8650 --htp V75 \
             --quant 4bit \
             --output models/genie_bundle/qwen2.5-1.5b/sm8650-v75/
```

### 13.7 Stage 6 — QIDK Deployment

```powershell
# Verify device connection
$env:Path = 'C:\Android\platform-tools;' + $env:Path
adb devices -l
adb -s 3ce9a4e2 shell getprop ro.soc.model  # Must return SM8650

# Create device directories
adb -s 3ce9a4e2 shell "mkdir -p /data/local/tmp/smart_city_edge/genie_bundle/llama"
adb -s 3ce9a4e2 shell "mkdir -p /data/local/tmp/smart_city_edge/genie_bundle/qwen"
adb -s 3ce9a4e2 shell "mkdir -p /data/local/tmp/smart_city_edge/models/anomaly"
adb -s 3ce9a4e2 shell "mkdir -p /data/local/tmp/smart_city_edge/incidents"

# Push Llama Genie bundles
.\scripts\deploy_bundle.ps1 -Adb 'C:\Android\platform-tools\adb.exe' -Serial 3ce9a4e2 -ModelName llama

# Push Qwen Genie bundle
.\scripts\deploy_bundle.ps1 -Adb 'C:\Android\platform-tools\adb.exe' -Serial 3ce9a4e2 -ModelName qwen

# Push anomaly model
adb -s 3ce9a4e2 push models/anomaly/model.onnx /data/local/tmp/smart_city_edge/models/anomaly/
adb -s 3ce9a4e2 push models/anomaly/norm_params.json /data/local/tmp/smart_city_edge/models/anomaly/
```

### 13.8 Stage 7 — On-Device Smoke Tests

```powershell
# Llama Orchestrator smoke test
python scripts/run_qidk_llama_roles.py \
  --adb "C:\Android\platform-tools\adb.exe" \
  --serial 3ce9a4e2 \
  --role orchestrator \
  --config llama_orchestrator_config.json

# Llama Energy Agent smoke test
python scripts/run_qidk_llama_roles.py --role energy --config llama_energy_config.json

# Qwen synthesis smoke test
python scripts/run_qidk_qwen_synthesis.py --serial 3ce9a4e2

# End-to-end pipeline smoke test
python scripts/demo_3mode.py --serial 3ce9a4e2 --events data/processed/scrc_events.jsonl --limit 5
```

**Pass Criteria for each smoke test:**
- ADB invocation exits with code 0.
- Output is valid JSON parseable into the correct schema.
- No thermal throttling event during the run.
- Latency within 2× the performance target.

---

## 14. Evaluation & Benchmarking Framework

### 14.1 Benchmark Modes

The evaluation harness (`src/smart_city_edge/evaluator.py`) runs three modes over the same fixed evaluation set:

| Mode | Description |
|---|---|
| **Mode 1: Rules Baseline** | `RuleEngine` evaluates each event. No LLM involved. |
| **Mode 2: Single-SLM** | Qwen receives the full multi-domain feature window directly (no Llama agents). |
| **Mode 3: Multi-Agent** | Full pipeline: Llama Orchestrator → Domain Agents → Qwen synthesis. |

### 14.2 Evaluation Dataset

- **Source:** `data/processed/scrc_events.jsonl` (1,000 `AnomalyEvent` windows)
- **Balance:** Roughly equal representation across the 5 domains, with cross-domain events (spanning 2+ domains) representing ≥ 30% of the set.
- **Ground Truth Labels:** Each event must be manually annotated with a `ground_truth_root_cause` field drawn from a predefined taxonomy (see below). This annotation is a critical pending step.
- **Train/Test Split:** The evaluation set must be drawn exclusively from the chronological **test split** (last 20%) of the dataset. No event window used in autoencoder or LoRA training may appear in the evaluation set.

### 14.3 Ground Truth Taxonomy

A predefined set of root cause categories is used for evaluating diagnostic accuracy:

```
TAXONOMY = {
  "HVAC_OVERLOAD": "HVAC system operating beyond rated capacity",
  "HVAC_FAULT": "HVAC mechanical/electrical fault",
  "ENERGY_GRID_EVENT": "External grid voltage/frequency event",
  "LIGHTING_FAULT": "Lighting system overconsumption",
  "WATER_PRESSURE_DROP": "Supply pressure loss due to demand or pipe event",
  "WATER_QUALITY_DEGRADATION": "pH, turbidity, or TDS out of range",
  "WATER_LEAK": "Suspected pipe leak or loss",
  "AIR_QUALITY_VENTILATION": "Inadequate ventilation causing CO2/PM buildup",
  "AIR_QUALITY_EXTERNAL": "External pollution ingress",
  "OCCUPANCY_OVERLOAD": "Occupancy exceeding rated capacity affecting systems",
  "WEATHER_HEAT_STRESS": "Outdoor temperature causing cascading indoor effects",
  "SENSOR_FAULT": "Sensor malfunction producing false anomaly",
  "UNKNOWN": "Root cause cannot be determined from available evidence"
}
```

### 14.4 Metrics

**Accuracy & Quality Metrics:**

| Metric | Definition | Target |
|---|---|---|
| Root-Cause Accuracy | % of events where predicted taxonomy label = ground truth | Mode 3 > Mode 2 > Mode 1 |
| Macro-F1 | F1 averaged across all taxonomy classes | Mode 3 > Mode 2 |
| Evidence Precision | % of cited evidence IDs that are in the valid set | Mode 3 ≈ 1.0 (policy enforced) |
| Policy Rejection Rate | % of reports rejected by PolicyGate | Lower is better |
| Hallucination Rate | % of reports with invalid evidence IDs before gate | Mode 3 < Mode 2 (specialization helps) |

**Resource Metrics (Measured On-Device):**

| Metric | Measurement Method | Target |
|---|---|---|
| Time-to-First-Token (TTFT) | Genie runner timestamp | < 3 seconds |
| Total End-to-End Latency | Wall clock from trigger to validated report | < 15 seconds (Mode 3) |
| Peak RAM Usage | `adb shell dumpsys meminfo` | < 4 GB total |
| Power Proxy (mA draw) | `adb shell dumpsys batterystats` (delta) | Log and report |
| HTP/NPU Utilization | Qualcomm profiling tools (qprofile/QNN profiler) | Log and report |
| Thermal State | `adb shell dumpsys thermalservice` | Must stay below throttle during benchmark |

**Per-Mode Latency Breakdown:**

| Mode | Expected Latency |
|---|---|
| Mode 1 (Rules) | < 10 ms (no LLM) |
| Mode 2 (Single-SLM Qwen) | 5–10 seconds |
| Mode 3 (Multi-Agent full) | 10–20 seconds (3–4 agents + Qwen) |

### 14.5 Statistical Rigor

- Run the benchmark three times on the same 1,000-event set to assess variance.
- Report mean ± standard deviation for all metrics.
- Use a paired t-test to assess statistical significance of Mode 3 vs Mode 2 accuracy improvements.
- Report p50, p95, p99 latency (not just mean).

### 14.6 Failure Mode Reporting

The benchmark must explicitly count and categorize:
- Events where the agent produced invalid JSON (parse failure).
- Events where PolicyGate rejected the output.
- Events where Qwen returned "UNKNOWN" taxonomy.
- Events where thermal throttling was detected during inference.

These failure cases are as scientifically important as successes.

---

## 15. Security, Privacy & Compliance

### 15.1 Data Privacy

The SCRC-IHub dataset contains real IIIT Hyderabad campus telemetry. The following constraints apply:

- **Occupancy Data:** Human occupancy counts are privacy-sensitive. All cloud-stored records must aggregate occupancy to zone-level (not individual tracking). Raw occupancy time-series must not leave the device unencrypted.
- **No PII in Evidence:** Evidence IDs and feature windows must not contain personally identifiable information. Sensor tags map to physical zones, not individuals.
- **Dataset Licensing:** The SCRC-IHub dataset is used under IIITH research access. It must not be uploaded to any public cloud without explicit authorization.

### 15.2 On-Device Data Security

- All model bundles stored on the QIDK device under `/data/local/tmp/smart_city_edge/` must have restricted permissions (`chmod 700`).
- Audit logs are append-only. No process (including the app) may delete or modify existing audit entries.
- The cloud sync connection must use HTTPS with certificate pinning.

### 15.3 Model Integrity

- Every deployed model file (ONNX, Genie bundles) has a SHA-256 hash stored in `model_manifest.json`.
- At startup, the Android app verifies the hash of each model file before loading. A hash mismatch halts the application and alerts the operator.

### 15.4 Adversarial Input Defense

- The conversational interface sanitizes all user input before passing to Qwen.
- Tool call outputs from the cloud API are schema-validated before injection into Qwen's context.
- Maximum user message length: 2000 characters.

---

## 16. Performance Targets & Success Criteria

### 16.1 Primary Research Success Criterion

> Mode 3 (Multi-Agent) achieves **statistically significantly higher Root-Cause Accuracy and Macro-F1** than both Mode 1 (Rules) and Mode 2 (Single-SLM), with p < 0.05.

### 16.2 Edge Resource Acceptance Criteria

The system is deemed edge-acceptable if all of the following are met:

| Constraint | Threshold |
|---|---|
| Mode 3 end-to-end latency (p95) | ≤ 20 seconds |
| Peak RAM consumption | ≤ 4.5 GB |
| Thermal throttling during benchmark | Zero events |
| Device storage footprint | ≤ 5 GB (all bundles + data) |

### 16.3 System Functional Success Criteria

| Feature | Acceptance Criterion |
|---|---|
| Anomaly Detection | False positive rate ≤ 5% on normal sensor data |
| Policy Gate | 100% rejection of reports with invalid evidence IDs |
| Cloud Sync | Incidents synced within 30 seconds of network availability |
| Conversational Interface | Correct tool invocation on ≥ 80% of test queries |
| Human Approval | 100% of reports require explicit human approval before cloud commit |
| Offline Mode | Full detection and local storage operational without network |

---

## 17. Risk Analysis & Mitigations

### 17.1 Critical Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Qwen Genie bundle fails to export for SM8650 | Medium | Critical | Fall back to Qwen2-1.5B; try alternative export tools; use CPU inference as last resort |
| Both LLMs cannot fit in device memory simultaneously | Medium | High | Implement strict model swap protocol; reduce Qwen to 1.5B; increase quantization |
| Thermal throttling during multi-agent benchmark | High | High | Add sleep intervals between agent calls; monitor thermalservice; run benchmark at night |
| LoRA fine-tuning produces low-quality domain agents | Medium | High | Augment SFT dataset; increase training examples; use stronger base prompt engineering |
| Ground truth annotation bottleneck | High | High | Define taxonomy early; use a small human-annotated set (100 events); use bootstrap labels for remainder |
| Cloud API unavailability | Low | Medium | Local JSONL buffer; offline conversational fallback |
| ADB connection instability during benchmark | Medium | Medium | Retry logic in evaluation harness; checkpoint intermediate results |

### 17.2 Fallback Architecture

If the full multi-agent Llama + Qwen pipeline cannot be achieved within the project timeline:

1. **Fallback 1:** Skip individual Llama domain adapters; use a single Llama 3.2 3B with domain-specific system prompts (no LoRA). This reduces training burden while maintaining the multi-agent architecture.

2. **Fallback 2:** If Llama Genie bundle fails, use **Qwen only** for both domain analysis (with individual domain prompts) and cross-domain synthesis. This reduces the two-tier SLM architecture to one-tier but preserves the multi-agent prompt structure.

3. **Fallback 3:** If on-device LLM inference is completely blocked, run inference over ADB from the host machine (ADB port-forward to Genie runtime on device). This degrades latency but preserves the full evaluation.

---

## 18. Future Extensions & Research Roadmap

### 18.1 Sensor Drift Recalibration

As sensors age, their baseline readings drift. A drift detection module could use the autoencoder's reconstruction loss trend over time to identify sensors that are consistently "anomalous" but always at the same offset — indicating calibration drift rather than genuine events. The autoencoder threshold could be dynamically adjusted per sensor.

### 18.2 Federated Edge Mesh

Multiple QIDK devices, each monitoring a different building cluster, could form a federated mesh. Each edge node would maintain its own local multi-agent pipeline. A lightweight federation protocol would allow nodes to share cross-campus incident alerts without sending raw sensor data.

### 18.3 Digital Twin Integration

The incident history and sensor statistics could feed a lightweight digital twin model — a simplified physical simulation of the campus buildings — to provide counterfactual reasoning: "If we had pre-cooled Zone 3A at 11 AM, what would the energy consumption have been?"

### 18.4 Voice Interface

The Android dashboard supports a microphone button placeholder. Adding Whisper Small (already demonstrated in QIDK) for speech-to-text and Melo TTS for text-to-speech would complete a full voice-interactive monitoring assistant.

### 18.5 Predictive Alerting

Rather than purely reactive anomaly detection, a second LSTM or Transformer-based time-series predictor could issue **predictive alerts** 15–30 minutes before a predicted anomaly, based on trajectory of sensor trends. This adds a proactive tier above the reactive autoencoder.

### 18.6 Multi-Campus Generalization

The current system is hardcoded to the IIITH campus topology. A generalization layer — making building IDs, zone IDs, domain mappings, and thresholds entirely configurable from a campus-specific YAML — would allow the system to be deployed on any smart campus or industrial facility.

---

## 19. Appendix A — Data Schema Reference

### A.1 SensorRecord (v1.0)
```python
class SensorRecord(StrictModel):
    record_id: str                    # Unique observation ID
    timestamp: datetime               # UTC timestamp
    building_id: str                  # Building code (e.g., "BH-01")
    zone_id: str                      # Zone within building (e.g., "3A")
    energy_kw: float                  # Current power draw (kW)
    indoor_pm25: float                # Indoor PM2.5 (µg/m³)
    indoor_co2: float                 # Indoor CO2 (ppm)
    indoor_temp_c: float              # Indoor temperature (°C)
    indoor_humidity: float            # Indoor RH (%)
    water_lpm: float                  # Water flow (L/min)
    water_pressure_kpa: float         # Water mains pressure (kPa)
    outdoor_temp_c: float             # Outdoor temperature (°C)
    outdoor_humidity: float           # Outdoor RH (%)
    wind_mps: float                   # Wind speed (m/s)
    occupancy_count: int              # Number of persons in zone
    hvac_state: Literal[...]          # HVAC operational state
    ventilation_state: Literal[...]   # Ventilation on/off/unknown
    schema_version: Literal["1.0"]    # Schema version for forward compatibility
```

### A.2 AnomalyEvent (v1.0)
```python
class AnomalyEvent(StrictModel):
    event_id: str                     # Unique event identifier
    timestamp: datetime               # Event detection timestamp
    building_id: str
    zone_id: str
    domains: tuple[Domain, ...]       # Triggered domains (1–5)
    trigger_sources: tuple[Literal["rule", "anomaly_model"], ...]
    severity: Literal["low", "medium", "high", "critical"]
    evidence_ids: tuple[str, ...]     # All evidence in the window
    anomaly_score: float | None       # Autoencoder reconstruction loss
```

### A.3 DomainAnalysis (v1.0)
```python
class DomainAnalysis(StrictModel):
    event_id: str
    domain: Domain
    hypothesis: str                   # max 500 chars
    evidence: tuple[str, ...]         # Must be subset of event evidence_ids
    confidence: float                 # [0.0, 1.0]
    uncertainty: str                  # max 500 chars
    recommendation: str               # Domain-specific action, max 500 chars
```

### A.4 RootCauseReport (v1.0)
```python
class RootCauseReport(StrictModel):
    event_id: str
    root_cause: str                   # Open-ended causal explanation
    causal_chain: list[str]           # NEW: step-by-step causal chain
    evidence: tuple[str, ...]         # Must be subset of event evidence_ids
    confidence: float                 # [0.0, 1.0]
    recommendation: str               # Human-reviewable action
    requires_human_approval: Literal[True]  # Immutable safety field
    uncertainties: tuple[str, ...]    # What Qwen does not know
```

---

## 20. Appendix B — Threshold Reference Table

The following table provides the rationale for each threshold in `thresholds.yaml`:

| Feature | Warning Threshold | Critical Threshold | Unit | Standard / Source |
|---|---|---|---|---|
| `energy_kw` | 80 | 120 | kW | IIITH campus ops baseline |
| `indoor_pm25` | 25 | 75 | µg/m³ | WHO Air Quality Guidelines 2021 |
| `indoor_co2` | 1000 | 1500 | ppm | ASHRAE Standard 62.1-2019 |
| `indoor_temp_c` | 28 | 35 | °C | ASHRAE 55-2020 thermal comfort |
| `indoor_humidity` | 70 | 80 | % | ASHRAE 55 — mold risk above 70% |
| `water_pressure_kpa` | 400 | 600 | kPa | IS 1742:1983 (Indian plumbing standard) |
| `water_turbidity_ntu` | 1.0 | 4.0 | NTU | WHO Drinking Water Quality Guidelines |
| `water_ph` | 6.5 low / 8.5 high | 6.0 / 9.0 | pH | IS 10500:2012 |
| `outdoor_temp_c` | 35 | 42 | °C | IMD heat wave alert thresholds |
| `occupancy_count` | 80 | 100 | persons | Fire code / HVAC design load (zone-specific) |
| `network_node_density` | — | < 30% of expected | nodes | Campus IT baseline |

---

*End of PRD v2.0. This document is authoritative. All implementation decisions must trace back to requirements stated here.*

---

**Document Control:**

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-09-17 | Antigravity (AI) | Initial draft |
| 2.0 | 2026-09-17 | Antigravity (AI) | Major revision — Added Qwen cross-domain reasoning, fog/cloud storage, conversational tool-call interface, full model training pipeline, complete schema appendix, threshold rationale. Supersedes all prior `.md` files. |
