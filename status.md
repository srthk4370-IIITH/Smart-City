# Smart City Edge AI — Unified Master Plan & Project Status

**Target Device**: Qualcomm QIDK / Snapdragon 8 Gen 3 (`SM8650`, HTP `V75`, Android 14)  
**Device Serial**: `3ce9a4e2`  
**Core Goal**: Deploy an on-device multi-agent AI system that monitors 5 smart city domains (Energy, Air Quality, Water, Weather, Occupancy), triggers on non-LLM edge anomaly spikes, and identifies root causes while remaining resource-friendly.

---

## Executive Overview: Completed vs. Remaining Work

| Phase / Component | Status | Primary Location / Output |
| :--- | :---: | :--- |
| **Phase 0: Environment & Hardware Discovery** | **[COMPLETED]** | QIDK SM8650 / Ubuntu 22.04 / Python 3.14 / `pytest` |
| **Phase 1: Core Data Models & Schemas** | **[COMPLETED]** | [`src/smart_city_edge/schemas.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/schemas.py) |
| **Phase 2: Campus Spatial Topology Registry** | **[COMPLETED]** | [`src/smart_city_edge/topology.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/topology.py) *(using [`data/raw/latest.json`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/data/raw/latest.json))* |
| **Phase 3: SCRC-IHub Dataset Ingestor** | **[COMPLETED]** | [`src/smart_city_edge/ingestor.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/ingestor.py) *(6.6 GB CSV dataset)* |
| **Phase 4: Always-On Edge Trigger Pipeline** | **[COMPLETED]** | [`src/smart_city_edge/rules.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/rules.py) & [`src/smart_city_edge/anomaly_model.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/anomaly_model.py) |
| **Phase 5: Autoencoder Model Training** | **[COMPLETED]** | [`scripts/train_anomaly.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/scripts/train_anomaly.py) $\rightarrow$ [`models/anomaly/model.onnx`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/models/anomaly/model.onnx) |
| **Phase 6: Evaluation Window Extraction** | **[COMPLETED]** | [`scripts/extract_events.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/scripts/extract_events.py) $\rightarrow$ [`data/processed/scrc_events.jsonl`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/data/processed/scrc_events.jsonl) |
| **Phase 7: Anti-Hallucination & Safety Gates** | **[COMPLETED]** | [`src/smart_city_edge/policy.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/policy.py) |
| **Phase 8: Multi-Agent Prompt Engine** | **[COMPLETED]** | [`src/smart_city_edge/prompts.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/prompts.py) |
| **Phase 9: Qualcomm Genie Model Executor** | **[COMPLETED]** | [`src/smart_city_edge/genie_runner.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/genie_runner.py) |
| **Phase 10: 3-Mode Benchmark Evaluator** | **[COMPLETED]** | [`src/smart_city_edge/evaluator.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/evaluator.py) |
| **Phase 11: Llama 3.2 3B Genie Bundle QIDK Deployment** | **[LEFT]** | Export/push Llama 3.2 3B Genie bundle to `/data/local/tmp/smart_city_edge/genie_bundle/` |
| **Phase 12: On-Device 3-Mode Benchmark Execution** | **[LEFT]** | Run `EvaluationHarness` on QIDK $\rightarrow$ generate [`reports/benchmark_report.md`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/reports/benchmark_report.md) |
| **Phase 13: Android Application Replay Prototype** | **[LEFT]** | Build & deploy Android app under `android/SmartCityEdge/` |

---

## 1. Detailed Breakdown of Completed Work

### 1.1 Core Data Models (`schemas.py`) — [COMPLETED]
- **File Location**: [`src/smart_city_edge/schemas.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/schemas.py)
- **What is built**:
  - `SensorRecord`: Captures 1 Hz multi-domain telemetry (Energy kW, PM2.5, CO2, Indoor Temp/Humidity, Water Flow/Pressure, Outdoor Weather, Occupancy Count).
  - `FeatureWindow`: Stores 60-minute sliding window statistics (means, min/max, trends) tagged with evidence IDs.
  - `AnomalyEvent`: Represents detected anomaly triggers (severity, domain tags, rule vs. autoencoder scores).
  - `DomainAnalysis`: Stores reasoning outputs from individual domain experts (Energy, Air Quality, Water, Weather, Occupancy).
  - `RootCauseReport`: Represents final cross-domain reasoning outputs (root cause, cited evidence IDs, confidence score, recommendation, and mandatory human-approval flag).

