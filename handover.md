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
- **Device Storage**: `/data` (19 GB free), working dir: `/data/local/tmp/smart_city_edge`
- **Host System**: Ubuntu Linux (Python 3.14, PyTorch, venv at `.venv/`)

---

## 3. Dataset: SCRC-IHub Data Collection

- **Dataset Path**: [`SCRC-IHub-Data/`](file:///home/rishit-nanda/Documents/esw/SCRC-IHub-Data) (renamed from `SCRC-IHub-Data Collection`)
- **Size**: **6.6 GB** of real IIIT Hyderabad smart campus sensor telemetry, 14 CSV files:

| File | Size | Contents |
|---|---|---|
| `aq.csv` | 1.80 GB | Air Quality (PM2.5, PM10, Temp, Humidity, Noise) |
| `em.csv` | 335 MB | Energy Meters (Voltage, Current, Power Factor, Energy) |
| `sl.csv` | 777 MB | Street Lights |
| `wm-wf.csv` | 188 MB | Water Flow (Flowrate, Pressure) |
| `wm-wd.csv` | 4.17 MB | Water Quality (pH, Turbidity, TDS, Temp) |
| `wm-wl.csv` | 33.3 MB | Water Level |
| `we.csv` | 18.1 MB | Weather (Temp, RH, Wind Speed, Gust) |
| `sr_oc.csv` | 59.6 MB | Smart Room Occupancy |
| `sr_ac.csv` | 2.09 GB | Smart Room AC Status |
| `sr-aq.csv` | 1.08 GB | Smart Room Air Quality |
| `sr-em.csv` | 91.8 MB | Smart Room Energy |
| `wn.csv` | 173 MB | Wireless Network Nodes |
| `cm.csv` | 286 KB | Campus Map metadata |
| `meta data.xlsx` | 42 KB | Parameter specs, units, sensor resolutions |

---

## 4. Codebase Architecture

```text
smart-city-edge-agent/
├── Makefile                        # make train / test / extract / clean
├── configs/
│   ├── thresholds.yaml             # Rule baseline threshold limits
│   └── prompts.yaml                # Prompt templates
├── data/
│   ├── raw/latest.json             # Campus topology snapshot
│   └── processed/scrc_events.jsonl # Extracted anomaly evaluation windows
├── models/anomaly/
│   ├── model.onnx                  # Trained ONNX binary (80/20 split)
│   └── norm_params.json            # Means, stds, train/test loss, threshold
├── reports/
│   └── test_results.log            # Automated test output (16/16 passed)
├── scripts/
│   ├── train_anomaly.py            # 80/20 split autoencoder trainer + ONNX exporter
│   ├── extract_events.py           # SCRC-IHub event extraction pipeline
│   └── run_tests.sh                # Bash test runner script
└── src/smart_city_edge/
    ├── schemas.py                  # Pydantic data contracts
    ├── topology.py                 # Campus topology spatial registry
    ├── ingestor.py                 # SCRC-IHub chunked CSV streaming reader
    ├── rules.py                    # Mode 1 Rule Engine baseline
    ├── anomaly_model.py            # Denoising Autoencoder & AnomalyScorer
    ├── policy.py                   # Anti-Hallucination & Safety Policy Gate
    ├── prompts.py                  # Single-SLM & Multi-Agent prompt builders
    ├── genie_runner.py             # Qualcomm Genie runtime wrapper (mock fallback)
    └── evaluator.py                # 3-Mode Evaluation Harness
```

---

## 5. Makefile Commands

From `smart-city-edge-agent/` with venv active:

| Command | What it does |
|---|---|
| `make train` | Train autoencoder (5,000 rows/CSV, 80/20 split) |
| `make train-full` | Train on full 6.6 GB dataset |
| `make train LIMIT=N` | Custom row limit per CSV |
| `make extract` | Extract anomaly event windows (5,000 rows) |
| `make extract-full` | Extract from full dataset |
| `make test` | Run all 16 unit tests, save log |
| `make test-unit` | Verbose per-test output |
| `make clean` | Remove model, events, logs |

---

## 6. Autoencoder Training Results (5,000 rows/CSV)

- **Architecture**: `Input(16) → Linear(64) → ReLU → Linear(16) → ReLU → Linear(64) → ReLU → Linear(16)`
- **Train/Test Split**: 80% / 20% (shuffled, seed=42)
- **Normalization**: Computed from train split only (no data leakage)
- **Anomaly threshold derived from test split 99th percentile** (correct for paper)

```
Train samples:                  12,000
Test samples:                    3,000
Train Reconstruction Loss:      0.265219
Test  Reconstruction Loss:      0.259721
Anomaly Threshold (99th pct):   0.881382
Overfitting gap:                -0.005  ✓ (no overfitting)
```

---

## 7. Key Safety Guardrails

### Anti-Hallucination Evidence Gate (`policy.py`)
Every evidence ID cited in the AI's report is cross-checked against the active sensor database. Fabricated evidence IDs cause instant rejection.

### Safety Control Gate
`requires_human_approval = True` is mandatory on all AI output. The schema enforces this at the Pydantic level, blocking autonomous machine control.

---

## 8. Unit Test Status

- **Tests**: 16 / 16 passed
- **New test added**: `test_autoencoder_train_test_split` — verifies disjoint train/test sets, normalization leakage, and that threshold comes from test split
- **Log**: [`reports/test_results.log`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/reports/test_results.log)

---

## 9. What's Left (QIDK Phase)

1. **Get Llama 3.2 3B Genie bundle** compiled for SM8650/V75 from [Qualcomm AI Hub](https://aihub.qualcomm.com/models/llama_v3_2_3b_instruct)
2. **Push to device** via `adb push`
3. **Run real 3-mode benchmark** using `evaluator.py` with `use_mock_fallback=False`
4. **Collect metrics**: Accuracy, Macro-F1, Latency, RAM, Power, NPU utilization
5. **Build Android app** under `android/SmartCityEdge/` with JNI bindings
