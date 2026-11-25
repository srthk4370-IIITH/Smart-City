# Research paper plan: question, corrections, data and runs (2026-11-20)

Written by Claude Opus 5. This is a response to Rishit's final-question proposal, checked against the stored October proofs.

**Status:** plan only. **Nothing here has been run.** The runs start after the big reasoner is gated and decided, with polish and fog done (`status.md`).

---

## 1. The research question (accepted, with one wording change)

> On an edge NPU that holds one large model at a time, serving a workload where ~86 % of incidents are single-domain, **when is it worth escalating** from a cheap path to a decomposed multi-agent path with a cross-domain reasoner, and **does that escalation pay** in grounding and diagnostic accuracy?

- **RQ1, cost:** what escalation costs. That is the agent stage plus the reasoner swap plus the 4B reasoner decode, against one call.
- **RQ2, benefit:** what escalation buys at N = 2–5 domains, the regime that actually occurs.
- **RQ3, trigger:** whether "2 or more domains" is the right escalation trigger, or whether domain count is the right trigger at all. Alternatives: severity, a disagreement between rules and agent, agent uncertainty, cross-domain links in the site tree.

The `isolatedReport` short-circuit (fewer than 2 domains means no reasoner call) becomes **the routing policy under test**, not a confound. A negative result ("collapse the path") counts as a valid outcome.

## 2. Corrections to the two retractions (from the October proofs)

Sources: `proofs/2026-10-16_htpd_v6_app_stress_report_final.json` (v6) and `proofs/2026-10-21_v2_app/stress/stress_report.json` (v2). Total incident time is in seconds; "calls" means NPU calls.

| Domains | Mode 2 (v6 / v2) | Mode 3 (v6 / v2) |
|---|---|---|
| 1 (median) | 4.3 s / 2.3 s, 1 call | **3.1 s / 2.8 s**, 1–3 calls |
| 2 | 3.6 s / 2.6–3.8 s, 1 call | **7.5 s** (3 calls) / – |
| 3 | not run | 6.9 s (3 calls, v2) |
| 4–6 | **not run** | 16.3–32.5 s (9–15 calls) |
| "42–47 s" | n/a | full AI report of one later multi-domain chaos incident (rsn_v1 reasoner era) |

**Correction to retraction 1:**
- At 1 domain, Mode 3 is **not slower**: about 3 s, the same as Mode 2.
- At 2 domains the measured ratio is about **2×** (7.5 vs 3.6 s), not 10–20×.
- The 10–20× figure compares Mode 2 at 1–2 domains with Mode 3 at 4–6 domains. **Mode 2 was never run at 3 or more domains,** so no paired ratio exists there yet.
- The conclusion stands that decomposition costs latency as N grows. The size of that cost is **unmeasured**, which is exactly RQ1.

**Correction to "~0 LLM on 86 %":**
- The short-circuit skips only the **reasoner**. A single-domain incident still runs its 3B domain agent on the NPU (1–3 calls, about 3 s), plus the CPU context agents.
- So the cheap path is "one specialist agent plus a rules template", not "no LLM".
- That is still cheap, and the routing story holds. Escalation adds the other agents, the 2.8–2.9 s swap and the 4B decode.

**Era caveat:**
- All the October numbers used an older stack: ft_B50 agent, rsn_v1 reasoner, htpd v6, the 8-in-a-row gate.
- The current stack is agt3_s0450, rsn_v3_4b_p2 (or the big top-up), htpd v9h with split decoding and verified drafts, and the 4-of-8 gate.
- **Every number in the paper must be re-measured on the current stack.** The October models can't be rebuilt from what's left, because their GGUF files were deleted (`status.md`).

Retraction 2 is accepted as written: a crossover at N = 8–12 is a stress figure, not the result.

## 3. Frozen data sets

Every set is frozen as full sensor-window JSON, with a SHA256 manifest, before any run. There is no regenerated jitter. The split is time-based: hold out the last weeks of campus replay.

