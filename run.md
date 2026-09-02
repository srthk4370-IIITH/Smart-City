# Smart City Edge AI — Execution & Testing Guide (run.md)

This guide provides step-by-step instructions for running unit tests, training the anomaly model, extracting evaluation windows, running the 3-mode evaluator, and deploying to Qualcomm QIDK hardware.

---

## 1. Environment Setup

From the repository root (`smart-city-edge-agent`):

```bash
cd smart-city-edge-agent

# Create virtual environment if needed
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install torch onnx onnxscript numpy pydantic pytest pyyaml
```

---

## 2. Running Automated Unit Tests

### Option A: Using the Executable Bash Test Runner (Recommended)
```bash
./scripts/run_tests.sh
```
*Outputs results to console and saves complete execution log to [`reports/test_results.log`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/reports/test_results.log).*

### Option B: Direct Pytest Execution
```bash
pytest -v
```

---

## 3. Training the Autoencoder Anomaly Detector

To train the PyTorch `DenoisingAutoencoder` on 10,000 rows from `SCRC-IHub-Data Collection` and export the binary ONNX model:

```bash
python3 scripts/train_anomaly.py
```

### Generated Artifacts:
- Binary ONNX Model: [`models/anomaly/model.onnx`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/models/anomaly/model.onnx) (2.5 KB binary ONNX Protobuf model)
- Normalization Metadata: [`models/anomaly/norm_params.json`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/models/anomaly/norm_params.json)

---

## 4. Extracting Anomaly Event Windows for Evaluation

To stream `SCRC-IHub-Data Collection` CSV datasets through `SCRCIHubIngestor` $\rightarrow$ `RuleEngine` / `AnomalyScorer` and generate 1,000 evaluation event windows:

```bash
python3 scripts/extract_events.py
```

### Generated Artifact:
- Extracted Anomaly Events: [`data/processed/scrc_events.jsonl`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/data/processed/scrc_events.jsonl)

---

## 5. Running the 3-Mode Benchmark Evaluator

To execute the 3-mode evaluator (**Mode 1: Rules**, **Mode 2: Single-SLM**, **Mode 3: Multi-Agent SLM**):

```bash
python3 -m smart_city_edge.evaluator
```

---

## 6. Qualcomm QIDK Device Deployment Commands (Snapdragon 8 Gen 3)

### Check Connected Device
```bash
adb devices -l
```

### Push Genie Model Bundle to Device
```bash
adb shell "mkdir -p /data/local/tmp/smart_city_edge/genie_bundle"
adb push models/genie_bundle/sm8650-v75/* /data/local/tmp/smart_city_edge/genie_bundle/
```

### Run On-Device Smoke Test via Genie Runtime
```bash
adb shell "cd /data/local/tmp/smart_city_edge/genie_bundle && export LD_LIBRARY_PATH=. && export ADSP_LIBRARY_PATH=. && ./genie-t2t-run -c llama_v3_2_3b_chat_quantized.json -p 'Return valid JSON for CO2 spike.'"
```
