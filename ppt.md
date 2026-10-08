# Agentic Edge AI for Smart Cities — mid-evaluation
*Qualcomm QIDK (Snapdragon 8 Gen 3, Hexagon NPU) · IIIT Hyderabad campus sensor data*

---

## 1. Goal
- Watch campus sensors: **air quality, water, power, occupancy, weather** (plus AC units as context).
- Detect *what pattern* is emerging (spike, step, gradual rise/fall, exponential, oscillation, throttling,
  flatline, ...).
- Explain *why*, across domains, with evidence. A human decides, nothing is actuated automatically.
- **Entirely on the edge device:** no cloud, no laptop at run time.

---

## 2. What runs on the board today
- A native Android app, **Smart City Edge**, installed on the QIDK. It starts on boot and runs without the laptop.
- 18 live sensors fed from **on-screen sliders** (the user is the sensor). Real devices can post to `/api/ingest`.
- Per reading: 4-hour window → statistics (SMA/EMA/trend/Bollinger) → rule pattern + status.
- An event gate → **one incident** for everything alarming → domain **AI agents on the NPU** → cross-domain report.
- Policy gate (valid JSON, real evidence, whitelisted actions) → human Approve / Dismiss → Android notification.

---

## 3. Architecture
```
 sliders / real sensors ──► sensor bank ──► 4 h windows ──► statistics + rule pattern/status
                                                          │
                       (warning/critical/faulty for 8 readings, all alarming sensors batched)
                                                          ▼
                                   ┌───────────── one incident ─────────────┐
                                   │ Mode 1: rules     Mode 2: one LLM call │
                                   │ Mode 3: orchestrator ─► context agents │
                                   │         (CPU, parallel)                │
                                   │         domain agents ─► synthesizer   │
                                   │         (Llama 3.2 3B on the NPU)      │
                                   └────────────────────────────────────────┘
                                                          ▼
                                     policy gate ─► report ─► human approval
```

---

## 4. Three-mode reasoning
| Mode | Idea | NPU calls | Latency |
|---|---|---|---|
| 1 Rules | statistical rules only | 0 | < 1 ms |
| 2 Single | one LLM sees everything | 1 | ~6-9 s |
| 3 Agents | one fine-tuned agent per alarming sensor, rule-based context agents for related domains, a synthesizer for the cross-domain cause | N + 1 | ~5 s per agent |

- A cause-and-effect map pulls related domains. CO2 → occupancy, AC units, room power, outdoor temperature.
- 3 domains alarming at once → 1 incident, 4 NPU calls, ~27 s.

---

## 5. Fine-tuning (laptop, zero budget)
- Llama 3.2 3B Instruct, **QLoRA** on a 6 GB RTX 4050: 5 domain roles, 6,480 examples, 2 epochs, ~7 h.
- Real SCRC campus data with patterns injected on calm windows. Test set = **Nov-Dec 2025**, never seen.

| Held-out (laptop) | Fine-tuned | Base model | Rules |
|---|---|---|---|
| Pattern accuracy | **94 %** | 20 % | 68 % |
| Evidence valid | **100 %** | 35 % | - |
| Answer length | 84 tokens | 199 | - |

---

## 6. Putting it on the NPU: the accuracy journey
| Step | Pattern on NPU |
|---|---|
| First export (published scales, rounded weights) | 54.3 % |
| GPTQ 4-bit weights, calibrated on our prompts | 67.4 % |
| **Fixed a double start token** (Genie adds one; our prompt had one) | **82.6 %** |
| Unquantised model, same windows (ceiling) | 91.3 % |
| **Live model, larger test (54 windows)** | **85.2 %** |

- The NPU keeps **~93 %** of the model's accuracy (85.2 % of 91.3 %), with **100 % valid JSON, evidence and
  policy**. Base model on the same device test: 11 %.
- Biggest single lesson: the prompt must be byte-identical to training, all the way to the NPU.

---

## 7. Latency on the NPU
- One agent: ~4-6 s (first token ~1.2 s, ~19 tokens/s), stopping the moment the JSON closes.
- Event maturity wait: 8 readings ≈ 16 s, chosen on purpose for accuracy.
- Single alarm: change → report ≈ 20 s. Three domains together ≈ 45 s.
- Compare reruns: 0 ms (exact-prompt cache; decoding is deterministic).

---

