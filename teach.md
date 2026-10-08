# How the whole system works

Written to teach the complete flow, from a slider on the screen to an AI report from the NPU. Read it top to bottom
once; afterwards each section works as a reference.

---

## 1. The whole thing in one paragraph

A Qualcomm QIDK board (Snapdragon 8 Gen 3, with a Hexagon **NPU**) runs an Android app called **Smart City Edge**.
The app simulates 18 campus sensors (air quality, water, power, occupancy, weather, AC units). **You are the
sensor**: every slider you move is that sensor's current value, and every poll (every 2 s) the app takes it as the
next 5-minute reading. For each sensor the app keeps the last 4 hours (48 readings) and computes statistics and a
rule-based *pattern* and *status*. When a reading stays **warning / critical / faulty** for 8 readings, the app opens
**one incident** for everything alarming at that moment. It asks **AI agents** (a fine-tuned Llama 3.2 3B running
on the NPU) to explain it, checks their answers with a **policy gate**, and shows a report that a human approves.
Everything runs on the board. No internet, no laptop.

---

## 2. What runs where

```
 LAPTOP (only for building, training and installing)          QIDK BOARD (runs everything at demo time)
 ---------------------------------------------------          ------------------------------------------------
 training/      fine-tune the model (GPU, QLoRA)               Smart City Edge app (Android, com.iiith.smartcityedge)
 training/export  quantise + compile for the NPU (AI Hub)        |-- full-screen dashboard (WebView)
 app/backend    the Go backend source                           |-- foreground service (keeps everything alive)
 app/device/web the dashboard source                            '-- starts the backend through the board's own adb
 app/android    the Android app source + installer             edge-agent (Go backend, runs as the shell user)
 qidk_backup/   full restore kit                                 |-- sensor bank, statistics, rules, event gate
                                                                 |-- incident store, policy gate, HTTP + live stream
                                                                 '-- calls Genie for every AI agent
                                                               Genie (Qualcomm's LLM runner) + Llama 3.2 3B on the NPU
```

Why the backend runs as the "shell" user: on this board's firmware an ordinary app is **not allowed** to open the
NPU (the vendor DSP service answers *Permission denied*). The adb shell user is allowed. So the app connects to the
board's own adb daemon on `127.0.0.1:5555` and asks it to start the backend. It's the same trick Shizuku/LADB use.
Details in section 9.

---

## 3. The data path, step by step

### 3.1 A reading is born
- `app/device/data/sensors.json` lists the 18 sensors: id, domain, range, default value, and **jitter** (realistic
  measurement noise, e.g. ±6 ppm for CO2).
- Moving a slider calls `POST /api/sensors {node, metric, value}`. A real device would call `POST /api/ingest` with
  the same body. Both just set the sensor's *current value*.
- Every poll (`poll_ms`, default 2000 ms) the engine writes one reading per sensor: current value + jitter.
  One poll = one "5-minute" reading, so **sensor time** runs fast (about 150× wall time). You can set the time of
  day (Morning/Afternoon/Evening/Night) because occupancy at 22:00-06:00 counts as *off-hours*.

### 3.2 Per-sensor analysis, on every reading (`engine.go`, `features.go`, `rules.go`)
For each sensor the engine takes its **4-hour window** (last 48 readings) and computes:
- **Statistics:** last value, mean, SMA and EMA over 1 h, trend per hour (slope), R² of the trend, curvature,
  Bollinger bands, largest jump, flat-run length, robust noise.
- **Pattern** (rule classifier): one of `stable, spike, dip, gradual_increase, gradual_decrease, step_increase,
  step_decrease, exponential_increase, oscillation, throttling, flatline, erratic`. Occupancy uses `vacant,
  occupied, arrival, departure, intermittent, off_hours_presence`.
- **Status:** `normal`, `warning`, `critical` (thresholds per metric, e.g. CO2 1000/1500 ppm) or `sensor_fault`
  (e.g. 16 identical readings means a stuck sensor).
- The dashboard receives all of this live (server-sent event `live`, every poll).

These rules are **exactly the "teacher" that produced the training labels** (same code in Python and Go; the
parity test checks 400/400 cases byte for byte).

### 3.3 The event gate: when is the AI called? (`engine.go: detect, batchEvents`)
1. **Only abnormal status counts.** A sensor at `normal` status never calls the AI, whatever its shape. So a
   board at rest, or a value going back to normal, costs **zero** NPU calls (tested: 2,000 rest readings → 0).
2. **Persistence: 8 readings.** The abnormal status must last 8 readings (~16 s). The agents were trained on
   events that had lasted at least 7 readings; on younger windows they mis-read the shape, for example calling a
   fresh step a spike. The *rule* status still shows on the dashboard instantly; only the AI waits.
   The dashboard shows "AI check in N readings".
3. **Batching.** When the first sensor is ready, the batch stays open for at least 3 more readings, and until
   every other alarming sensor also has 8 readings (at most 10 readings). Then **everything alarming becomes ONE
   incident** with one batch of NPU calls, e.g. "3 sensors alarming: CO2 critical, Power factor warning, TDS warning".
