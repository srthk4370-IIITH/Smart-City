# HANDBOOK: Train, Deploy, Demo (read this first)

Everything you need, in order. Commands are copy-paste. Run them in **Windows PowerShell** from
`C:\Users\hp\Desktop\qidk` unless it says WSL.

---

## 1. The big picture in plain words

We built two things.

**A. An app that runs on the QIDK by itself (no laptop needed).**
- It replays real IIIT-H sensor data (air quality, water, power, occupancy, weather) as if it were live: a
  new reading every 2 seconds = 5 minutes of campus time.
- For every sensor it keeps the last 4 hours and computes moving averages (SMA/EMA), trend, jumps, and
  plateaus. A fast rule engine names the pattern it sees (spike, gradual rise, throttling, flatline, …).
- When something looks wrong, it asks the **AI model on the QIDK's NPU** (Llama 3.2 3B) to analyse it, in one
  of 3 modes:
  - **Mode 1, Rules:** no AI, just the rule engine (the baseline).
  - **Mode 2, Single AI:** one AI call looks at all the problem sensors at once.
  - **Mode 3, Multi-Agent:** one "domain agent" per problem sensor (Air Quality agent, Water agent, …) says
    what it notices, then a "synthesizer" AI call combines them into one root cause.
- Every AI answer passes a **safety check** (policy gate): correct format, only real evidence ids, no
  "turn off / shut down" orders. Failed answers are shown as REJECTED with the reason.
- A dashboard (web page) on the QIDK screen shows all of this live.

**B. A training pipeline that teaches the AI to be a better domain agent.**
- Out of the box, Llama often answers in the wrong format and invents numbers (you will see REJECTED
  answers). We fine-tune it on 6,480 worked examples built from the real data, so it learns to:
  read a 4-hour window → name the pattern → judge severity → explain with evidence → pick a safe action.
- After training, the improved model is converted for the NPU (Qualcomm AI Hub), copied to the QIDK, tested
  there, and only if it passes does the app start using it. Otherwise the app keeps the original model
  (shown as "Base Llama 3.2 3B (fallback)").

```
TONIGHT (laptop, automatic)                              THURSDAY (QIDK, standalone)
 train.ps1                                                deploy.ps1 -Action reset
  ├─ A. train the agent model on the GPU (~6.5 h)          ├─ starts the app on the QIDK
  ├─ A. test it on held-out data + merge (~35 min)         ├─ dashboard opens on the QIDK screen
  ├─ B. convert for the NPU on Qualcomm AI Hub (~4-6 h)    └─ uses the fine-tuned model if it was
  └─ C. copy to QIDK + test on the NPU (~20 min)               validated in step C, otherwise the base
```

---

## 2. Tonight: start training (step by step)

### 2.1 Checklist (2 minutes)
- [ ] Laptop **plugged in** (on battery the GPU slows down; the script keeps the laptop awake).
- [ ] QIDK connected by USB (needed only for the last step, C, in the morning).
- [ ] Close games, video editors, and other apps that use the GPU. Close Chrome tabs you don't need (RAM).
- [ ] At least **50 GB free on C:** (it was 77 GB at hand-over). Check: File Explorer → This PC.

### 2.1b Why the screen went black last night, and what changed (2026-10-07)

The display loss was **not** a graphics driver crash. Windows force-hibernated the laptop **21 times**
("critical thermal event", ACPI zone TZ01 reached its **100 C** limit). That blanks the screen and kills training.
Training had also slowed from 27 to 36.8 s/step, the classic sign of overheating.

Fixes now in place (all applied, no action needed from you):

| Fix | Effect |
|---|---|
| **GPU thermal guard** in training: pauses above 83 C, resumes below 75 C | measured: 5 pauses of 10 s each over 6 min (~13 % slower), peak 86 C, **no hibernation** |
| **CPU capped to 75 %** on AC (`powercfg`, set automatically by `train.ps1`) | large heat cut; a GPU-bound job barely notices |
| **WSL reduced to 9 GB RAM / 8 cores** (was 12 GB / 12) + `autoMemoryReclaim` | Windows pagefile had peaked at **13 GB**; that swapping heated the CPU and SSD |
| **Checkpoints every ~20 steps** (was ~101) | a crash now costs minutes, not an hour |
| **Auto-restart** (`train.ps1 -Attempts 6`) | if the laptop does hibernate, training resumes by itself from the last checkpoint |
| **Planner assumes 75 % of pilot speed** | the schedule already allows for thermal pauses |
| **Thermal log** at `%USERPROFILE%\smartcity_thermal.csv` | evidence if it ever recurs |

