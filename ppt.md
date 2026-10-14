# Agentic Edge AI for Smart Cities — presentation script

Slide-by-slide content with speaker notes. Every number here was measured on the Qualcomm QIDK
(Snapdragon 8 Gen 3, Hexagon V75 NPU) unless marked otherwise; HANDBOOK.md has the raw evidence.
The mid-evaluation deck this replaces is kept as `ppt_mideval.md`. `Presentation/ppt.md` predates
the build and describes a Llama + Qwen design that was never shipped.

---

## 1. Title

**Agentic Edge AI for Smart Cities**
Multi-agent reasoning over live campus sensors — entirely on a phone-class NPU, no cloud.

IIIT Hyderabad · Qualcomm QIDK (SM8650) · Llama 3.2 3B, fine-tuned, running on the Hexagon NPU

> Notes: one sentence — "A campus monitor that notices problems, reasons about *why* across
> buildings and utilities, and asks a human before anything happens, all on one small device."

---

## 2. The problem

- A campus produces thousands of readings an hour: air quality, water, power, occupancy, weather.
- Threshold alarms say *what* crossed a line, never *why* — and they fire in floods.
- Real causes cross domains: a crowded room raises CO2 **and** room power **and** cooling load.
- Sending every reading to the cloud costs bandwidth and privacy, and fails when the link does.

> Notes: the gap is reasoning. Rules can detect; they cannot explain, and they cannot connect
> "power rose" with "people arrived" with "CO2 is climbing".

---

## 3. What we built

- **An on-device monitor**: 18 live sensors across 5 domains, a 4-hour window per sensor,
  statistics and pattern detection every reading.
- **AI domain agents on the NPU**: one fine-tuned 3B model plays five specialist roles —
  Air Quality, Water, Power, Occupancy, Weather.
- **A cross-domain synthesizer** that combines the agents' findings into one root cause.
- **A policy gate and a human in the loop**: every AI answer is validated; every recommendation
  waits for an operator's decision. Nothing is ever actuated automatically.
- **A native Android app** that keeps all of it running on the QIDK by itself.

---

## 4. Three reasoning modes (the experiment)

| Mode | What runs | Role in the study |
|---|---|---|
| 1 · Rules | deterministic statistics + rule engine | baseline, microseconds |
| 2 · Single AI | one model call over all flagged sensors | "just ask the LLM" |
| 3 · Multi-Agent | one NPU agent per abnormal sensor + rule agents for steady context + synthesizer | our design |

> Notes: the same model and the same data in Modes 2 and 3, so differences come from the
> architecture, not the model.

---

## 5. Architecture

```
 sensors (sliders / API / replay)
        │  every reading
        ▼
 statistics engine  ── SMA, EMA, trend, curvature, jumps, flat runs, plateaus (E1..E8)
        │
 rule engine        ── pattern + status per sensor, instantly on the dashboard
        │
 event gate         ── abnormal for 8 consecutive readings; co-occurring alarms batched
        │
 orchestrator (CPU) ── every abnormal sensor -> NPU domain agent
        │              related steady sensors -> deterministic context agents (parallel, µs)
        ▼
 NPU domain agents  ── fine-tuned Llama 3.2 3B on the Hexagon NPU via Genie, via genied
        │
 synthesizer (NPU)  ── one cross-domain root cause, evidence-cited
        │
 policy gate        ── enums, real evidence ids only, no actuation; repair or deterministic fallback
        ▼
 operator           ── approve / dismiss (with a note)  ─────► feedback data for self-learning
```

> Notes: AI does the heavy reasoning; deterministic code does what must be exact — statistics,
> evidence, validation, and the decision of *when* to call the AI.

---

## 6. The model

- **Llama 3.2 3B Instruct**, QLoRA fine-tuned on **6,480 worked examples** (5 roles × 1,296)
  built from real IIIT-H sensor data; 2 epochs; best dev loss 0.027.
- Output is strict JSON: pattern, status, observations citing evidence ids, likely cause,
  confidence, action.
- Host evaluation (150 held-out windows), fine-tuned vs base Llama:

| | fine-tuned | base | rules |
|---|---|---|---|
| pattern | **94.0 %** | 20.0 % | 68.0 % |
| cause | **93.3 %** | 18.0 % | – |
| evidence valid | **100 %** | 34.7 % | – |
| output tokens | **84** | 199 | – |

---

## 7. Getting it onto the NPU — the quantisation journey

| step | pattern accuracy on device |
|---|---|
| first w4a16 export | 54.3 % |
| MSE-clipped weight scales | 39.1 % (worse) |
| GPTQ weights (error-compensating rounding, our own calibration prompts) | 67.4 % |
| **found a double BOS token** (Genie adds its own) — fixed | **82.6 %** |
| live model, 54-window device test | **85.2 %** · status 87 % · cause 81.5 % · JSON, evidence, policy **100 %** |

> Notes: the biggest single gain was not a quantisation trick but a prompt mismatch — every device
> prompt began with two BOS tokens the model had never seen. Finding it took the same weights from
> 67 % to 83 %.