4. **Once per episode.** A sensor that was reported is not reported again until it has returned to normal.

### 3.4 One incident, three possible modes (`reason.go`)
You choose the mode at the top of the app.

| Mode | What runs | NPU calls | Time |
|---|---|---|---|
| **1 Rules** | rule finding + rule summary only | 0 | < 1 ms |
| **2 Single** | one LLM call that sees all sensors at once | 1 | ~6-9 s |
| **3 Agents** (default) | one **domain agent** per alarming sensor + context agents + a **synthesizer** | N + 1 | ~5 s per agent |

Mode 3 in detail:
1. **Orchestrator** (`orchestrator.go`, CPU, microseconds). For each alarming sensor it looks up a cause-and-effect
   map: CO2 → occupancy, AC units, room power, outdoor temperature; tank level → water flow, occupancy, weather;
   and so on. It picks those related sensors, preferring the same building and skipping faulty sensors.
2. **Context agents** (CPU, in parallel goroutines). Each related sensor gets a quick rule-based analysis.
3. **Domain agents** (NPU, one after another; the NPU runs one model at a time, and running two crashed the board).
   Each alarming sensor's 4-hour window goes into a prompt with **evidence lines E1..E8** (last value, mean, trend,
   max, min, flat run, ...). The fine-tuned model answers in strict JSON:
   `{"pattern", "status", "observations" (each citing evidence ids), "likely_cause", "confidence", "action"}`.
   Tokens stream to the dashboard live.
4. **Synthesizer** (NPU, same model). It sees every flagged sensor, the agents' findings and the context sensors,
   and writes the cross-domain report:
   `{"root_cause", "label", "affected_domains", "evidence", "confidence", "action", "explanation"}`. It's skipped
   when only one domain carries information; the report is then built from the agent's finding.
5. **Policy gate** (`policy.go`). Every LLM answer is checked: valid JSON, allowed values only, every cited
   evidence id must exist, actions must be from a whitelist, **no automatic actuation**. Three transparent repairs
   are logged, never hidden: a missing action derived from the stated cause; packed evidence ids split; malformed
   JSON salvaged from the model's own words. Rejected answers fall back to the rule finding.
6. **Human in the loop.** The incident waits for **Approve** or **Dismiss** (dismiss needs a note).

### 3.5 Speed tricks that don't change any answer
- **Prefill:** the model's answer is started with `{"pattern": "` (or `{"root_cause": "`), so it starts in JSON.
- **Early stop:** generation stops the moment the JSON object closes.
- **Exact-prompt cache:** decoding is greedy (deterministic), so an identical prompt returns the cached answer
  instantly, e.g. "Compare" reruns.
- **Single model resident:** all roles use the same NPU bundle, which avoids reloading 2.9 GB between calls.
- **0.6 s gap** between NPU sessions (measured: starting sooner halves the speed).

---

## 4. The model

- **Base:** Meta Llama 3.2 3B Instruct.
- **Fine-tuning** (laptop RTX 4050, 6 GB): QLoRA, 4-bit NF4 base, LoRA rank 16 on all attention and MLP projections,
  24 M trainable parameters, 5 roles (air quality, water, power, occupancy, weather), 1,296 examples per role,
  2 epochs, 810 steps, ~7 h with a thermal guard (the laptop overheated once and hibernated).
- **Data:** real IIIT-H campus sensor data (SCRC). Patterns were injected on real calm windows, and occupancy came
  from the raw feed. Split by month: train Jan-Aug, dev Sep-Oct, **test Nov-Dec 2025** (never seen).
- **Labels:** written by the rule teacher (section 3.2) plus cause/action rules. Answers average 84 tokens.
- **Result on the laptop** (150 held-out windows): pattern **94 %** vs base model 20 % vs rules 68 %; evidence
  valid 100 %.

---

## 5. Getting the model onto the NPU, and the accuracy story

The NPU wants a **w4a16** model: 4-bit integer weights, 16-bit integer activations, compiled ahead of time
into 3 "context binaries". We compile with Qualcomm **AI Hub** (free) through `qai-hub-models`.

Every step, measured on the same 46 held-out windows:

| Step | Pattern on NPU |
|---|---|
| First export: Qualcomm's base-model scales, rounded weights | 54.3 % |
| **GPTQ** weights (error-compensating 4-bit rounding, calibrated on our prompts) | 67.4 % |
| **Removed a double BOS token** (Genie adds its own; our prompt had one too) | **82.6 %** ← live |
| Same live model on a larger test (54 windows) | **85.2 %** (JSON, evidence, policy 100 %) |
| (reference) the same fine-tuned model **unquantised** on the laptop | 91.3 % |

Lessons:
- **The prompt must be byte-identical to training, all the way to the NPU.** One extra start token cost 15 points.
- **Plain 4-bit rounding hurts LLMs;** GPTQ fixes most of it. Its weights lie exactly on the int4 grid, so the NPU
  reproduces them bit for bit.