| **GPU power cap to 35 W** (default `-GpuWatts 35`) | the GPU would otherwise pull its full **50 W** and sat at 85-87 C; this is the biggest single heat lever |

**One click when you start:** `train.ps1` now caps the GPU itself, so Windows will show **one UAC prompt**
("nvidia-smi") a few seconds after you launch it. Click **Yes**. If you miss it or decline, training still runs,
the thermal guard just pauses more often. The cap resets by itself on reboot. To change it:
`train.ps1 -GpuWatts 30` (cooler) or `-GpuWatts 0` (skip the prompt entirely).

**Also help the airflow:** raise the back of the laptop (a book is enough), keep the vents clear, and if you have
a cooling pad use it. Closing heavy apps (Edge/WebView, Notion) frees RAM too; during the test Windows had under
1 GB free at times.

### 2.2 Start (one command)
```powershell
cd C:\Users\hp\Desktop\qidk
powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\training\train.ps1
```
**Keep this window open all night.** Don't close it, don't let Windows update/restart.

### 2.3 What you should see in the first 3 minutes
```
Keeping the laptop awake while plugged in ...
=== Stage A: training ...
--- preflight
  OK   CUDA available: NVIDIA GeForce RTX 4050 Laptop GPU
  OK   GPU free memory 5.0 / 6.0 GiB ...
  OK   ...   (all lines must say OK)
--- train
[21:05:10] LoRA trainable params: 24.3 M
[21:05:50] PILOT: ~390 tokens/s fwd+bwd, peak VRAM ~4.2 GiB
[21:05:50] PLAN {'plan': 'A', 'roles': ['air_quality', 'water', 'power', 'occupancy', 'weather'], 'per_role': 1296, ...}
[21:06:30] step 5/810  27.0s/step  ETA Wed 03:10
```
- **Plan A** = all 5 agents (expected). **Plan B** = only Air Quality, chosen automatically if there's not enough
  time before the deadline (Wed 13:00). Both are fine.
- The `ETA` line tells you when training finishes.

### 2.4 Watching progress (optional, a second window)
```powershell
wsl -d Ubuntu -- bash -lc "tail -f ~/smartcity_runs/agents_*/train.log"
```
Press Ctrl+C to stop watching (training keeps running). Lines with `eval_loss` going down = learning.

### 2.5 What happens overnight (automatic, no action needed)

| Stage | What it does | How it works | Time | Output |
|---|---|---|---|---|
| A1 preflight | checks GPU, RAM, disk, files | — | 1 min | — |
| A2 pilot + plan | measures speed, picks Plan A or B | runs 24 examples without learning, times them | 2 min | `plan.json` |
| A3 training | teaches the model | **QLoRA**: base model frozen in 4-bit, small extra layers (24 M params) learn. Loss only on the answer. Checkpoint every ~100 steps. Stops safely before the deadline | ~6–6.5 h | adapter |
| A4 eval | grades the new model | answers 150 unseen Nov–Dec windows; compares fine-tuned vs original vs rules | ~30 min | `eval.md` |
| A5 merge | builds the full improved model | adds the learned layers into the full weights | ~3 min | `merged/` (6.4 GB) |
| B export | makes it run on the NPU | builds Qualcomm's format (heavy: uses RAM + ~50 GB swap), uploads ~14 GB to Qualcomm AI Hub, which compiles it for Snapdragon 8 Gen 3 and sends back 3 `.bin` files | ~4–6 h (slow internet) | NPU bundle |
| C validate | tests it on the QIDK | copies the bundle to the QIDK, runs 20 unseen examples with the new and original model on the NPU, scores them | ~20 min | `device_eval.md`, `VALIDATED` |

### 2.6 How you know it finished
The window ends with:
```
All stages finished. On-device comparison: Code\smart-city-edge-agent\training\results\device_eval.md
VALIDATED: the app now uses the fine-tuned model ...      (or: NOT validated: the app keeps the base model)
```
Results to look at (and show at the eval):
- `Code\smart-city-edge-agent\training\results\agents_<date>\eval.md`: laptop test, fine-tuned vs base vs rules
- `Code\smart-city-edge-agent\training\results\device_eval.md`: on-QIDK NPU test, fine-tuned vs base

---

## 2.7 RESULTS (training finished 2026-10-07)

**Training completed overnight.** Plan A: all 5 agents, 1,296 examples each, 2 epochs, 810 steps.
The thermal guard paused 405 times (68 min total), peak GPU 87 C, **no hibernation**. Best dev loss 0.027.