| Set | Size | Content | Carries |
|---|---|---|---|
| **A, natural replay** | 200 | sampled from the 433 archived real incidents plus campus replay, matching the measured 86 / 7 / 7 mix (1 / 2–4 / 5+ domains) | routing and operator-value claims; short-circuit rate |
| **B, cross-domain core** | ~150 paired, N ≥ 2 | 40+ curated real multi-domain incidents (genuine co-occurring events, not start-up bursts), then injected cases to reach 150; strata N = 2, 3–4, 5+; **real and injected never pooled in a headline number** | RQ2 |
| **C, stress sweep** | 10 repeats each at N = 1, 2, 4, 8, 12 (synthetic) | latency, prefill tokens, swap, TTFT, stream cap (`--agents 10`: N = 12 means 10 parallel plus 2 queued) | RQ1; every N ≥ 8 figure labelled synthetic |
| **D, negative controls** | ~50 normal windows plus ~15 genuine sensor-fault windows | the right answer is "nothing is wrong", or a real sensor fault | false-alarm rate, false sensor_fault rate, fault/event confusion both ways |
| **E, host held-out** | 150 (laptop, Q4_0) | Mode 2-as-built vs **Mode 2-fair** (reasoner model, reasoner prompt, no agent findings) vs Mode 3 | the missing fair comparison; no board time |

The real-data supply is thin. Only about 40 of the 433 archived real incidents are multi-domain, and many of those are start-up bursts, so real-only Set B may reach roughly 20–40 cases once curated.

## 4. Leakage controls (must run before any scoring)

1. **Retrieval memory leak.**
   - Mode 3's reasoner prompt includes retrieved past incidents (memory M# lines). Mode 2 has none.
   - Before the runs: diff the retrieval index (seed reference cases plus stored finished reports) against the frozen sets. Either purge the overlaps or freeze the index at a timestamp before the test window. Report the retrieval-hit rate per case.
   - Ablation: Mode 3 with retrieval off.
2. **Training-distribution leak.**
   - 140,690 of the 163,567 rows that trained the deployed models are synthetic.
   - Injected Set B cases come from the same generators, so report them separately from real cases. Real cases come from the held-out time window, after the training data cut-off.
3. **Gate-set overlap.** The frozen sets must not overlap any training, dev or gate set. The existing checks hash the sensor-window E-lines; reuse them.

## 5. Arms and ablations
- **Mode 1:** rules.
- **Mode 2-as-built:** agent model plus the old `singlePrompt`.
- **Mode 2-fair:** reasoner model plus the reasoner's prompt, with no agent findings and no tools.
- **Mode 3:** the deployed pipeline.
- **Ablations on Mode 3:**
  - no retrieval;
  - no tools / no more-data;
  - no context agents;
  - no guards;
  - reasoner forced on at N = 1;
  - alternative triggers for RQ3.

## 6. Per-case logging
Each case records:
- mode; N domains; N flagged sensors;
- prefill tokens; TTFT; decode ms; swap ms (separately); `total_ms`;
- start temperature; warm or cold; stream occupancy if available;
- tool calls; retrieval hits; gate rejections; retries; fallback fired; short-circuit fired;
- the full report JSON.

## 7. Metrics
- **Headline:** root-cause label accuracy on Set B (real and injected reported separately), with the **missed-critical rate** as the safety floor.
- **Primary:**
  - severity macro-F1 and confusion matrix;
  - affected-domain set F1;
  - evidence-id validity, evidence coverage, ungrounded-number rate;
  - false sensor_fault rate (Set D).
- **Root-cause text:** judged by a human or a local LLM judge, on anonymised reports with the mode field stripped and the order shuffled.
- **Appendix:** BLEU, ROUGE-L, chrF, BERTScore. Demoted because part of the gold text is self-distilled.
- **Statistics:** bootstrap 95% confidence intervals; McNemar for accuracy, Wilcoxon for latency; minimum effect fixed in advance (10 points on labels, about 150–200 pairs).
- **Baselines:**
  - **No cloud frontier model** (the privacy framing).
  - The ceiling is a larger **local** model run offline on the laptop, for example a 14B Q4 if it fits the 8 GB GPU with offload, or Kaggle.
  - Classical baselines: rules, Isolation Forest, seasonal decomposition with thresholds.

