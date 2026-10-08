# app.md — Mid-Eval App: On-Device Polling + 3-Mode Backend + Llama on NPU

> Written 2026-10-01. Target: **show a working on-device system in 3–4 days.**
> Fine-tuning (see `training_plan.md`) is parked until after mid-evals. This app uses the **existing** Llama 3.2 3B Genie bundle on the HTP, same as today, with prompting only.
> Nothing has been built yet. This file defines what we will build.

---

## 0. TL;DR

- **What we show:** the QIDK, on its own, polls sensor values every few seconds (replayed real SCRC data, KH building), runs data-quality checks + rules + baselines continuously, and when an anomaly appears it calls **Llama 3.2 3B on the NPU** according to the selected mode (1 Rules / 2 Single-LLM / 3 Multi-Agent). Domain agents say what they notice, the synthesizer says what the problem is, and every claim has tappable evidence IDs. The dashboard is open on the QIDK screen like an app.
- **Do we need the Android NDK?** **No, not for mid-eval.** We also don't need Android Studio, the Android SDK or a JDK.
- **How:** one small **native backend binary** (written in Go, cross-compiled on the laptop for Linux/arm64) pushed with `adb` to the device. It runs as the **shell user**, the same context in which `genie-t2t-run` already works on the NPU today. It calls Genie **locally on the device** (no laptop, no ADB hop per call) and serves the dashboard on `http://127.0.0.1:8000`. The dashboard opens in Chrome on the QIDK and is installed to the home screen as a full-screen app (PWA).
- **Only new tool:** the Go toolchain (~70 MB, free) on the laptop. Everything else already exists.
- **After mid-eval:** wrap the same backend into a real APK (Track B, §9), then swap in the fine-tuned model.

---

## 1. Why this architecture (and not an APK right now)

