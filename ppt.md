# Agentic Edge AI for Smart Cities: final evaluation deck

Final evaluation, 2026-10-29, 12:00 IST. Team NASA (esw-m26-14).

This file gives the content of each slide: the title, 3 to 6 bullets, the figure or table to show, and one
"why" line. Every number comes from a file in the repo, and the proof folder is named next to it. Unless a
number is marked "host", it was measured on the QIDK. Text inside `<<filled from …>>` is replaced by
`proofs/2026-10-28_master/finalize_docs.sh` once the overnight job writes that file.

---

## 1. Title

- **Agentic Edge AI for Smart Cities**: a campus monitor that notices problems, explains why they happen
  across domains, and asks a person before anything is done.
- It runs entirely on a Qualcomm QIDK: Snapdragon 8 Gen 3 (SM8650), Hexagon V75 NPU, Android 14.
- There are two fine-tuned models on the NPU: Llama-3.2-3B domain agents ("B50") and a Qwen3.5-4B
  cross-domain reasoner ("rsn_v1").
- No cloud and no laptop are needed after setup.

**Show:** the app's live tab (`proofs/2026-10-23_ux_v34/screens/`).
**Why:** the claim is that the whole agentic pipeline fits on one phone-class board.

---

## 2. The problem

- A campus produces readings every 5 minutes from air quality, water, power, occupancy, weather and HVAC
  sensors (SCRC-IHub data).
- Threshold alarms say *what* crossed a line, not *why*, and they fire in floods.
- Real causes cross domains. A crowded room raises CO2, room power and cooling load together.
- **Why the edge:** occupancy by room and time reveals where people are (privacy). An answer is needed in
  seconds, not after a cloud round trip (latency). The monitor must also keep working when the uplink fails
  (offline).

**Show:** the crowded-room incident screenshots (`proofs/2026-10-27_reasoner_fast/screens/chaos_0_*.png`).
**Why:** rules can detect a problem, but they cannot connect "power rose" with "people arrived" with
"CO2 is climbing".

---

## 3. System overview

```
sensors (/api/ingest, app sliders, replay)            one reading per sensor per 5 min
  -> statistics + rules (CPU, every reading)           pattern + status shown at once
  -> event gate: 8 abnormal readings, 3-reading batch  critical fast path: 2 readings past the critical limit
  -> domain agents: B50 (Llama-3.2-3B QLoRA blend) on the NPU, all agents of an incident in ONE htpd batch
  -> post-rules + policy gate (enums, evidence ids, no actuation)
  -> cross-domain reasoner: rsn_v1 (Qwen3.5-4B QLoRA), swapped into the same htpd, split decoding
  -> two-stage report: instant preliminary (retrieval or rules) -> the AI report on the same incident
  -> operator: acknowledge -> checklist -> close; re-checks at 1.5 h and 3 h of sensor time
```

- One htpd process holds one model at a time. It swaps between the agents' model and the reasoner, and
  the agents' model is back about 3 s after the report.
- Re-checks re-read every sensor of the incident at 1.5 h and 3 h, with a window chosen by the shape of
  the event. They can raise or lower the severity, or mark the incident resolved (HANDBOOK 2.39, 2.42, 2.43).

**Show:** the diagram above and one finished incident sheet (`proofs/2026-10-27_reasoner_fast/screens/chaos_4_2_done.png`).
**Why:** deterministic code does what must be exact (statistics, limits, evidence, validation). The models
do the reading and the explaining.

---

## 4. Hardware placement: why the NPU

- **NPU (Hexagon HTP through llama.cpp, our htpd daemon).** Decode is bound by memory bandwidth, so the
  lever is serving every agent in one sweep over the weights. A 12-agent chaos incident took about 46-48 s
  with Genie and 20.7 s with htpd (`proofs/2026-10-16_htpd_ab/RESULTS.md`, HANDBOOK 2.37).
- **GPU (Adreno 750, llama.cpp OpenCL), measured:** about 8.4 s per agent, no gain from batching, and 82%
  agreement with the NPU. GPU-only and hybrid placements were slower at every size
  (`proofs/2026-10-16_gpu_bringup`, `proofs/2026-10-16_hw_grid`).
- **CPU:** used for statistics, rules and retrieval (under 5 ms), not for the models.
- **Memory safety.** GPU and NPU buffers are unmovable and must fit the 7.26 GB Normal zone. A second 3B
  model next to Genie rebooted the board. The rules since then: one NPU client at a time, llama processes
  at `oom_score_adj 1000`, and big files copied as .part + md5 + mv (HANDBOOK 2.37, 2.43).

**Show:** the Genie vs htpd table (HANDBOOK 2.37 "Results").
**Why:** on a shared LPDDR5X bus, more engines do not mean more speed. Fewer weight sweeps do.

