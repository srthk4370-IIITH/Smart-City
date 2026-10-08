# Mid-eval runbook (Tue night → Thu 2 pm)

> Full explanation, every step and what to do on errors: **`HANDBOOK.md`**. This is the short version.

Everything below is one command per step, run from `C:\Users\hp\Desktop\qidk` in **Windows PowerShell**.

## Tonight: start the overnight pipeline

QIDK connected over USB, laptop **plugged in**, no game/GPU app open:

```powershell
powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\training\train.ps1
```

Leave the window open. It runs automatically:

| Stage | What | Time (measured / estimated) |
|---|---|---|
| A1 preflight | GPU, WSL 12 GB RAM, disk, base model, dataset | 1 min |
| A2 pilot + plan | measures tokens/s (390 tok/s, 4.2 GB VRAM measured) → **Plan A: 5 agents** (air quality, water, power, occupancy, weather), 1,296 examples each, 2 epochs. Falls back to **Plan B: air quality only** automatically if Plan A can't finish by the deadline | 2 min |
| A3 QLoRA training | Llama 3.2 3B, r=16 on all projections, checkpoints, time guard | ~6–6.5 h |
| A4 eval | tuned vs base vs rules on held-out Nov–Dec 2025 → `training/results/<run>/eval.md` | ~30 min |
| A5 merge | full bf16 weights for export | ~3 min |
| B export | Qualcomm AI Hub (free): build checkpoint, upload ~14 GB at ~11 Mbit/s, compile for SM8650 | ~4–5 h |
| C validate | push tuned bundle to QIDK, run held-out prompts on the NPU (tuned vs base) → `training/results/device_eval.md`; marks bundle VALIDATED only if it passes | ~20 min |

If anything after A5 fails, the app keeps using the base model on the NPU (fallback). Nothing breaks.

Verified before handing over (Tue evening):
- Training smoke run end to end: pilot, train, eval, merge. Real pilot speed 390 tok/s, peak VRAM 4.24 GiB.
- Export environment: qai-hub-models 0.63.0 (CPU torch 2.10, transformers 4.56.2, aimet-onnx 2.28). The AI Hub token works and the Galaxy S24 / SM8650 target is listed. AI Hub's default QAIRT is **2.50.0.260828221209, the same build as the bundle on the QIDK**.
- Export spike with the base model: the Qualcomm graph built from our weights matches **1233/1233 weight and 11711/11711 activation encodings** of the published w4a16 quantisation.
- Laptop limits handled: WSL 12 GB RAM + 64 GB swap (the build peaks at about 47 GB swap). Intermediate 14 GB ONNX copies are deleted after the build. Qualcomm's S3 transfers are tuned to 16 parallel parts, because this network gives only about 30–40 KB/s per S3 connection and about 1.3 MB/s upload.
- The slowest part of stage B is the upload (about 14 GB) and the bundle download. If stage B is still running on Wednesday afternoon, leave it running. The app works with the base model in the meantime.
- Keep at least ~50 GB free on C: overnight. It was 77 GB at hand-over.
Progress: `wsl -d Ubuntu -- bash -lc "tail -f ~/smartcity_runs/*/train.log"`. Resume after a crash: see `Code/smart-city-edge-agent/training/TRAINING.md`.

## Thursday: before the eval

```powershell
powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\app\deploy.ps1 -Action reset
```
This starts the app on the QIDK with a clean incident history and opens the dashboard on the device (also on the laptop at http://localhost:8000).
The header shows which model the agents use: **Fine-tuned agent model** (green) or **Base Llama 3.2 3B (fallback)** (amber).
After it starts you can unplug the USB cable; the app keeps running on the QIDK.

Thermal: the QIDK gets hot under continuous NPU use (we measured 94 °C NPU junction after a long test session).
Keep it on a hard surface with airflow and start the app shortly before the demo. A thermal guard defers background
LLM analysis while hot; demo scenarios always run.

## Demo flow (~5 min)

1. Header: *Running on QIDK, standalone*, NPU status, model badge, temperatures. Unplug USB.
2. **Live**: five domain cards, each sensor with SMA/EMA 1 h, trend/h, pattern chip (spike, throttling, exponential…).
3. **Scenarios → Ventilation failure** (mode 3). **Incidents**: timeline shows the Air-Quality agent running on the NPU,
   then the synthesizer, then the policy gate. Open it: observations with evidence chips, raw output, per-call latency. Approve it.
4. **Compare → Mode 1 / Mode 2** on the same windows (rules vs single LLM vs multi-agent).
5. **Scenarios → Crowded room**: occupancy + CO2 + power → cross-domain report.
6. Other scenarios: throttling, load surge, tank leak, pump cycling, stuck sensor, heat build-up, presence at night.
7. Show `training/results/<run>/eval.md` and `device_eval.md` (before/after fine-tuning numbers).

Verified: all 10 scenarios produce the intended pattern (`app/tools/check_scenarios.sh`). Device prompts are
byte-identical to the training prompts (`app/test.sh`, 400/400).

## Where things are

| Path | What |
|---|---|
| `Code/smart-city-edge-agent/training/` | data extraction, dataset generator, QLoRA training, eval, merge, `export/` (NPU export + device validation) |
| `Code/smart-city-edge-agent/app/` | on-device app: `backend/` (Go), `device/` (binary, replay data, web dashboard), `deploy.ps1`, `README.md` |
| `Code/smart-city-edge-agent/data/series`, `data/sft` | 5-min sensor series (clean CSVs + raw-zip occupancy), SFT dataset 6480/600/900 |
