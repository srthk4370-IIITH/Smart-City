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

## 2.8 Latency work, 2026-10-13 (model frozen)

All measurements below are from Genie's own profiler on the live fine-tuned bundle. The fine-tuned
weights were not modified.

**Where one agent call actually goes** (800-token prompt, 109 generated tokens):

| stage | time | share |
|---|---|---|
| `GenieDialog_create` (init) | 0.635 s | 11 % |
| prefill (1481 tok/s) | 0.541 s | 9 % |
| **decode (23.1 tok/s)** | **4.678 s** | **78 %** |
| `GenieDialog_free` | 0.089 s | 1 % |

**Measurement trap - do not use wall clock on the device.** `date +%s%N` arithmetic in the Android
shell reported 1.67 s for a run that Genie's profiler *and* the shell `time` builtin both measured at
5.97 s. An early conclusion that the Go app added ~4.2 s of overhead per call came from that faulty
timer and was wrong: the app's own number (5.907 s) matches the profiler (5.945 s) almost exactly.
`app/tools/bench_device.sh` now reads Genie's profiler only.

**`poll` setting: keep `true`.** A third-party project measured `poll:false` giving +55 % decode at
context depth 4096. It does not reproduce here. A/B/A on this board, same prompt, 3 runs each:

| config | decode rate | temp |
|---|---|---|
| poll=true | 22.9 / 22.4 / 22.6 tok/s | 46 C |
| poll=false | 21.0 / 21.0 / 20.8 tok/s | 54 C |
| poll=true (control) | 22.6 / 22.4 / 23.0 tok/s | 57 C |

`poll=false` is 7-8 % slower, and the control run was hotter than the test, so the direction is real.

**Action is now derived, not generated (+3.7 points).** `action` was the weakest metric at 0.778 while
`likely_cause` was 0.815 - the model sometimes picked the wrong action from a correct cause. Because
the gold targets were generated by `action_of(cause, status)` (`generate_dataset.py:360`, mirrored by
`ActionOf` in `rules.go:283`), `policy.go` now always derives it. Measured on the same 54 windows:

| metric | generated | derived |
|---|---|---|
| action | 0.778 | **0.815** |

Per-sample check: 2 cases corrected, **0 cases made worse**. Everything else reproduced exactly
(pattern 0.852, status 0.870, cause 0.815, JSON/evidence/policy 1.000), confirming the run is stable.
The model still emits the field; we ignore it and log disagreements as a drift signal.
Per-sample rows are kept in `training/results/device_eval_samples.jsonl`.


## 2.9 Export pipeline: checkpoint identity and host capacity (2026-10-13/14)

Two failures cost most of a night. Both are avoidable and both are now guarded.

**A. The checkpoint must be w4a16, and the w4 one looks identical from the outside.**
Three checkpoints existed; only one produced the deployed bundle:

| dir | precision | role |
|---|---|---|
| `ftgptq_ckpt` | **w4** | dead end - compiles fine but **does not load on 8 Gen 3** (err 1002) |
| `ftgptq16_ckpt` | **w4a16** | produced the LIVE bundle; had been deleted in a disk cleanup |
| `ftcal_ckpt` | w4a16 | same weights, Kaggle-recalibrated activations; never adopted |

An export was launched against `ftgptq_ckpt` by mistake. The only visible symptom was the AI Hub
download path containing `-genie-w4-` instead of `-genie-w4a16-`. **Always check `args.json` and the
output directory name before trusting an export.**

**Reconstructing the deleted w4a16 checkpoint.** `merge_calibrated.py` had built `ftcal_ckpt` from
`ftgptq16_ckpt` by replacing *only* `activation_encodings` and hard-linking `model.data`. The inverse
therefore rebuilds the original exactly - GPTQ param encodings (untouched) plus the published
activation encodings from the qaihm cache. `restore_published_acts.py` does this; `model.data` is
hard-linked so no weight can change. Result: all **11,711** activation encodings matched by name,
scale ratio median 1.016, inode preserved. Identity must still be proven by `compare_bundles.py`.

**B. The export fills the disk and then WSL dies.**
The export writes multi-GB upload zips and downloads compiled parts into the WSL ext4 image, which
grows on C:. C: reached **0 bytes**, and WSL then failed to start at all:
`Wsl/Service/CreateInstance/E_UNEXPECTED`. This looks like a WSL fault and is not one.

Recovery and prevention:
- `wsl --shutdown` is required after freeing space; WSL does not recover on its own.
- `disk_guard.sh` now aborts the export below a free-space floor on C:.
- WSL 2.6.3 has **disabled sparse VHD** ("potential data corruption"); `--set-sparse true` is refused
  without `--allow-unsafe`, which is not worth the risk. Use `diskpart compact vdisk` instead:
  **171.1 GB -> 41.0 GB, returning 109 GB**, with the guest filesystem untouched.
- w4a16 needs far more memory than w4 (QuantSim over 11,711 activation quantizers). With 8 GB RAM +
  8 GB swap it stalled with no progress and ~6 GB of swap consumed. 32 GB swap is the working figure.
- `ftgptq16_ckpt` is now also copied outside the VHDX to `qidk_backup\ckpt_ftgptq16` (verified
  byte-exact), because after the cleanup it is the only copy of the GPTQ-quantised fine-tuned weights.

**C. Benchmarking note.** Do not use `date +%s%N` arithmetic in the Android shell: it reported 1.67 s
for a run that Genie's profiler and the `time` builtin both measured at 5.97 s. Use `--profile`.


## 2.10 Overnight latency work, 2026-10-14

**`allow-async-init: true` - adopted, ~65 ms/call.** QAIRT 2.45 added parallel initialisation of the
HTP context binaries and the tokenizer; our exported config shipped with it off. A/B/A with Genie's
profiler, same prompt (548 prompt tokens, 59 generated):

| config | init (mean of 3) | decode rate |
|---|---|---|
| false @49 C | 703 ms | 23.11 tok/s |
| false @48 C (control) | 711 ms | 22.78 tok/s |
| **true @68 C** | **640 ms** | 22.45 tok/s |

The decode spread is thermal noise (the `true` run was 20 C hotter and still within the `false`
range); the init saving is consistent across every run. Init-only, so no accuracy risk. Roughly
0.33 s off a 5-call incident. Previous config kept at `smartcity_agent.json.bak` on the device.

**Gotcha: self-heal silently reverts device config edits.** `EdgeService.healScript` compares the
size of `smartcity_agent.json` (and the three .bin files and tokenizer.json) against the on-device
backup and restores the *whole bundle* if any differ. Editing only
`/data/local/tmp/genie_bundle_ft/smartcity_agent.json` therefore lasts until the next heal tick
(~5 min) and then disappears - which is exactly what happened to the first async-init change. Any
config change must be written to **both**:

    /data/local/tmp/genie_bundle_ft/smartcity_agent.json
    /sdcard/Android/data/com.iiith.smartcityedge/files/backup/genie_bundle_ft/smartcity_agent.json

and the two must end up the same size, or the heal will keep fighting it.

**Trimming the `action` field - rejected.** Since policy.go derives `action`, the tokens spent
generating it are waste, so generation was stopped before that key. Measured saving was only
**~2.5 tokens (~0.17 s)** per call, and the streaming implementation was defective: when
`, "action"` straddles a stdout read boundary the already-written comma cannot be retracted and the
output ends `... "confidence": 0.85, "action}` - invalid JSON. Removed from the generation path.
`trimscan.go` and its tests are kept, unwired, with the defect documented; a correct version needs an
accumulator supporting retroactive truncation rather than a `strings.Builder`.

**Benchmark harness caveat.** `app/tools/bench_device.sh` drives Genie's own `--profile`; the busy-poll
A/B harness was abandoned because each adb round-trip made one measurement take ~25 minutes.