---

## 8. Latency: where the time actually goes

Per agent call (548-token prompt, 59 tokens out), Genie's own profiler:

| phase | share | what it is |
|---|---|---|
| model init | 18 % | loading the model — now paid once (genied) |
| prefill | 11 % | reading the prompt, ~1800 tok/s |
| **decode** | **70 %** | writing the answer, ~25 tok/s |

**Decode is at the memory-bandwidth roof.** Each token streams the 4-bit layers (and 8-bit lm_head)
from DDR; measured traffic sits at a large fraction of the NPU's measured DMA ceiling. Clock, DCVS
and threading knobs were already at their best. Only three things move decode: fewer bytes per token,
fewer tokens, or several tokens per weight sweep.

---

## 9. Latency: what we did, measured

| change | effect | gate |
|---|---|---|
| context window 4096 → 2048 (re-export, same weights) | **−721 ms / call**, 20.7 → 25.0 tok/s | 14/14 byte-identical |
| genied: persistent NPU dialog (C API) | init once; single call **3640 → 2543 ms**, first token **~1.2 s → 0.31 s** | 28/28 identical, forward + reverse |
| stop generating the `action` field policy derives anyway | −199 ms / agent call | 14/14 valid |
| inter-call gap 600 → 250 → 0 ms (no teardown with genied) | −0.35 s per extra call | 10 measurements |
| adaptive incident window | **−4 s** on isolated incidents, −2 s cross-domain | gate's own trace |
| Analyze/Rerun queued instead of interleaved | a 58 s incident was 10.8 s of model time | stress test |

**End to end:** single-sensor incident ~**4.4 s** analysis; 3-call cross-domain ~**12.5 s**
(was 18.7 s). App orchestration overhead inside an incident: **~11 ms**.

> Notes: every change was gated on output identity or validity before it shipped.

---

## 10. What we tried and rejected — and why

| idea | result | why rejected |
|---|---|---|
| LADE lookahead decoding | up to −45 % decode | **1/14 answers identical**; "flatline/sensor_fault" became "flat78/normal" — Genie does not verify drafts |
| grammar-constrained decoding | +440 ms init, no tokens saved | jump-forward only exists in draft-engine dialogs |
| continuous batching (shared engine) | looked 76 % faster | **truncated every answer**, even one at a time |
| multi-graph bundles | slower | graph switching costs ~350 ms per call |
| RPC/DCVS knobs, `llm_decode_*` profiles | no effect / V79+ only | already at burst; not on V75 |
| a second model resident beside the 3B | **rebooted the board** | DSP address space and RAM |

> Notes: a fast wrong answer is worse than a slow right one. LADE was the most tempting — and the
> one that would have told an operator a stuck sensor was normal.

---

## 11. Two context windows — chosen per call

- Every agent call (~600 tokens) and ordinary synthesizer calls run on the fast **ctx-2048** bundle.
- A large incident needs more: ~190 prompt tokens per sensor, so "every sensor failing" needs ~3,400.
- Evidence is **never trimmed** to fit. genied swaps in the **ctx-4096** bundle for that call
  (same weights, byte-identical outputs), ~0.9 s each way, only when needed.
- Gate: alternating normal / large / normal / large / normal — **5/5 identical** to the CLI.

---

## 12. Orchestration — the AI does the heavy lifting

- Every abnormal sensor gets its own NPU domain agent — **no cap**.
- Related sensors that are steady are checked by deterministic context agents in parallel (µs),
  so the synthesizer sees verified "this domain is fine" evidence instead of guessing.
- One incident at a time on the NPU, first in, first out; real alerts before manual requests.
- The synthesizer runs whenever two or more domains carry information.

---

## 13. Safety and robustness — the policy gate

- Every AI output: valid JSON, whitelisted enums, every evidence id must exist, no actuation.
- Transparent repairs, each recorded: stray brackets, unclosed strings, an object closed with `]`.
- A rejected report is **never shown**: rebuilt deterministically from the findings that passed
  (Mode 3) or from the rule findings (Mode 2), with the rejected text kept for audit.
- **AI vs rule disagreement is surfaced, not resolved silently.** In stress tests the AI said
  "normal" on a rule-flagged sensor in 3 of 18 calls — the rule was right once (a missed pump
  oscillation), the AI twice (a CO2 episode that had already cleared). The report states the conflict.
- Every recommendation needs a human; a dismissal needs a note.

---

## 14. Production hardening