---

### 1.2 Campus Topology Registry (`topology.py`) — [COMPLETED]
- **File Location**: [`src/smart_city_edge/topology.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/topology.py)
- **Data Source**: [`data/raw/latest.json`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/data/raw/latest.json)
- **How it works**: Reads raw sensor node codes (e.g. `WM-WF-PL00-70`) and translates them into physical campus locations (*"Palash Nivas Hostel"*), attaches exact GPS coordinates, and assigns them to their proper domain (Air Quality `AQ`, Water Flow `WF`, Water Quality `WD`, Energy `EM`, Street Lights `SL`, Weather `SR`, or Network Nodes `WN`).

---

### 1.3 SCRC-IHub Dataset Ingestor & Streaming Reader (`ingestor.py`) — [COMPLETED]
- **File Location**: [`src/smart_city_edge/ingestor.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/ingestor.py)
- **Dataset Source**: [`SCRC-IHub-Data Collection/`](file:///home/rishit-nanda/Documents/esw/SCRC-IHub-Data%20Collection) (6.6 GB raw CSV files across 14 categories & [`meta data.xlsx`](file:///home/rishit-nanda/Documents/esw/SCRC-IHub-Data%20Collection/meta%20data.xlsx) schema specification).
- **How it works**: Streams raw CSV telemetry chunk-by-chunk without memory overload into validated `SensorRecord` and `FeatureWindow` streams.

---

### 1.4 Non-LLM Edge Trigger Pipeline (`rules.py` & `anomaly_model.py`) — [COMPLETED]
- **File Locations**:
  - Rule Engine Baseline: [`src/smart_city_edge/rules.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/rules.py) (uses [`configs/thresholds.yaml`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/configs/thresholds.yaml))
  - Autoencoder Neural Network: [`src/smart_city_edge/anomaly_model.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/anomaly_model.py)
- **How it works**:
  - **Rule Engine**: Evaluates hard threshold breaches (e.g. CO2 > 1000 ppm, water pressure > 400 kPa).
  - **Autoencoder (`F -> 64 -> 16 -> 64 -> F`)**: Neural network trained on normal sensor behavior. Compresses features into a 16-number bottleneck and attempts reconstruction. High reconstruction loss spikes wake up the AI model.

---

### 1.5 Autoencoder Training & Event Window Extraction — [COMPLETED]
- **Training Script**: [`scripts/train_anomaly.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/scripts/train_anomaly.py)
  - Fit on 10,000 telemetry rows from `aq.csv` and `wm-wf.csv`.
  - Reconstruction Loss — Mean: `0.248103`, 99th Percentile Threshold: `0.596307`.
  - Exported ONNX model: [`models/anomaly/model.onnx`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/models/anomaly/model.onnx)
  - Metadata & norm parameters: [`models/anomaly/norm_params.json`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/models/anomaly/norm_params.json)
- **Extraction Script**: [`scripts/extract_events.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/scripts/extract_events.py)
  - Extracted **1,000 validated `AnomalyEvent` evaluation windows** saved to [`data/processed/scrc_events.jsonl`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/data/processed/scrc_events.jsonl).

---

### 1.6 Anti-Hallucination & Safety Control Gate (`policy.py`) — [COMPLETED]
- **File Location**: [`src/smart_city_edge/policy.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/policy.py)
- **How it works**:
  - **Anti-Hallucination Gate**: Rejects any report citing evidence IDs that never occurred in the active sensor window.
  - **Safety Gate**: Enforces `requires_human_approval = True` on all AI output, preventing autonomous machine control.
  - **Audit Logger**: Automatically logs accepted and rejected AI reports.

---

### 1.7 Multi-Agent Prompt Engine & 3-Mode Evaluator (`prompts.py`, `genie_runner.py`, `evaluator.py`) — [COMPLETED]
- **File Locations**:
  - Prompt Engine: [`src/smart_city_edge/prompts.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/prompts.py)
  - Qualcomm Genie Runner: [`src/smart_city_edge/genie_runner.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/genie_runner.py)
  - 3-Mode Evaluator: [`src/smart_city_edge/evaluator.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/evaluator.py)
- **The 3 Modes Benchmarked**:
  1. **Mode 1: Rules Baseline** (No AI) — Hardcoded IF-THEN rules (0 ms AI latency, zero memory).
  2. **Mode 2: Single-SLM** — 1 Llama 3.2 3B call reviewing all 5 domain summaries together.
  3. **Mode 3: Multi-Agent SLM** — 5 domain-specialized calls (Energy, Air Quality, Water, Weather, Occupancy) + 1 Cross-Domain Orchestrator call synthesizing hypotheses into a final report.

## 2. Test Suite Breakdown & Verification Results

- **Executable Bash Test Runner**: [`scripts/run_tests.sh`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/scripts/run_tests.sh)
- **Saved Test Output Log**: [`reports/test_results.log`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/reports/test_results.log)

All **15 automated unit tests passed cleanly in 0.19 seconds** (`pytest -v`).

| Test Category | Test File | Key Test Cases & Purpose | Status |
| :--- | :--- | :--- | :---: |
| **Data Ingestion** | [`tests/test_ingestor.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/tests/test_ingestor.py) | • `test_scrc_ihub_ingestor_aq_streaming`: Air Quality streaming (`aq.csv`).<br>• `test_scrc_ihub_ingestor_wf_streaming`: Water Flow streaming (`wm-wf.csv`). | **PASSED** |
| **Data Contracts** | [`tests/test_schemas.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/tests/test_schemas.py) | • `test_sensor_record_accepts_contract`: Validates telemetry dicts.<br>• `test_sensor_record_rejects_negative_occupancy`: Rejects bad data (`occupancy = -1`).<br>• `test_report_requires_human_approval`: Enforces `requires_human_approval = True`. | **PASSED** |
| **Safety & Execution** | [`tests/test_core_modules.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/tests/test_core_modules.py) | • `test_policy_gate_valid_report`: Valid grounded reports pass.<br>• `test_policy_gate_rejection_ungrounded_evidence`: Rejects fake evidence IDs (`ev_hallucinated_099`).<br>• `test_policy_gate_rejection_safety_approval_false`: Rejects reports bypassing human approval.<br>• `test_genie_runner_mock_execution`: Verifies Genie runner wrapper. | **PASSED** |
| **Phase Modules** | [`tests/test_phase_modules.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/tests/test_phase_modules.py) | • `test_topology_registry_parsing`: Maps `"WM-WF-PL00-70"` to *"Palash Nivas Hostel"*.<br>• `test_rule_engine_threshold_eval`: Threshold breach detection (CO2 @ 1250 ppm).<br>• `test_autoencoder_anomaly_scorer`: PyTorch/Numpy autoencoder loss & ONNX export.<br>• `test_evaluation_harness_3mode_benchmark`: End-to-end 3-mode evaluation run. | **PASSED** |

---

## 3. Detailed Breakdown of Remaining Work (What is Left)

### Task 1: Llama 3.2 3B Genie Bundle Deployment on QIDK Device (Phase 11) — [LEFT]
- **Target Hardware**: Qualcomm Snapdragon 8 Gen 3 (SM8650 / HTP V75)
- **Actions Required**:
  1. Obtain/export Llama 3.2 3B Genie model bundle configured for SM8650/V75.
  2. Push model bundle files (`qnn_context.bin`, `llama_v3_2_3b_quantized.json`, tokenizer, C++ libraries) to QIDK device directory:
     `/data/local/tmp/smart_city_edge/genie_bundle/`
  3. Execute local on-device smoke test via `genie-t2t-run` over ADB.

---

### Task 2: On-Device 3-Mode Benchmark Execution (Phase 12) — [LEFT]
- **Target File**: [`data/processed/scrc_events.jsonl`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/data/processed/scrc_events.jsonl) (1,000 extracted anomaly windows)
- **Actions Required**:
  1. Run `EvaluationHarness` on QIDK device across all 3 modes:
     - Mode 1: Rules Baseline
     - Mode 2: Single-SLM
     - Mode 3: Multi-Agent SLM
  2. Record metrics and generate final benchmark report (`reports/benchmark_report.md`):
     - Diagnostic Root-Cause Accuracy & Macro-F1
     - Evidence Precision & Policy Rejection Rate
     - End-to-End Latency (ms) & Time-to-First-Token
     - Peak RAM (MB), Power proxy, and NPU/HTP Utilization.

---

### Task 3: Android Replay Prototype App (Phase 13) — [LEFT]
- **Target Directory**: `android/SmartCityEdge/`
- **Actions Required**:
  1. Build Android app with JNI bindings for Genie C++ runtime (`libgenie-t2t-run.so`).
  2. Implement live mode selection (Rules, Single-SLM, Multi-Agent), evidence citation UI, and audit log viewer.