## 2.11 Graphs per context binary: the ceiling I first measured (SUPERSEDED - see 2.12)

> **This section's conclusion was wrong.** The 6-graph bundle failed because our config was
> missing `enable-graph-switching: true`, not because the SoC cannot hold the graphs. Qualcomm
> ships a working 8-graph config for this exact model. Read 2.12 instead; the measurements below
> are kept because they are what the failure looks like before you know the cause.

The multi-context-length re-export (`--context-lengths 1024,2048,4096`, default
`--sequence-lengths 128,1`) built correctly - w4a16, rope-scaling 32.0, parts slightly larger than
live as expected - and then **would not load**:

```
[INFO]  "Using create From Binary List Async"
[ERROR] "Could not create context from binary List Async for context, err 5005"     <- async path
[ERROR] "Could not create context from binary for context index = 2 : err 1002"     <- sync path
```

Reproduced 3/3 with **9.45 GB host RAM free and nothing else on the NPU**, so it is not the known
transient post-boot 1002 and not host memory. err 1002 is `QNN_COMMON_ERROR_MEM_ALLOC` - DSP/VTCM
side. Each graph carries its own IO and KV buffers, and 3 context lengths x 2 sequence lengths =
**6 graphs per part** exceeds what this SoC will allocate. The live bundle has **2** and is fine.

Community guidance says keep graphs-per-part <= 8 (decode collapses ~30x at 10). **On 8 Gen 3 the
practical ceiling is far lower - somewhere between 3 and 5.** Plan exports accordingly:

| seq x ctx | graphs/part | status |
|---|---|---|
| [128,1] x [4096] | 2 | live, works |
| [128,64,1] x [4096] | 3 | chosen for the LADE attempt |
| [128,1] x [2048,4096] | 4 | untested |
| [128,1] x [1024,2048,4096] | 6 | **fails, err 1002** |

Also note `allow-async-init: true` is safe on the 2-graph live bundle (and saves ~65 ms) but took the
6-graph bundle down the async path to err 5005. If a future bundle fails to load, test with async
init off before concluding the bundle is bad.


## 2.12 Why multi-graph bundles really fail: CDSP SMMU, not graph count (2026-10-14)

§2.11 recorded the symptom. This is the cause, read out of the kernel driver log.

Run the failing bundle, then `adb logcat -d`. Genie only prints `err 1002`; `adsprpc` prints what
actually happened:

```
fastrpc_mmap failed to map buffer fd 76, addr 0x6d48bae000, length 0x6ffd980,
    domain 3, flags 0x3, ioctl ret 0xffffffff, errno Bad address
fastrpc_mmap_create: dma_buf_map_attachment for fd 76 failed for len 0x6ffd980
    on device soc:qcom,msm_fastrpc:qcom,msm_fastrpc_compute_cb2 ret -22
fastrpc_internal_mem_map: failed to map fd 76, len 0x6ffd980, flags 3, map 0, err -14
```

`0x6ffd980` = 112 MB. The CDSP SMMU context bank (`compute_cb2`) refuses the mapping with
`-22 EINVAL`, Genie turns that into `QNN_COMMON_ERROR_MEM_ALLOC` = **err 1002**. So this is DSP
*address-space* exhaustion for the fastrpc session, not host RAM and not a graph-count rule.

The margin is thin, which is why it looks like a graph-count cliff: live `part3` is 1,122,754,560
bytes and loads; the 3-graph `part3` is 1,129,140,224 bytes - **6.4 MB more** - and does not.

### Runtime knobs do not fix it (all measured on the 3-graph bundle, all still err 1002)

| config change | result |
|---|---|
| `spill-fill-bufsize: 0 -> 1200000000` | fails |
| `mmap-budget: 0 -> 2048` | fails |
| `use-mmap: true -> false` | fails |
| `context.size: 4096 -> 2048` | fails |
| `allow-async-init: false` (to unmask err 5005) | fails, with the real 1002 |

Every one printed the identical `Allocated total size = 270369280 across 5 buffers`, i.e. none of
those knobs changed what gets mapped.

### THE FIX: `enable-graph-switching: true`

One knob does fix it, and it was missing from our config entirely:

```json
"QnnHtp": { ... "enable-graph-switching": true }
```

With it, the 3-graph bundle (`--sequence-lengths 128,64,1 --context-lengths 4096`) loads and
generates on the first try. Without it, Genie instantiates every graph in the context binary
eagerly at load, and the third one's 112 MB mapping is what the SMMU refuses.

It was found by reading Qualcomm's own config for *our* model,
`examples/Genie/configs/llama3-3b/llama3-3b-htp-long-context.json` in the QAIRT SDK:

```
"ctx-bins": [ "weight_sharing_model_ar32_ar128_cl2048_cl4096_cl6144_cl8192_1_of_4.serialized.bin", ... ]
"QnnHtp": { "enable-graph-switching": true, "allow-async-init": true, "poll": false, ... }
```

That is 2 sequence lengths x 4 context lengths = **8 graphs per part**, shipped as a working
reference. So the community's "<= 8 graphs" guidance was right all along; **§2.11's "the real
ceiling is ~3" was wrong**, and so was the conclusion above that only an export-side change could
help. The ceiling was our own missing flag.

Keep the unpacked SDK at `~/qairt/qairt/2.50.0.260828` (WSL): `examples/Genie/configs/` and
`docs/QAIRT-Docs/Genie/` answered in minutes what days of black-box testing did not.

### Why more splits is not the answer either

Smaller parts would also map, but `NUM_SPLITS = 3` is not a parameter:
`llama_v3_2_3b_instruct/model.py` hardcodes `Llama3_2_3B_Part1_Of_3 / Part2_Of_3 / Part3_Of_3`, and
the published activation encodings we reuse are keyed to those split names. A 4-way split would
change the model. Rejected.

### Multi-graph loads, but it is not free

With graph switching on, the 3-graph bundle is byte-identical to live (12/12 prompts via
`compare_bundles.py`) and **slower**, because switching graphs costs time on every call:

| | init | ttft | decode | total |
|---|---|---|---|---|
| live, 2 graphs | 695 ms | 397 ms | 2646 ms | 3738 ms |
| 3 graphs, basic | 845 ms | 597 ms | 2849 ms | 4291 ms |

So only add graphs when the extra graph buys more than ~550 ms.

### Debugging recipe for any future `err 1002`

1. Set `allow-async-init: false` so you see 1002 and not 5005.
2. Check `enable-graph-switching` is `true` if the bundle has more than 2 graphs per part.
3. `adb logcat -c`, run the load, `adb logcat -d | grep -E "fastrpc|dma_buf|mem_map"`.
4. `dma_buf_map_attachment ... ret -22` means SMMU address space, i.e. too much mapped at once -
   which is what eager graph instantiation causes.

## 2.13 Where the 3.8 s actually goes, and two dead ends (2026-10-14)

Profiler numbers on the live bundle, 548-token prompt, 59 generated tokens, 3 runs:

| phase | time | share |
|---|---|---|
| model init | 687 / 700 / 697 ms | 18% |
| prefill (ttft) | 395 / 401 / 395 ms | 11% |
| decode | 2613 / 2664 / 2662 ms | **70%** |
| total | ~3.76 s | |

Prefill is already fast (548 tokens in ~397 ms ≈ 1380 tok/s). **Decode at ~22 tok/s is the target** -
anything that does not cut the number of forward passes cannot move the needle much.

### Dead end 1: DSP RPC knobs do not touch decode

`htp_backend_ext_config.json`, live bundle, 2 runs each:

