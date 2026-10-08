# Smart City Edge AI: Run Guide

This guide takes you from a fresh clone to the native **Smart City Edge** app running on a Qualcomm QIDK.
The app runs Llama 3.2 3B (fine-tuned, w4a16) on the Hexagon NPU, and after setup it works without the laptop.

Run commands in **Windows PowerShell** from the repo root unless a step says WSL.
For the full explanation of the system, see `teach.md`. For results and decisions, see `HANDBOOK.md`.

---

## 1. What you need

| Item | Details |
|---|---|
| Board | Qualcomm QIDK, Snapdragon 8 Gen 3 (SM8650), Hexagon NPU V75, Android 14 userdebug |
| Laptop | Windows 10/11 with **WSL2 Ubuntu**; NVIDIA GPU with 6 GB or more is needed only for training |
| USB | needed only for setup; the app runs standalone afterwards |
| Tools in WSL | Go (`~/go-sdk/go/bin`), Android SDK build-tools + platform 34 (`~/android-sdk`), JDK 17, `zip` |
| Accounts | Qualcomm AI Hub (export of the NPU model), Hugging Face (Llama 3.2 licence, training only) |

The repo bundles `adb` at `Code\platform-tools\adb.exe`.

**Files that are NOT in git** (too large, or licensed SDK files):
- model bins (`*.bin`, `*.safetensors`)
- the QAIRT/Genie runtime
- datasets
- built APK and binaries

Section 3 explains how to get each one.

```powershell
git clone https://github.com/ESW-M26/esw-m26-14_nasa.git
cd esw-m26-14_nasa
.\Code\platform-tools\adb.exe devices        # expect: 3ce9a4e2  device
```

If it shows `unauthorized`, unlock the QIDK and tap **Always allow from this computer**.

---

## 2. Quick path (board already set up)

If `/data/local/tmp/genie_bundle` (runtime + base model) and `/data/local/tmp/genie_bundle_ft` (fine-tuned model)
are already on the QIDK:

```powershell
powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\app\android\install_app.ps1 -Build -ClearHistory
```

The script does the following:
1. Builds the Go backend and APK in WSL.
2. Installs the app.
3. Enables the on-device adb loopback the app needs to reach the NPU.
4. Makes the app a device admin, so it cannot be uninstalled by accident.
5. Copies the models into the app's self-heal backup.
6. Starts the app.

You can unplug the USB afterwards. The app restarts its backend after every reboot.

---

## 3. Full setup of a new board

### 3.1 NPU runtime (QAIRT 2.50 Genie)

Get these from the Qualcomm AI Engine Direct / QAIRT SDK 2.50:
- `genie-t2t-run`
- `libGenie.so`, `libQnnHtp.so`, `libQnnHtpNetRunExtensions.so`, `libQnnHtpV75Stub.so`, `libQnnSystem.so` (aarch64-android)
- the V75 DSP libs (`libQnnHtpV75Skel.so`, `libQnnHtpV75.so`, …)

Push them to the QIDK:

```
/data/local/tmp/genie_bundle/genie-t2t-run-2.50
/data/local/tmp/genie_bundle/qairt_2_50_libs/   (the 5 ARM libs)
/data/local/tmp/genie_bundle/dsp_2_50/          (the DSP libs)
```

Then run `adb shell chmod 755 /data/local/tmp/genie_bundle/genie-t2t-run-2.50`.

### 3.2 Base model (fallback)

```bash
# WSL, with qai-hub-models 0.63 installed and `qai-hub configure` done
qai-hub-models export llama_v3_2_3b_instruct --device "Samsung Galaxy S24 (Family)" --target-runtime genie --skip-profiling \
  --output-dir Code/smart-city-edge-agent/models/genie_bundle
```

Push the three `llama_v3_2_3b_instruct_part_*_of_3.bin` files and `tokenizer.json` to `/data/local/tmp/genie_bundle/`.
Then push `Code/smart-city-edge-agent/configs/llama3.2-3b-sm8650-genie.json` and `htp_backend_ext_config.json` to the same folder.

### 3.3 Fine-tuned model

