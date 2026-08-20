# Environment and QIDK Capability Report

**Date:** 2026-08-20  
**Workspace:** `C:\Users\hp\Desktop\qidk`  
**QIDK checkout:** `C:\Users\hp\Desktop\qidk\qidk`  
**QIDK commit inspected:** `175e8d4` (`master`)

## What the deck requires

The existing deck describes a working, edge-native, event-driven multi-agent system for smart-building/city signals across five domains:

- Energy
- Air quality
- Water
- Weather
- Occupancy

The system must compare three configurations under identical inputs: rule-based thresholds, one SLM seeing all domains, and a multi-agent SLM with domain agents plus a cross-domain orchestrator. The committed scope is phases 1–3: core pipeline, domain agents, and cross-domain reasoning. UI, long-term storage, digital twin, edge mesh, and drift recalibration are extensions.

## QIDK repository contents

The repository contains `Examples/`, `GenAI-Solutions/`, `Model-Enablement/`, `QHCI/`, `Solutions/`, `Tools/`, `docs/`, and `images/`.

QIDK does **not** contain the smart-city sensor dataset, sensor-ingestion service, anomaly benchmark, or multi-agent orchestrator required by the deck. Those must be implemented in this project.

## QIDK software stack verified from the repository

- Qualcomm AI Runtime (QAIRT), including QNN / AI Engine Direct and SNPE.
- Repository baseline QAIRT download: `2.47.0.260601`.
- AIMET and AIMET Model Zoo for quantization and model efficiency.
- Android Studio Panda 4 `2025.3.4` for current mainline solutions.
- Android target ABI: `arm64-v8a`.
- C++/JNI native integration, CMake, and OpenCV in the vision solutions.
- Genie C++ APIs for on-device LLM execution.
- QAIRT Docker and notebooks for model conversion.

## Models demonstrated by QIDK and their role here

| Model / component | QIDK evidence | Role in this project |
|---|---|---|
| Llama 3.2 3B Instruct | `GenAI-Solutions/ASR-LLM-TTS/readme_assets/llm_Readme.md`, AI Assistant README | Primary on-device SLM; instantiate as single-SLM baseline and prompt-specialized domain/orchestrator agents |
| YoloNAS-S | `Solutions/QNN/VisionSolution1-ObjectDetection-YoloNas` | Optional physical occupancy/vehicle perception input; not required for the first sensor-only milestone |
| HRNet + YoloNAS | `Solutions/VisionSolution4-PoseEstimation` | Optional occupancy/posture extension |
| Whisper Small | `Solutions/NLPSolution3-AutomaticSpeechRecognition-Whisper` and ASR-LLM-TTS | Optional voice query input |
| Melo TTS | ASR-LLM-TTS TTS README | Optional spoken response |

QIDK does not provide a domain-specific smart-building SLM. Do not claim that one exists. Domain agents should initially be role-specialized prompts over the same exported Llama 3.2 3B model; train the non-LLM anomaly model and evaluate whether prompt specialization is sufficient.

## Connected device — verified 2026-08-20

ADB was run from `C:\Android\platform-tools\platform-tools\adb.exe`.

- Serial: `3ce9a4e2`
- Model: `Pineapple for arm64`
- SoC: `SM8650` / Snapdragon 8 Gen3
- Android: 14
- ABI: `arm64-v8a`
- HTP target: **V75**
- SELinux: enforcing
- `/data`: 19 GB free of 45 GB
- `/data/local/tmp`: approximately 5.1 GB used
- Root filesystem: full; do not write there
- Thermal status: nominal at inspection time

Existing device artifacts include a 2.9 GB Gemma 3N task file, YoloV8n and HRNet ONNX files, SNPE benchmark/run directories, and installed QIDK demo packages. Inventory them before cleanup.

### Install and expose ADB on Windows

1. Download **Android SDK Platform-Tools for Windows** from the official Android developer site.
2. Extract it to `C:\Android\platform-tools`.
3. Open a new PowerShell window and run:

```powershell
$env:Path = 'C:\Android\platform-tools;' + $env:Path
adb version
adb start-server
adb devices -l
```

4. Unlock the QIDK device, enable USB debugging, accept the RSA prompt, and rerun `adb devices -l` until the state is `device`, not `unauthorized`.
5. Record the output of:

```powershell
adb shell getprop ro.product.model
adb shell getprop ro.soc.model
adb shell getprop ro.build.version.release
adb shell getprop ro.build.fingerprint
adb shell getprop ro.boot.hardware
adb shell df -h
adb shell getenforce
adb shell dumpsys thermalservice
```

6. Map the SoC to the HTP target: SM8550→V73, SM8650→V75, SM8750→V79, SM8850→V81.

Do not run `adb disable-verity`, `adb root`, `adb remount`, or `setenforce 0` until a DSP-loading error is observed and the development device can be restored.

## Host dependencies to install

Install these before implementation:

1. Git.
2. Android Studio Panda 4 `2025.3.4`, Android SDK, NDK, CMake, and platform tools.
3. Python 3.10 or 3.11 with a project virtual environment.
4. Docker Desktop if using `qidk/Tools/qairt_docker`.
5. Qualcomm AI Runtime SDK from QPM or the repository README’s QAIRT link. Store it outside the repo and set `QAIRT_SDK_ROOT` to its extracted directory.
6. Access to Qualcomm AI Hub/QPM for Llama export. The repository notes that LLM export can require 40–80 GB temporary storage.

Recommended Python setup:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install numpy pandas scipy scikit-learn pydantic fastapi uvicorn orjson pyarrow matplotlib seaborn pytest torch onnx onnxruntime
```

Pin the resolved versions in `requirements-lock.txt` after the first successful install. Do not install random QAIRT versions; use the version compatible with the exported model bundle.

## Cleanup status

No files were removed. The QIDK checkout is source code and must retain `.git`, docs, notebooks, model scripts, Android projects, demos, SDK references, and assets. Cleanup may remove only confirmed caches or reproducible outputs after a manifest is created.