| Option | What it needs | Risk in 3–4 days | Verdict |
|---|---|---|---|
| **A. Native backend binary via adb (shell user) + PWA dashboard** | Go toolchain only | **Low.** Genie on HTP from a shell process is already proven on this device (`/data/local/tmp/genie_bundle`, ~7 s/call). Shell can read `/data/local/tmp` and `/sys/class/thermal` | **Mid-eval** |
| B. Kotlin APK, exec `genie-t2t-run` packaged in the APK's native-lib dir | JDK 17 + Android SDK + Gradle (~2 GB downloads), APK signing | **Medium–high.** App SELinux domain: model files must move out of `/data/local/tmp` (apps can't read it), FastRPC/DSP library paths from an app context are unverified on this device | After mid-eval |
| C. Kotlin APK + JNI to the Genie C API | B + **NDK** + QAIRT SDK headers (not on this machine) | **High** | Later, for best latency |
| D. Keep laptop FastAPI + ADB (today's demo) | Nothing | Low, but **not on-device** and the root-cause output is currently faked (see `context.md` §3) | No |

So the NDK only becomes necessary for option C (JNI). Options A and B need none.

---

## 2. What runs where

```
LAPTOP (prep + deploy only)                 QIDK  (Android 14, SM8650, runs standalone after start)
───────────────────────────                 ───────────────────────────────────────────────────────────
ihub-clean-datasets/*.csv                   /data/local/tmp/smart_city_edge/
   │ build_replay_pack.py (stdlib Python)     ├── edge-agent              ← Go binary (linux/arm64, static)
   ▼                                          ├── config/  sensors.json, thresholds.json, baselines.json,
replay pack (KH bldg, ~7–14 days, 1-min)      │            scenarios.json, modes.json, genie-agent.json
   │                                          ├── prompts/  *.tmpl  (Llama-3 chat format)
   │ deploy.ps1 (adb push)  ───────────────►  ├── replay/   *.jsonl.gz
   │ start.ps1  (adb shell setsid nohup)      ├── web/      index.html, app.js, styles.css, manifest.json
   ▼                                          └── state/    incidents.jsonl, audit.jsonl, logs/
go build (GOOS=linux GOARCH=arm64)
                                            /data/local/tmp/genie_bundle/   ← EXISTING, unchanged
                                              genie-t2t-run-2.50, qairt_2_50_libs/, dsp_2_50/, *.bin, tokenizer.json

                                            edge-agent ──exec──► genie-t2t-run-2.50 ──► HTP V75 (NPU)
                                                │
                                                └── HTTP :8000 ◄── Chrome on QIDK (PWA "Smart City Edge")
                                                               ◄── laptop browser via `adb forward` (optional)
```

---

## 3. Backend components (inside `edge-agent`)

| # | Component | Responsibility | Notes |
|---|---|---|---|
| 1 | **ReplaySource** (poller) | Every *poll interval* (default 5 s wall clock) advances a **replay clock** by *N* simulated minutes (default 1 min/tick ⇒ 1 h of building data every ~5 min) and emits the readings with timestamps ≤ clock | Interface `SensorSource` so a live SCRC HTTP source can replace it later |
| 2 | **WindowBuilder** | Per node & metric rolling stats over last 60 sim-min: `last, mean, min, max, slope`; inferred occupancy (CO2 rate + AC-on count) | Same stats the agents see |
| 3 | **Evidence builder** | Creates evidence IDs `ev:{node}:{metric}:{stat}:{epoch}` with value, unit, window; stored per event | Grounding for policy gate + UI chips |
| 4 | **QualityGate** | Range check (from `meta data.xlsx`), sentinels (CO2 4294965, AQI > 1000, WD −40/125…), stuck (flat N ticks), stale (no data > TTL) → `SENSOR_FAULT`, never an anomaly | Prevents false alarms from dirty data |
| 5 | **Detectors** | (a) Rules from `thresholds.json` with min-duration + hysteresis, warning/critical; (b) seasonal baseline: robust z = \|x − median(hour-of-week)\| / MAD > k, from `baselines.json` precomputed on laptop | Autoencoder (ONNX) deferred to Track B, since ONNX Runtime in Go needs cgo |
| 6 | **EventGate** | Groups triggers per building within 15 sim-min, dedup, cooldown, **max LLM events per hour**, thermal check | Keeps NPU load sane |
| 7 | **Reasoner** | Mode 1 / 2 / 3 (§4). Builds prompts from templates, calls GenieRunner, parses JSON | Prompts use the **Llama 3 chat template**, not ChatML |
| 8 | **GenieRunner** | `exec` of `genie-t2t-run-2.50` locally: writes prompt file, sets `LD_LIBRARY_PATH` / `ADSP_LIBRARY_PATH`, timeout, parses text between `[BEGIN]:` and `[END]`, records latency. **Single-flight mutex** (one NPU job at a time) + queue | Uses a **new** config `genie-agent.json` (copy of the current one with `max-num-tokens` ≈ 300, temp 0); the existing config stays untouched |
| 9 | **PolicyGate** | JSON schema, evidence ⊆ event evidence, per-agent domain ownership, action enum, `requires_human_approval: true`; one repair retry, then fail closed with the reason shown | Real result shown in UI (no hardcoded "passed") |
| 10 | **IncidentStore** | Append-only `incidents.jsonl` + `audit.jsonl` (raw LLM output, validation result, latency, mode); approve/dismiss | Survives restarts |
| 11 | **HTTP API + SSE** | Serves `web/` and JSON API (§6); Server-Sent Events push live updates and "agent thinking…" progress | |
| 12 | **System monitor** | Thermal zones, free RAM, NPU busy flag, last Genie latency | Shown in header |

---

## 4. The three modes

Detection (components 1–6) is identical in all modes. Only the reasoning step differs.

| | Mode 1 — Rules | Mode 2 — Single-LLM | Mode 3 — Multi-Agent |
|---|---|---|---|
| NPU calls / event | 0 | 1 | 1 per affected domain (max 3) + 1 synthesizer |
| Input | Rule breaches | All affected domains' evidence tables in one prompt | Each agent gets **only its domain's** evidence + weather context. Synthesizer gets the agents' JSON findings + evidence list |
| Output | Template `RootCauseReport` (rule text, `UNKNOWN` label unless rule maps to a label) | `RootCauseReport` | Per-agent `DomainFinding` ("what I notice") + synthesizer `RootCauseReport` ("what the problem is") |
| Expected latency (cold Genie, ~7 s/call) | < 10 ms | ~7–10 s | ~20–30 s (UI shows each agent finishing live) |

- **Shadow Mode 1:** Mode 1 always runs too, so every incident shows the rules baseline next to the LLM answer.
- **Compare button** on an incident: re-runs the same frozen event in the other modes for side-by-side display at the eval.

Agents for KH data: **HVAC**, **Indoor Air**, **Energy**, **Water**, plus **Weather** as context (always attached, never a separate call in mid-eval to save time).

### JSON contracts

```jsonc
// DomainFinding (agent)
{"domain":"hvac","status":"abnormal|normal|insufficient_data",
 "observations":[{"text":"...","evidence":["ev:..."]}],
 "suspected_cause":"HVAC_FAULT","confidence":0.0,"missing_data":["..."]}

// RootCauseReport (Mode 2 / synthesizer)
{"root_cause_label":"HVAC_OVERLOAD","summary":"...","causal_chain":["..."],
 "evidence":["ev:..."],"confidence":0.0,"recommended_action":"inspect_hvac",
 "uncertainties":["..."],"requires_human_approval":true}
```

Labels: HVAC_OVERLOAD, HVAC_FAULT, HVAC_FILTER, VENTILATION_INSUFFICIENT, OUTDOOR_AIR_INGRESS, ENERGY_ABNORMAL_LOAD, WATER_LEAK_OR_DRAIN, WATER_SUPPLY_LOW, WATER_QUALITY, WEATHER_HEAT_LOAD, SENSOR_FAULT, UNKNOWN.
Actions: inspect_hvac, clean_or_replace_filter, inspect_ventilation, inspect_water_system, check_sensor, review_energy_schedule, request_facility_review.

To keep the 3B model reliable without fine-tuning: short schemas, one few-shot example per role, the evidence table pre-digested (numbers, deltas vs baseline, units), output capped at ~250 tokens, JSON extracted from the first `{` to its matching `}`.

---

## 5. Data for the demo (replay pack)

Built on the laptop by `build_replay_pack.py` (stdlib only, streams the CSVs):

| Domain | Source nodes | Resampled |
|---|---|---|
| HVAC | SR-AC KH00–KH03 (aggregated per floor: units on, compressor-on fraction, mean room temp, mean setpoint, alarms, malfunction codes, filter signs) | 1 min |
| Indoor air | SR-AQ KH00-01/02, KH03-01/02/03, KH95-00 | 1 min |
| Energy | SR-EM KH04-00/01/02 | 1 min (ffill ≤ 10 min) |
| Water | WM-WL KH00, KH98 · WM-WF KH95, KH98 · WM-WD KH95/96/98 | 1 min (ffill with TTL) |
| Weather (context) | WE-VN04-00 (+ nearest outdoor AQ) | 1 min (ffill ≤ 15 min) |

- **Window:** 7–14 days chosen where all KH domains have good coverage (the script reports coverage and picks the window; hot-season weeks preferred).
- **Baselines:** median/MAD by hour-of-week per node/metric from Jan–Aug data → `baselines.json`.
- **Fault scenarios** (`scenarios.json`), injectable on demand from the UI so the demo doesn't depend on luck:
  1. HVAC fault on KH02: compressor on, room temp climbing, energy up
  2. Ventilation failure on KH03: CO2 ramps to 1,500+ ppm, AC fan off
  3. Heat wave: outdoor temp +6 °C, all floors' load up (cross-domain)
  4. Water leak: KH98 tank drains at night with no inflow
  5. Sensor fault: CO2 stuck / overflow value (should become `SENSOR_FAULT`, not an anomaly)
  6. Filter clog: slow cooling degradation

Injected values are applied on top of real readings and clearly marked "injected" in the UI and incident record.

---

## 6. API (served by `edge-agent`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Device, NPU ready, Genie last latency, thermal, mode, replay clock/speed |
| GET | `/api/live` | Latest per-domain readings + status (normal / warning / alert / sensor-fault) |
| GET | `/api/series?node=&metric=&minutes=` | Chart data |
| GET | `/api/events` | **SSE stream**: readings tick, new event, agent started/finished, incident ready |
| GET | `/api/incidents` · `/api/incidents/{id}` | List / detail (findings, report, evidence values, policy result, raw LLM output, latencies) |
| POST | `/api/incidents/{id}/approve` · `/dismiss` | Human approval (dismiss needs a note) |
| POST | `/api/incidents/{id}/rerun?mode=` | Compare modes on the frozen event |
| POST | `/api/mode` | `{ "mode": 1 \| 2 \| 3 }` |
| POST | `/api/replay` | `{ "speed": ..., "play": true/false, "jump_to": ... }` |
| POST | `/api/inject` | `{ "scenario": "hvac_fault_kh02" }` |
| POST | `/api/evaluate` | Manual sliders (keeps today's demo panel), **now with the real model output** |

---

## 7. Dashboard (PWA on the QIDK)

Built from the existing `webapp/static` files (restyled, same tech: plain HTML/JS/CSS, no build step, everything bundled locally so it works offline).

1. **Header:** NPU status (green when Genie ready), mode selector 1/2/3, replay clock + play/pause/speed, thermal + RAM.
2. **Live:** KH floor cards per domain (value, sparkline, status colour), weather strip, event ticker.
3. **Incident detail:** synthesizer summary + causal chain + label + confidence; agent cards ("HVAC agent noticed…") with evidence chips → tap to see the value/mini-chart; Mode 1 shadow result; policy-gate verdict (real); per-call NPU latency; raw model output (collapsible); Approve / Dismiss.
4. **Scenario panel:** inject buttons (§5).
5. **Compare view:** same event in Modes 1/2/3 side by side.
6. **PWA:** `manifest.json` (name, icon, `display: standalone`) so Chrome's "Add to Home screen" gives a full-screen app icon on the QIDK.

---

## 8. Build & deploy steps

| Step | What | Who |
|---|---|---|
| D0.1 | Plug in QIDK; `adb shell sha256sum /data/local/tmp/genie_bundle/*.bin` vs `SHA256SUMS.txt` (re-push part 2 only if it differs) | **You** + me |
| D0.2 | On device: `./genie-t2t-run-2.50 --help`, list the bundle dir (is there a `genie-app` binary?), one timed call, check the HTP backend in logs | **You** run, me read |
| D0.3 | Check that a process started with `setsid nohup` via `adb shell` **keeps running after unplugging USB** | **You** |
| D0.4 | Install Go (Windows installer or WSL tarball) | **You** |
| D1 | `build_replay_pack.py` + `baselines.json` + `scenarios.json` (laptop) · Go skeleton: ReplaySource, WindowBuilder, QualityGate, rules, baselines, evidence, `/api/live` + SSE → cross-compile → push → run on device | Me (code) + **You** (run deploy) |
| D2 | GenieRunner (local exec, mutex, new `genie-agent.json`), prompts, JSON parse/repair, PolicyGate, Modes 1/2/3, IncidentStore, rerun/compare | Me + **You** (device test) |
| D3 | Dashboard (live, incident detail, scenarios, compare, PWA), `deploy.ps1` / `start.ps1` / `stop.ps1` / `logs.ps1`, end-to-end on device | Me + **You** (feedback) |
| D4 | Buffer + mini-eval: run all 6 scenarios × 3 modes, record latency, JSON-valid rate, grounded rate, correct label. Demo script + screen recording | Me (harness) + **You** (run, record) |

**Scripts (laptop, PowerShell):**
- `deploy.ps1`: `go build` → `adb push edge-agent config prompts web replay` → `chmod 700`
- `start.ps1`: `adb shell "cd /data/local/tmp/smart_city_edge && setsid nohup ./edge-agent >state/logs/agent.log 2>&1 &"` then opens Chrome on the device at `http://127.0.0.1:8000` via `adb shell am start -a android.intent.action.VIEW -d http://127.0.0.1:8000`
- `stop.ps1`, `logs.ps1` (tail), `forward.ps1` (`adb forward tcp:8000 tcp:8000` to view on the laptop too)

---

## 9. After mid-eval (Track B → fine-tuned model)

1. **Real APK:** Kotlin app with WebView UI + foreground service. Backend reused either by (a) porting the Go logic to Kotlin, or (b) `gomobile bind` → `.aar` (needs the NDK). Genie via binaries packaged in the APK's native-lib dir (no NDK) or JNI (NDK + QAIRT SDK) for a resident model (removes ~4 s load per call). Models move to `/sdcard/Android/data/<pkg>/files/`.
2. **Persistent Genie session:** if `genie-app` or the Genie C API is available, load the model once and keep it loaded. Mode 3 latency drops from ~25 s to under 10 s.
3. **Autoencoder** detector via ONNX Runtime (Kotlin/JNI).
4. **Fine-tuned model** per `training_plan.md` (full data, export round trip, AI Hub compile), then swap the bundle and re-run the same eval for before/after numbers.
5. **Live SCRC source** replacing ReplaySource.

---

## 10. Risks for the 3–4 day window

| Risk | Mitigation |
|---|---|
| Mode 3 too slow with cold Genie (~7 s × 4) | Cap agents at 3; weather as context only; ~250-token outputs; live per-agent progress in UI; check for `genie-app`/persistent mode on D0 |
| Base 3B model returns invalid JSON | Short schema + few-shot + JSON extraction + one repair retry; failures shown honestly with the raw output |
| Backend dies when USB is unplugged | Test on D0.3. Fallback: keep USB connected during the demo (laptop is still not in the inference path) |
| Device rebooted → `/data/local/tmp` state | `deploy.ps1` is idempotent; bundle hash check before start |
| Thermal throttling in long demo | EventGate rate limit + thermal guard pauses LLM calls; show thermal in header |
| Replay window has gaps in some KH domains | Pack builder picks the best-coverage window and reports coverage; QualityGate marks stale data |

---

## 11. Definition of done (mid-eval)

- [ ] `start.ps1` → USB can be unplugged → dashboard runs full-screen on the QIDK.
- [ ] Readings tick live; normal periods show no LLM calls.
- [ ] Injecting a scenario produces an incident within ~1–2 replay minutes.
- [ ] Mode 2 and Mode 3 incidents are produced **by Llama 3.2 3B on the HTP** (Genie latency + backend shown; raw output viewable).
- [ ] Mode 3 shows per-domain agent findings + synthesizer report, each claim with valid evidence IDs.
- [ ] Policy gate verdict is real; a rejected output shows its reasons.
- [ ] Sensor-fault scenario is classified as `SENSOR_FAULT`, not escalated as an anomaly.
- [ ] Mini-eval table: 6 scenarios × 3 modes → label correct?, JSON valid?, grounded?, latency.