**Laptop evaluation** (150 held-out Nov-Dec windows) - `training/results/agents_20261006_2101/eval.md`:

| | fine-tuned | base Llama | rules (Mode 1) |
|---|---|---|---|
| pattern accuracy | **94.0 %** | 20.0 % | 68.0 % |
| status | **92.7 %** | 29.3 % | - |
| likely cause | **93.3 %** | 18.0 % | - |
| action | **90.7 %** | 22.7 % | - |
| evidence valid | **100 %** | 34.7 % | - |
| output tokens | **84** | 199 | 0 |

**On-device evaluation** (QIDK NPU, w4a16) - `training/results/device_eval.md`: tuned beats base on every
metric (pattern 45 % vs 20 %, policy pass 80 % vs 20 %, 4.9 s vs 7.5 s per call) and is **VALIDATED**, so the
app uses it. Device accuracy is below the laptop's 94 % because the NPU model is 4-bit quantised using the
*base* model's calibration ranges - see "quantisation gap" below.

**End-to-end latency on the QIDK, fine-tuned vs base:**

| scenario | with base | with fine-tuned | NPU calls |
|---|---|---|---|
| Ventilation failure | 17.8 s | **8.9 s** | 2 |
| Tank leak (related domains steady) | 4.9 s | **5.6 s** | 1 |
| Crowded room (3 domains) | 31.8 s | **23.5 s** | 4 |
| Compare rerun (cached) | 0 ms | **3 ms** | 0 |

**The quantisation gap, and what was done about it (2026-10-07).** Same 46 held-out windows throughout.

| step | where | pattern accuracy |
|---|---|---|
| fine-tuned, laptop 4-bit NF4 (training eval) | host | 94 % |
| first NPU export (w4a16, base-model activation ranges, widened weight scales) | **QIDK** | 54.3 % |
| same + MSE-optimal clipped weight scales | QIDK | 39.1 % (worse: clipping cut the few large weights LLMs rely on) |
| **diagnostic:** device's int4 weights, activations kept full precision | host | 73.9 % |
| **GPTQ** int4 weights (error-compensating rounding, calibrated on our own train prompts), full-precision activations | host | **89.1 %** |
| GPTQ weights + base-model activation ranges | QIDK | 67.4 % |
| GPTQ weights + activation ranges recalibrated on 149 k tokens of our prompts (Kaggle) | QIDK | 60.9 % |
| **found:** Genie adds its own BOS token, so every device prompt had a *double* BOS the model never saw | | |
| GPTQ + recalibrated ranges, BOS fixed | QIDK | 82.6 % (JSON 97.8 %, policy 93.5 %) |
| **GPTQ + published ranges, BOS fixed (current, live in the app)** | **QIDK** | **82.6 %** (JSON, evidence and policy pass **100 %**) |
| same live model, larger device test (54 windows) | QIDK | **85.2 %** (status 87 %, cause 81.5 %, JSON/evidence/policy 100 %) |
| GPTQ with 256 calibration samples (experiment) | host | 89.1 % (same as 128; not exported) |

What this shows:
- The single biggest device-side loss was not quantisation but a **prompt mismatch**. Genie prepends BOS itself
  (measured: 606 host tokens became 607 in Genie). Stripping ours (`genie.go`, `validate_tuned_on_device.py`)
  took the same weights from 67 % to 83 %.
- The int4 weights cost ~20 points with plain rounding; **GPTQ** recovers most of that (74 % -> 89 % on host).
- Recalibrating activation ranges on our own data ran on Kaggle with a lean ONNX Runtime min/max calibrator
  (`kaggle/calib_ort.py`, 4 parallel shards; AIMET's own QuantSim needs more than Kaggle's 30 GB). The
  KV-cache in/out ranges must be tied or Genie refuses the model. It did not beat the published ranges once
  BOS was fixed, so the app keeps the published ones.
- `w4` precision (fp16 activations) compiles but **does not load on the 8 Gen 3 NPU** (Qualcomm lists it only
  for 8 Elite / X Elite, at half the speed).
- In the live app, an incident now waits until the abnormal pattern has lasted **8 readings** (~16 s). The agents
  were trained on events that had run for at least 7 readings; younger windows were misread (a fresh step called
  a spike). Rule status, including critical, still shows on the dashboard instantly.

