# Smart City Edge AI — Run Guide (Other Computer)

> **This guide assumes you are running on a NEW computer that has never had this project before.**
> The model is NOT in this repo (it's 2.8 GB). You will need the QIDK device with the model already on it, OR follow the "First-time device setup" section below.

---

## Prerequisites

### Hardware Required
- **Qualcomm QIDK** development board (Snapdragon 8 Gen 3 / SM8650) — with model already deployed
- **USB cable** to connect QIDK to laptop
- Laptop running **Windows 10/11** (with WSL2 recommended) or Linux

### Software Required
| Tool | Install |
|---|---|
| Python 3.11+ | https://www.python.org/downloads/ |
| Git | https://git-scm.com/ |
| WSL2 (Windows) | `wsl --install` in PowerShell (admin) |
| ADB (Android Debug Bridge) | Bundled in `platform-tools/` — no extra install |

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/srthk4370-IIITH/Smart-City.git
cd Smart-City
```

---

## Step 2 — Set Up Python Environment

> Run these commands in **WSL** (on Windows) or any bash terminal (on Linux).

```bash
cd smart-city-edge-agent

# Create virtual environment
python3.11 -m venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

**On Windows without WSL:**
```powershell
cd smart-city-edge-agent
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

---

## Step 3 — Connect QIDK and Verify

Plug in the QIDK via USB. Then verify ADB sees it:

**Windows (PowerShell):**
```powershell
.\platform-tools\adb.exe devices
```

**WSL / Linux:**
```bash
/mnt/c/Users/<YourName>/Desktop/qidk/platform-tools/adb.exe devices
# OR if adb is in PATH:
adb devices
```

Expected output:
```
List of devices attached
3ce9a4e2    device
```

> If it shows `unauthorized`: unlock the phone → tap **"Always allow from this computer"** on the device screen.

---

## Step 4 — Verify the Model is on the Device

```bash
# Check that model files are present (they should be, if the device was handed to you pre-loaded)
adb shell "ls -lh /data/local/tmp/genie_bundle/*.bin"
```

Expected:
```
-rw-rw-rw- 1 root root  752M  llama_v3_2_3b_instruct_part_1_of_3.bin
-rw-rw-rw- 1 root root  860M  llama_v3_2_3b_instruct_part_2_of_3.bin
-rw-rw-rw- 1 root root  1.2G  llama_v3_2_3b_instruct_part_3_of_3.bin
```

**If the model is NOT on the device** → see [First-Time Device Setup](#first-time-device-setup-model-not-on-device) below.

---

## Step 5 — Start the Web Server

```bash
# In WSL or any bash terminal
cd /mnt/c/path/to/Smart-City/smart-city-edge-agent   # adjust path
source .venv/bin/activate
uvicorn src.smart_city_edge.webapp.app:app --host 0.0.0.0 --port 8000
```

You should see:
```
INFO:  Application startup complete.
INFO:  Uvicorn running on http://0.0.0.0:8000
[GenieRunner] QIDK connected. Ready for inference. (1 NPU call per request)
```

---

## Step 6 — Open the Dashboard

Open your browser and go to: **http://localhost:8000**

The header badge will turn **green (⚡ NPU Active — 1-Call Mode)** once the device is detected.

### Running a Demo
1. Pick a preset: **"🌐 Full Multi-Domain Crisis"** or **"⚡ Energy Surge"**
2. Click **"Evaluate Sensors"**
3. Wait ~7 seconds for on-device NPU inference
4. View the Root Cause Report, Domain Agent outputs, and Execution Trace

---

## Troubleshooting

**Port 8000 already in use:**
```bash
# WSL / Linux
fuser -k 8000/tcp
# Then re-run uvicorn
```

**ADB not found:**
- Use the bundled ADB: `platform-tools/adb.exe` (Windows) or install via `sudo apt install adb` (Linux)
- If on Linux, copy `platform-tools/adb.exe` from a Windows machine, or download Android platform-tools for Linux from https://developer.android.com/tools/releases/platform-tools

**"Failed to create device: 14001" in logs:**
- The QIDK device was rebooted and `/data/local/tmp/` was wiped. Re-deploy the model (see below).

**Inference timeout / no output:**
- Check device is not thermally throttled: `adb shell dumpsys thermalservice | grep -i temperature`
- Try a direct genie test (see First-Time Device Setup section)

---

## First-Time Device Setup (Model NOT on Device)

> Only needed if the QIDK is freshly reset or you're setting up a new device.

### 1. Download the Genie Bundle

```bash
# From the project root, in WSL with venv active
cd smart-city-edge-agent
python scripts/download_genie_bundle.py
```

This downloads the Llama 3.2 3B Instruct Genie bundle for SM8650 from Qualcomm AI Hub.
You will need a **Qualcomm AI Hub account** (free): https://aihub.qualcomm.com

### 2. Push the Bundle to Device

The model files go to `/data/local/tmp/genie_bundle/` on the device. Use the deploy script:

```powershell
# Windows PowerShell — from the smart-city-edge-agent directory
.\scripts\deploy_bundle.ps1
```

Or manually via ADB:
```bash
BUNDLE=./models/genie_bundle/sm8650-v75   # adjust to your actual path

adb shell "mkdir -p /data/local/tmp/genie_bundle"
adb push $BUNDLE/genie-t2t-run-2.50         /data/local/tmp/genie_bundle/
adb push $BUNDLE/llama_v3_2_3b_instruct_part_1_of_3.bin /data/local/tmp/genie_bundle/
adb push $BUNDLE/llama_v3_2_3b_instruct_part_2_of_3.bin /data/local/tmp/genie_bundle/
adb push $BUNDLE/llama_v3_2_3b_instruct_part_3_of_3.bin /data/local/tmp/genie_bundle/
adb push $BUNDLE/tokenizer.json             /data/local/tmp/genie_bundle/
adb push configs/llama3.2-3b-sm8650-genie.json /data/local/tmp/genie_bundle/
adb push $BUNDLE/qairt_2_50_libs/           /data/local/tmp/genie_bundle/qairt_2_50_libs/
adb push $BUNDLE/aarch64-android/          /data/local/tmp/genie_bundle/aarch64-android/
adb push $BUNDLE/dsp_2_50/                 /data/local/tmp/genie_bundle/dsp_2_50/
adb push $BUNDLE/htp_backend_ext_config.json /data/local/tmp/genie_bundle/

# Make binary executable
adb shell "chmod +x /data/local/tmp/genie_bundle/genie-t2t-run-2.50"
```

### 3. Verify Direct Inference Works

```bash
adb shell "cd /data/local/tmp/genie_bundle && \
  LD_LIBRARY_PATH=./qairt_2_50_libs:./aarch64-android \
  ADSP_LIBRARY_PATH='./dsp_2_50;./dsp;/vendor/dsp/cdsp;/dsp' \
  ./genie-t2t-run-2.50 -c llama3.2-3b-sm8650-genie.json -p 'Hello'"
```

You should see `[BEGIN]: ...response...[END]` within ~7 seconds.

---

## Project Structure (Quick Reference)

```
Smart-City/
├── platform-tools/          ← ADB binary for Windows (bundled)
├── PRD.md                   ← Full Product Requirements Document
├── deploy.md                ← Demo runbook (for the pre-loaded device)
├── ppt.md                   ← Presentation guide
├── run.md                   ← This file
└── smart-city-edge-agent/
    ├── src/smart_city_edge/ ← Core Python source code
    │   ├── genie_runner.py  ← ADB↔QIDK NPU inference engine
    │   ├── rules.py         ← Rule-based anomaly detection
    │   ├── prompts.py       ← Prompt templates
    │   ├── policy.py        ← Safety policy gate
    │   └── webapp/          ← FastAPI server + web dashboard
    ├── configs/             ← Genie config, thresholds, prompts
    ├── scripts/             ← Setup, training, and utility scripts
    ├── pyproject.toml       ← Python package definition
    └── requirements-*.txt   ← Dependency lists
```

---

## Hardware & Software Versions (Tested)

| Component | Version |
|---|---|
| QIDK SoC | Snapdragon 8 Gen 3 (SM8650) |
| Genie Runtime | `genie-t2t-run-2.50` / libGenie.so 1.20.0 |
| QAIRT | 2.50 |
| Model | Llama 3.2 3B Instruct (4-bit quantized, HTP V75) |
| Python | 3.11.9 |
| FastAPI / Uvicorn | latest (see pyproject.toml) |
| Host OS | Windows 11 + WSL2 Ubuntu 22.04 |
| ADB | 35.0.2-11882874 |
