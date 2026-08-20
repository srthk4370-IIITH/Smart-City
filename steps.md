# Agentic Edge AI for Smart Cities — implementation steps

## 0. Goal and boundary

Build the system described by `Agentic Edge AI for Smart Cities.pptx`, **not** another presentation. The deliverable is an on-device, event-driven smart-city prototype that reasons about Energy, Air Quality, Water, Weather, and Occupancy on the Qualcomm QIDK.

The core experiment must compare the same labelled sensor events in three modes:

1. Rule-based thresholds.
2. A single Llama 3.2 3B SLM call that receives every domain summary.
3. Five prompt-specialized domain calls followed by one cross-domain Llama orchestrator call.

Do not fine-tune Llama, load five copies of the model, use cloud inference in the critical path, or autonomously actuate building equipment. The first milestone is sensor-only; camera, voice, UI, storage, digital-twin, mesh, and drift features are optional follow-ons.

## 1. Workspace facts already checked

- `qidk/` is the Qualcomm QIDK source checkout, currently clean. Preserve it and do not edit its example apps in place.
- `smart-city-edge-agent/` exists but is empty. This is the correct location for the new project.
- `qidk/GenAI-Solutions/AI-Assistant/` is the primary Genie C++/JNI integration reference.
- `qidk/GenAI-Solutions/ASR-LLM-TTS/` provides a second Llama 3.2 3B/Genie reference and optional Whisper/Melo extensions.
- `qidk/Tools/qairt_docker/` is the supported Linux Docker environment. Its base image downloads QAIRT `2.47.0.260601` and NDK `r26c`.
- The connected QIDK is Android 14 on SM8650 (Snapdragon 8 Gen 3), `arm64-v8a`, HTP V75, SELinux enforcing. Use the exact model bundle's `qairt_version.txt` as the runtime-version authority.
- Device storage is constrained: do not clean any existing device artifact before recording a manifest. Use `/data/local/tmp/smart_city_edge` for this project.

## 2. Prerequisites and decisions (complete before coding)

1. Keep the QIDK checkout immutable; create everything below in `smart-city-edge-agent/`.
2. Decide whether work will run in WSL2 Ubuntu 22.04 with Docker Desktop integration or on a native Ubuntu 22.04 host. QIDK model/build tooling is Linux-oriented.
3. Verify Docker has at least 18 GB free, and reserve 40–80 GB temporary host storage before any Llama export.
4. Obtain Qualcomm AI Hub/QPM and Hugging Face access for `llama_v3_2_3b_instruct`.
5. Keep QAIRT versions isolated. Do not assume the repository's `2.47` works with an AI Hub bundle; the bundle's `qairt_version.txt` must match the deployed runtime.
6. Confirm the project evaluation label taxonomy before generating data: `normal`, `hvac_stuck_high`, `poor_ventilation`, `water_leak`, `weather_driven_load`, `occupancy_drift`, and at least one compound fault such as `hvac_air_quality_occupancy`.

Current environment gap: the available WSL distribution is Ubuntu 24.04.4 with Python 3.12, while QIDK documents Ubuntu 22.04; Docker Desktop WSL integration is not enabled. Install/enable Ubuntu 22.04 and Docker integration before running QIDK Docker. This does not affect the connected QIDK device.

## 3. Create the project and reproducible environment

From the workspace root:

```powershell
Set-Location C:\Users\hp\Desktop\qidk\smart-city-edge-agent
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install numpy pandas scipy scikit-learn pydantic fastapi uvicorn orjson pyarrow matplotlib seaborn pytest torch onnx onnxruntime
pip freeze | Set-Content requirements-lock.txt
```

Create this initial structure:

```text
smart-city-edge-agent/
  configs/{thresholds.yaml,prompts.yaml,device-sm8650-v75.json}
  data/{raw,processed,manifests}
  models/{anomaly,genie_bundle/sm8650-v75}
  src/
  tests/
  reports/
  android/SmartCityEdge/
```

Add a `README.md` that states the experiment, a `.gitignore` excluding virtual environments, generated data, model bundles, APKs, and reports, and a `requirements-lock.txt` after the first successful install.

## 4. Implement the data contract first

Implement Pydantic models and unit tests before implementing inference:

- `SensorRecord`: timestamp, building/zone ID, all raw fields, unit/version metadata, and replay ID.
- `FeatureWindow`: fixed window bounds, fixed feature order, summaries, normalization version, and evidence IDs.
- `AnomalyEvent`: stable event ID, trigger source, score/rules, severity, and compact state.
- `DomainAnalysis`: domain name, hypothesis, evidence IDs, confidence, uncertainty, and permitted recommendation.
- `RootCauseReport`: root cause, cited evidence IDs, confidence in `[0,1]`, recommendation, uncertainties, and `requires_human_approval=true`.

Validate and reject unknown domains, missing timestamps, duplicate IDs, out-of-order events, invalid units, and negative occupancy. Document the canonical data field order:

```text
timestamp, building_id, zone_id,
energy_kw, indoor_pm25, indoor_co2, indoor_temp_c, indoor_humidity,
water_lpm, water_pressure_kpa, outdoor_temp_c, outdoor_humidity,
wind_mps, occupancy_count, hvac_state, ventilation_state
```

Write tests for valid parsing and every rejection path. Run `pytest -q` until this layer is green.

## 5. Generate a reproducible labelled benchmark

1. Implement `src.simulate` to generate synchronized 1 Hz data for 30 days, 10 buildings, and 5 zones.
2. Make building characteristics, normal daily patterns, weather, occupancy, and noise deterministic from a seed.
3. Inject the taxonomy from Section 2 with start/end times and labels stored only in the evaluation sidecar.
4. Split by building, never random rows: 60% train, 20% validation, 20% test.
5. Write Parquet data plus a JSON manifest containing seed, split IDs, generator version, scenarios, and file hashes.

Example acceptance command:

```powershell
python -m src.simulate --days 30 --buildings 10 --zones 5 --seed 20260820 --out data/processed/synthetic.parquet
```

Do not expose scenario/fault labels to the anomaly detector, SLM prompts, or policy gate. Add a small replay fixture for unit and Android tests.

## 6. Build the always-on non-LLM edge pipeline

Implement these modules in order and test each independently:

1. `SensorIngestor`: JSONL/Parquet replay now; MQTT/serial adapters later.
2. `RingBuffer`: bounded 60-minute per-building/per-zone state; prove it cannot grow unbounded.
3. `FeatureExtractor`: mean, min, max, standard deviation, slope, final value, occupancy-normalized energy, and defined cross-domain ratios. Keep a fixed feature order.
4. `RuleEngine`: domain thresholds, hysteresis, and minimum-duration requirements from `configs/thresholds.yaml`.
5. `AnomalyDetector`: a small multivariate denoising autoencoder.
6. `TriggerEngine`: produces a deduplicated event only after a persistent rule or anomaly trigger.

Train the anomaly detector only on normal training windows. Initial architecture: `F → 64 → 16 → 64 → F`, with ReLU between layers. Fit normalization only on training buildings, set reconstruction threshold at the validation 99th percentile, export fixed-shape ONNX, and store feature order, normalizer, threshold, seed, and metrics alongside it.

Required host commands:

```powershell
python -m src.rules_baseline --data data/processed/synthetic.parquet --out reports/rules.jsonl
python -m src.anomaly_train --data data/processed/synthetic.parquet --out models/anomaly --seed 20260820
python -m src.anomaly_infer --model models/anomaly/model.onnx --data data/processed/synthetic.parquet --out reports/anomaly_events.jsonl
```

Gate: publish anomaly recall, false-positive rate, trigger rate, model hash, and reconstruction-loss report before starting LLM/device work.

## 7. Define safe compact reasoning I/O

Use compact JSON only: event ID, allowed action list, recent summary statistics/trends, and evidence IDs. Never pass complete histories, labels, or camera frames to Llama.

Require this final response shape and validate it locally:

```json
{
  "root_cause": "string",
  "evidence": ["feature-or-event-id"],
  "confidence": 0.0,
  "recommendation": "string",
  "requires_human_approval": true,
  "uncertainties": ["string"]
}
```

Implement a `PolicyGate` that rejects invalid JSON, omitted/unknown evidence, unsupported actions, out-of-range confidence, and any response claiming automatic physical action. Persist rejected responses in a separate audit log.

## 8. Implement the three matched evaluation modes

All modes must consume exactly the same held-out `AnomalyEvent` objects and produce the same validated report schema.

1. **Rules**: emit rule IDs, measured values, and a conservative recommendation. Make no model calls.
2. **Single SLM**: make one Llama call containing the five compact domain summaries. Fix the prompt template, decoding settings, input cap, output schema, and allowed actions.
3. **Multi-agent SLM**: make five sequential calls over the same shared bundle — energy, air quality, water, weather, occupancy — then one orchestrator call over only those analyses and shared evidence. Do not load five model instances.