| setting | decode |
|---|---|
| `rpc_control_latency: 100` (live) | 2613-2664 ms |
| `rpc_control_latency: 0` | 2641 / 2645 ms |
| `rpc_control_latency: 0` + `rpc_polling_time: 9999` | 2680 / 2682 ms |

All inside noise, polling slightly worse. Decode is NPU-bound, not RPC-bound. Do not retry this.

### Dead end 2: you cannot pre-warm `genie-t2t-run`

The backend spawns one `genie-t2t-run` per request (`genie.go`, `exec.CommandContext` + `cmd.Wait`),
so the 695 ms init is paid on **every** call. The obvious trick is to start the process early and
feed it the prompt late, so init overlaps request assembly.

It does not work: **Genie reads the whole prompt before it touches the DSP.** Measured by marking
logcat around a stdin-fed run (`--prompt_file /proc/self/fd/0`, producer stalled 6 s):

```
09:06:37.447 SCEMARK : A spawn
09:06:43.493 SCEMARK : B writing prompt
09:06:43.555 dsp-manager: openSession: device fd 7 opened for domain 3   <- 62 ms AFTER the prompt
```

Six seconds of doing nothing, then init. (`mkfifo` in `/data/local/tmp` is refused by SELinux, hence
stdin.) So the prompt must exist before the process starts - pre-warming is impossible.

### Not a dead end: `genie-app` can batch, and that is worth ~630 ms per extra agent

The QAIRT 2.50 SDK (unpacked at `~/qairt/qairt/2.50.0.260828` in WSL) ships
`bin/aarch64-android/genie-app`, the same Genie API driven by a script of commands. One invocation
creates the dialog once and then runs many queries, so init is paid once for the whole script:

```
dialog config create CFG smartcity_agent.json
dialog create D CFG
dialog reset D
dialog query D <prompt file>     <- repeat per prompt
exit
```

N queries in one process, bracketed with logcat marks:

| N | total | |
|---|---|---|
| 1 | 3.920 s | |
| 2 | 7.022 s | |
| 3 | 10.120 s | |
| 5 | 16.537 s | steady state (16.537-3.920)/4 = **3.15 s per query** vs 3.74 s per CLI call |

Output is unchanged: three consecutive queries all hashed to `b35b74c0123cc1ce28a118db70c2bf2f`,
the same answer the CLI gives. `dialog reset D` clears the KV cache between queries, and decoding
is greedy, so each query sees exactly what a fresh process would.

It is a **batch**, not a daemon. `genie-app` reads its whole script to EOF before executing
anything - a producer that wrote two commands, slept 10 s and closed gave:

```
09:26:27.371 SCEMARK : STREAM start
09:26:37.441 SCEMARK : STREAM eof-now
09:26:37.475 dsp-manager: openSession: device fd 7 opened for domain 3   <- 34 ms after EOF
```

Plain piped stdin with no `--script` produces no output at all; only `--script /dev/stdin` is read,
and still only at EOF. So all prompts must be known up front - true of one Mode-3 incident's
agents, false of request-by-request serving.

## 2.14 LADE (lookahead decoding): REJECTED - it changes the answers (2026-10-14)

Genie 1.20 does support LADE (`lade`, `ngram`, `gcap`, `ALWAYS_FWD_ONE` are all in `libGenie.so`,
and there is a tutorial plus `examples/Genie/configs/llama2-7b/llama2-7b-htp-lade.json`). It needs
a token graph with AR-N >= `(window + gcap) * (ngram - 1)`, which is why the 3-graph bundle was
exported with `--sequence-lengths 128,64,1`.

**It is fast. It is also wrong. Do not ship it.**

> **2026-10-14, later: re-tested properly and CONFIRMED DEAD. See the end of this section for the
> isolated A/B over all three `update-mode` values - the verdict is unchanged and now unambiguous.**

### It is fast

Alternating A/B, 3 rounds each, same prompt, identical output every round:

| | init | ttft | decode | total |
|---|---|---|---|---|
| live, no LADE | 807 ms | 414 ms | 2703 ms | 3947 ms |
| LADE, `window=gcap=8 ngram=5`, `allow-async-init: true` | 713 ms | 584 ms | 2061 ms | **3380 ms** |

Decode -24%, end to end **-14%**. Parameter sweep: `8/5` was the best of `8/5`, `4/9`, `16/3`,
`8/3`; `allow-async-init: true` on top was worth another ~200 ms.

### It is wrong

`compare_bundles.py` over 24 role/pattern prompts: **the answers diverge, and they degrade.**

```
A (live): "pattern": "spike"        B (LADE): "pattern": "sp.peak"
A:        "pattern": "oscillation"  B:        "pattern": "osc strings"
A:        "pattern": "exponential_increase"   B: "pattern": "ex._increase"
A:        "pattern": "occupied"     B:        "pattern": "occupied agent"
A:        "pattern": "flatline", "status": "sensor_fault"
B:        "pattern": "flat78",   "status": "normal"
```

The last one is the disqualifier: a stuck sensor reported as normal. Another swapped `PM10` for
`PM2.5` - a metric that was never in the prompt.

Turning the speculation down does not help. At the minimum useful setting (`window=gcap=4,
ngram=3`) it was still only **4/13 identical** and was *slower* than no LADE at all (18.2 vs
19.7 tok/s).

### What this means

The premise written in `make_lade_config.py` - "speculative decoding verifies every drafted token
against the full model, so output is identical by construction" - **does not hold for this
implementation on this model**. Genie's lookahead branch is accepting n-gram guesses that the
model did not produce. Treat Genie's speculative modes (`lade`, and by extension `ssd-q1`, `spd`,
`eaglet`) as approximate until proven otherwise on a wide prompt set.

### The process lesson

The first LADE measurement used **one prompt, repeated**. All three runs hashed identically
(`b35b74c0...`) and it looked like a clean 14% win. The corruption only appeared on a set with
**different** prompts. One prompt proves nothing: it is the same prompt's own n-grams being
speculated, which is the easiest possible case. Always gate on `compare_bundles.py` across roles
and patterns before believing a decode-side optimisation.

`app/backend/genieapp.go` implements this as `runBatch` + `Prefetch`, wired into Mode 3 behind
**`SCE_GENIE_BATCH=1` (default OFF)**. `Prefetch` answers all of an incident's agent prompts in one
process and parks the results in the existing prompt cache, so `runAgent` is unchanged - each
agent's `genie.Run` simply finds its answer already there. A failed batch caches nothing and every
agent falls back to the normal per-call path, retries included.

Measured through the Go code on device, 3 agent prompts:

```
3 prompts: per-call 16.41s, batched 13.748s, saved 2.662s (1331 ms per extra prompt)
```

1331 ms, not 630 ms, because the batch also skips the 600 ms inter-call gap `Run` enforces.

Correctness is gated twice, which is what 2.14 taught:
- `training/export/verify_batch.py` - 16/16 byte-identical across all five roles, including every
  prompt LADE corrupted
- `app/backend/genieapp_test.go` - runs on the board (`go test -c` for arm64, push, run) and checks
  the Go stdout parser itself: N answers, in order, each valid JSON, streamed text == returned text

That second test earned its keep immediately: the first parser used `idx++` to advance to the next
answer, which from `-1` is always `0`, so all three answers landed in slot 0 and the other two came
back empty. `verify_batch.py` could never have caught it - it tests `genie-app`, not our parser.

**Why it was off by default at first:** in every Mode-3 incident I could produce that morning the
orchestrator ran exactly **one** NPU agent (`"npu_calls":1`), so the batch never engaged. **That
was my testing error, not a product fault - see 2.16.** Batching is now ON by default.

### LADE re-tested properly: all three update modes, isolated. Still dead. (2026-10-14, later)