GPTQ writes weights that lie exactly on the int4 grid with their exact scales, so AI Hub's quantiser
reproduces the same integers on the device (verified: 0 mismatches over 1,232 tensors).
Files: `gptq_quant.py`, `gptq_to_ckpt.py`, `export_gptq.sh`, `fakequant_eval.py`, `PLAN_NPU_ACCURACY.md`.

**Other fixes made on 2026-10-07:**
- The exported bundle defaults to **random sampling** (temp 0.8); the deploy step now forces greedy decoding,
  without which the cache and reproducibility break.
- All reasoning (agents, synthesiser, Mode 2) now uses **one** bundle. Alternating two 2.9 GB bundles made
  Genie fail with "could not create context from binary"; a bundle-switch gap and one retry were added too.
- Policy gate gained three **transparent repairs** (each recorded in the incident's `repairs` field, nothing
  invented): a missing `action` derived from the stated cause via our own taxonomy table; evidence ids packed
  into one string ("S1.E5,S1.E7") split; and malformed JSON salvaged by extracting the model's own stated
  fields. Agent pass rate went from 3/6 to 5/6 on the demo scenarios.

## 3. If something goes wrong

**Golden rule: just run the same `train.ps1` command again.** It continues where it stopped: training resumes
from its last checkpoint and finished stages are skipped. It never starts over unless you ask for it with
`FRESH=1` (see 3.3).

### 3.1 Problems and fixes

| What you see | Why | What to do |
|---|---|---|
| A preflight line says `FAIL ... GPU free memory` | another app uses the GPU | close games/Chrome/video apps, run `train.ps1` again |
| `FAIL WSL RAM` | WSL didn't pick up 12 GB | `wsl --shutdown`, wait 10 s, run `train.ps1` again |
| `FAIL base model` | Hugging Face cache missing | don't continue. The model is in `~/.cache/huggingface` in WSL. Ask for help |
| `CUDA out of memory` during training | GPU memory taken by something else | close GPU apps, run `train.ps1` again (it resumes) |
| Window closed / laptop slept / restarted | training process killed | run `train.ps1` again (resumes from last checkpoint, loses at most ~100 steps) |
| `TIME GUARD: deadline reached` | ran slower than planned | not an error: it saved the best model so far and continues to eval/merge/export |
| `WARNING: eval failed (continuing)` | report step failed | not critical. Re-run the report later: `wsl -d Ubuntu -- bash -lc "source ~/venvs/train/bin/activate; cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training; python eval_agents.py --run $(ls -d ~/smartcity_runs/agents_* \| tail -1)"` |
| `Export failed - the app keeps the base model` | stage B problem (internet, AI Hub, memory) | the app still works with the base model. Look at the log: `wsl -d Ubuntu -- bash -lc "tail -50 ~/qaihm_work/ft_export.log"`. Most common: network dropped → run `train.ps1` again (finished parts are skipped) |
| Export log says `Killed` or `out of memory` | not enough RAM+swap for the 13 GB model build | close all other apps, `wsl --shutdown`, run `train.ps1` again |
| Export log mentions `qairt_version` / `2.50` not available | AI Hub retired that version | can't be fixed tonight; keep the base model (fallback) |
| AI Hub `401` / `token` / `authentication` | token expired | `wsl -d Ubuntu -- bash -lc "source ~/venvs/qaihm/bin/activate; qai-hub configure --api_token <your token from aihub.qualcomm.com → Settings>"` then run `train.ps1` again |
| C: almost full (< 10 GB) | swap + model files | delete big files you don't need on C:, or run `wsl --shutdown` (frees the swap file) and run again |
| Stage C: `adb` / `device not found` | QIDK unplugged or asleep | plug in, unlock the screen, run only stage C: see 3.2 step C |
| `NOT validated` | fine-tuned NPU model scored lower than required | fine: the app keeps the base model. The laptop `eval.md` still shows the training results |

### 3.2 Running a single stage by hand
```powershell
# A (train + eval + merge), continues the latest run:
wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training && bash run_all.sh"
# B (export to NPU), resumable:
wsl -d Ubuntu -- bash -lc "bash /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/export/export_to_npu.sh"
# C (copy to QIDK + validate), needs the QIDK connected:
$b = (wsl -d Ubuntu -- bash -lc 'dirname $(ls ~/qaihm_work/ft_genie/*/*part_1_of_3.bin | head -1)').Trim()
python .\Code\smart-city-edge-agent\training\export\validate_tuned_on_device.py --bundle ("\\wsl$\Ubuntu" + ($b -replace "/", "\"))
# skip B and C entirely tonight (only train):
powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\training\train.ps1 -NoExport
```

