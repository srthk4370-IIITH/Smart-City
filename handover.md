# Handover — Executable Smart-City Edge-AI Prototype

## Goal

Build the system described in `Agentic Edge AI for Smart Cities.pptx`, not another presentation. The prototype is an event-driven multi-domain reasoning system for Energy, Air Quality, Water, Weather, and Occupancy running locally on Qualcomm QIDK.

## Required comparison

Run the same labeled sensor events through:

1. Rule-based thresholds.
2. One Llama 3.2 3B SLM seeing all compact domain summaries.
3. Five prompt-specialized domain roles plus one Llama orchestrator call.

The research question is whether cross-domain multi-agent reasoning improves root-cause accuracy under edge resource constraints.

## What QIDK supplies

- QAIRT, QNN / AI Engine Direct, SNPE, Genie, AIMET, Android/CMake/OpenCV examples.
- Llama 3.2 3B deployment examples in `qidk/GenAI-Solutions/AI-Assistant` and `ASR-LLM-TTS`.
- Optional YoloNAS, HRNet, Whisper Small, and Melo TTS.

## What we must build

- Five-domain sensor schema and replay generator.
- Synthetic labeled dataset, followed by a small real pilot if available.
- Sliding windows, compact summaries, ring-buffer state, and event trigger.
- Rule baseline.
- Trainable small denoising autoencoder anomaly detector.
- Single-SLM and multi-agent SLM pipelines.
- Evidence-constrained JSON output and policy gate.
- Android/QIDK event replay app and benchmark harness.

## Device status

ADB is available at `C:\Android\platform-tools\platform-tools\adb.exe`. The connected device is serial `3ce9a4e2`, model `Pineapple for arm64`, SoC `SM8650` / Snapdragon 8 Gen3, Android 14, ABI `arm64-v8a`, HTP target `V75`, with SELinux enforcing.

Use:

```powershell
$adb = 'C:\Android\platform-tools\platform-tools\adb.exe'
& $adb devices -l
& $adb shell getprop ro.soc.model
& $adb shell getprop ro.build.version.release
& $adb shell getenforce
```

The device has only about 19 GB free in `/data`, `/data/local/tmp` already uses about 5.1 GB, and the root filesystem is full. Use a dedicated working directory and do not delete existing artifacts until they are inventoried.

## Version constraint

QIDK’s repository README references QAIRT `2.47.0.260601`, but the GenAI examples document solution-specific versions `2.40`, `2.43`, and `2.45`. The exported Llama bundle’s `qairt_version.txt` is authoritative. Never mix model-export and runtime versions casually.

## First working session

From `C:\Users\hp\Desktop\qidk`:

```powershell
New-Item -ItemType Directory -Force smart-city-edge-agent | Out-Null
Set-Location smart-city-edge-agent
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install numpy pandas scipy scikit-learn pydantic fastapi uvicorn orjson pyarrow matplotlib seaborn pytest torch onnx onnxruntime
```

Then implement the schema and simulator before requesting AI Hub exports. This proves the data contract and evaluation setup without consuming the device or LLM export quota.

## Important implementation decision

Do not train/fine-tune the Llama model initially. Use the QIDK-supported exported Llama 3.2 3B as a fixed SLM and train only the small anomaly detector. Domain agents are roles/prompts over one shared model so the comparison remains feasible on bounded hardware.

## Cleanup

No files have been deleted. Preserve the QIDK repo and all source assets. Remove only confirmed caches or reproducible generated outputs after making a manifest.

## Source documents

- `environment.md` — verified QIDK facts, missing device facts, installs, and exact ADB steps.
- `plan.md` — complete implementation plan, schemas, model choices, commands, Android port, and evaluation.
- `Agentic Edge AI for Smart Cities.pptx` — requirements source.