The first LADE test compared the **live 2-graph bundle in basic mode** against the **3-graph bundle
in lade mode**, so it changed two things at once and could not prove which caused the corruption.
It also only ever tried `update-mode: ALWAYS_FWD_ONE`. Re-run properly: one bundle
(`/data/local/tmp/genie_lade`), one set of binaries, **only the config differs**.

Single-prompt profiler numbers (and note these exceed the ~26.8 tok/s bandwidth ceiling of 2.15,
which is exactly what speculation is supposed to do - several tokens per weight sweep):

| config | decode | rate |
|---|---|---|
| `basic` | 2730 / 2737 ms | 21.2 tok/s |
| `ALWAYS_FWD_ONE` | 1881 / 1897 ms | 30.7 tok/s |
| `FWD_MAX_HIT` | 1933 / 1934 ms | 30.0 tok/s |
| `FWD_LEVEL` | 1828 / 1864 ms | **31.4 tok/s** |

On one easy prompt all four produced **byte-identical** output. That is the trap. Across 14
role/pattern prompts (`compare_bundles.py`, now able to compare two configs in one bundle via
`--cfg-a` / `--cfg-b`), the fastest mode scores:

```
identical outputs: 1/14
A basic      decode 3778 ms  20.5 tok/s
B FWD_LEVEL  decode 3028 ms  25.1 tok/s   (-20%)
```

and the failures are semantic, not cosmetic:

```
A "flatline",  "sensor_fault"  "Humidity stuck at 78.7 % (21 samples), typical of a stuck sensor"
B "flat78",    "normal"        "Humidity flat at 78.5 % with no meaningful trend"

A "PM10 oscillates between 9.6 and 94.4"   B "PM2.5 oscillates ..."      <- metric not in the prompt
A "throttling"                              B "th at max 19 pts"
A "spike" / "oscillation" / "occupied"      B "sp.peak" / "osc strings" / "occupied agent"
```

**`FWD_LEVEL` is exactly as broken as `ALWAYS_FWD_ONE`, so no update mode fixes it.** Genie's
lookahead is not verifying drafted tokens against the full model; the algorithm is lossless by
construction in the literature and in Qualcomm's own ExecuTorch implementation, so this is a defect
in Genie's implementation, not in the method. The revision history supports that reading: LADE was
added in 2.28 and has had exactly one fix since, while SSD/SPD/Eaglet got ~10 between 2.32 and 2.50.

20% faster decode, 1 in 14 answers correct, and one of the failures reports a stuck sensor as
normal. **Closed for good. Do not re-open without a different mechanism** (SSD-Q1 is the one mode
Qualcomm explicitly claims is output-identical, and it needs a forecast-prefix binary we do not have).

## 2.15 Decode is at the memory-bandwidth roof: the number that reorders everything (2026-10-14)

Read the context-binary metadata rather than guessing at the weight size:

| Part | Size | Content |
|---|---|---|
| `part_1_of_3.bin` | 788 MB | **embedding table only** - a `Gather`. Per decode token it reads **one row** (3072 x 2 B = 6 KB), not 788 MB |
| `part_2_of_3.bin` | 901 MB | transformer layers |
| `part_3_of_3.bin` | 1301 MB | transformer layers + `lm_head` |

`graphBlobInfoV2` reports `sharedWeightsSize` identical for the ar128 and ar1 graphs, so weight
sharing is active and decode does not hold a second copy.

**So ~2.20 GB must stream from DDR per decode token.** At our measured 22.4 tok/s that is
**49.3 GB/s of real read bandwidth.** Published measurements for this SoC: **59 GB/s** for the NPU
DMA path (DDR->VTCM) on a V75 device, and **68 GB/s** practical whole-device peak on 8 Gen 3.

> **We are at ~84% of the measured NPU DMA ceiling.** The entire addressable decode budget from
> configuration is about **440 ms**, not 2 s. No JSON knob gets below ~2.2 s of decode while
> 2.20 GB/token has to cross the bus.

Cross-checks: Qualcomm's own AI Hub card for this model reports 28.2 tok/s - on **8 Elite Gen 5**,
newer silicon with faster memory. Research work reaches 29.9 tok/s for Llama-3B on 8 Gen 3 only by
driving GPU **and** NPU concurrently to exceed one engine's bandwidth share.

**Consequences, all verified on device:**
- `perf_profile` is already `burst`, `weight_sharing_enabled` already true, `allow-async-init`
  already true. There is no sleeping clock to wake up. This is also why the RPC knobs (2.13) were
  flat: they are already at their burst defaults.
- `llm_decode_*` perf profiles - the tier Qualcomm built *for exactly this bottleneck*, including
  DDR Perf Mode - are **V79 and newer, rejected at runtime on V75**. A real generational gap.
- `vtcm_mb`, `O`, `hvx_threads`, `dlbc`, `weights_packing` are **graph-finalize-time** options baked
  into the context binary. Setting them in a runtime config does nothing. VTCM is ~8 MB against
  2.20 GB of weights, so weight residency is arithmetically impossible - it is a DMA staging buffer.
- The largest byte reduction available is `lm_head`: 128256 x 3072 at 16-bit = 788 MB, **~36% of
  per-token traffic**. Quantising it would cut decode 20-25%, but it needs a re-export, so it is
  out of scope while the model is frozen.

**The lesson: stop tuning decode. Attack init (18%) and token count.**

## 2.16 Grammar-constrained decoding: tested, REJECTED (2026-10-14)

Genie ships xgrammar, and it is compiled into the **live** `libGenie.so` on the device - confirmed
by `strings`: `(supported: "json-schema", "regex", "ebnf")`, `(supported: "xgrammar")`. The config
block is `dialog.context.grammar` with keys `type`, `backend`, `file`. The hope was jump-forward
decoding: deterministic schema tokens emitted with **no NPU forward pass**, which would be the only
lever that beats the bandwidth roof without touching the weights.

Built a JSON-schema for the air-quality agent (pattern/status/observations/likely_cause/confidence/
action with the real enums), dropped the `{"pattern": "` prefill so the grammar could drive from
`{`, and measured with Genie's own profiler:

| arm | init | ttft | gen_tok | decode | rate |
|---|---|---|---|---|---|
| baseline | 695 / 731 ms | 396 / 398 ms | 59 | 2574 / 2652 ms | 22.5 / 21.9 tok/s |
| grammar | **1130 / 1196 ms** | 395 / 391 ms | **62** | **2750 / 2781 ms** | 22.2 / 21.9 tok/s |

**Net loss: +440 ms of init to compile the schema, and no tokens saved.**

**Root cause, from the library's own strings:** every jump-forward message references a draft
engine - `[JumpForward] draft engine prefill failed`, `[JumpForward] target engine reports zero
embedding buffer size`, `prefillPostJumpForwardReseed`. **JF lives in the `eaglet`/`spd` speculative
paths, which need a trained draft head.** With `dialog.type: basic` the grammar only masks logits:
it constrains what may be sampled, it does not skip forward passes. Also note
`Grammar-constrained decoding is not supported for batched queries (size > 1)`, which would collide
with 2.14's batching anyway.

Worth keeping in mind for a different reason: grammar would *guarantee* schema-valid output. That
is a robustness argument, not a latency one, and it costs 440 ms/call.

## 2.17 Four scenarios were un-injectable, and that is why Mode 3 looked single-agent (2026-10-14)

`POST /api/inject {"scenario":"crowded_room"}` returned:

```
scenario target SR-AQ-KH95-00 co2 is not a live sensor
```

`crowded_room` targets CO2 node `SR-AQ-KH95-00`, which does not exist in this topology (the live AQ
node is `SR-AQ-KH03-03`), and the target carried **no `Alt` list** - and `Engine.PickTargets` only
remaps through `Alt`. Same dead-node fault in `pm_spike` (`AQ-VN90-00`), `stuck_sensor`
(`SR-AQ-KH00-02`) and `off_hours_presence` (`SR-OC-GW-KH95-22`). **4 of 10 scenarios could not fire.**