---

## 5. Accuracy: the domain agents

| model | what it is | key result | source |
|---|---|---|---|
| v1 | QLoRA, 4 h windows | 85.2% pattern on 54 device windows; 42% when the event is only 40 min old | HANDBOOK 2.39, `proofs/2026-10-16_placement_study` |
| v2 | retrain: 35,946 rows, 6 roles (HVAC added), 2-12 h windows | 40 min: 73.8% (v1 42%); false alarms 18% (v1 31%) | HANDBOOK 2.42 |
| v2 + post-rules | deterministic checks after the model | status on test 81.5 → 86.4% (57 wins / 1 loss) | `proofs/2026-10-24_trackB/RESULTS.md` |
| mixA50 | v2 + 0.5·(c49 − v2), a WiSE blend | board A/B: chaos 31/34 vs 29/34; clean-window false alarms 22 → 18% | `proofs/2026-10-24_v2t3g/board_ab` |
| **B50 (live)** | mixA50 + 0.5·(v2.1 − v2) | gate2 PASS vs mixA50: dev3f net +1, severity-weighted +61, E1 +4, safety 16/16 | `proofs/2026-10-25_domain_plan/B50_STAGED.json` |

- **gate2** compares a candidate with the live model on the same rows, paired. It requires: dev3f net
  wins > 0, severity-weighted net ≥ 0, E1 stories net ≥ 0, safety stories not lower, and no slice worse
  under a Holm-corrected sign test (`scripts/gate2.py`). It replaced a slice gate that failed equal models
  70-80% of the time.
- **Why blends:** every plain top-up forgot old skills (3e: compound −13 to −17 points; v2.1: status
  86.5 → 84.3%). A weight-space blend keeps most of the base and takes part of the new skill.

**Show:** the table above, plus `proofs/2026-10-21_v2_confirm/placement_s24/` for the placement plot.
**Why:** accuracy comes first; a model ships only if it beats the live one on paired rows.

---

## 6. Accuracy: the cross-domain reasoner

- **Model choice (P0, host):** Qwen3.5-4B was the only candidate with a reasoning score above 0.75 (0.80);
  its weighted total was 0.79 (`proofs/2026-10-23_reasoner_research/P0/host_bench/RESULTS.md`).
- **rsn_v1** = a QLoRA r32 fine-tune, checkpoint 612. On the host it scored RW6 0.99 (base 0.84), RWH 0.927
  (n=150, severity 0.919, label 0.878) and 0 ungrounded numbers. Its P0 total was 0.763 against the base
  model's 0.79, because chat regressed (`proofs/2026-10-25_reasoner_final/eval/results/summary_v3.json`, SPEC §10).
- **On the board** (30 RWH prompts, split-3): 30/30 parse, severity = gold 26-27/30, label = gold 24-25/30
  (`proofs/2026-10-27_reasoner_fast/RESULTS.md` §6; `final.log`).
- **Consistency:** the HTP is not bit-deterministic. Over 6 prompts × 5 runs, severity and label agree 97%
  of the time, and 100% with the light severity guard (RESULTS §0.1).
- **Severity guard:** when the rules put a flagged sensor at warning or critical, the reasoner may not
  report "normal". Every disagreement is logged (`reasoner_v3.go severityGuard`).

**Show:** the consistency table (RESULTS §0.1) and the RWH accuracy table (RESULTS §6).
**Why:** the reasoner owns the wording, but it must never talk an operator out of a real alarm.

---

## 7. What we rejected, and why