## 8. Problems we hit, and what fixed them
| Problem | Fix |
|---|---|
| Laptop overheated and hibernated 21× during training | thermal guard (pause at 81 °C), CPU cap, WSL memory limits, auto-resume |
| CUDA out-of-memory during training / merge | sliced loss over answer tokens; merge on CPU |
| Two NPU models at once **crashed the board** | strictly one NPU session at a time, 0.6 s gap |
| Exported bundle used random sampling | force greedy decoding at deploy |
| Alternating two 2.9 GB bundles: "could not create context" | one bundle for every role |
| 4-bit rounding lost ~20 points | GPTQ with exact grid scales |
| Weight clipping made it worse (39 %) | dropped; LLMs need their large weights |
| `w4` precision doesn't load on 8 Gen 3 | stay on w4a16 |
| AIMET needs > 30 GB; Kaggle killed it | own ONNX Runtime calibrator, 4 parallel Kaggle shards |
| Genie rejected the model: KV in/out encodings differ | tie in/out ranges |
| **Double BOS token** on every NPU call | strip ours before Genie (+15 points) |
| Android apps may **not** open the NPU on this firmware | app drives the board's own adb on 127.0.0.1:5555 |
| Go crashed under the app sandbox (SIGSYS, faccessat2) | absolute paths for system commands |
| Board clock reset to 2023 at every boot | install-time clock offset |
| Young events misread (fresh step called a spike) | AI waits for 8 abnormal readings |
| Two domains alarming gave separate incidents | batching: one incident, one batch of NPU calls |
| Recorded replay data felt like a black box | sliders and ingest API: the user is the sensor |

---

## 9. Trade-offs, and why
- **Go backend + WebView UI** rather than a full NDK app: one engine for laptop tests and the device, built in days.
- **adb loopback** to reach the NPU: fully standalone after reboots, **but** adb is unauthenticated on this dev
  kit. We keep it off untrusted Wi-Fi; reverting is one command.
- **Sequential NPU calls:** parallel was 3× slower and once crashed the board.
- **Wait 8 readings before the AI:** costs ~16 s, but the agents see events like the ones they were trained on.
  Rule status stays instant.
- **One model for all roles** (the synthesizer too): no 2.9 GB reloads, no context failures.
- **GPTQ on the laptop** instead of Qualcomm's SeqMSE (needs a 40 GB GPU): free, and most of the gain.
- **Kept Qualcomm's activation ranges:** our recalibration didn't beat them once the token bug was fixed.
- **Transparent repairs** in the policy gate (logged, never silent) instead of discarding near-correct answers.
- **Zero budget throughout:** laptop GPU, free AI Hub compile, free Kaggle CPU.

---

## 10. Robustness for the field
- Starts on boot; a watchdog restarts the backend.
- **Self-healing:** a 5.7 GB on-device backup restores deleted or damaged model files automatically.
- **Uninstall protection:** device administrator, so `adb uninstall` and Settings both refuse.
- Laptop restore kit: `qidk_backup\restore_qidk.ps1` rebuilds a wiped board in one command.
- At rest: 2,000 readings → **0** AI calls. Thermal guard for the NPU.
- NPU hiccup after reboot/idle (err 1002, hardware): retries with backoff, plus a re-run at the end of the batch.
  It is no longer shown as a safety rejection. Verified with a reboot: failed once, recovered, all checks passed.
- Clock: correction applied only while the RTC is unsynced (fixed the wrong 2029 dates).

---

## 11. Limitations (honest)
- On-device pattern accuracy is 85.2 % (54 windows), not 94 %. The remaining loss is 4-bit weights plus
  int8/int16 activations; the model's own ceiling on these windows is 91 %.
- **Cause** accuracy is a weaker point (~83 %), e.g. a TDS jump called "tank filling".
- The sensor clock is compressed (one reading = 5 sensor-minutes, every 2 s), so long-horizon patterns are simulated.
- adb loopback is a dev-kit workaround, not a production security model.

---

## 12. Future plans
- **Model:** add hard examples (young events, cause confusions) and retrain; evaluate on a larger device set.
- **NPU accuracy:** mixed precision (8-bit weights for the most sensitive layers); SeqMSE on a borrowed big GPU.
- **Latency:** keep a Genie session alive (save/restore the prompt prefix) to cut ~1 s per call.
- **Reasoning:** add a stronger reasoning model (e.g. Qwen) for the synthesizer step.
- **Real sensors:** ESP32 / MQTT into `/api/ingest`; multiple boards; authentication.
- **Platform:** request vendor NPU access for apps (drop adb loopback); OTA updates.

---

## 13. Live demo script
1. Show the app on the QIDK (no laptop), the NPU temperature and the "fine-tuned" badge.
2. At rest: no incidents. Move **CO2** to 1600 → countdown "AI check in N readings" → agent tokens stream →
   report → Approve.
3. Move **CO2**, **TDS** and **power factor** together → **one** incident, "3 sensors alarming", one batch of NPU calls.
4. **Occupancy** on + room power up + CO2 up → cross-domain explanation ("occupancy-driven load").
5. Set jitter to 0 → after 16 readings a **stuck-sensor** alert.
6. Compare Mode 1 / 2 / 3 on the same incident.