## 8. Order (after the reasoner decision)
1. Freeze the sets and write the manifests (about 1 day: curating real Set B, the gold labels, Set D).
2. Leakage diff and retrieval freeze (about 2 h).
3. Prefill table, host only (about 2 h).
4. Set E on the host (about half a day; can run alongside board work).
5. Board: Set C stress (about half a day, with cooldown curves), then Sets A, B and D (about 1.5 days).
6. Scoring, statistics, `RESULTS.md` (about 1 day).

## 9. Open decisions (asked through AskUserQuestion)
- Who labels the real cases.
- The local ceiling model.
- The RQ3 candidate triggers.
- How much board time is available.
- Whether the paper's systems section stays in.

## 10. Owner decisions (2026-11-20)
- **Main question:** the escalation / routing question as written (RQ1 cost, RQ2 benefit at 2–5 domains, RQ3 trigger). A negative result is acceptable.
- **Labels:** **injected cases only for now** (truth known by construction). Labelled real cases come later, as future work or an extension once real data can be uploaded and labelled.
  - Set A (natural replay) and the real part of Set B are run and logged, but **not scored for accuracy** in this version. They carry only cost, routing-rate and short-circuit numbers.
  - Accuracy claims come from injected Set B and Set D, and must be stated as such.
- **RQ3 triggers to compare against "2 or more domains":**
  - any critical sensor;
  - rules vs agent disagreement;
  - agent uncertainty (low confidence, or it asked for more data);
  - site-tree links (flagged sensors linked by room, floor or feed).
- **Ceiling model:** to be discussed later.
- **Injected test cases:** faults are injected into **real held-out campus windows** (the last weeks of replay), so the background noise and daily cycles are real. The test injection generators stay separate from the training generators.
- **Board time:** runs start right after the reasoner decision (freeze and host work first, then about 2 board days).
- **Systems section:** kept, but only as RQ1 support (swap, streams, drafts, thermal pacing). Not a separate systems paper.

## 11. Rishit's additions (2026-11-20, accepted into the plan; to apply before freezing)
1. **One board pass, triggers evaluated offline.** Run **both arms** (cheap path and full path) on every case once. Record both outcomes plus every trigger's input signal:
   - the critical flag;
   - rules-vs-agent agreement;
   - agent confidence and whether it asked for more data;
   - site-tree links;
   - the domain count.

   All five policies (and any later ones) are then evaluated offline against that table, so the trigger study can be re-run without board time.
2. **Force the full path on single-domain cases.** About 50 cases from Set A, weighted toward criticals and rules-vs-agent disagreements. Without them, missed escalations can't be measured, only wasted ones.
3. **Oracle and trivial baselines.**
   - The oracle escalates exactly when the full path is right and the cheap path is wrong. It's the ceiling, and not implementable.
   - Always escalate and never escalate. At about 2× cost, "always" is a serious baseline.
   - **The main figure is a cost–accuracy curve:** share escalated on x, root-cause accuracy on y, each trigger as a point, the oracle as the frontier.
   - Score the triggers as a detection problem: precision and recall against the oracle.
4. **Extended leakage check.**
   - **Window level:** the host windows must not be in the retrieval corpus; freeze the corpus before the test window.
   - **Fault-family level:** list the injected fault families against the training manifest (140,690 of 163,567 training rows are synthetic) and report the overlap explicitly.
5. **Pilot the discordance rate first.** Run about 30 Set B cases and count how often the two arms disagree. If discordance is well below the 20–30% assumed, increase n or change the primary endpoint before spending the 2 board days.
- **Scoping line, to sit next to the trigger results (not only in Limitations):** every accuracy number is conditional on injected faults being representative. The disagreement and uncertainty triggers may behave differently on messy real faults.
- **Owner (2026-11-20):** the cheap path at every N is **domain agents plus the template report** (`isolatedReport`, no reasoner). Escalation means adding the reasoner. Mode 2-fair stays a separate host-only arm (Set E).
- **Board time:** about 3–4 board days. Day 1 is the 30-case discordance pilot plus the freeze; the final n is set from the pilot before the full runs.
