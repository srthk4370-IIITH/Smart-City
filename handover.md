# Smart City Edge AI — Full Project Handover & Context

This document provides the complete context, architectural design, component mapping, and operational state of the **Agentic Edge AI for Smart Cities** project.

---

## 1. Project Background & Research Question

### 1.1 Goal
Deploy a privacy-focused, resource-efficient, on-device AI system on Qualcomm Snapdragon edge hardware (Snapdragon 8 Gen 3 / QIDK) to monitor 5 smart city domains:
1. **Energy** (power kW, voltage, current, total energy)
2. **Air Quality** (PM2.5, PM10, CO2, indoor temp/humidity, noise)
3. **Water** (flowrate m³/h, pressure bar, water level, turbidity, pH, TDS)
4. **Weather** (outdoor temp, humidity, wind speed, gust, dew point)
5. **Occupancy** (people count, room occupancy, network node density)

### 1.2 Research Question
*"Does multi-agent cross-domain reasoning (5 domain expert roles + 1 orchestrator) improve diagnostic root-cause accuracy and evidence grounding while remaining acceptable for edge resource constraints (latency, RAM, power, NPU utilization) compared to single-SLM and rule-based baselines?"*

---

## 2. Target Hardware & Host Environment Specifications

- **Target Device**: Qualcomm QIDK Development Kit
- **SoC**: Qualcomm Snapdragon 8 Gen 3 (`SM8650`, HTP `V75`, Android 14)
- **Connected Serial**: `3ce9a4e2`
- **Device Storage**: `/data` (19 GB free), `/data/local/tmp` (5.1 GB used)
- **Device Working Directory**: `/data/local/tmp/smart_city_edge`
- **Host System**: Ubuntu Linux (Python 3.14, PyTorch, PyYAML, Pydantic, pytest)

---

## 3. Dataset Architecture: SCRC-IHub Data Collection

- **Dataset Path**: [`SCRC-IHub-Data Collection/`](file:///home/rishit-nanda/Documents/esw/SCRC-IHub-Data%20Collection)
- **Size**: **6.6 GB** of real-world IIIT Hyderabad smart campus sensor telemetry across 14 CSV files & metadata:
  - `aq.csv` (1.80 GB) — Air Quality (PM2.5, PM10, Temp, Humidity, Noise)
  - `em.csv` (335 MB) — Energy Meters (Line Voltages, Current, Power Factor, Frequency, Total Energy)
  - `sl.csv` (777 MB) — Street Lights (Voltage, Current, Power, Energy)
  - `wm-wf.csv` (188 MB) — Water Flow (Flowrate, Total Flow, Line Pressure)
  - `wm-wd.csv` (4.17 MB) — Water Quality (pH, Turbidity, TDS, Temp)
  - `wm-wl.csv` (33.3 MB) — Water Level
  - `we.csv` (18.1 MB) — Weather Station (Temp, RH, Wind Speed, Wind Direction, Gust)
  - `sr_oc.csv` (59.6 MB) & `sr_ac.csv` (2.09 GB) — Smart Room Occupancy & AC Status
  - `wn.csv` (173 MB) — Wireless Network Nodes (Signal RSSI, Latency, ETX, RPL rank)
  - `meta data.xlsx` — Parameter specifications, units, and sensor resolutions.

---

## 4. Completed Codebase Architecture & File Mapping

```text
smart-city-edge-agent/
├── configs/
│   ├── thresholds.yaml         # Rule baseline threshold limits
│   └── prompts.yaml            # Single-SLM & Multi-Agent domain prompt templates
├── data/
│   ├── raw/latest.json         # IIIT-H campus spatial topology registry snapshot
│   └── processed/scrc_events.jsonl # 1,000 extracted anomaly evaluation windows
├── models/
│   └── anomaly/
│       ├── model.onnx          # Binary ONNX Protobuf Denoising Autoencoder (2.5 KB)
│       └── norm_params.json    # Scaling means/stds & 99th percentile loss threshold (0.661877)
├── reports/
│   └── test_results.log        # Automated test execution output log (15/15 passed)
├── scripts/
│   ├── train_anomaly.py        # PyTorch autoencoder training & ONNX exporter
│   ├── extract_events.py       # SCRC-IHub dataset event extraction pipeline
│   └── run_tests.sh            # Executable bash test runner script
├── src/smart_city_edge/
│   ├── schemas.py              # Pydantic data models & contracts
│   ├── topology.py             # Campus topology spatial registry
│   ├── ingestor.py             # SCRC-IHub chunked CSV streaming reader
│   ├── rules.py                # Mode 1 Rule Engine baseline
│   ├── anomaly_model.py        # Denoising Autoencoder & PyTorch/Numpy scorer
│   ├── policy.py               # Anti-Hallucination & Safety Control Gate
│   ├── prompts.py              # Single-SLM & Multi-Agent prompt builders
│   ├── genie_runner.py         # Qualcomm Genie runtime interface wrapper
│   └── evaluator.py            # Matched 3-Mode Evaluation Harness
└── tests/
    ├── test_schemas.py         # Data contract unit tests
    ├── test_core_modules.py    # Policy gate, prompt engine & genie runner tests
    ├── test_phase_modules.py   # Topology, rule engine, autoencoder & evaluator tests
    └── test_ingestor.py        # SCRC-IHub CSV streaming ingestor tests
```

---

## 5. Key System Guardrails & Model Design

### 5.1 Autoencoder Anomaly Trigger (`F -> 64 -> 16 -> 64 -> F`)
- **Bottleneck Architecture**: `Input(16) -> Linear(64) -> ReLU -> Linear(16) -> ReLU -> Linear(64) -> ReLU -> Linear(16)`.
- **Function**: Trained exclusively on normal campus telemetry. High reconstruction loss spikes (reconstruction loss > `0.661877`) trigger an `AnomalyEvent` to wake up the main reasoning model.

### 5.2 Anti-Hallucination Evidence Gate
- Located in [`src/smart_city_edge/policy.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/policy.py).
- Cross-examines every evidence ID cited in the AI's diagnostic report against the active 60-minute sensor database. If the AI cites a non-existent evidence tag, the report is instantly rejected.

### 5.3 Safety Control Gate
- Mandatory schema rule requiring `requires_human_approval = True` on all AI output, blocking unauthorized autonomous machine control.

---

## 6. Automated Unit Test Verification

- Executable script: [`scripts/run_tests.sh`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/scripts/run_tests.sh)
- Execution Log: [`reports/test_results.log`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/reports/test_results.log)
- **Pass Status**: **15 / 15 unit tests passed in 0.20s** (`pytest -v`).