Fixed by giving each a live fallback in `Alt`; the original node is still preferred where it exists,
so no topology that worked before changes behaviour.

**With that fixed, Mode 3 fans out exactly as designed.** `crowded_room` (occ + co2 + power, all
`Dur 36`, so they mature together) produced:

```
INC-0003  "2 sensors alarming: Power critical ..."   npu_calls: 3    (2 domain agents + synthesizer)
```

So 2.14's "the orchestrator only ever runs one agent" was **wrong, and the fault was in my test**:
I had been triggering incidents through the dashboard Analyze button, and `server.go` builds a
**one-element** candidate slice there by construction. Real incidents arrive through the event gate
(`batchEvents`), which batches everything alarming at once. §5's measured table (2 calls for
ventilation failure, 4 for crowded room) was right all along.

**Batching measured on a real multi-agent incident:**

| | total | agent pair | synthesizer |
|---|---|---|---|
| batch OFF | 18691 ms | 4198 + 6519 (+600 ms gap) = 11316 | 6769 |
| **batch ON** | **17726 ms** | **10188** | 6936 |

**965 ms off the incident, ~1.1 s off the agent pair.** Now ON by default (`SCE_GENIE_BATCH=0` to
disable) - a code default, not an env var, because the Android watchdog restarts the backend
without our environment.

## 2.18 The `action` trim: now shipped, ~199 ms/call (2026-10-14)

2.10 recorded this as measured-and-rejected. It is now fixed and ON by default.

`policy.go` **always** overwrites the model's `action` with `ActionOf(cause, status)` whenever the
cause is a valid enum, so every token spent generating it is pure latency. The original attempt
failed on a streaming defect: with a `strings.Builder` the comma in `, "action"` could not be
retracted once a chunk boundary had absorbed it, producing `... "confidence": 0.85, "action}` -
invalid JSON. Two fixes, both in `genie.go`:

- `gen` is now a **`[]byte`**, so the cut index can truncate text already accumulated;
- the token stream is held back by **`trimHoldback` = 16 bytes**, so the dashboard is never shown
  text that is then retracted.

Measured through the real app on the same sensor:

| arm | gen chunks | latency |
|---|---|---|
| baseline | 58 | 3838.9 ms |
| **trim** | **55** | **3640.1 ms** |

**~199 ms/call (5.2%).** Raw output now ends `..."confidence": 0.85}` instead of
`..."confidence": 0.85, "action": "none"}`.

**Correctness gate - 14 findings, 0 problems**, across all five roles and the patterns `stable`,
`spike`, `flatline`, `throttling`, `exponential_increase`, `step_decrease`, `vacant`, with statuses
`normal` / `warning` / `critical` / `sensor_fault`. Every raw output closed cleanly; `action` never
appeared in the raw; the derived actions were correct (`flatline`+`sensor_fault` -> `check_sensor`,
i.e. the exact case LADE corrupted in 2.14). `policy.go` no longer logs "action missing" as a
repair when the trim is on, since the absence is deliberate.

**Caution carried forward from 2.14:** `genie.go` counts one "token" per stdout read, not per token,
so `gen_tokens` is a **chunk count**. Use Genie's `--profile` (`app/tools/bench_device.sh`) whenever
a token number matters.

## 2.19 The persistent-process question: no shortcut exists (2026-10-14)

Init is 687-731 ms on **every** call, 18% of a request, and after 2.15 it is the largest addressable
cost left. Reading the Genie C++ source that ships in the SDK
(`examples/Genie/Genie/src/qualla/engines/qnn-htp.cpp`) confirms **dialog reuse would remove it**:

- the load happens in the engine constructor (`NspEngine::NspEngine` -> `load()` ->
  `initializeModel` / `initializeIOTensors` / `initializeKVManager` / `calculate_rope_embeddings`);
- `GenieDialog_reset` -> `Dialog::reset()` only zeroes `_n_past` / `_n_prompt` / `_n_generated` and
  the KV; **there is no `load()`/`unload()` in the reset path**.

So `GenieDialog_create` once, then `reset` + `query` forever, pays the 687 ms exactly once.
`GenieDialog_signal(dlg, GENIE_DIALOG_ACTION_ABORT)` from a second thread is a clean replacement for
the SIGINT we use today, and `GenieDialog_setStopSequence` / `setMaxNumTokens` may remove the need
to abort at all.

**Two shortcuts were tried on device so that this would not need cgo. Both are dead:**

1. **Named pipe as the `--script` argument.** `mkfifo` is refused by SELinux in **every** writable
   location: `/data/local/tmp`, `/data/local/tmp/genie_bundle`, `/sdcard`, `/data/data`. (Confirms
   2.13.)
2. **`-s /proc/self/fd/0` fed by a slow pipe.** The SDK source shows a `while (std::getline(ifs,
   line))` loop with execution *inside* it, which suggested incremental execution. Measured twice:

   | run | query line written | output file appeared | pipe closed (EOF) |
   |---|---|---|---|
   | unpadded | t=30 s | t=90 s | t=95 s |
   | +5 KB of padding after each command | t=30 s | t=112 s | t=110 s |

   Execution tracks **EOF**, not the buffer. Padding past the 4 KB `ifstream` block changed nothing.
   `genie-app` consumes the whole script before running any of it, exactly as 2.13 recorded.

**Therefore a persistent engine needs the Genie C API via cgo**, which also means an Android NDK
cross-compile (`GOOS=android`, `CGO_ENABLED=1`, link only `libGenie.so`; everything else is
`dlopen`ed) and giving up the static binary. Est. **~700 ms/call**, plus possibly the 600 ms
inter-call gap if the burst DCVS vote is held by the context rather than the query - that part is
unverified. The docs are explicit that **"the Genie C API currently does not offer thread safety
guarantees"**, so every call must sit behind one mutex (except `signal`), which matches our existing
one-NPU-session-at-a-time rule.

Also noted for later: `dialog rewindQuery` exists in `genie-app`, and `GENIE_DIALOG_SENTENCE_REWIND`
does real prefix matching - but **only** on the slot path, which requires `"shared-engine": true`
plus `"allow-async-init": true`. On the fallback path `NspEngine::rewindKVCacheToPrefixMatch` is a
stub that returns "zero prefix matched" and re-prefills everything. That is the route to reusing our
~314-token static prefix, and it is a separate project after in-process reuse.

## 2.20 The 600 ms inter-call gap was costing us for nothing (2026-10-14)

`GenieRunner.Run` spaced NPU sessions 600 ms apart because of a measurement from 2026-10-07: a
session started < 0.5 s after the previous one exited decoded at **~9 tok/s instead of ~19**,
having collided with the previous session's HTP teardown. That was the **base** model, 200-token
generations, and **before `allow-async-init: true`**.

Re-measured on the fine-tuned bundle, twice, with the gaps ascending and then descending so that
temperature drift could not favour either end (the board climbs to ~90 C over a run of these):

| gap | 0.0 s | 0.2 s | 0.3 s | 0.4 s | 0.6 s | 1.0 s |
|---|---|---|---|---|---|---|
| ascending | **22.53** | 22.20 | 21.94 | 22.31 | 22.31 | 22.29 |
| descending | **22.43** | - | 22.42 | - | 22.44 | 22.10 |

tok/s on the **second** call. **There is no cliff any more, not even back-to-back.** Init is in fact
slightly *lower* back-to-back (586-631 ms vs the usual ~690), which fits: the HTP stays warm.

