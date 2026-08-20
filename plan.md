# QIDK Build Plan — Agentic Edge AI for Smart Cities

## 1. Deliverable

Build the working prototype described in \`Agentic Edge AI for Smart Cities.pptx\`, not a new presentation.

The prototype ingests synchronized Energy, Air Quality, Water, Weather, and Occupancy signals; keeps bounded local state; detects anomalies; and produces a cross-domain root-cause explanation and recommendation on Qualcomm QIDK.

Compare three systems on identical data and hardware:

1. Rule-based thresholds.
2. One SLM receiving all domain summaries.
3. Multi-agent SLM: five domain roles plus one cross-domain orchestrator.

The research question is whether multi-agent cross-domain reasoning improves root-cause accuracy while remaining acceptable for edge latency, memory, power, model size, network usage, and NPU utilization.

## 2. QIDK-specific prerequisites

The QIDK quick-start requires Ubuntu 22.04, internet access, at least 18 GB free on the Docker storage partition, QAIRT \`2.47.0.260601\`, Android NDK \`r26c\`, and the QIDK QAIRT Docker workflow. The container provides TensorFlow, PyTorch, ONNX, QAIRT, and Android tooling.

The current host is Windows. Use Ubuntu 22.04 in WSL2 with Docker Desktop WSL integration, or use a native Ubuntu 22.04 machine. Keep Windows PowerShell for ADB if convenient.

Official QIDK workflow:

\`\`\`
clone repository → run Tools/qairt_docker/run_qairt_docker.sh
→ generate/quantize models in Docker → resolveDependencies.sh
→ build APK in Android Studio → prepare Snapdragon device
→ adb install → run CPU/GPU/HTP comparison
\`\`\`

## 3. Target device facts

Collected with \`C:\\Android\\platform-tools\\platform-tools\\adb.exe\`:

- Serial: \`3ce9a4e2\`
- Model: \`Pineapple for arm64\`
- SoC: \`SM8650\` / Snapdragon 8 Gen3
- Android: 14
- ABI: \`arm64-v8a\`
- HTP target: **V75**
- SELinux: enforcing
- \`/data\`: approximately 19 GB free of 45 GB
- \`/data/local/tmp\`: approximately 5.1 GB used
- Root filesystem: full; do not write there

Existing artifacts include a 2.9 GB Gemma task model, YoloV8n and HRNet ONNX files, SNPE benchmark directories, and QIDK demo packages. Inventory before cleanup. Use \`/data/local/tmp/smart_city_edge\` for this project.

## 4. Exact stack and models

### Host and Android

- Ubuntu 22.04 + Docker for QIDK model/build work.
- Android Studio Panda 4 \`2025.3.4\`.
- Android Gradle app, \`arm64-v8a\`.
- Kotlin/Java app shell, C++/JNI + CMake for hot paths.
- Python, NumPy, pandas, SciPy, scikit-learn, PyTorch, ONNX, ONNX Runtime, Pydantic, pytest, Parquet, JSONL.
- QAIRT, QNN / AI Engine Direct, Genie C++ APIs.

### Primary reasoning model

Use **Llama 3.2 3B Instruct**, exported through Qualcomm AI Hub/Genie for SM8650/V75. QIDK documents this model in \`GenAI-Solutions/AI-Assistant\` and \`GenAI-Solutions/ASR-LLM-TTS\`.

Use one shared Llama bundle. The five domain agents are sequential prompt-specialized calls, not five loaded models.

### Trainable anomaly model

Train one multivariate denoising autoencoder for event triggering:

\`\`\`
F features → Linear(64) → ReLU → Linear(16) → ReLU
→ Linear(64) → ReLU → Linear(F)
\`\`\`

Train only on normal windows. Threshold validation reconstruction error at the 99th percentile. Export fixed-shape ONNX; convert to QNN only after host behavior is proven.

Optional models—YoloNAS/HRNet for camera occupancy or pose, Whisper Small for voice, and Melo TTS for spoken output—are not first-milestone dependencies.

## 5. Phase 0 — create the official QIDK build environment

### Windows WSL2 setup

In Administrator PowerShell:

\`\`\`powershell
wsl --install -d Ubuntu-22.04
\`\`\`

After reboot, open Ubuntu and verify:

\`\`\`bash
lsb_release -a
docker --version
git --version
docker system df
df -h /
\`\`\`

If Docker is unavailable, install Docker Desktop, enable **Use the WSL 2 based engine**, and enable Ubuntu-22.04 under Docker Desktop → Settings → Resources → WSL Integration. Ensure Docker has at least 18 GB free.

### QIDK checkout and container

Inside Ubuntu:

\`\`\`bash
mkdir -p ~/work
cd ~/work
git clone https://github.com/quic/qidk.git
cd qidk/Tools/qairt_docker
chmod +x run_qairt_docker.sh
./run_qairt_docker.sh -m /mnt/c/Users/hp/Desktop/qidk -t /local
\`\`\`

The first build downloads QAIRT \`2.47.0.260601\` and Android NDK \`r26c\` and may take 30+ minutes. Inside the container verify:

\`\`\`bash
echo "$QAIRT_SDK_ROOT"
echo "$ANDROID_NDK_ROOT"
qnn-net-run --version
python --version
\`\`\`

If using the existing Windows clone, confirm the mounted path and record:

\`\`\`bash
git rev-parse --short HEAD
\`\`\`

## 6. Phase 1 — create project skeleton and contracts

Create a sibling project; do not edit QIDK examples in place:

\`\`\`text
smart-city-edge-agent/
  data/{raw,processed,manifests}
  models/anomaly/
  models/genie_bundle/sm8650-v75/
  src/{schema.py,simulate.py,features.py,anomaly_train.py,anomaly_infer.py}
  src/{rules_baseline.py,single_slm.py,domain_agents.py,orchestrator.py,evaluate.py}
  android/SmartCityEdge/
  configs/{thresholds.yaml,prompts.yaml,device-sm8650-v75.json}
  tests/
  reports/
\`\`\`

Implement Pydantic models for \`SensorRecord\`, \`FeatureWindow\`, \`AnomalyEvent\`, \`DomainAnalysis\`, and \`RootCauseReport\`. Reject unknown domains, invalid units, negative occupancy, missing timestamps, duplicate IDs, and out-of-order events.

Run:

\`\`\`bash
pytest -q
\`\`\`

## 7. Phase 2 — generate reproducible five-domain data

Generate synchronized 1 Hz data for 30 days, 10 buildings, and 5 zones. Required fields:

\`\`\`text
timestamp, building_id, zone_id,
energy_kw, indoor_pm25, indoor_co2, indoor_temp_c, indoor_humidity,
water_lpm, water_pressure_kpa, outdoor_temp_c, outdoor_humidity,
wind_mps, occupancy_count, hvac_state, ventilation_state,
scenario_id, fault_domain, fault_start, fault_end
\`\`\`

Inject HVAC-stuck-high, poor-ventilation, water-leak, weather-driven-load, occupancy-drift, and compound HVAC/air-quality/occupancy scenarios. Split by building: 60% train, 20% validation, 20% test. Save seed and split IDs.

Run:

\`\`\`bash
python -m src.simulate --days 30 --buildings 10 --zones 5 --seed 20260820 --out data/processed/synthetic.parquet
\`\`\`

Do not expose \`scenario_id\` or \`fault_domain\` to any model.

## 8. Phase 3 — build the always-on edge trigger

Implement in order:

1. \`SensorIngestor\`: replay now; MQTT/serial later.
2. \`RingBuffer\`: bounded 60-minute state per building/zone.
3. \`FeatureExtractor\`: fixed feature order and train-only normalization.
4. \`RuleEngine\`: thresholds, hysteresis, minimum duration.
5. \`AnomalyDetector\`: autoencoder score and threshold.
6. \`TriggerEngine\`: deduplicated \`AnomalyEvent\` only after a persistent trigger.

For each 60-minute window compute mean, slope, min, max, standard deviation, last value, occupancy-normalized energy, and cross-domain ratios.

Run:

\`\`\`bash
python -m src.rules_baseline --data data/processed/synthetic.parquet --out reports/rules.jsonl
python -m src.anomaly_train --data data/processed/synthetic.parquet --out models/anomaly --seed 20260820
python -m src.anomaly_infer --model models/anomaly/model.onnx --data data/processed/synthetic.parquet --out reports/anomaly_events.jsonl
\`\`\`

Save model, normalization, feature order, threshold, training split, reconstruction loss, anomaly recall, false-positive rate, and trigger rate. Do not proceed to the device until this report exists.

## 9. Phase 4 — define safe reasoning I/O

Send compact JSON only: event ID, domain summaries, bounded history, and allowed actions. Never send full history or raw camera frames to the SLM.

Require:

\`\`\`json
{
  "root_cause": "string",
  "evidence": ["feature or event IDs"],
  "confidence": 0.0,
  "recommendation": "string",
  "requires_human_approval": true,
  "uncertainties": ["string"]
}
\`\`\`

Reject invalid JSON, missing evidence, unsupported actions, or confidence outside \`[0,1]\`. Log rejected outputs.

## 10. Phase 5 — implement the three comparison systems

### Rule baseline

Thresholds only; emit evidence values and rule IDs; no LLM calls.

### Single-SLM baseline

One Llama 3.2 3B call receives all compact domain summaries. Fix system prompt, decoding settings, input schema, output schema, and allowed actions.

### Multi-agent SLM

Five sequential role calls use the same Llama bundle:

- Energy: load, occupancy-normalized load, HVAC relationship.
- Air quality: CO2, PM2.5, ventilation, indoor/outdoor context.
- Water: flow, pressure, leak persistence.
- Weather: temperature, humidity, wind, expected load effect.
- Occupancy: count, trend, consistency with CO2/energy.

Each returns \`DomainAnalysis\`. The orchestrator receives only the five analyses plus shared evidence and returns \`RootCauseReport\`.

Use identical events, test buildings, output schema, and action list. Log model calls, tokens, latency, memory, and failures.

## 11. Phase 6 — export and smoke-test Llama on SM8650/V75

Request Qualcomm AI Hub/QPM and Hugging Face access. Follow the QIDK AI Assistant/ASR-LLM-TTS export workflow and export \`llama_v3_2_3b_instruct\` for Snapdragon 8 Gen3 / SM8650. Use reduced context length suitable for compact JSON.

Store the bundle at:

\`\`\`text
models/genie_bundle/sm8650-v75/
\`\`\`

It must contain model config, tokenizer, context binaries, backend config, and \`qairt_version.txt\`. The bundle’s QAIRT version is authoritative; use the Docker QAIRT version only when it matches.

Inside the QIDK container:

\`\`\`bash
export QAIRT_SDK_ROOT=/path/to/matching/qairt
export BUNDLE=/local/smart-city-edge-agent/models/genie_bundle/sm8650-v75
cp "$QAIRT_SDK_ROOT/lib/aarch64-android/"* "$BUNDLE/"
cp "$QAIRT_SDK_ROOT/lib/hexagon-v75/unsigned/"* "$BUNDLE/"
cp "$QAIRT_SDK_ROOT/bin/aarch64-android/genie-t2t-run" "$BUNDLE/"
\`\`\`

Update the Genie config so tokenizer, context binaries, and backend paths point to \`/data/local/tmp/smart_city_edge/genie_bundle/\`.

In Windows PowerShell:

\`\`\`powershell
$adb = 'C:\Android\platform-tools\platform-tools\adb.exe'
$bundle = 'C:\Users\hp\Desktop\qidk\smart-city-edge-agent\models\genie_bundle\sm8650-v75'
& $adb shell "mkdir -p /data/local/tmp/smart_city_edge/genie_bundle"
Get-ChildItem $bundle -File | ForEach-Object { & $adb push $_.FullName /data/local/tmp/smart_city_edge/genie_bundle/ }
& $adb shell "cd /data/local/tmp/smart_city_edge/genie_bundle && export LD_LIBRARY_PATH=. && export ADSP_LIBRARY_PATH=. && ./genie-t2t-run -c llama_v3_2_3b_chat_quantized.json -p 'Return valid JSON for energy rising to 18.4kW, CO2 1420ppm, ventilation off, occupancy 18.'"
\`\`\`

Use the exact config filename generated by export. Save stdout, stderr, exit code, and latency.

If HTP fails:

\`\`\`powershell
& $adb logcat -d -t 400 | Select-String -Pattern 'FastRPC|DSP|HTP|QNN|Genie|error|Error'
\`\`\`

The QIDK quick-start documents \`adb disable-verity\`, reboot, \`adb root\`, \`adb remount\`, and \`adb shell setenforce 0\` for development devices when HTP needs permissive SELinux. These are state-changing operations. Use only after logs show CPU fallback is caused by HTP/SELinux, and record the pre-change state.

## 12. Phase 7 — generate and prepare QIDK Android assets

For optional YoloNAS/HRNet/camera work, inside Docker:

\`\`\`bash
cd Solutions/<SolutionName>/Generate_models
jupyter notebook --ip=0.0.0.0 --no-browser --allow-root
\`\`\`

Open the printed Jupyter URL, set dataset paths, run all cells, and confirm \`.dlc\` files appear in \`app/src/main/assets/\`.

For any QIDK Android solution:

\`\`\`bash
export QAIRT_SDK_ROOT=/path/to/matching/qairt
cd Solutions/<SolutionName>
bash resolveDependencies.sh
\`\`\`

Confirm QAIRT headers, OpenCV, and required \`.so\` files exist under \`jniLibs/arm64-v8a/\`, and model assets exist under \`app/src/main/assets/\`.

The sensor-only prototype does not need camera model generation.

## 13. Phase 8 — build and deploy Android prototype

Create \`android/SmartCityEdge\` as a new app, using QIDK AI Assistant only as the Genie integration reference. Implement:

1. \`ReplaySource\`: timestamped JSONL replay.
2. \`RingBuffer\`: bounded 60-minute state.
3. \`FeatureExtractor\`: identical host feature order.
4. \`TriggerEngine\`: rules and autoencoder.
5. \`ReasoningEngine\`: rules, single-SLM, or multi-agent mode.
6. \`PolicyGate\`: schema validation and human approval.
7. \`EventView\`: event, evidence, explanation, confidence, mode, latency.
8. \`TraceWriter\`: JSONL metrics.

Build in Android Studio: File → Open → \`android/SmartCityEdge\`; wait for Gradle sync; Build → Make Project; confirm \`app/build/outputs/apk/debug/app-debug.apk\`.

Install:

\`\`\`powershell
$adb = 'C:\Android\platform-tools\platform-tools\adb.exe'
& $adb devices -l
& $adb install -r -t 'C:\path\to\app-debug.apk'
\`\`\`

Run synthetic replay first. Select CPU, then GPU, then HTP/V75 if runtime selection exists.

## 14. Phase 9 — evaluate on QIDK

Run all three modes against the same held-out buildings and scenarios. Measure:

- Root-cause accuracy and macro-F1.
- Evidence precision and unsupported-evidence rate.
- Recommendation validity.
- End-to-end latency and time-to-first-token.
- LLM calls and token counts.
- Peak memory.
- Model/package size.
- Power and temperature.
- NPU/HTP utilization.
- Network bytes; target zero in the critical path.

Use:

\`\`\`powershell
& $adb shell dumpsys meminfo <package.name>
& $adb shell dumpsys batterystats --reset
& $adb shell dumpsys thermalservice
& $adb shell dumpsys batterystats <package.name>
\`\`\`

Record serial, SoC, Android build, QAIRT/model versions, model hashes, seed, thermal state, and git commit with every benchmark.

## 15. Phase 10 — optional extensions

Only after the sensor-reasoning benchmark passes:

- Add YoloNAS camera occupancy/vehicle events.
- Add HRNet pose/fall cues.
- Add Whisper Small push-to-talk.
- Add Melo TTS short responses.
- Add local historical storage and dashboard.
- Investigate digital twin, edge mesh, and sensor-drift recalibration.

## 16. Definition of done

- Official QIDK Docker environment starts and reports QAIRT/NDK versions.
- Data generation and labels are reproducible.
- Rule, single-SLM, and multi-agent modes consume identical events.
- Autoencoder triggers bounded reasoning.
- Llama 3.2 3B runs locally on SM8650/V75 with matching QAIRT.
- At least one compound event is diagnosed with cited evidence.
- Outputs are schema-valid and policy-gated.
- Android replay prototype runs on QIDK.
- Latency, memory, power, temperature, NPU, and network measurements are captured.
- The process can be repeated from this document.

## 17. First-milestone non-goals

- Fine-tuning Llama 3.2 3B.
- Five simultaneously loaded LLM copies.
- Cloud inference in the critical path.
- Autonomous physical actuation.
- Production dashboard, digital twin, edge mesh, or long-term database.
- Real-world accuracy claims based only on synthetic data.