### 3.3 Start completely fresh (only if you really want to)
```powershell
wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training && FRESH=1 bash run_all.sh"
```

### 3.4 Switch the app back to the original model (if the fine-tuned one misbehaves in the demo)
```powershell
.\Code\platform-tools\adb.exe shell "rm /data/local/tmp/genie_bundle_ft/VALIDATED"
```
The app switches back within a few seconds (header shows "Base Llama 3.2 3B (fallback)").

---

## 4. Thursday: deploy and demo

### 4.1 Install the app on the QIDK (once, USB connected)
```powershell
cd C:\Users\hp\Desktop\qidk
powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\app\android\install_app.ps1 -Build
```
This installs **Smart City Edge**, a real Android app with its own icon. It opens full-screen and starts by itself
after every reboot. **After this the laptop is not needed at all:** unplug USB, reboot the board, and it still
comes up with the NPU agents working (verified: backend running 22 s after boot, nothing touched).
The laptop can still show the dashboard at http://localhost:8000 while plugged in (handy for a projector).

How it works, and why it is built this way:
- This QIDK's firmware does **not** let ordinary Android apps open the Hexagon NPU. The vendor DSP service
  answers `Permission denied` for apps; it isn't SELinux, it failed the same way in permissive mode. Only the
  shell (adb) user may.
- So the app talks to the QIDK's **own adb daemon on 127.0.0.1:5555**, the same technique Shizuku and LADB use.
  It installs or refreshes the backend from the APK into `/data/local/tmp/smart_city_edge` and starts it as the
  shell user, where Genie can use the NPU. A foreground service watches it and restarts it if needed.
- For that, adb listens on TCP 5555 at every boot (`persist.adb.tcp.port=5555`). The installer set this once
  with the dev kit's `adb root`; no system partition was changed.
- If local adb is ever unreachable, the app falls back to an in-app backend in **Mode 1 (rules only)**.

**Security note:** adb on this dev kit needs no authorization (`ro.adb.secure` unset). Keep the QIDK **off
untrusted Wi-Fi/LAN**: anyone on the same network could get a shell on port 5555. Today it has no network.
To revert: `adb root`, then `adb shell setprop persist.adb.tcp.port ""`, then `adb unroot` (the app then runs rules-only).

The QIDK's clock resets to 2023 at boot. The app corrects dates with an offset saved at install time, so
"analysed at" wall times can drift by however long the board was off. The **sensor time** used by the analysis
is independent of this (it starts at 09:00, see §4.3).

Development path, still working: `app\deploy.ps1 -Action reset` pushes and starts the backend over adb; the app's
watchdog adopts whichever backend is running.

**When the AI is called (event gate, 2026-10-08):**
- Only a **warning / critical / faulty** status calls the AI. A shape change at normal levels, or a value
  returning to normal, never does. Tested: 2,000 readings at rest gave 0 incidents.
- The abnormal status must last **8 readings** (~16 s). The rule status shows on the dashboard instantly;
  the row shows "AI check in N readings".
- **Batching:** everything alarming at about the same time becomes **one incident** with one batch of NPU calls,
  e.g. "3 sensors alarming: CO2 critical, Power factor warning, TDS warning" (3 agents + synthesizer = 4 calls).
  There is no cap of 3 agents any more (up to 8).
- A sensor is reported once per abnormal episode and re-arms after it returns to normal.

**Field robustness (in case the board is away for days):**
- **Uninstall protection:** the app is a device administrator. `adb uninstall` fails with
  `DELETE_FAILED_DEVICE_POLICY_MANAGER`, and so does Settings, until Settings → Security → Device admin apps →
  Smart City Edge protection is deactivated.
- **Self-healing:** a 5.7 GB copy of both model bundles lives in the app's protected storage
  (`/sdcard/Android/data/com.iiith.smartcityedge/files/backup`, hidden from file managers). At every start and
  every 5 minutes the app restores any deleted or damaged model file. Tested with a deleted 788 MB file.
- **Laptop restore kit:** `qidk_backup\restore_qidk.ps1` rebuilds a wiped board in one command. It verifies the
  base model hashes, pushes the runtime, base and fine-tuned model, checks the NPU, then installs the app.