Reduced 600 -> **250 ms**, not to 0. Nothing was measured between 0 and 250, and if this is ever
wrong the penalty is decode halving, which costs far more than 250 ms. Measured end to end on a
real 3-call `crowded_room` incident: **17726 -> 17393 ms**.

**The 2500 ms bundle-change gap is unchanged.** It guards a different failure - loading a different
set of context binaries straight after a teardown intermittently fails with "Could not create
context from binary" - and that was not re-tested.

## 2.21 Two bugs the trim introduced, and how they showed up (2026-10-14)

**1. The trim must apply to agent calls ONLY.** `policy.go` derives `action` from (cause, status)
for an agent **finding**, which is what makes those tokens waste. But `checkReport` does **not**
derive it for the synthesizer / Mode 2 **report** - there the model's `action` is the real output.
The first version of `answerScanner` trimmed anything with a prefill, so it trimmed the synthesizer
too. A `crowded_room` incident came back `done_with_errors`:

```
errors: ["unknown label ''", "action '' not whitelisted", "no evidence cited"]
raw:    {"root_cause": "Ventilation_insufficient cause=... action=inspect_ventilation explanation=..."}
```

The synthesizer had degenerated into key=value text inside `root_cause` and then emitted a real
`, "action":` field - and the trim cut exactly there and closed the object, taking `label`,
`affected_domains`, `evidence` and `action` with it. Fixed by gating on `prefill == AgentPrefill`.
After the fix the same scenario returns `state: done`, label `ventilation_issue`, action
`inspect_ventilation`, evidence cited, no errors.

**Worth remembering:** the trim is only safe because something downstream recomputes the field. Any
future "stop before field X" needs that same check, per call type, not globally.

**2. Batching bypasses the trim.** `runBatch` streams whole answers out of one `genie-app` process
and cannot abort an individual query mid-script, so batched agent calls still generate `action`
(visible in their `raw`). The two optimisations do not compose. That is an acceptable trade -
batching saves ~1331 ms per extra agent against the trim's ~199 ms - and the trim keeps its full
value on single-agent incidents, where there is no batch to amortise init across.

**Shared scanner:** both the CLI path and the (new) daemon path now go through one `answerScanner`
(`answerscan.go`), so there is exactly one copy of "when do we stop and what may the UI see". That
matters because this class of bug - two stream parsers drifting apart - already bit us once, when
`runBatch` used `idx++` from `-1` and put every answer in slot 0.

## 2.22 Context 4096 -> 2048: the biggest win of the day, and it is free (2026-10-14)

**Same checkpoint, same encodings, same weights, same 4-bit params and 8-bit lm_head. No retraining,
no recalibration.** The only change is the compiled context window: `--context-lengths 2048`.

**Why it should work:** the KV cache is a fixed buffer sized by the compiled context length -
28 layers x 8 KV heads x 128 head-dim x 2 (K,V) x ctx x 2 bytes = **469 MB at 4096, 235 MB at
2048** - and those bytes are part of what the NPU moves per decode token. Decode is bandwidth-bound
(2.15), and we use only ~610 of the 4096 slots, so the upper half of that buffer was pure waste.

**ctx 1024 was rejected**, not guessed at: generation has been measured reaching ~1120 tokens total,
and the Mode 2 / synthesizer prompts are far longer than an agent prompt, so 1024 would overflow.

**The binaries barely changed size**, which is the clue that the KV buffer is a *runtime*
allocation, not something baked into the blob:

| part | ctx4096 | ctx2048 | delta |
|---|---|---|---|
| 1 | 788,066,304 | 788,066,304 | 0 |
| 2 | 724,959,232 | 721,842,176 | -3.0 MB |
| 3 | 1,122,754,560 | 1,119,670,272 | -2.9 MB |

So whether it helped was an empirical question. It does, substantially. Averaged over the same 14
role/pattern prompts used for the identity gate:

| | ctx4096 | ctx2048 | change |
|---|---|---|---|
| init | 761.4 ms | 768.4 ms | ~0 |
| prefill (ttft) | 386.6 ms | **302.0 ms** | **-22%** |
| decode | 3736.8 ms | **3100.1 ms** | **-17%** |
| rate | 20.7 tok/s | **25.0 tok/s** | **+21%** |

**-721 ms per call.** (A 2-run sample first showed init +110 ms; over 14 prompts that vanished - it
was thermal noise. The board runs hot, so always prefer the 14-prompt aggregate.)

**Correctness: `compare_bundles.py` -> 14/14 byte-identical.** Required, since the weights did not
change: any mismatch would have meant the export altered something it should not have.

**End to end on a real 3-call `crowded_room` incident: 18691 -> 14727 ms**, and a second incident at
14488 ms. State `done`, no policy errors, report well-formed.

### Deploying a new bundle: three places, not one

`EdgeService.healScript` compares **file sizes** against the backup at
`/sdcard/Android/data/com.iiith.smartcityedge/files/backup/` and silently restores the old bundle if
they differ. `backendStart` also runs `cp -r $X/web/. $D/web/` from
`/sdcard/Android/data/com.iiith.smartcityedge/files/app/web/`, so web assets edited only in
`/data/local/tmp` are reverted on the next service restart. A real deploy is therefore:

1. web assets -> `files/app/web/`
2. bundle -> `files/backup/genie_bundle_ft/` (**backup first**, so a heal mid-swap restores the NEW
   bundle rather than fighting you)
3. bundle -> `/data/local/tmp/genie_bundle_ft/`

Rollback: the 4096 bundle is kept on device at `/data/local/tmp/genie_bundle_ft_4096`, and on the
laptop at `qidk_backup\genie_bundle_ft`.

## 2.23 Token streaming was working all along - the list view just never painted it (2026-10-14)

Captured the live SSE stream through a complete incident: **305 `token` events**, correctly split
per call (`S1` 69, `S2` 122, `final` 114), each carrying incremental text. The backend, the hub and
`Prefetch`'s per-agent routing were all fine - batching included.

The gap was one line in `app.js`:

```js
if (S.incId !== d.incident) return;   // tokens painted ONLY into an already-open detail sheet
```

and nothing auto-opened a new incident, so from the incident list an answer simply appeared after
~15 s. Fixed two ways: a live token tail now renders on the incident **card** (`.cstream`, seeded
from `S.cardStream` because cards are rebuilt whenever the incident JSON changes), and a newly
running incident **auto-opens** - but only when no other sheet is open, so it can never steal the
view from someone reading another incident.

**Process note:** my first check reported "zero token events" and was wrong - I grepped for
`"type":"token"` when the SSE wire format is `event: token`. The pipeline was never broken. Check
the wire format before concluding a feature is missing.

## 2.24 genied in production: the persistent dialog, and what it took (2026-10-14)

`genied` (app/genied) holds one GenieDialog for the life of the process; the backend talks to it over
127.0.0.1:8777 and falls back to the per-call CLI if it is absent.

- **Gate:** `training/export/verify_daemon.py` sends 14 prompts twice, forward then reverse, so each
  prompt follows a different predecessor the second time. 28/28 byte-identical to the CLI -
  `GenieDialog_reset` is a clean state wipe. Single agent call 3640 -> 2543 ms, TTFT ~1.2 s -> 312 ms.
- **`"poll": true` must be off in a daemon.** Genie busy-waits on the NPU. The CLI exits after each
  answer so the spinning stops; a daemon never does. genied idled at **359% CPU** and drove the board
  to 94 C, tripping the thermal guard so no analysis ran at all. genied forces poll off for itself:
  0% idle CPU, still 28/28, same speed (3670 vs 3686 ms). The shared config keeps poll on for the CLI.
- **Batching (genie-app) is off while genied is up**: it loads a second model copy, and two resident
  models is what hits the DSP SMMU limit and (see 2.27) reboots the board.