- Clipping weight outliers made it worse (39 %). LLMs rely on a few large weights.
- `w4` (16-bit float activations) compiles, but doesn't load on the 8 Gen 3 NPU.
- Recalibrating activation ranges on our own data (on free Kaggle machines, 149 k tokens) didn't beat Qualcomm's
  ranges once the BOS problem was fixed.
- The NPU keeps about **90-93 %** of what the model can do (82.6-85.2 % vs 91.3 %), with 100 % valid JSON, evidence
  and policy. A larger GPTQ calibration (256 samples) gave the same accuracy, so the live model stays.

---

## 6. Latency (on the NPU, fine-tuned model)

| Thing | Time |
|---|---|
| One agent call | ~4-6 s (first token ~1.2 s, then ~19 tokens/s) |
| Waiting for the event to mature | 8 readings ≈ 16 s at 2 s polling |
| 1 domain alarming | ~20 s from the change to the report |
| 3 domains alarming together | ~27 s of AI (3 agents + synthesizer), ~45 s after the last change |
| Mode 1 | < 1 ms |

Why not run agents in parallel? Tested: two models on the NPU at once ran 3× slower in total, and the first try
crashed and rebooted the board. One NPU = one model at a time.

---

## 7. Safety

- Only whitelisted actions, and **no automatic actuation**: every report says *requires human approval*.
- Evidence ids are verified, so an agent can't cite a number that isn't in its window.
- The thermal guard pauses AI analysis if the NPU is above 88 °C or the skin above 60 °C (rules keep running).
- Every incident stores the prompts, the raw model output, the policy verdict and the repairs, for audit.
- **Hardware failure is not a safety failure.** If the NPU cannot open a session (err 1002, seen after a reboot
  or idle period), there is no model output for the policy to check. Genie retries after 3, 7 and 15 s, and the
  orchestrator re-runs that agent at the end of the batch. If the NPU is still down, the rule finding is kept
  and the timeline says "NPU temporarily unavailable". Only real model output can be "policy REJECTED".

---

## 8. The app on the board

- **Install** (once, USB): `app\android\install_app.ps1 -Build`. After that the laptop is not needed.
- **Starts by itself** on boot (`BootReceiver`). A foreground service supervises the backend and restarts it
  if it dies.
- **Notifications** for every new incident, even with the screen off.
- **Cannot be removed easily:** the app is a *device administrator*, so Android refuses to uninstall it
  (`DELETE_FAILED_DEVICE_POLICY_MANAGER`) until it's deactivated in Settings → Security → Device admin apps.
- **Self-healing:** a 5.7 GB copy of both model bundles is kept in the app's protected storage. At every start,
  and every 5 minutes, the app checks the files in `/data/local/tmp` and restores anything deleted or truncated.
  Tested: a deleted 788 MB model file came back on its own.
- **Clock:** the board's clock resets to 2023 at boot. The app applies an offset saved at install time.

---

## 9. Why adb on 127.0.0.1:5555 (and the one security rule)

- The NPU is opened through Qualcomm's FastRPC. For ordinary apps this firmware refuses
  (`open_device_node ... Permission denied`); for the shell user it works.
- So the app's `AdbLocal.java` speaks the adb protocol to the board's own adb daemon, on the port set once with
  `persist.adb.tcp.port=5555`. It runs one command as shell: refresh the backend files from the APK, then start it.
- **This dev kit's adb needs no password.** If the board joins a Wi-Fi network, anyone on that network could get a
  shell. Keep it off untrusted networks. To undo: `adb root`, `adb shell setprop persist.adb.tcp.port ""`, `adb unroot`.

---

## 10. Commands you need

| Goal | Command (from `C:\Users\hp\Desktop\qidk`) |
|---|---|
| Install/update the app (USB) | `powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\app\android\install_app.ps1 -Build` |
| Same, starting with an empty incident list | add `-ClearHistory` |
| Restore everything onto a wiped board | `powershell -ExecutionPolicy Bypass -File .\qidk_backup\restore_qidk.ps1` |
| Validate a model bundle on the NPU | `.\Code\smart-city-edge-agent\training\deploy_tuned.ps1 -Bundle <path> -PerRole 10` |
| Dashboard on the laptop (USB plugged) | http://localhost:8000 |
| Feed a value from a real device | `curl -X POST http://<qidk-ip>:8000/api/ingest -d '{"node":"SR-AQ-KH03-03","metric":"co2","value":850}'` |

---

## 11. Words

- **NPU / HTP / Hexagon:** the AI accelerator in the Snapdragon chip.
- **Genie:** Qualcomm's program that runs an LLM on the NPU.
- **w4a16:** 4-bit weights, 16-bit activations.
- **GPTQ:** a smarter way to round weights to 4 bits; it compensates each rounding error in the weights not yet rounded.
- **QLoRA:** fine-tuning a small add-on (LoRA) on top of a 4-bit base model, cheap enough for a 6 GB GPU.
- **BOS:** "beginning of sequence", the special start token.
- **Evidence ids (E1..E8):** numbered facts from the window that every observation must cite.
- **Policy gate:** the checker between the AI and the user.
- **Context agent:** fast rule-based check of a related sensor (no NPU).
- **Synthesizer:** the final AI call that writes the cross-domain report.
