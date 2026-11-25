# For Rishit: evaluation plan and the questions to settle before the final runs (2026-11-20)

Written by Claude Opus 5.

**Context.** The final evaluation runs after polish, the big-reasoner top-up (gate about 22:00–23:00 IST today) and fog are done. Current state: `status.md`. Mode 2/3 confounds: `answer_rishit.md`.

## 1. What will be on the board when we evaluate
- **Domain agent:** `agt3_s0450` (Llama-3.2-3B LoRA, Q4_0, Hexagon NPU, up to 10 parallel streams, tool calls).
- **Reasoner:** `rsn_v3_4b_p2`, or the "big" top-up if its gate passes and you approve (Qwen3.5-4B, edited and fine-tuned, Q4_0, split decoding with verified drafts).
- **App:** the 4-of-8 rules gate, early AI on criticals, the orchestrator with context agents, retrieval memory, guards, refinement, the operator workflow, on-board chat with voice, and fog (Supabase, reports only).
- **What is fixed:** decoding is greedy everywhere, so outputs are deterministic for a given prompt.

## 2. What I plan to measure (tell me what to add, drop or re-weight)

### A. Text and report quality
- BLEU, ROUGE-L, chrF and BERTScore against gold report text, per model and per family.
- Exact match on the structured fields: severity, label, affected domains, suspect sensors.

### B. Diagnostic accuracy (the main application claim)
- Severity accuracy and macro-F1 per class (normal, warning, critical, sensor_fault), with a confusion matrix.
- Root-cause label accuracy and macro-F1, and affected-domain set F1.
- **False sensor_fault rate**, a key operator metric. **Missed-critical rate** (recall on critical), the safety metric.
- Calibration: expected calibration error of the reported confidence.

### C. Grounding and faithfulness
- Evidence-id validity: cited ids exist in the input.
- Evidence support: the cited line actually supports the claim, judged by an LLM judge plus a human sample.
- Hallucination rate: numbers, times or ids that are not in the input.
- Coverage: the share of alerting sensors the report addresses.

### D. Reasoning by type
- Accuracy split by reasoning type: pairwise, transitive, multi-hop, causal chain, counterfactual.
- Accuracy split by number of domains (1, 2, 3–4, 5 or more).

### E. Tool use (agents and reasoner)
- Call needed and made, tool choice accuracy, argument validity.
- Two-call chain completion; results used faithfully; unneeded-call rate.

### F. Chat
- Answer correctness (gold facts), format compliance, refusal correctness, context-bleed rate.
- Tool sequence vs gold; latency.
- Voice word error rate (whisper tiny.en) on a small spoken set.