| problem found | fix |
|---|---|
| daemon busy-waited on the NPU: 359 % idle CPU, board at 94 °C | poll off for the daemon: 0 % idle, same speed |
| thermal guard **discarded** incidents while hot | queued, run when the board cools (verified) |
| more than 8 alarms → the rest silently dropped | every alarm analysed |
| app update left the old backend and old UI running | redeploy on any binary or web change |
| WebView kept serving stale UI across installs | storage reset per install, no-cache headers |
| 4 of 10 demo scenarios targeted sensors that did not exist | live fallbacks; Mode 3 fans out again |
| dashboard redesign used ~220 % CPU at idle (185 % with an incident open), board at 75 °C | solid bars, stepped animations, composited background: 5–11 %, 43 °C |
| a late early-stop abort killed the next NPU query (synthesizer got 0 tokens) | aborts tied to their query id; zero-token query retried once |
| CO2 at 270 ppm (below outdoor air) raised nothing | plausibility rule: sensor fault; AI disagreement surfaced |
| genied killed mid-answer: truncated text treated as an answer | detected; CLI re-runs the call (model no longer resident); daemon back in 15 s |
| backend killed mid-analysis: the alert vanished | persisted at creation, reloads as "interrupted - rerun" |
| anyone on the Wi-Fi could approve incidents or inject values | off-device writes need an API token; reads stay open |
| dashboard silently showed stale data while the backend restarted | "reconnecting" banner |
| incident log kept every version forever, all in RAM | compaction, retention 1000 + archive, crash-safe IDs |
| a failing daemon could make the CLI load a 2nd model (reboots the board) | never two models: port lock, no CLI while genied lives, wedged daemon killed |
| watchdog stayed in rules-only mode after adbd came back | returns to the NPU backend automatically |
| unbounded request queue / request bodies | 16 queued requests (429 beyond), 1 MiB bodies, timeouts |

The app survives a cold reboot: backend and NPU daemon back in ~10 s with no laptop.

---

## 15. How we tested — through the app, not a benchmark

`app/tools/stress_app.py` drives the real app API:

- garbage inputs (NaN, strings, absurd values, unknown sensors): rejected or clamped, never a crash
- 90 s of realistic random drift: **no false alarms**
- random excursions on random sensors: every one raised, analysed and passed policy
- faults: spikes, flapping, stuck sensors
- every scenario in every mode; **chaos**: every sensor failing at once
- operator actions, and 240 concurrent requests while the NPU is busy

`review_answers.py` then checks the *diagnosis* against what was injected, not just validity.

---

## 16. Results

- Agent diagnoses matching the injected scenario: **8/10** (the two misses were the water tank —
  one was the scenario refilling itself, now fixed; one a genuine miss, now surfaced to the operator).
- Mode 3 analysis across stress incidents: min 2.5 s · **median 4.4 s** · max 13.8 s.
- Chaos (every sensor failing, uncapped): see `stress_report.json` for the run's figures.
- Board under sustained load: back to ~39 °C at rest; thermal guard holds work rather than dropping it.

---

## 17. The interface

- Instrument-panel design: near-black panels, dot-matrix headings drawn as SVG (no font files),
  dot-matrix charts, monospace throughout, one orange accent.
- **Live token streaming**: you watch each agent think, per agent, as it generates.
- A new analysis opens itself; incident cards show a live preview.
- The UI uses 5–11 % of one core on every tab (it was 220 % before the power fix); board ~43 °C idle.

---

## 18. Self-learning, already started

Every AI call is stored with its prompt, raw output, policy repairs, and the operator's verdict.
`export_feedback.py` turns that into:

- **SFT positives** — approved, unrepaired answers
- **DPO pairs** — what the model wrote vs what policy corrected it to, no labelling needed
- **dismissed cases** with the operator's reason

The first real incident already produced a preference pair for the synthesizer.

---

## 19. What's next

- **A dedicated cross-domain reasoner** (Qwen3-1.7B preferred): separate from the five agents so
  cross-domain reasoning cannot degrade them, and improvable on its own from operator feedback.
  Swapped in per incident (~+1.5 s), since two models cannot be resident.
- **Speculative decoding with a trained draft head** (EAGLE-style): the only way past the bandwidth
  roof — the 3B verifies, so outputs stay identical.
- **Recent-onset awareness**: a "last hour" evidence line and onset examples, fixing the one
  systematic miss (subtle anomalies diluted by 4-hour aggregates).
- **Causal discovery across sensors** (PCMCI) as evidence the synthesizer can cite.

---

## 20. Lessons

1. **Measure before believing** — several "obvious" wins (LADE, grammar decoding, batching) were
   faster *and wrong*. Gate every change on output identity, not just speed.
2. **The biggest bugs were not in the model** — a double BOS token, a dropped-incident thermal guard,
   a scenario aimed at a sensor that did not exist.
3. **Test through the product** — a stress harness on the real app found what unit tests could not.
4. **Keep the human in the loop** — and give them the disagreement, not a confident wrong answer.

---

## 21. Demo script

1. Live tab: 18 sensors, dot-matrix charts, rules updating every reading.
2. Inject *Crowded room*: power and CO2 alarm together → one incident opens itself.
3. Watch the agents stream on the NPU; the synthesizer names ventilation as the root cause.
4. Show the policy gate's evidence ids; approve with a note.
5. Inject *Stuck sensor*: flatline → `sensor_fault`, action `check_sensor`.
6. Switch to Mode 1 and Mode 2 on the same incident to compare.
