# Research summary: when should an edge city-monitoring system escalate to a reasoner?

Status 2026-11-26: every planned experiment for this round has been run, except the ceiling model (see `CEILING_AND_API.md`). The fixes found by the study are deployed on the QIDK board.

## The system

- **Cheap path:** one fine-tuned domain agent per flagged sensor (agt3_s0450, Q4_0, on the Snapdragon NPU). A deterministic template turns the agent findings into a report.
- **Full path (escalation):** the same agents, plus a cross-domain reasoner (rsn_v3_4b_v5, Qwen3.5-4B fine-tune, Q4_0, swapped onto the NPU) that writes the report: root cause, label, severity and causal chain.
- **Research questions:** RQ1, what escalation costs; RQ2, what it buys at 2–5+ domains; RQ3, which trigger should decide.

## Data

| Set | Size | What |
|---|---|---|
| A | 200 | Real campus windows after the training cutoff, unscored (routing behaviour) |
| B | 153 | Injected multi-domain events in real held-out windows (N = 2, 3–4, 5+) |
| C | 50 + 1 | N = 1/2/4/8/12 flagged sensors × 10 windows, measured on the board, plus 1 overflow probe |
| D | 65 | 50 real normal windows + 15 real sensor faults (negative controls) |
| F | 50 | Single-domain cases (30 injected with gold) |

Leakage check: 0 case or prompt overlaps with training, and all windows are after the cutoff (`findings/LEAKAGE.md`).

## Main results

**RQ2: escalation clearly pays (Set B).**

| Path | Both label and severity correct | Severity correct | Missed critical |
|---|---|---|---|
| Cheap (agents + template) | 25.5 % | 82.4 % | 4/88 |
| Full (agents + reasoner) | **75.2 %** | **92.8 %** | 6/88 |
| Reasoner without agents (Mode 2-fair) | 71.2 % | 79.7 % | 22/88 |

- The gain holds at every N: 2 domains 42.9 → 79.4 %, 3–4 domains 10.0 → 70.0 %, 5+ domains 20.0 → 76.7 % (p < 0.001).
- Agents matter for safety: without them the reasoner misses 22 of 88 criticals.

**RQ3: "two or more domains" is a good trigger.**

- It reaches 70.2 % both-correct at 74 % escalation. That matches always escalating (69.8 %) at about 12 % less cost, with 92 % recall of the cases that escalation fixes.
- A perfect (oracle) trigger would reach 81.5 %, so smarter routing could gain about 11 points.

**RQ1: cost.**

- Host: the full path is 1.6–3.7× the cheap path.
- Board, live: escalation costs 5–6× (18–37 s per incident).
- Board, Set C: agents grow about 10 s per flagged sensor (10 s at N = 1, 123 s at N = 12). The reasoner grows only from 30 to 53 s. Swap-in is about 3 s.
- Prompts over 8192 tokens end with an empty report and the template fallback; nothing crashes.

**Board = host.**

- Sets B and D run on the board give Set B both-correct 73.9 % against 75.2 % on the host (McNemar p = 0.88). The host-run paper numbers therefore carry to the device.
- Individual answers differ in 41 % of cases (NPU vs GPU arithmetic), but the number of errors does not.

## Problems found and fixed (deployed 2026-11-26)

1. **Forced-schema decoding looped on the board.** 30 of 50 Set C reports were invalid, 29 of them because a sentence repeated until the token limit. Adaptive thinking (`reasoner_think=adaptive`) gave 48 of 50 valid at about the same time. Deployed.
2. **False alarms on normal windows (42 %).** In 15 of the 21 false alarms every agent and rule said normal, and the reasoner raised the severity anyway. Fix: skip the reasoner when every flagged agent and rule says normal. False alarms fall to 12 % on the host (10 % on the board), Set B is unchanged, and one injected event (F-024) that both the rule and the agent missed would be hidden. Deployed in `reason.go`.
3. **Small JSON slips** (a trailing comma) made 1 of 50 adaptive reports invalid. Fix: a lenient repair before the parse fails. Deployed in `reasoner_v3.go`.

Deploy check on the board:
- A hidden system check on normal data now ends in 2.7 s with "every agent and rule normal" (16.2 s with a reasoner call before).
- A chat answer uses the reasoner normally.
- Go tests pass.
- The previous APK and profile are kept for rollback.

## Early AI before the gate (2026-11-27)

- **Question:** can the reasoner run after k < 8 readings on strong warnings, to cut the 40–55 min gate wait?
- **Answer: no.** 440 event groups, 1,102 AI runs with the board models: no shape clears at any k = 3–7. Verdicts flip vs
  the full-gate verdict 22–76 % of the time (limit 15 %); flatline, noisy and fault lose 23–33 pp severity accuracy.
- Early AI stays off on the board. Details: `findings/EARLY_AI.md`, figure `figures/fig_early_ai_flip.png`.

## What did not help

- **Retrieval:** a populated past-incident store reached 152 of 153 prompts, but both-correct went 75.2 → 74.5 % (p = 1.0) and the reasoner never called the incident tools.
- **Tools, context agents, guards:** none changed both-correct beyond noise (±9–15 pp CIs), but dropping context agents cut severity accuracy 90 → 80 %, so all sensors are still sent.

## Text quality

- **v5 (deployed) is the best reasoner on every text metric.** BLEU 43.1, ROUGE-L 52.1, chrF 52.9 (p2: 33.2 / 42.2 / 45.0). BERTScore F1 92.3 (rescaled 54.5) on reports and 94.3 on chat.
- **These metrics are secondary:** part of the gold text is self-distilled.
- **The local 4B text judge is not valid:** a wrong-case decoy scored almost as high as real reports. Root-cause quality needs human or stronger judging.

## Limitations

- **Injected gold:** events are injected into real windows, and the gold follows one story per family. About 20 days of post-cutoff real data limit the number of independent baselines.
- **Test conditions on the board:** every case started cold (≤ 55 °C) and heated to 79–85 °C, so these timings are upper bounds.
- **Sensor faults are still hard:** 40 % caught on the host, 27 % on the board.
- **No ceiling model:** see `CEILING_AND_API.md`.

## Files

- `RESEARCH_PAPER.md`: the plan.
- `findings/RESULTS.md`: every table.
- `findings/BOARD_RQ1.md`: board cost and Set C.
- `findings/METRICS_MODELS.md`: BLEU / ROUGE / chrF / BERTScore per model.
- `findings/EARLY_AI.md`: early AI before the gate (no shape clears).
- `findings/LEAKAGE.md`, `findings/PILOT.md`, `findings/extra34.md`: leakage, pilot, ablations.
- `results/`: aggregate JSON per analysis.
- `figures/`: RQ1–RQ3 plots.
- `code/`: every script used (frozen sets, runs, scoring, board harness).
- Raw prompts, sensor windows and board logs stay on the laptop (`proofs/2026-11-26_paper/sets`, `runs`, `results/setc_board_raw`, `results/board_drive`). They contain real per-sample campus readings, which are not pushed.
