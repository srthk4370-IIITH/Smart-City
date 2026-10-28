# Domain-agent retrain v2: training run log (started 2026-10-17)

Spec: `Code/smart-city-edge-agent/training/RETRAIN_V2_SPEC.md`.
Code:
- `training/v2/` (`generate_v2.py`, `train_v2.py`, `run_v2.ps1`, `start_v2.sh`, `session_v2.sh`)
- `training/v2/hvac.py`

## Setup
- **Data:** `data/sft_v2/` (gitignored; manifest and checks copied here).
  - train 35,946 / dev 1,947 / test 2,965 rows, all 6 roles.
  - Every hard QA check passed (`dataset_checks.md`). Train sha256/16 = `2bbbe5fe4f663975`.
- **Model:** Llama-3.2-3B-Instruct.
  - Local copy from the ungated `unsloth/` mirror; its tokenizer is byte-identical to Meta's (sha256/16 `6b9e4e7fb171f92f`).
  - QLoRA nf4, LoRA r=32 / alpha 64 on all 7 projections (48.6 M trainable).
  - lr 2e-4, cosine schedule, grad-accum 16, max length 1280, 2 epochs = 4,494 optimizer steps (`plan.json`).
- **Hardware:** laptop RTX 4050 6 GB, in WSL.
  - Pilot: 411 tokens/s, peak VRAM 4.58 GiB (`pilot.json`).
  - The GPU runs at its locked ~50 W cap. The thermal guard pauses at 76 °C (81 °C before 2026-10-17 14:15).

## Loss so far
| step | epoch | dev loss | when |
|---|---|---|---|
| 300 | 0.13 | 0.1311 | 2026-10-17 13:04 |
| 600 | 0.27 | 0.0985 | 2026-10-18 02:27 |
| 900 | 0.40 | 0.0923 | 2026-10-18 12:08 |
| 1200 | 0.53 | 0.0809 | 2026-10-18 17:42 |
| 1500 | 0.67 | **0.0772** | 2026-10-18 22:45 (best_adapter) |

| 1800 | 0.80 | 0.0685 | 2026-10-19 |
| 2100 | 0.93 | 0.0682 | 2026-10-19 06:19 |
| 2400 | 1.07 | **0.0660** | 2026-10-19 09:47 (best_adapter) |

- **Speed:** background mode 45.5 s/step (79 steps/h); full mode overnight 42 s/step (85 steps/h). Full mode now also sets lid close on AC to "Do nothing" during training (restored on stop): 0 standby events overnight.
- **Stopped cleanly** 2026-10-19 11:10 at step 2,514 / 4,494 (56%).

- **Train loss scale.** The trainer logs loss summed over the 16 grad-accumulation micro-batches. Divided by 16, train loss per token is ≈ 0.085 at epoch 0.53, close to the dev loss: no sign of overfitting.
- **Plot and points:** `loss_curve.svg`, `loss_points.json`. Raw log: `train.log.txt`.
- **Dev loss is not accuracy.** The acceptance test (RETRAIN_V2_SPEC) runs on the QIDK NPU after training.

## Interruptions and fixes (evidence in this folder)
| when | what happened | cause (evidence) | fix |
|---|---|---|---|
| 10-17 01:53–01:58 | the session exited at once, 3× | `Start-Process` split the `bash -lc "..."` command string | `start_v2.sh` wrapper with no arguments |
| 10-17 02:03 | Windows almost out of RAM | WSL at 13 GB, with model files in page cache | WSL capped at 10/11 GB; supervisor drops the WSL cache when Windows has < 2.5 GB free |
| 10-17 05:45 | **blue screen**; steps 276–300 lost | bugcheck 0xD1 in `vfpext.sys`, the Hyper-V virtual-switch filter used by WSL networking (`crash_0xD1_analysis.txt`) | WSL `networkingMode=none` while training (restored afterwards); checkpoints every 14 steps; auto-resume at logon |
| 10-17 10:25–13:04 | frozen 2.6 h | sleep, `Reason: Thermal Zone` (`power_events.txt`) | GPU pause 81 → 76 °C; WSL 4 cores |
| 10-17 13:05, 15:43 | supervisor died (training kept running) | it was a child of the assistant's shell, killed when that shell was cleaned up | launched through WMI (`Invoke-CimMethod Win32_Process Create`); attach mode |
| 10-17 | the new checkpoint interval was ignored | the Trainer restores `save_steps` from the checkpoint | `train_v2.py` writes the intervals into `trainer_state.json` before resuming |
| 10-18 01:12–08:52 and 16:18–16:46 | frozen (Modern Standby) | `Reason: Lid`: the lid was closed (`power_events.txt`) | keep the lid open (a closed lid can't be overridden without disabling Modern Standby) |
| 10-18 16:18 | ran on battery | AC unplugged | the battery guard stops cleanly below 40 % |

## Modes (`run_v2.ps1`)
- **Full:** WSL 11 GB / 4 cores.
- **Background (`-Background`):** WSL 6 GB / 2 cores at low priority, so the user can work. Same speed, because the GPU is the bottleneck.
- **Both modes:** keep-awake (system + display), networking off, cache-drop guard, C: / battery / stop-flag guards, logon auto-resume. The user's `.wslconfig` and power timeouts are restored on stop.
- A GPU duty-cycle throttle (`DUTY` file) exists in `train_v2.py`. It is unused: the user chose not to sleep between micro-batches.

## Admin cleanup (2026-10-17, `admin_cleanup.log.txt`)
- WSL disk compacted from 138 → 51 GB; C: free went from 18 → 105 GB.
- Deleted: GGUF/HF intermediates, a duplicate checkpoint, temp/cache folders and git tmp packs.
- User apps closed and auto-starts disabled except Wispr Flow (backup `sce_train\startup_backup.reg`).