| candidate | result | source |
|---|---|---|
| v2.1 (continued SFT) | host400 pattern 87.7 → 85.3%; water status 72.7 → 63.6% | HANDBOOK 2.51 |
| model 3e (DPO + NLL) | compound −13 to −17 points; c49 tied | HANDBOOK 2.48 |
| P3 / P3b blends (replay + WiSE 0.5 / 0.7 / 1.0) | every one fails gate2; HVAC worse (P3B05 dev net −27, severity −65) | HANDBOOK 2.54b, `p3b_gate.txt` |
| T30 (the P2/P3 winner) | head to head vs B50: dev +7, CI [−19, +35], severity −13, E1 −4 → FAIL | `diag/gate2_T30_vs_B50.json` |
| rsn_v2 (round 2, Kaggle) | first board try: 1 of 3 prompts parsed; htpd stalled at 100% CPU on q11 | `FINAL_STATUS.md` |
| rsn_v2 retry (htpd_v8x3 fix) | DEPLOYED htpd_v8x3 + rsn_v1: app check PASS (chaos 3 3 3, fastcheck {"fast_incident": "INC-0433", "fast_s": 5.6, "ai_update_s": 47.2, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity": "sensor_fault", "title": "KH building, level 03: Suspect CO2 readings", "pass": true}) | `RSN_V2_RETRY.md` |

**Why:** a gain on the laptop (HF, teacher-forced) did not reliably carry over to the Q4_0 model on the
NPU, so every decision is made on the board or the faithful host GGUF proxy (207/208 rows agree, HANDBOOK 2.45).

---

## 8. Latency: the ladder

| step | what changed | measured | source |
|---|---|---|---|
| Genie (mid-eval) | persistent NPU dialog, ctx 2048 | single call 3.64 → 2.54 s; chaos 11-13 agents 41-57 s | old deck, HANDBOOK 2.22-2.24 |
| htpd batching | all agents in one weight sweep, per-stream flash attention, verified n-gram drafts, prefix cache | chaos 12 agents + synthesizer 46-48 → 20.7 s | HANDBOOK 2.37 |
| reasoner added | Qwen3.5-4B swapped into htpd | event → report 30-43 s | RESULTS §5 |
| OPPOLL | host polls for HTP completions | reasoner 27.8 → 25.8 s (−7%), lossless | RESULTS §2 |
| split decoding | head once, then 3 field groups in parallel | 25.7 → 23.7 s (30 RWH); 25.6 → 21.7 s (10 prompts) | RESULTS §6 |
| two-stage report | preliminary first, the AI report replaces it | preliminary 1-7 s after the event; done 28-39 s | RESULTS §6-7 |
| retrieval preliminary | nearest past AI reports, live values | preliminary 0 s after the incident opens | `RAG_STATUS.md` |

**Show:** this table, plus `proofs/2026-10-27_reasoner_fast/screens/` (injected → title → done).
**Why:** the operator needs something useful at once, while the full AI report follows within a minute.

---

## 9. Latency: the roof, and what did not help

- **Bandwidth roof:** one reasoner token takes 60 ms on the HTP and reads 2.6 GB of weights at about
  52 GB/s. Decode is 87% of the reasoner time. Per stream, nothing beats about 17-20 tok/s on this SoC
  (RESEARCH.md §0-1, `GPU_RESEARCH.md` §4).
- **Rejected:** MTP speculation (72-78% acceptance, still +1 to +20%); n-gram speculation (+7 to +11%,
  doubles prefill); a Q4_0 lm_head (−4%, but moved an RWH label); the Hexagon SDK route (upstream llama.cpp
  and a new 32x4 HVX kernel: reasoner +3 to +6%, agents −4 to −5%, net about zero). Sources: RESULTS §1, §2, §8.1.
- **The split-6 HMX finding:** a 6-row step costs 106 ms, less than a 3-row step (113 ms), because from 5
  rows the HMX path takes over (`raw/bench_server/llama_bench.md`). Tonight split-4 gave 21.2 → 21.0 s
  (−1%, same gold scores) and failed its app check. Split-6 does not fit the NPU session memory at
  6 × 4096. Split 3 stays (`split_post.log`, `raw/split_post/acc.md`).
- **GPU reasoner (deduction, not deployed):** about 19-20 s per report, against about 24 s today. It would
  remove the 3.6 s swap and let agents and reasoner overlap during bursts (`GPU_RESEARCH.md` §2).
- **Pruned lm_head:** on hold. The board rebooted during its first A/B, cause inconclusive (RESULTS §9).

**Why:** a fast wrong answer is worse than a slow right one. Every lever was gated on identical decisions.

---

## 10. Real-world latency: sensor time, not compute time

- Real sensors send one reading per 5 minutes. The AI gate (8 abnormal readings) plus the batch window
  (up to 3 more) means **40-55 minutes of sensor time** before the AI runs (`fastpath.go` header, HANDBOOK 2.55).
- The agents were trained on events at least 7 readings old. At 40 minutes they read events less well
  (v1 42%, v2 73.8%), so simply calling earlier would cost accuracy.
- **Critical fast path (live):** 2 fresh readings past the critical limit open the incident at once with
  the rules report. The AI updates the same incident at 8 readings. Tonight on the board: fast incident
  in 6.3 s, then the AI on the same incident at 55.2 s (`FINAL_STATUS.md`).
- **Planned, built but off:** early AI at 4 readings for shapes the gate study clears (`earlyai.go`,
  `ai_early_k`). It needs the gate study and the young-window top-up, which were not run because the
  laptop GPU was returned to the owner (`gate_study/`, `young_window/`).

**Show:** the timeline: reading 1 → 2 (fast incident) → 8 (AI) → 11 (batch closes).
**Why:** for a real campus, minutes of waiting for evidence matter more than seconds of NPU time.

---

## 11. Retrieval preliminary (new tonight)

- Every finished AI report is indexed. The index has a structured vector (role, metric, pattern, status,
  magnitude bins, time of day) and TF-IDF over the title, cause and observations (`retrieval.go`).
- A new incident is matched only against reports with the same role and metric, scored 0.7 structured +
  0.3 text, above a threshold tuned so the retrieved severity agrees with the AI's at least 90% of the time.
- **Hit:** the preliminary uses the retrieved label, action and wording, but numbers come from the live
  values only. Severity = max(rules, retrieved), so it cannot under-alert.
- **Miss:** the rules report, with "full AI report coming". It runs on the CPU in under 5 ms.
- **Board:** PASS: 4/4 incidents had a preliminary within 2 s and the AI report on the same incident; fastcheck {"fast_incident": "INC-0427", "fast_s": 5.5, "ai_update_s": 47.5, "final_model": "deterministic (related domains verified steady)", "valid": true, "severity": "sensor_fault", "title": "CO2 step incr... (2 of 4 incidents hit; edge-agent ebd08e13).

**Show:** the RAG_STATUS.md table (incident, preliminary basis, AI report on the same incident).
**Why:** the first report should be as good as possible without a new model or extra NPU time.

---

## 12. Robustness and safety

- **Board rules:** one NPU client at a time; every board request starts at ≤ 60 °C; never reboot; big
  files are copied as .part + md5 + mv.
- **Rollbacks:** every deploy snapshots the known-good state first (`final/known_good`,
  `rag_build/known_good`), and a failed app check rolls back automatically.
- **Watchdog:** a stalled htpd (≥ 90% CPU for 10 minutes with no log growth) is sent SIGTERM. The supervisor
  restarts it, and a bad batch answer is re-run alone.
- **Policy gate:** valid JSON, whitelisted enums, only evidence ids that exist, no actuation; a human
  approves every action.
- **Proofs discipline:** every result has raw data, a manifest and a log in `proofs/<date>_<topic>/`.
  Nothing is overwritten; a rerun gets a new folder.

**Show:** `OVERNIGHT_PLAN.md` (the chain, with the "if it fails" column).
**Why:** a demo board that reboots during the evaluation would erase every other result.

---

## 13. Results today

| part | live | evidence |
|---|---|---|
| final app check | PASS: chaos 6/6 done and valid; fast path 6.3 s → the AI on the same incident at 55.2 s | `FINAL_STATUS.md` |
| agents | B50 (`ft_B50_q4_0.gguf`) | `final/agents_why` |
| reasoner | rsn_v1 (`qwen35_reasoner_q4_0.gguf`); rsn_v2 retry: DEPLOYED htpd_v8x3 + rsn_v1: app check PASS (chaos 3 3 3, fastcheck {"fast_incident": "INC-0433", "fast_s": 5.6, "ai_update_s": 47.2, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity": "sensor_fault", "title": "KH building, level 03: Suspect CO2 readings", "pass": true}) | `FINAL_STATUS.md`, `RSN_V2_RETRY.md` |
| split decoding | 3 (split-4 −1% only and failed its app check; split-6 does not fit) | `split_post.log` |
| retrieval preliminary | PASS: 4/4 incidents had a preliminary within 2 s and the AI report on the same incident; fastcheck {"fast_incident": "INC-0427", "fast_s": 5.5, "ai_update_s": 47.5, "final_model": "deterministic (related domains verified steady)", "valid": true, "severity": "sensor_fault", "title": "CO2 step incr... | `RAG_STATUS.md` |
| app / daemon | edge-agent ebd08e13 (retrieval build on top of fast-path c97afdeb), htpd_v8x2 | `RAG_STATUS.md`, `FINAL_STATUS.md` |
| B50 chaos through the app | 6/6 valid; wall time 38.8-51.5 s, tank leak 98.9 s | `CHAIN_STATUS.json` |

**Why:** the evaluators asked for evidence. Each row points to the file that proves it.

---

## 14. Limits and next steps

- **Limits.**
  - Most labels come from injected faults on real calm windows. Real facility-log events are still missing.
  - Occupancy pattern labels are circular with the rules (HANDBOOK 2.36).
  - Recurring small spikes are still missed.
  - The board runs hot (89-94 °C in back-to-back chaos runs) and needs a heatsink.
  - The AI needs 40-55 minutes of sensor time, except on the critical fast path.
- **Next steps.**
  - Run the gate study and the young-window top-up, then switch on early AI for the shapes that pass.
  - Fill the retrieval library with seed reports.
  - Measure the GPU reasoner: coexistence memory test first (`GPU_RESEARCH.md` §4).
  - Retry the pruned lm_head under the guarded script.
  - Run rsn_v2 again if the retry fails, and build a real-event test set from the new raw data.

**Why:** we report what is not solved as clearly as what is.
