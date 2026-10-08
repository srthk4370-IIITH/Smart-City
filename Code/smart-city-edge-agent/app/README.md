# Smart City Edge: on-device app for the Qualcomm QIDK

Standalone smart-campus monitor that runs **entirely on the QIDK**: polling, statistics, anomaly gating,
three reasoning modes and Llama 3.2 3B inference on the **Hexagon NPU (HTP V75)** through Qualcomm Genie.
After it starts, the laptop and USB cable are not needed.

## Run it (one command)

QIDK connected over USB, from `C:\Users\hp\Desktop\qidk` in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\app\android\install_app.ps1 -Build -ClearHistory
```

This installs the native **Smart City Edge** Android app (`android/`). The app is a WebView UI plus a
foreground service. The service starts the NPU backend through the board's own adbd (127.0.0.1:5555),
because Android apps cannot open the NPU on this firmware. It restarts the backend after every reboot,
self-heals deleted model files from an on-device backup, and is a device admin (uninstall blocked).
The dashboard is mirrored on the laptop at http://localhost:8000 (`adb forward tcp:8000 tcp:8000`).
`deploy.ps1` is the older script, which runs the backend without the app (`-Action status | logs | stop | start | open`).

## What runs where

```
QIDK (Android 14, SM8650)                                    /data/local/tmp/smart_city_edge/
 edge-agent (native Go binary, linux/arm64, shell user)
  ├─ SensorBank       18 live sensors: app sliders (user = sensor) or POST /api/ingest from real devices
  ├─ WindowBuilder    4-h windows (48 × 5 min), SMA/EMA 1 h, Bollinger, slope, curvature, plateau, flat runs
  ├─ Mode-1 rules     deterministic pattern classifier + domain rules (status, cause, action)
  ├─ EventGate        only warning/critical/sensor_fault, 8 readings persistence, all alarming sensors -> ONE incident
  ├─ Reasoner         Mode 1 Rules | Mode 2 Single-SLM | Mode 3 Multi-Agent (domain agents + synthesizer)
  │    └─ GenieRunner  genie-t2t-run-2.50 on HTP, single-flight, retries transient NPU errors (3/7/15 s), /data/local/tmp/genie_bundle (base)
  │                    or /data/local/tmp/genie_bundle_ft (fine-tuned, used for agents once VALIDATED)
  ├─ PolicyGate       JSON, enums, evidence ids ⊆ prompt evidence, action whitelist, actuation blocked
  ├─ IncidentStore    state/incidents.jsonl (append-only), human approve/dismiss
  └─ HTTP :8000 + SSE dashboard (web/), offline PWA
```

### Modes

| Mode | NPU calls per incident | Output |
|---|---|---|
| 1 Rules | 0 | rule pattern + status/cause/action per sensor |
| 2 Single-SLM | 1 | one cross-domain report from all flagged sensors |
| 3 Multi-Agent | 1 per alarming sensor (up to 8) + 1 synthesizer | each domain agent: pattern (spike, dip, gradual/step change, exponential, oscillation, throttling, flatline, erratic; occupancy: vacant/occupied/arrival/departure/intermittent/off-hours), status, observations citing evidence E1..E8, cause, action. The synthesizer then writes the cross-domain root cause |

Mode 1 always runs as a shadow baseline. Each incident has *Compare* buttons that re-run the same frozen windows in the other modes.

### Model in use (shown in the header)

* **Fine-tuned agent model**: used for the domain agents when `/data/local/tmp/genie_bundle_ft/VALIDATED` exists.
  `training/export/validate_tuned_on_device.py` writes this file after the tuned bundle passes on-device tests.
* **Base Llama 3.2 3B (fallback)**: otherwise. The synthesizer and Mode 2 always use the base model.

The agent prompt text is byte-identical to the training prompts (`training/features.py` ↔ `backend/features.go`,
checked by `backend/parity_test.go` on 400 fixtures).

## Demo script (≈5 min)

1. Header: *Running on QIDK, standalone*, NPU idle, model badge, 59 °C. Unplug USB to show it keeps running.
2. Live tab: five domain cards, live SMA/EMA/slope, pattern chips per sensor.
3. Scenarios → **Ventilation failure** (Mode 3). Watch the incident timeline: Air-Quality agent on NPU → synthesizer → policy gate.
4. Open the incident: agent observations with evidence chips, rule baseline, raw model output, latency per NPU call. Approve it.
5. **Compare** → Mode 1 and Mode 2 on the same windows.
6. Scenarios → **Crowded room**: occupancy + CO2 + power together, cross-domain report.
7. Map tab: buildings/levels, coverage; About: pipeline.

## Build from source (laptop, WSL)

```bash
bash app/build.sh            # vet + build device/edge-agent (arm64) and device/edge-agent-host
bash app/test.sh             # prompt/rule parity vs training (must say 0 mismatches)
python app/tools/build_replay.py   # rebuild replay pack from data/series
```
Development without the device: `device/edge-agent-host --dir app/device --mock --addr 0.0.0.0:8090` (fake LLM, never used on the QIDK).