- **Inter-call gap is 0 for daemon calls**: it guarded one process's NPU teardown against the next
  process's start, and one persistent process has no teardown.

**App pipeline.** `build_apk.sh` packages genied as `libgenied.so`; `EdgeService.backendStart` copies
it out like `libedgeagent.so`, and edge-agent launches and supervises it (`superviseDaemon`, restarts
it if it dies, never under an in-flight call). Two update gaps fixed in EdgeService: a HEALTHY backend
used to keep the old binary and the old dashboard after an APK update until something crashed. It now
compares the APK's backend, daemon and web files with what is deployed at service start and redeploys
on any difference (`staleScript`). Verified by shipping a newer genied and newer CSS through a plain
`adb install -r`. Also verified: after a cold reboot the app restores edge-agent and genied in ~10 s.

## 2.25 Continuous batching: REJECTED on QAIRT 2.50 (2026-10-14)

Traced in the Genie source: dialogs whose engine has QnnHtp `"shared-engine": true` resolve to ONE
engine via a registry, each takes a scheduler slot, and an engine-level `"batching"` block
(`max-slots`, `mixed-prefill-decode`, `coalesce-window-us`, `prefill-chunk-size`) lets the
InferenceScheduler fuse slots' decode tokens into one graph fire. genied implements this behind
`-slots N`. Sharing works - dialogs 2 and 3 attached in ~0.2 ms with no reload.

**But it truncates answers.** Three prompts concurrently: 1/12 identical, most answers cut after a few
tokens (`"spike"` -> `"sp"`, some empty). The 76% "speedup" was answers stopping early. Then
**sequentially** on the same shared-engine daemon: every answer truncated in 300-480 ms. So it is not
thread safety - shared-engine slot mode itself ends generation early under our reset-then-query
pattern. Not shippable. `-slots` stays in genied, default 1 (re-verified 28/28). The ar4 re-export,
which only existed to feed batching, was cancelled.

## 2.26 Runtime knobs, measured: nothing left here (2026-10-14)

On the live ctx-2048 bundle, 3 runs each with Genie's profiler: `mmap-budget` 0 -> 25 changed init by
noise only (633-671 vs 648-695 ms), decode unchanged. `direct-io: true` failed to produce output at
all (SELinux on the dma-heap, or the config edit); since genied pays init once, not worth pursuing.

## 2.27 A second model next to the 3B reboots the board (2026-10-14)

With genied holding the fine-tuned 3B, loading the base 3B in a second process dropped the device off
USB and rebooted it (`up 0 min`), as on 2026-10-07. Free RAM was 5.8 GB beforehand, so a free-memory
check is NOT a sufficient guard. **Two full models cannot be resident.** The separate cross-domain
reasoner (owner's decision: a distinct, self-improving model, Qwen3-1.7B preferred) is therefore a
**swap per incident**: agents on the resident 3B, then genied releases it, the reasoner loads, reasons
and exits, the 3B reloads - about +1.5 s per multi-domain incident; single-domain incidents skip it.

**Parked until after the eval** because of the network: Qualcomm's pre-quantized Qwen3-1.7B asset
(8.28 GB) is only on S3 us-west-2, which this connection reaches at **~18 KB/s**; HuggingFace is 72x
faster (1.36 MB/s) but unquantized. Next step: download the asset on another network, or self-quantize.

## 2.28 Self-learning: the data is already being captured (2026-10-14)

Every LLM call persists `prompt`, `raw` (model output BEFORE policy repair), `parsed`, `valid`,
`errors`, `repairs`; every incident persists the operator's `approval` and `approval_note`. The log is
append-only, so the newest line per incident is authoritative.
`training/feedback/export_feedback.py` turns it into:

- `sft_positive.jsonl` - operator-approved calls that passed policy with no repairs;
- `dpo_pairs.jsonl` - calls policy repaired: chosen = policy-corrected output (in trained field
  order, policy-only fields like `requires_human_approval` removed), rejected = the raw output. These
  need no human labelling, so they accumulate from day one;
- `dismissed.jsonl` - dismissed incidents with the operator's note, for review.

First real run: one approved incident gave 2 SFT positives and 1 DPO pair (the synthesizer put
non-domain names in `affected_domains` and evidence text inside its ids; policy fixed both).

## 2.29 Where the app's time really went: the batch window, not the analysis (2026-10-14)

With `SCE_GENIE_TRACE=1` the orchestrator now logs millisecond phase marks. A real 3-call incident:

```
agents  2617 + 4488 ms  ->  phase took 7112 ms   (overhead ~8 ms)
synth          4454 ms  ->  phase took 4457 ms   (overhead ~3 ms)
total 11570 ms, of which non-model time ~11 ms
```

So inside the analysis there is nothing left to optimise in the app - genied and the zero gap removed
it. The time was BEFORE the analysis starts. The event gate needs 8 abnormal readings (~16 s at the
2 s poll; deliberate false-alarm suppression, left alone), and then the batch window waited
**3 more readings unconditionally** (~6 s) so co-occurring sensors could join one incident - even
when no other sensor was abnormal at all.

`batchEvents` now closes the window after one reading when no other sensor is abnormal-but-young,
and otherwise behaves exactly as before. Measured from the gate's own trace (`gate: batch opened` /
`closed`):

| incident | window before | window after | sensors |
|---|---|---|---|
| `power_throttling` (isolated) | 3 readings, 6.0 s | **1 reading, 2.0 s** | 1 |
| `ventilation_failure` (isolated) | 6.0 s | **2.0 s** | 1 |
| `crowded_room` (cross-domain) | >= 6.0 s | **2 readings, 4.0 s** | **2, still one incident** |

**-4 s on every isolated incident, -2 s here on the cross-domain one, Mode 3 batching intact.**
Trade-off to know: a correlated sensor that is not yet abnormal AT ALL one reading after the first
one matures will now form its own incident instead of joining. The scenario catalogue's only
multi-target scenario still batches correctly.

Note for measuring: end-to-end "inject -> analysis" times are dominated by how fast each scenario
crosses its threshold (tank_leak varied 93-129 s between identical runs). Measure gate changes from
the gate trace, and reset first with `POST /api/replay {"restart":true,"clock":"10:00"}` - otherwise
the sim drifts into off-hours and spurious occupancy incidents get measured instead.

## 2.30 Thermals, and a stale-UI bug that hid UI changes (2026-10-14)

**Board heat, measured:** idle on every dashboard tab 50 C steady, app + WebView ~10% of ONE core,
genied 0%. Mid-inference the WebView is ~0% and genied ~46% (real work). After three back-to-back
incidents: 39 C CPU / 38 C NPU at rest, 63-69 C immediately after inference. The earlier 94 C was
entirely genied's poll busy-wait (2.24). The UI did not heat the board - until the DeerFlow redesign, see 2.35.