For each call log prompt-template version, input/output tokens where available, latency, model/runtime version, failure status, and validated/rejected result. Use deterministic decoding if supported; otherwise record the exact sampling settings and repeat count.

## 9. Prove Llama 3.2 3B on the QIDK before Android integration

1. Run QIDK Docker from Linux/WSL and record the commit, QAIRT, NDK, and tool versions.
2. Export `llama_v3_2_3b_instruct` for Snapdragon 8 Gen 3 / V75 using AI Hub or the supported QPM notebook workflow.
3. Read the exported bundle's `qairt_version.txt`, install that matching QAIRT SDK, and add V75 Android/Hexagon runtime artifacts. The repository examples document V79/V81, so verify the V75 library names from the matching SDK rather than copying those paths blindly.
4. Put the bundle under `models/genie_bundle/sm8650-v75/`; include a manifest with hashes and no credentials.
5. Configure all model/tokenizer/context/backend paths for `/data/local/tmp/smart_city_edge/genie_bundle/`.
6. Copy the bundle to that dedicated directory, set `LD_LIBRARY_PATH` and `ADSP_LIBRARY_PATH`, and run a one-prompt JSON smoke test with `genie-t2t-run`.
7. Save stdout, stderr, return code, elapsed time, device/thermal facts, and logcat excerpts. If HTP fails, diagnose `FastRPC`, `DSP`, `HTP`, `QNN`, and `Genie` logs first. Do not alter SELinux, remount, root, or disable verity unless a logged HTP issue proves that it is necessary and the device can be restored.

Gate: the model must generate a schema-valid, evidence-constrained report locally on the SM8650 before writing app-level orchestration.

## 10. Port the proven pipeline to Android

Create a new Android app in `android/SmartCityEdge`; use `qidk/GenAI-Solutions/AI-Assistant` as a reference only. Reuse its Genie C++/JNI pattern, `GenieDialog` lifecycle, and device-library configuration, while keeping this app's package/name separate.

Implement:

1. `ReplaySource` for timestamped JSONL input.
2. Bounded `RingBuffer` and feature extractor matching the Python feature order exactly.
3. Rule and ONNX/QNN anomaly trigger.
4. `ReasoningEngine` selector for rules, single-SLM, and multi-agent modes.
5. JNI/Genie adapter that serializes calls so only one shared model session is active.
6. `PolicyGate` and JSONL `TraceWriter`.
7. A minimal event screen showing mode, evidence, report, confidence, human-approval state, and latency.

First run the exact small replay fixture used by host tests. Confirm host/device outputs agree for rules and features before comparing LLM behavior. Build, install, and run CPU first; then evaluate GPU/HTP only when the matching runtime supports it.

## 11. Run the research evaluation

Run all three modes on the same held-out buildings, scenarios, event boundaries, action list, and device state as far as possible. Measure:

- Root-cause accuracy and macro-F1.
- Evidence precision and unsupported-evidence rate.
- Recommendation validity and policy-gate rejection rate.
- End-to-end latency and time-to-first-token.
- LLM call count, token counts, peak memory, model/package size.
- Battery/power proxy, thermal state, and NPU/HTP utilization.
- Network bytes, targeting zero in the critical path.

Write one experiment manifest per run with source commit, dataset/model hashes, QAIRT/model versions, device serial/SoC/Android build, seed, decoding parameters, thermal state, and timestamps. Report synthetic-data results as synthetic; do not make real-world performance claims until a separately documented real pilot exists.

## 12. Definition of done for the core milestone

- Reproducible synthetic data and split manifest exist.
- The bounded pipeline and autoencoder trigger are tested on host.
- Rules, single-SLM, and multi-agent SLM receive identical events.
- Outputs are schema-valid, evidence-grounded, and policy-gated.
- Llama 3.2 3B runs locally on SM8650/V75 with the matching QAIRT version.
- The Android replay app runs on the QIDK and records traces.
- At least one compound event has an evidence-cited diagnosis.
- Accuracy, latency, memory, model size, thermals/power proxy, NPU use, and network use are captured in a repeatable benchmark report.

## 13. Only then consider extensions

Add one extension at a time after preserving a core benchmark baseline: YoloNAS camera occupancy/vehicle events, HRNet posture/fall cues, Whisper push-to-talk, Melo TTS, local history, dashboard, digital twin, mesh deployment, or drift calibration. Each extension must add a new ablation and must not change the core comparison silently.