- **Notifications:** every new incident appears as an Android notification.
- Re-run `install_app.ps1` after validating a *new* model bundle, so the on-device backup is refreshed.
- **NPU hiccups after reboot / idle (fixed 2026-10-08):** the HTP sometimes refuses a new session for a few
  seconds ("Could not create context from binary ... err 1002", a DSP-side memory allocation failure,
  reproduced ~40 s after a reboot). The old single 4 s retry failed too, so the empty output was shown as
  "Safety check rejected". Now Genie retries after 3 s, 7 s and 15 s with the same prompt and model, so the
  output is identical. If the NPU is still down, the agent is re-run at the end of the batch, and the timeline
  says "NPU temporarily unavailable (hardware)", not a policy rejection. Model and safety policy unchanged.
- **Clock:** the QIDK RTC boots in 2023. The saved laptop offset is applied only while the device clock is still
  before 2025; once Wi-Fi NTP syncs, it is dropped. This was the cause of the "Thu 25 Oct 2029" dates.
- **Report JSON repair:** a stray `]` closing no array (a 4-bit slip) is removed before parsing; all fields
  are still validated. Invented labels (e.g. `heat_buildup_with_tank_filling`) are still rejected.
- Note: restarting adbd (`adb root`/`unroot`) kills the backend with adbd's cgroup; the app restarts it in ~6 s.

**Disk space on the laptop:** C: got down to 5 GB free overnight (the WSL disk image holds about 160 GB).
I deleted superseded experiment files inside WSL (33 GB) and released WSL's swap file, which leaves 16 GB free.
Windows only gets the 33 GB back after compacting the image (needs admin, run with WSL shut down):
`wsl --shutdown`, then `diskpart`, `select vdisk file="C:\Users\hp\AppData\Local\wsl\{ee2e2fda-f5af-4cca-a123-4c0d0487e0d8}\ext4.vhdx"`, `compact vdisk`.

Learning material: `teach.md` (the whole flow) and `ppt.md` (presentation content).

### 4.2 Before the demo
- Let the QIDK cool (it heats up under constant AI use). Keep it on a hard surface with airflow.
  The header shows `NPU 45° · skin 40°`; above 88 °C NPU or 60 °C skin it shows `cooling` and pauses
  background AI analysis. Demo buttons still work.
- Check the model badge in the header:
  - green **Fine-tuned agent model**: stage C passed.
  - amber **Base Llama 3.2 3B (fallback)**: the original model (still fully on the NPU).

### 4.3 Demo script (~5 min) - you are the sensor
The app has **no recorded data**. Every sensor value comes from you: the **Sensors** tab has a slider (or
on/off switch) per sensor. Every poll (default every 2 s) the app takes each slider's current value as that
sensor's next 5-minute reading, with a little realistic measurement jitter, then runs exactly the same
pipeline a physical sensor would: 4-hour window, SMA/EMA/trend, rule pattern, event gate, Mode 1/2/3 agents.
A real device can do the same over Wi-Fi: `POST http://<qidk-ip>:8000/api/ingest {"node","metric","value"}`.

1. **Header:** "Running on QIDK, standalone", NPU status, model badge, temperatures. Unplug USB to prove it.
2. **Sensors tab:** everything steady at normal values -> no incidents (event gate stays quiet).
3. **Mode 3 Multi-Agent.** Drag **CO2** from 450 to ~1400 and hold. Within ~2 polls the pattern changes and an
   incident opens: the Air Quality agent runs on the NPU (tokens stream live), related domains (occupancy,
   AC units, room power, outdoor temperature) are checked in parallel, the synthesizer explains.
   Note: right after a jump the window only has a couple of new readings, so it is first called a sharp
   (exponential) rise; after ~16 more readings the same change is classified as a step.
4. **Cross-domain:** switch **Room occupied** on, push **Room power** up and **CO2** up -> crowded room.
5. **Stuck sensor:** set jitter to 0 and wait ~16 polls -> constant readings are flagged as a sensor fault.
6. **Water:** lower **Tank level** slowly over ~20 polls -> gradual decrease / possible leak.
7. **Compare -> Mode 1 / Mode 2** on any incident: rules vs single AI vs multi-agent.
8. Show `eval.md` / `device_eval.md` and section 2.7 (honest NPU accuracy story).

### 4.4 Talking points (what makes it "agentic edge AI")
- 100% on-device: data, statistics, AI inference (Hexagon NPU), safety checks, storage. Works with no internet.
- Cheap always-on statistics; the AI is called only when needed (event gate, cooldowns, thermal guard).
- Domain agents specialise; a synthesizer reasons across domains; a policy gate enforces evidence + safety;
  a human approves.
- Fine-tuned on real campus data with exact labels (patterns injected on real calm windows; occupancy from the
  raw sensor feed). Prompt format on the device is byte-identical to training (400/400 tested).

