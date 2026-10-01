# Smart City Edge AI — Comprehensive Run Guide

This guide provides end-to-end instructions for cloning the repository, setting up the environment, downloading the Llama 3.2 3B Instruct model, optionally training domain agents, and deploying everything to the Qualcomm QIDK edge device.

---

## 1. Prerequisites

### Hardware Required
- **Qualcomm QIDK** development board (Snapdragon 8 Gen 3 / SM8650)
- **USB cable** to connect QIDK to laptop
- Laptop running **Windows 10/11** (with WSL2 recommended) or Linux

### Software Required
- Python 3.11+
- Git
- WSL2 (if on Windows)
- Qualcomm AI Hub Account (free) for model downloads

---

## 2. Clone the Repository

Clone the project from GitHub and navigate into the `Code/` folder where the agent lives.

```bash
git clone https://github.com/ESW-M26/esw-m26-14_nasa.git
cd esw-m26-14_nasa/Code/smart-city-edge-agent
```

---

## 3. Set Up Python Environment

Run these commands in **WSL** (on Windows) or any bash terminal.

```bash
# Create virtual environment
python3.11 -m venv .venv

# Activate it
source .venv/bin/activate

# Install all dependencies (including training tools)
pip install -e ".[dev]"
```

**On Windows without WSL:**
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

---

## 4. Download and Compile the Edge Model (Llama 3.2 3B)

The orchestration AI relies on a quantized version of Llama 3.2 3B. We download it via the Qualcomm AI Hub.

```bash
# Ensure your virtual environment is active
# Downloads the Genie bundle from AI Hub
python scripts/download_genie_bundle.py
```
*Note: This requires you to log in to Qualcomm AI Hub via the terminal prompt if not already authenticated.*

The bundle will be saved to `models/genie_bundle/sm8650-v75/`.

---

## 5. (Optional) Training Domain Agents

If you want to fine-tune the lightweight domain agents (e.g., Energy, Water, Occupancy) on your own anomaly data before deployment:

```bash
# Train the anomaly detection models (creates .onnx and .joblib files)
python scripts/train_anomaly.py --domain energy
python scripts/train_anomaly.py --domain water
```
The trained lightweight agents will automatically be saved to `models/bootstrap/` and picked up by the pipeline.

---

## 6. Connect and Verify the QIDK Device

Plug in the QIDK via USB. Make sure your laptop recognizes it using the bundled ADB tool:

**Windows (PowerShell, from the root of the repo):**
```powershell
.\Code\platform-tools\adb.exe devices
```

**WSL / Linux:**
```bash
../platform-tools/adb devices
```

Expected output:
```
List of devices attached
3ce9a4e2    device
```
> If it shows `unauthorized`: unlock the QIDK screen and tap **"Always allow from this computer"**.

---

## 7. Deploy the Model to the QIDK

Push the Llama 3.2 3B Genie bundle to the device's NPU memory (`/data/local/tmp/genie_bundle/`).

**Using PowerShell (Windows):**
```powershell
# From the Code/smart-city-edge-agent directory
.\scripts\deploy_bundle.ps1
```

**Manual ADB Push (Linux/WSL):**
```bash
BUNDLE=./models/genie_bundle/sm8650-v75

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

# Make the NPU inference binary executable
adb shell "chmod +x /data/local/tmp/genie_bundle/genie-t2t-run-2.50"
```

---

## 8. Run the Web Dashboard and Inference Pipeline

Once the model is deployed on the device, you can launch the control dashboard.

```bash
# In WSL/Linux (inside Code/smart-city-edge-agent)
uvicorn src.smart_city_edge.webapp.app:app --host 0.0.0.0 --port 8000
```

1. Open your browser and go to: **http://localhost:8000**
2. The header badge will turn **green (⚡ NPU Active — 1-Call Mode)** once the web app confirms the QIDK is connected over ADB.
3. Select a preset (e.g., **"🌐 Full Multi-Domain Crisis"**) and click **"Evaluate Sensors"**.
4. The dashboard will trigger the Python anomaly rules locally, then compile the context, and send a single inference request to the QIDK's NPU.
5. In ~7 seconds, you will receive the full Root Cause Report and AI-orchestrated plan directly from the Edge!

---

## 9. Troubleshooting

**Port 8000 already in use:**
```bash
fuser -k 8000/tcp
```

**"Failed to create device: 14001" / Model missing:**
If the device was restarted, the `/data/local/tmp/` directory is cleared automatically by Android. You must re-run **Step 7 (Deploy)** to push the model back to the QIDK.
