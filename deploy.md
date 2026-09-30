# Smart City Edge AI — Demo Runbook

> Everything is already deployed. The Llama 3.2 3B model, Genie runtime, and all
> libraries live on the QIDK device at `/data/local/tmp/genie_bundle/` and persist
> across USB disconnect. You do not need to re-push anything.

---

## When You Come Back to Demo This

### Step 1 — Connect the QIDK

Plug the QIDK into your laptop via USB. Confirm it shows up:

```powershell
# In PowerShell (or use the bundled ADB)
C:\Users\hp\Desktop\qidk\platform-tools\adb.exe devices
```

You should see something like:
```
List of devices attached
3ce9a4e2    device
```

If it shows `unauthorized`, unlock the phone and tap **"Always allow from this computer"** on the device screen.

---

### Step 2 — Start the Web Server

Open **WSL** (Windows Subsystem for Linux) and run:

```bash
cd /mnt/c/Users/hp/Desktop/qidk/smart-city-edge-agent
source .venv/bin/activate
uvicorn src.smart_city_edge.webapp.app:app --host 0.0.0.0 --port 8000
```

You'll see:
```
INFO:  Application startup complete.
INFO:  Uvicorn running on http://0.0.0.0:8000
[GenieRunner] QIDK connected. Ready for inference. (1 NPU call per request)
```

Leave this terminal open.

---

### Step 3 — Open the Dashboard

Go to: **http://localhost:8000**

The header badge will turn **green** (⚡ NPU Active — 1-Call Mode) once the server confirms the device is connected. This takes about 2–3 seconds after the page loads.

---

## Running the Demo

1. Pick any preset from the top bar — e.g. **"⚡ Energy Surge"** or **"🌐 Multi-Domain Crisis"**
2. Click **"Evaluate Sensors"**
3. Watch the results populate:
   - **Anomaly score** and status badge
   - **Orchestrator plan** showing which domains were flagged
   - **Domain agent outputs** (Air Quality, Energy, Water, etc.)
   - **Root Cause Report** with recommendations
   - **Execution Trace** at the bottom showing per-step timing

**Expected latency:** ~7 seconds per query (1 NPU inference on the Qualcomm HTP V75).

---

## What Is Running Under the Hood

| Component | Where | Notes |
|---|---|---|
| Llama 3.2 3B Instruct | QIDK device — `/data/local/tmp/genie_bundle/` | Quantized `.bin` files, already on device |
| Genie Runtime (`genie-t2t-run-2.50`) | QIDK device | Qualcomm's NPU inference binary |
| FastAPI Web Server | Your laptop (WSL) | Routes sensor data → ADB → QIDK |
| Rule Engine + Domain Analysis | Your laptop (Python) | Pure Python, runs in <5ms |
| NPU Synthesis (cross-domain root cause) | QIDK HTP V75 | The single LLM call per query |

The pipeline: **Browser → FastAPI → Rule Engine (Python) → Single Genie call over ADB → QIDK NPU → Response**

---

## Troubleshooting

**"adb devices" shows nothing / offline**
- Unplug and replug the USB cable
- Run `adb kill-server && adb start-server` then `adb devices` again
- Make sure USB debugging is enabled in Developer Options on the device

**Port 8000 already in use**
```bash
# In WSL
fuser -k 8000/tcp
# Then re-run uvicorn
```

**Inference returns no output / timeout**
- The model files are still on the device — check with:
  ```powershell
  C:\Users\hp\Desktop\qidk\platform-tools\adb.exe shell "ls -lh /data/local/tmp/genie_bundle/*.bin"
  ```
- If the device was **rebooted** (not just disconnected), `/data/local/tmp/` may have been cleared. In that case, re-push the bundle — see the original setup notes.

**"ANOMALY NOT DETECTED" on anomaly scenarios**
- Slider values may have been reset to defaults. Use the preset buttons to load correct values, then click Evaluate.

---

## What Is Already on the Device (No Re-push Needed)

```
/data/local/tmp/genie_bundle/
├── genie-t2t-run-2.50              ← Genie NPU inference binary
├── llama3.2-3b-sm8650-genie.json   ← Model config (max 60 tokens, greedy, HTP backend)
├── llama_v3_2_3b_instruct_part_1_of_3.bin  (752 MB)
├── llama_v3_2_3b_instruct_part_2_of_3.bin  (860 MB)
├── llama_v3_2_3b_instruct_part_3_of_3.bin  (1.2 GB)
├── tokenizer.json
├── qairt_2_50_libs/                ← Qualcomm QAIRT 2.50 shared libraries
└── aarch64-android/                ← Android AArch64 runtime libs
```

Total model size on device: ~2.8 GB. **All of this persists across USB disconnect.**