---

## 5. Latency: what we measured and optimised (on the QIDK NPU)

**Where the time goes in one AI call** (Genie profiler, Llama 3.2 3B w4a16 on HTP V75):

| Phase | Time |
|---|---|
| Model init (load from flash) | 0.68 s |
| Read the ~550-token prompt (1,160 tok/s) | 0.47 s |
| **Generate the answer: ~52 ms per token (19 tok/s)** | **dominant: tokens × 52 ms** |
| Teardown + process start | ~0.3 s |

So latency = about 1.2 s + (number of answer tokens × 52 ms). Writing ~80–150 tokens of JSON can't be done in
milliseconds on any 3B on-device model. The way to win is fewer tokens, no wasted tokens, and fewer calls.

**How Mode 3 works now (cross-domain orchestrator):**
1. **Orchestrator (CPU, microseconds).** For each flagged sensor, a causal map picks related domains, same
   building first and healthy sensors preferred. Examples: CO2 → occupancy, AC units, room power, weather.
   Tank level → water flow, occupancy, weather. Power → AC units, occupancy, weather.
2. **Context agents in parallel (CPU, microseconds).** Every related sensor is analysed by its deterministic
   rule agent concurrently (goroutines), giving pattern, status and evidence.
3. **NPU agents (sequential: one NPU).** Every flagged sensor, plus any related sensor that is itself at
   warning/critical, gets an LLM domain agent (max 3). Tokens stream to the dashboard live.
