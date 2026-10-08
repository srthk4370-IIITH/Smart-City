# Agentic Edge AI for Smart Cities

### Team Details
- Team Number: esw-m26-14
- Team Name: NASA
- Course/Module: ESW-M26

---

# Repository Instructions

This repository contains the codebase, resources, and demonstration materials for our Agentic Edge AI for Smart Cities project.

## 1. Repository Structure

- `Code/` - Contains all project source code, scripts, configs, and the core Edge Agent implementation.
- `Resources/` - Contains supporting material such as references, documents, and resource documentation.
- `Demos/` - Contains demonstration videos, images, screenshots, or a README file with public links to the media.
- `Presentation/` - Contains the final presentation in PDF format used for evaluation.

## 2. Project Overview

**Smart City Edge** is a native Android app for the Qualcomm QIDK (Snapdragon 8 Gen 3). It monitors a smart campus
across Air Quality, Water, Power, Occupancy and Weather, and reasons about incidents with a fine-tuned
**Llama 3.2 3B (w4a16) on the Hexagon NPU**. Everything runs on the board; no cloud and no laptop are needed after setup.

- **Input:** live sensors. In the demo, sliders in the app act as the sensors; real devices post to `/api/ingest`.
- **Pipeline:**
  1. 4-hour statistics per sensor.
  2. Rule baseline.
  3. Event gate: only warning/critical/fault readings call the AI, and everything alarming at once becomes one incident.
  4. Domain agents on the NPU.
  5. Cross-domain synthesizer.
  6. Policy gate.
  7. Human approval.
- **Results on the device:**
  - 85.2 % pattern accuracy (bf16 ceiling 91.3 %); 100 % valid JSON, evidence and policy.
  - About 5 s per agent call.
  - 0 AI calls at rest.
- **Robustness:**
  - The app starts on boot and restarts its backend.
  - It restores deleted model files from an on-device backup.
  - Uninstalling is blocked (device admin).
  - It retries transient NPU errors.

## 3. Documentation & Execution

- `run.md`: setup, build, install, training/export and troubleshooting (start here).
- `teach.md`: how the whole flow works, file by file.
- `HANDBOOK.md`: results, measurements and engineering decisions.
- `ppt.md`: project status, problems faced, trade-offs and future plans.
- `Code/smart-city-edge-agent/app/README.md`: the on-device app.
- `Code/smart-city-edge-agent/training/TRAINING.md`: fine-tuning runbook.

One-command install (QIDK on USB):

```powershell
powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\app\android\install_app.ps1 -Build -ClearHistory
```

## 4. Reproducibility

- Go 1.22+, Android SDK (build-tools, platform 34) and JDK 17 in WSL2 to build the app.
- Python 3.11 and an NVIDIA GPU (6 GB or more) for QLoRA training; qai-hub-models 0.63 for the NPU export.
- Qualcomm QAIRT 2.50 Genie runtime on the device.
- Model weights, the QAIRT runtime and datasets are **not in git** (size and licence). `run.md` §3 explains how
  to obtain or rebuild each one.

## 5. AI Usage and Transparency

- Generative AI (Claude) was used to help write code, scripts and documentation.
- Llama 3.2 3B Instruct (Meta) is the on-device model. We fine-tuned it with QLoRA on our own windows built from the
  SCRC IIIT-H sensor data, then quantised it to w4a16 for the NPU.
