# Smart City Edge AI — Implementation Plan (What To Do Next)

This document outlines the exact execution roadmap to transition the verified host prototype onto the **Qualcomm QIDK Snapdragon 8 Gen 3 (`SM8650` / `V75` HTP)** hardware and run the final research benchmarks.

---

## Roadmap Summary

```
 ┌─────────────────────────────────────────────────────────┐
 │               Host Prototype (COMPLETED)                │
 │ • Data Contracts, Topology & Ingestor                   │
 │ • Trained PyTorch Autoencoder (model.onnx)             │
 │ • 1,000 Extracted Anomaly Events (scrc_events.jsonl)   │
 │ • Policy Gate, Prompt Engine & 15/15 Passed Unit Tests │
 └────────────────────────────┬────────────────────────────┘
                              │
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │          Phase 1: QIDK Model Deployment (NEXT)          │
 │ • Obtain/export Llama 3.2 3B Genie bundle (SM8650/V75)  │
 │ • Push bundle to /data/local/tmp/smart_city_edge/       │
 │ • Run ADB smoke test via genie-t2t-run                  │
 └────────────────────────────┬────────────────────────────┘
                              │
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │       Phase 2: On-Device 3-Mode Research Benchmark      │
 │ • Execute EvaluationHarness over scrc_events.jsonl      │
 │ • Mode 1 (Rules) vs Mode 2 (Single) vs Mode 3 (Multi)   │
 │ • Record Accuracy, Macro-F1, Rejection, Latency, NPU    │
 └────────────────────────────┬────────────────────────────┘
                              │
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │      Phase 3: Android Prototype & Final Evaluation      │
 │ • Build Android app with Genie JNI C++ bindings         │
 │ • Display live mode selection, evidence & audit log UI  │
 └─────────────────────────────────────────────────────────┘
```

---

## Detailed Execution Steps

### Phase 1: Llama 3.2 3B Genie Bundle Deployment on QIDK Device
- **Target Hardware**: Qualcomm QIDK / Snapdragon 8 Gen 3 (`SM8650`, HTP `V75`, Android 14, device `3ce9a4e2`).
- **Steps**:
  1. Export or download the `llama_v3_2_3b_instruct` Genie bundle compiled for Snapdragon 8 Gen 3 (`SM8650` / `V75`).
  2. Create device working directory over ADB:
     ```bash
     adb shell "mkdir -p /data/local/tmp/smart_city_edge/genie_bundle"
     ```
  3. Push the compiled Genie bundle, tokenizer, context binaries, and backend libraries to the QIDK device:
     ```bash
     adb push models/genie_bundle/sm8650-v75/* /data/local/tmp/smart_city_edge/genie_bundle/
     ```
  4. Run on-device smoke test via `genie-t2t-run`:
     ```bash
     adb shell "cd /data/local/tmp/smart_city_edge/genie_bundle && export LD_LIBRARY_PATH=. && export ADSP_LIBRARY_PATH=. && ./genie-t2t-run -c llama_v3_2_3b_chat_quantized.json -p 'Return valid JSON for CO2 1200ppm spike.'"
     ```

---

### Phase 2: Execute On-Device 3-Mode Research Benchmark
- **Input Data**: [`data/processed/scrc_events.jsonl`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/data/processed/scrc_events.jsonl) (1,000 extracted `AnomalyEvent` evaluation windows).
- **Steps**:
  1. Execute [`src/smart_city_edge/evaluator.py`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/src/smart_city_edge/evaluator.py) on the QIDK device across all 3 modes:
     - **Mode 1: Rules Baseline (No AI)** — Fixed threshold rules.
     - **Mode 2: Single-SLM** — 1 Llama 3.2 3B call reviewing all 5 domain summaries together.
     - **Mode 3: Multi-Agent SLM** — 5 domain-specialized expert calls + 1 Cross-Domain Orchestrator call.
  2. Collect performance metrics using `dumpsys`:
     ```bash
     adb shell dumpsys meminfo <package.name>
     adb shell dumpsys batterystats <package.name>
     ```
  3. Generate final research report at [`reports/benchmark_report.md`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/reports/benchmark_report.md) measuring:
     - **Root-Cause Diagnostic Accuracy & Macro-F1**
     - **Anti-Hallucination Evidence Precision & Policy Rejection Rate**
     - **End-to-End Latency (ms) & Time-to-First-Token (TTFT)**
     - **Peak Memory (RAM), Power Proxy, and NPU/HTP Utilization**

---

### Phase 3: Build Android Prototype Application
- **Target Location**: `android/SmartCityEdge/`
- **Steps**:
  1. Initialize Android Gradle application with JNI C++ bindings (`CMakeLists.txt`) linking `libgenie-t2t-run.so`.
  2. Implement Kotlin/Java UI components:
     - Mode selection toggle (Rules vs Single-SLM vs Multi-Agent SLM)
     - Live sensor stream replay view
     - Cited evidence tags & anti-hallucination status indicator
     - Mandatory human-approval action confirmation modal.
  3. Compile APK and install on QIDK device:
     ```bash
     adb install -r -t app-debug.apk
     ```