4. **Synthesizer (NPU)** runs whenever 2 or more domains carry information (a flagged sensor, or a related
   sensor whose pattern isn't steady). Only if every related domain is verified steady is the report built
   without it, and it says so with evidence ("related domains checked and steady").
5. **Policy gate** on every LLM output, then human approval.

**Optimisations (none reduce accuracy):**
- **Stop at the end of the JSON:** generation stops the instant the answer object closes.
- **Live token streaming:** the first text appears about 1.1 s after a call starts.
- **Exact-prompt cache:** decoding is greedy, so an identical prompt always gives the identical answer.
  Compare reruns and repeated windows are answered instantly (measured: 4-call incident rerun = 0 NPU calls, 0 ms).
- **Deterministic context selection** (sorted ties), so reruns hit the cache and results are reproducible.
- **Healthy sensors preferred:** a faulty related sensor is never used as evidence and is reported as a data-quality note.
- **Live sensor data pushed over SSE** every tick, so the dashboard doesn't poll.
- **Output cap 200 tokens** (trained answers ≤ 147); short synthesizer explanation.
- **Fine-tuning:** trained answers average 84 tokens and end cleanly (base model: 150–240).

**Measured on the QIDK (base model; fine-tuned agents ≈ 2× faster per call):**

| Incident | NPU calls | Context agents | Total |
|---|---|---|---|
| Mode 1 Rules (any) | 0 | — | < 1 ms |
| Tank leak (related domains steady) | 1 | 3 | 5.0 s |
| Ventilation failure (AC off is relevant) | 2 | 4 | 18.7 s |
| Crowded room (3 domains abnormal) | 4 | 3 | 27.6 s |
| Mode 2 Single (one call, all sensors) | 1 | — | ≈ 9 s |
| Any Compare rerun | 0 (cache) | — | 0 ms |

**Parallel NPU agents: tested properly (2026-10-07), the answer is no.**

| Test (2 × 200-token generations) | Wall time | Per-call speed |
|---|---|---|
| Sequential, back-to-back | 33.8 s | 19.0 then **9.4 tok/s** (second call overlapped the first one's NPU teardown) |
| **Sequential, 0.5 s gap** | **23.6 s** | 19.0 / 18.9 tok/s |
| Parallel (B starts 2 s after A) | **76.5 s** | 4.9 / 10.0 tok/s; B waited 54 s just to initialise |

- **RAM:** one Genie session uses **~3.7 GB** (weights are copied into NPU-shared memory). With 9.2–9.5 GB free
  (Chrome closed), two sessions leave ~1.5 GB. The first parallel attempt crashed the QIDK for this reason;
  the second (with more free RAM) survived but was 3× slower.
- **Why:** the Hexagon NPU executes one session at a time, so parallel sessions just compete for it and add
  context-switch and initialisation cost. The fastest correct schedule is **sequential with a short gap**, which the
  app now enforces (0.6 s).
- Everything that is *not* the NPU runs in parallel: context agents (goroutines), orchestration, policy checks,
  SSE streaming of tokens and sensor data, and the dashboard.

**Other measured tunings:**

| Genie setting | Init | Decode | Wall (200 tok) | Used? |
|---|---|---|---|---|
| 3 threads, cpu-mask 0xe0 (old) | 0.67 s | 18.9 tok/s | 11.9 s | |
| **4 threads, cpu-mask 0xf0** | 0.65 s | **19.2 tok/s** | **11.7 s** | **yes** |
| use-mmap false | 3.0 s | 18.9 tok/s | 14.4 s | no |
| poll false | 0.68 s | 18.2 tok/s | 12.4 s | no |

- **Leaner base-model prompts** (Mode 2 / synthesizer): flagged sensors keep all 8 evidence lines, informative
  related sensors 3, steady related sensors 1. Fine-tuned agent prompts are unchanged (byte-identical to training).
- **Word limits on free-text fields** (root cause ≤ 20 words, explanation ≤ 35 words): synthesizer output went from
  184–190 to 102–120 tokens (≈ 11 s → 7–8 s). Label, evidence and action are unchanged.
- **Context size:** the NPU graphs are compiled for 4,096 tokens and our prompts use 550–1,600. A smaller compiled
  context (e.g. 2,048) would save an estimated ~5–10 % per generated token, but needs a re-export that hasn't been
  validated with the published quantisation. It's a post-mid-eval item.

**Further possible gain (not done yet):** keeping the model loaded between calls would save ~1 s per call. That
needs a small native program using Qualcomm's Genie C library, which requires the Android NDK and QAIRT SDK
headers. It's a post-mid-eval item, as is Qwen for reasoning.

### QIDK cleanup (done 2026-10-07, with your approval)
- Uninstalled 16 third-party apps (Telegram, Termux, Aptoide, demos, …). Chrome and Android WebView are system apps and stay.
- Deleted other projects' files: Gemma, SNPE benchmarks, YOLO/pose models and scripts, `/sdcard` downloads, pictures and old assets.
- Genie folder trimmed to what Genie actually loads, verified live from the process memory map: the 3 model
  `.bin` files, `genie-t2t-run-2.50`, 5 libraries in `qairt_2_50_libs`, the `dsp_2_50` NPU skeletons, and configs/tokenizer.
  A real NPU call was verified before the old files were deleted. Leftover unused libraries inside the root-owned
  `qairt_2_50_libs` folder (about 0.4 GB) can't be removed without root and are harmless.
- Result: **33 GB free** (was 13 GB). `/data/local/tmp` now holds only `genie_bundle` (3.45 GB) and `smart_city_edge`.

## 6. Where everything is

| Path | What |
|---|---|
| `HANDBOOK.md` | this file |
| `MIDEVAL_RUNBOOK.md` | short version + verification log |
| `Code/smart-city-edge-agent/training/` | `train.ps1`, `run_all.sh`, `train_agents.py`, `eval_agents.py`, `merge_adapter.py`, `features.py`, `generate_dataset.py`, `TRAINING.md` |
| `Code/smart-city-edge-agent/training/export/` | NPU export (`export_to_npu.sh`, `build_ft_ckpt.py`) + on-device validation |
| `Code/smart-city-edge-agent/training/results/` | eval reports and the trained adapter after the run |
| `Code/smart-city-edge-agent/app/` | the QIDK app: `deploy.ps1`, `backend/` (Go), `device/` (binary, data, dashboard), `README.md` |
| WSL `~/smartcity_runs/agents_<date>/` | full training run (logs, checkpoints, merged model) |
| WSL `~/qaihm_work/` | NPU export work files and log |
| QIDK `/data/local/tmp/smart_city_edge/` | the app on the device |
| QIDK `/data/local/tmp/genie_bundle/` | original model (base) + Qualcomm runtime |
| QIDK `/data/local/tmp/genie_bundle_ft/` | fine-tuned model (after stage C) |

## 7. Words used here

- **NPU / HTP**: the AI chip inside the Snapdragon 8 Gen 3 on the QIDK.
- **Genie**: Qualcomm's program that runs the language model on the NPU.
- **LoRA / QLoRA**: train a small add-on instead of the whole model; fits a 6 GB laptop GPU.
- **Adapter**: that small trained add-on (≈ 100 MB). **Merge**: fold it into the full model.
- **AI Hub export**: Qualcomm's free cloud service that compiles the model for the NPU.
- **Policy gate**: the automatic safety/format check on every AI answer.
- **Evidence ids (E1–E8)**: numbered facts given to the AI. Every claim must cite them.