Either rebuild it (section 5) or copy it from a laptop that has `qidk_backup\genie_bundle_ft\`.
On such a laptop, `qidk_backup\restore_qidk.ps1` restores a wiped board in one command.

### 3.4 Install the app

Run the same command as section 2.

---

## 4. Using the app

- **Sensors tab:** the user acts as the sensors. Each slider is one sensor; its value is read every poll
  (one 5-minute reading every 2 s). Real sensors can post the same data to
  `POST /api/ingest {"node":..,"metric":..,"value":..}`.
- **Event gate:** the AI is called only for `warning`, `critical` or `sensor_fault` readings, after 8 abnormal
  readings in a row. Everything alarming together becomes **one incident** and one batch of NPU calls.
  At rest the AI is never called.
- **Modes:**
  - Mode 1: rules only.
  - Mode 2: one model call.
  - Mode 3: one domain agent per alarming sensor, plus a cross-domain synthesizer.
- **Safety:** every model output goes through the policy gate:
  - the JSON must be valid;
  - pattern, status, cause and action values must come from the allowed lists;
  - the evidence ids must exist in the prompt;
  - every action needs human approval, so there is no automatic actuation.
- **NPU hiccups (fixed):** after a reboot or an idle period the NPU sometimes refuses a session (`err 1002`).
  The app retries after 3, 7 and 15 s and re-runs the agent at the end of the batch. This is shown as
  "NPU temporarily unavailable", not as a safety rejection.

Useful device commands:

```powershell
$A = ".\Code\platform-tools\adb.exe"
& $A shell cat /data/local/tmp/smart_city_edge/state/agent.log           # backend log
& $A shell "curl -s http://127.0.0.1:8000/api/status"                     # NPU / model / thermal status
& $A forward tcp:8000 tcp:8000; start http://localhost:8000               # dashboard mirrored on laptop
```

---

## 5. Rebuilding the fine-tuned NPU model (optional, about 1 night)

1. **Train (QLoRA, 5 roles):**
   `powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\training\train.ps1`
   - Stages: preflight, plan, train, eval, merge. See `training/TRAINING.md`.
   - The datasets (`ihub-clean-datasets/`, `Code/smart-city-edge-agent/data/`) are not in git. Rebuild them with
     `training/extract_series.py`, `training/extract_occupancy.py` and `training/generate_dataset.py`.
2. **Quantise:** GPTQ int4, per channel.
   `python training/export/gptq_quant.py`, then `python training/export/gptq_to_ckpt.py` (WSL).
3. **Export to Genie:** `bash training/export/export_gptq.sh` (Qualcomm AI Hub).
   - Optional: activation calibration on Kaggle, in `training/export/kaggle/`.
4. **Validate on the device:** `powershell -File .\Code\smart-city-edge-agent\training\deploy_tuned.ps1`
   - This writes `VALIDATED` only if the bundle passes on the NPU.
   - Then re-run `install_app.ps1` so the on-device backup is refreshed.

Results so far:
- Host bf16: 91.3 % pattern accuracy.
- Device w4a16: **85.2 %** pattern accuracy.
- JSON, evidence and policy validity: 100 %.

---

## 6. Development without the board

```bash
bash Code/smart-city-edge-agent/app/build.sh      # go vet + arm64 binary + host binary
bash Code/smart-city-edge-agent/app/test.sh       # prompt/rule parity vs training (0 mismatches)
cd Code/smart-city-edge-agent/app/backend && go test ./...
Code/smart-city-edge-agent/app/device/edge-agent-host --dir Code/smart-city-edge-agent/app/device --mock --addr 0.0.0.0:8090
```

Use any port except 8000 for mocks, because 8000 is forwarded to the real device.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| App shows "Rules only, NPU offline" | adb loopback is off. Re-run `install_app.ps1` (it sets `persist.adb.tcp.port=5555`) |
| `Could not create context from binary ... err 1002` | Transient NPU state after a reboot or idle; retried automatically. If it persists, reboot the QIDK |
| Dates years in the future | Fixed: the clock offset is now applied only while the QIDK clock is unsynced (before 2025) |
| Backend restarted by itself | Restarting adbd (`adb root`/`unroot`) kills it; the app restarts it in ~6 s |
| Uninstall refused | Intended. Settings → Security → Device admin apps → turn off Smart City Edge protection first |
| Model file deleted | The app restores it from its on-device backup within 5 min |

**Security:** adb on this dev kit has no authentication, and the app keeps port 5555 open. Keep the QIDK off
shared or untrusted Wi-Fi/LAN. To revert: `adb root; adb shell setprop persist.adb.tcp.port ""; adb unroot`.