**Stale UI across APK updates.** A fixed incident title stayed unchanged across two installs and
relaunches although the backend served the new app.js and the WebView uses LOAD_NO_CACHE. Cause: the
dashboard's service worker keeps its own Cache Storage and registration, which survive app updates
and are outside the HTTP cache. Fixed three ways: MainActivity wipes WebView web storage once per
APK install (keyed on lastUpdateTime); the backend sends `Cache-Control: no-cache` for the dashboard
(the board's clock resets to 2023 at boot, so Last-Modified freshness is meaningless); and the
service worker fetches the shell with `cache: 'no-cache'`/`'reload'`. Verified on device.

Also fixed in the UI: the incident title inherited the page-heading treatment (uppercase, wide
tracking) and filled half the sheet; it would also have been turned into dot-matrix by a tab change.
It is now `.inc-title`, excluded from both.

## 2.31 Stress testing through the app; one queue; no agent cap (2026-10-14/15)

Everything is now tested the way an operator would use it: `app/tools/stress_app.py` drives only the
app's own API (sliders, scenarios, approve/dismiss/rerun, mode switches) with random values, random
sensor faults and "every sensor haywire" chaos rounds, and checks the board (backend + genied alive,
temperature, thermal guard) after each phase. `--only quiet,faults,scenarios,chaos,operator,load`.

- **Analyze/Rerun interleaved.** Each request ran its own pipeline, so 8 requests interleaved their
  NPU calls; one incident took 58 s for 10.8 s of model time. `Reasoner.Submit` now queues requests
  FIFO behind pending event-gate alerts (alerts first). Bounded at 16 waiting requests, identical
  requests de-duplicated; a full queue answers HTTP 429.
- **No agent cap.** Every alarming sensor gets its own NPU agent (chaos: 13 agents + synthesizer in
  48.9 s, 9 agents in 40.8 s). The thermal guard queues work until the board cools instead of dropping.
- **Results, pass 3:** 238/240 checks; Mode 3 analysis min 2.3 s, median 4.1 s, max 48.9 s (chaos).

## 2.32 Two context windows (ctx 2048 + ctx 4096)

The live bundle is ctx 2048 (fastest). A chaos-scale synthesizer prompt (18+ sensors) does not fit,
so a second bundle with the same weights and ctx 4096 lives at `/data/local/tmp/genie_bundle_ft_4096`.
The backend sets bit 31 of genied's length field when `estTokens*1.08 + 320 + 40 > 2048`; genied frees
the normal dialog and loads the large one (~0.9 s), never both. Outputs are byte-identical on the gate
(5/5). Nothing is trimmed to fit: the window grows instead. If the swap fails after the old dialog is
freed, genied exits (supervisor restarts it on the normal window) rather than keep a dangling handle.

## 2.33 When the AI and the rules disagree; fallback reports

Decision: surface the disagreement, neither side overrides. If an agent says "normal" while the rule
view of the same sensor is warning/critical, the report explanation says so (`surfaceDisagreements`).
If the synthesizer's answer fails policy, a report is assembled from the agents' own findings
(Mode 3) or from rule findings (Mode 2) and marked as such - an operator always gets a report.
Policy also completes `affected_domains` with every flagged domain whose own sensor is
warning/critical (chaos INC-0114 listed only `weather` while power, water and air quality were
critical); the label and root cause stay the model's.

## 2.34 Reboots: power, not code; the clock

The board rebooted during chaos (peak load). Boot reason "reboot" (not thermal), and it reports
AC/USB online = false: a brownout on the USB supply. **Use the DC adapter for the evaluation.** After
any reboot the RTC is back to 2023; the app passes its saved offset (`--clock-unix`), and incidents are
now ordered by ID, not wall clock, so a clock jump can never reorder the list. A power cut mid-write
can tear the last line of `incidents.jsonl`; see 2.35 for how the store survives that.

## 2.35 Night-run hardening (2026-10-15)

- **The dashboard was the heater.** With the DeerFlow redesign, app + WebView used ~220% CPU at idle
  and held the board at 75 C - hotter than a 13-agent incident. Cause: 22 px backdrop blurs
  re-rasterised every frame under 60 fps infinite animations. Bars are now solid, endless indicators
  step at 2 frames/s, the sparkline loop runs at 1 Hz. Measured: 5-11% on every tab, board 43 C idle.
- **Incident store** (`backend/store.go`): one line per version used to be kept forever, every
  incident in RAM. Now compacted (temp file + fsync + rename), newest 1000 kept
  (`SCE_MAX_INCIDENTS`), older ones moved to `incidents.archive.jsonl` (the self-learning export reads
  both), next ID from the highest ID seen so a torn line never reuses an ID. Test: `store_test.go`.
- **Never two models on the NPU.** genied binds its port before loading the model, so the port is a
  single-instance lock. The backend never spawns the CLI while any genied process is resident (only
  when none exists); two failed calls in a row, or 3 checks alive-but-not-listening, kill genied so
  the supervisor starts a clean one. Zombies are ignored. genied.log rotates at 4 MB; the parent's
  log fd no longer leaks per restart.
- **Watchdog (EdgeService):** returns from rules-only fallback to the NPU backend when local adbd
  comes back (previously stuck in Mode 1 until restarted by hand); restarts a dead in-app backend;
  polls `/api/incidents?limit=50`; the ctx-4096 bundle is backed up and self-healed like the others.
- **Off-device writes need a token.** The backend listens on 0.0.0.0 for Wi-Fi sensors; any POST
  from a non-loopback address needs `X-API-Token` (`SCE_API_TOKEN` or `state/api_token`), else 403.
  Reads stay open; the app (WebView) and the laptop via adb forward are loopback and unaffected.
- **API:** 1 MiB request bodies, 10 s header timeout, 120 s idle timeout (no write timeout: SSE);
  at most 16 queued analysis requests, duplicates merged, HTTP 429 beyond. Dashboard lists the newest
  300 incidents, sorted numerically (string order broke past INC-9999).
- **Stale abort killed the next query.** The backend stops a query early (abort byte) once the JSON
  closes. When that byte arrived just after the query had finished on its own, `GenieDialog_signal`
  hit the idle dialog and the NEXT query - usually the synthesizer - returned zero tokens in
  19-448 ms with "Context Size was exceeded" (on a 1.1k-token prompt). Before 2.35's no-CLI rule
  this fell back to the CLI, i.e. a second model on the NPU beside genied. Now each abort carries the
  query id and is dropped if that query is over; a query that yields no tokens without being
  aborted is reset and retried once.
- **Incident sheet power.** The fixed full-screen stipple re-rasterised on every small update; with
  a sheet open (new incidents open themselves) the app used ~185% CPU. Stipple on its own layer, the
  page under an open sheet not rendered: ~10%.
- **Fault injection on the device** (each verified through the app):
  | injected | before | now |
  |---|---|---|
  | `kill -9 genied` mid-answer | EOF read as a normal end, truncated text "answered", policy rejected | error; no genied left, so the CLI re-runs the call with the streamed prefix held back (valid answer, 4.9 s); genied back in <=15 s |
  | `kill -9 edge-agent` | - | watchdog restarts it in 8 s; incidents intact; one genied |
  | kill backend mid-analysis | the running incident vanished (persisted only at the end) | persisted at creation; reloads as `failed`; approve refused (409), rerun allowed, dashboard says "interrupted - rerun" |
  | torn last line in incidents.jsonl | (newer line glued to the torn one on next append) | skipped, logged, store compacted on load |
- Analyze/Rerun now answer `queued_ahead`, shown as "queued, N ahead" - a rerun queued behind
  event-gate alerts used to give no sign of life for a minute.
- **Thermal pacing inside an incident.** The guard holds work only between incidents; one 13-agent
  chaos incident reached 94 C. Before each NPU call at >= 88 C the runner waits (<= 15 s) for 82 C.
  Latency at the extreme only; prompts unchanged. Chaos peak after: ~90 C. Use a heatsink in the field.
- **Physical plausibility:** indoor CO2 below 350 ppm (under outdoor air) is a sensor fault. The
  stress test drove CO2 to 270 ppm and the training-parity rules called it a harmless step decrease;
  this one check is outside the training rules and documented as such in `rules.go`.
- **Memory:** edge-agent 15 MB RSS, genied 81 MB after 24 min of stress; re-checked after the run.

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
A real device can do the same over Wi-Fi: `POST http://<qidk-ip>:8000/api/ingest {"node","metric","value"}` with header
`X-API-Token: <token>` (token in `SCE_API_TOKEN` or `state/api_token`; off-device writes are refused
without it, reads stay open - see 2.35).

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
