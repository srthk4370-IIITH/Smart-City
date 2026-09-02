# Smart City Edge AI — How to Run & Test

All commands run from `smart-city-edge-agent/` after activating the venv:

```bash
cd ~/Documents/esw/smart-city-edge-agent
source .venv/bin/activate
```

---

## Quick Reference (Makefile)

| Command | What it does | Time |
|---|---|---|
| `make train` | Train autoencoder, 5,000 rows/CSV, 80/20 split | ~30s |
| `make train-full` | Train on **all rows** from all CSVs | ~10-30 min |
| `make train LIMIT=50000` | Custom row limit per CSV | varies |
| `make extract` | Extract 5,000 anomaly event windows | ~10s |
| `make extract-full` | Extract events from entire 6.6 GB dataset | ~15-30 min |
| `make test` | Run all 16 unit tests, save log | ~4s |
| `make test-unit` | Verbose test output (per-test) | ~4s |
| `make clean` | Delete model, events, test logs | instant |

---

## 1. Environment Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install torch onnx onnxscript numpy pydantic pytest pyyaml
```

---

## 2. Training the Autoencoder Anomaly Detector

Trains on SCRC-IHub CSV data with **80/20 train/test split**. Threshold is derived from the held-out test split (honest for paper).

```bash
# Sampled (default: 5,000 rows per CSV — recommended for iteration)
make train

# Full dataset (~6.6 GB across 3 CSVs — use before final submission)
make train-full

# Custom limit
make train LIMIT=50000

# Custom seed for reproducibility
make train SEED=123
```

**Output:**
- [`models/anomaly/model.onnx`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/models/anomaly/model.onnx) — trained ONNX binary
- [`models/anomaly/norm_params.json`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/models/anomaly/norm_params.json) — means, stds, train/test loss, 99th percentile threshold

**What to check in output:**
```
Train Reconstruction Loss (mean):  0.265219
Test  Reconstruction Loss (mean):  0.259721
Anomaly Threshold (test 99th pct): 0.881382
✓  No significant overfitting (gap=-0.005)
```
If overfitting gap > 0.5, you need more diverse training data.

---

## 3. Extracting Anomaly Event Windows

Streams SCRC-IHub CSVs through the Rule Engine and extracts `AnomalyEvent` windows for evaluation.

```bash
# Sampled (5,000 rows — fast, good for testing)
make extract

# Full dataset — more events = more robust benchmark stats
make extract-full
```

**Output:**
- [`data/processed/scrc_events.jsonl`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/data/processed/scrc_events.jsonl) — extracted anomaly windows (JSONL)

---

## 4. Running Unit Tests

```bash
# Quiet (summary only) — log saved automatically
make test

# Verbose (per-test output)
make test-unit
```

**Expected:** `16 passed` in ~4s. Log saved to [`reports/test_results.log`](file:///home/rishit-nanda/Documents/esw/smart-city-edge-agent/reports/test_results.log).

Tests cover:
- Data contract schemas (`test_schemas.py`)
- Policy gate & anti-hallucination (`test_core_modules.py`)
- Topology, Rule Engine, Autoencoder **80/20 split**, 3-mode Evaluator (`test_phase_modules.py`)
- SCRC-IHub CSV streaming ingestor (`test_ingestor.py`)

---

## 5. Running the 3-Mode Evaluator (Mock / On-Device)

```bash
# Runs all 3 modes in mock fallback mode on laptop
python -m smart_city_edge.evaluator
```

On QIDK device with real Genie bundle, set `use_mock_fallback=False` in `GenieRunner`.

---

## 6. Cleanup

```bash
make clean   # removes model.onnx, norm_params.json, scrc_events.jsonl, test logs
```

---

## 7. QIDK Device Commands (when physically connected)

```bash
adb devices -l                                   # confirm device connected

# Create working directory on device
adb shell "mkdir -p /data/local/tmp/smart_city_edge/genie_bundle"

# Push Genie bundle (SM8650/V75 compiled)
adb push models/genie_bundle/sm8650-v75/* /data/local/tmp/smart_city_edge/genie_bundle/

# Smoke test
adb shell "cd /data/local/tmp/smart_city_edge/genie_bundle && \
  export LD_LIBRARY_PATH=. && export ADSP_LIBRARY_PATH=. && \
  ./genie-t2t-run -c llama_v3_2_3b_chat_quantized.json \
  -p 'Return valid JSON for CO2 spike.'"
```