### G. Architecture comparison (the controlled ablation)
- Mode 1 (rules) vs Mode 2-as-built vs Mode 2-fair (same model and inputs as Mode 3's reasoner, no agents) vs Mode 3.
- Measured on the same frozen incidents: B, C and D above, plus latency.
- Ablations: no tools, no retrieval memory, no context agents, no guards, base model vs fine-tuned, 1 agent vs parallel.

### H. Systems
- Per-stage latency: rules gate, agents (TTFT and decode), swap, reasoner, total; p50 and p95.
- Prefill token counts by N; tokens/s and parallel scaling from 1 to 10 streams.
- Thermal curve over a sustained run; cooldown time.
- Memory footprint; energy per report (battery fuel-gauge proxy).
- Host vs device accuracy gap (Q4_0 on the laptop vs the NPU on the board).
- Uptime and recovery in a 24–72 h soak: restarts, watchdog failovers, queue drops.

### I. Operator value
- Alert-flood reduction: breaches vs incidents vs criticals per day.
- Time from alarm to an actionable report, with sensor time and compute time shown separately.
- Dismissal and false-alarm rate on real replays; checklist usefulness (human rating).

### J. Privacy and edge
- Bytes leaving the device per incident: expected 0 raw readings; only report rows, if fog is on.
- Offline operation: everything works with the network unplugged.

### K. Statistics
- 95% confidence intervals (bootstrap). Paired tests: McNemar for accuracy, Wilcoxon for latency.
- Effect sizes; the minimum effect and n fixed before running (about 150–200 paired incidents for a 10-point label difference).

## 3. Questions for you (please answer each)

### Paper and claims
1. **Target venue and deadline.** These set the page budget and rigour; edge AI, IoT, applied NLP and systems venues expect different things.
2. **Main claim.** Pick one or two:
   - (a) multi-agent beats single-call on cross-domain diagnosis;
   - (b) a full agentic pipeline runs on a phone-class NPU in practice;
   - (c) fine-tuned small models match larger ones;
   - (d) operator value: fewer, better alerts.
3. **Systems and application in one paper or two?** (I recommend two, or clearly separate sections.)
4. **Baselines you need:**
   - rules only;
   - single-call small model;
   - **a cloud frontier model** (for example, an API model on the same incidents, report text only);
   - classical anomaly detection (Isolation Forest, or seasonal decomposition with thresholds);
   - published works (see `proofs/2026-11-19_prod_audit/FINDINGS.md`, research section).

   Is a cloud baseline allowed, given the privacy rule? Only synthetic or replayed report text would go out.

### Data and ground truth
5. **Gold source.** I propose: injected faults (known by construction) plus curated real multi-domain replays with labels you or a domain expert confirm. Who labels the real ones, and how many?
6. **Test set size.** Fix it now: about 200 incidents across 1, 2, 3–4 and 5+ domains, plus 100 chat questions? Is that acceptable?
7. **Held-out guarantees.** Freeze and hash the test set before any final training, and use a time split (the last weeks of campus data) or a building split. Which split?
8. **Real vs synthetic share.** What minimum share of real or replayed incidents do you want in the headline numbers?

### Metrics and judging
9. **Headline metric for the abstract:**
   - severity macro-F1;
   - root-cause accuracy;
   - false sensor_fault rate;
   - missed-critical rate;
   - or a weighted operator score.
10. **LLM-as-judge for evidence support and root-cause text:** allowed? Which judge model? A human agreement check on a 10–20% sample?
11. **Human evaluation:** who rates checklist usefulness and report clarity (facilities staff, you, students)? How many raters, blind to mode?
12. **BLEU and similar:** keep them as secondary metrics only (they measure surface overlap, not correctness)?

### Experiments
13. **Ablations:** which are must-have (tools, memory, context agents, guards, fine-tune vs base, edited vs plain reasoner, Q4_0 vs FP16)?
14. **N sweep:** 1, 2, 4, 8, 12, with 8 and 12 reported as stress or synthetic only?
15. **Energy:** is the battery fuel-gauge proxy enough, or should we borrow a USB power meter?
16. **Soak test length:** 24 h or 72 h, and does it need the network unplugged (offline proof)?

### Logistics and limits
17. **Board time:** the evaluation needs about 2–3 days of board time (a grid of about 600 runs plus replays, at 2–3 h per 100 with cooldowns). Is that available, and is a fan or heatsink possible?
18. **Kaggle and laptop GPU budget** for host-side evals (Mode 2-fair on held-out data, BLEU and BERTScore, judge runs).
19. **Reproducibility:** should I re-export and archive every evaluated GGUF with checksums and keep it (C: space), since the October ones are gone?
20. **Release:** code, test set and models public, private, or "on request"? Real campus data stays private.

## 4. What you get back after the runs
- A results pack, `proofs/<date>_paper_eval/`:
  - every metric with confidence intervals and the confusion matrices;
  - per-stage latency tables, prefill tables, the thermal curve;
  - ablation tables and the N sweep;
  - the raw incident JSON for every case;
  - the frozen test-set manifest with hashes;
  - a one-page RESULTS.md with each claim and its evidence.
- A paper-ready table and figure set on the private website.
- An honest limitations list: single site, replayed data, synthetic share, host vs device gap, sensor-time latency.
