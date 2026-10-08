# Training runbook: 5-role smart-city agent (Llama 3.2 3B, QLoRA)

> **Start with `HANDBOOK.md` in the repo root.** It has the full step-by-step guide, an explanation and error handling. This file is the technical detail.

## Start (one command)

Laptop **plugged in**, nothing else using the GPU (close games/video editors). In **Windows PowerShell** from `C:\Users\hp\Desktop\qidk`:

```powershell
powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\training\train.ps1
```

Keep the window open. The script keeps the laptop awake, then runs `run_all.sh` in WSL:

1. **preflight**: GPU, WSL RAM (12 GB), disk, base model, dataset.
2. **pilot**: measures real tokens/s and VRAM, then chooses the plan.
   - **Plan A**: all 5 roles (air_quality, water, power, occupancy, weather), 1,296 examples each, 2 epochs.
   - **Plan B (automatic fallback)**: air_quality only, trained fully, if Plan A cannot finish before the deadline.
3. **train**: QLoRA r=16 on all attention + MLP projections, checkpoint + dev-loss every ~100 steps, best checkpoint kept. A time guard stops cleanly before the deadline.
4. **eval**: tuned vs base vs Mode-1 rules on held-out Nov–Dec 2025 windows → `eval.md`.
5. **merge**: adapter merged into full bf16 weights (CPU) → ready for Qualcomm export.

Measured on this laptop (RTX 4050 6 GB): 390 tokens/s, peak VRAM 4.24 GiB, ~632 tokens/example
→ Plan A ≈ **6–6.5 h** training + ~30 min eval + ~3 min merge.

## Watch progress (second terminal, optional)

```bash
wsl -d Ubuntu -- bash -lc "tail -f ~/smartcity_runs/*/train.log"
```
Lines like `step 120/810  27.5s/step  ETA Wed 01:40`.

## If it stops (crash, reboot, closed window)

Run the **same command again** (`train.ps1`, or `bash run_all.sh` in WSL). It continues the latest run: training
resumes from its last checkpoint and finished stages are skipped. Only `FRESH=1 bash run_all.sh` starts over.

## Outputs

| What | Where |
|---|---|
| LoRA adapter + training_meta.json | `training/results/<run>/adapter/` (also in WSL `~/smartcity_runs/<run>/adapter`) |
| Plan, logs | `training/results/<run>/plan.json`, `train.log`, `run_all.log` |
| Evaluation table | `training/results/<run>/eval.md` |
| Merged full model (6.4 GB, for NPU export) | WSL `~/smartcity_runs/<run>/merged/` |

## Data (already built, re-run only if the source data changes)

```bash
python training/extract_series.py        # clean CSVs  -> data/series (5-min per node), ~5 min
python training/extract_occupancy.py     # RAW zip sr_oc.csv -> binary occupancy (0=occupied in raw -> 1 here)
python training/generate_dataset.py      # -> data/sft/{train,dev,test}.jsonl  (6480 / 600 / 900)
```
Labels are exact: real calm 4-hour windows + one injected pattern (spike, dip, gradual/step change, exponential,
oscillation, throttling, flatline, erratic) or real occupancy sequences; targets written by deterministic domain
rules and validated (evidence ids, enums). Split by time: train Jan–Aug, dev Sep–Oct, test Nov–Dec 2025.
Prompt format = exactly what the QIDK app sends (`features.py` ↔ `app/backend/features.go`).
