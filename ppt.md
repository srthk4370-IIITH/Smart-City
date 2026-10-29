# Agentic Edge AI for Smart Cities: the final evaluation deck

Final evaluation, 2026-10-29, 12:00 IST. Team NASA (esw-m26-14).

The deck tells one story: **a CO2 alarm in a campus room, followed from the first reading to the person
who fixes it**. Along the way it shows what runs on the board today, how we know it works, what we tried
and threw away, and where it goes next.

Every slide has a title, the bullets, what to show, and a **Say** line for the speaker. Every number comes
from a file in the repo (the source is named). Numbers are measured on the QIDK unless marked "host"; host
runs use the same Q4_0 model files, which agree with the board on 207 of 208 rows. The full fact sheet is
`proofs/2026-10-28_master/FACTS_2026-10-29.md`.

---

## 1. A room on campus, 2:10 in the afternoon

- KH building, level 3. The CO2 sensor jumps to 2000 ppm.
- A threshold alarm would say "CO2 high" and stop there. Is it people? Broken ventilation? A faulty sensor?
- Our system says *why*. It connects CO2, occupancy, AC and power across domains, writes a report a
  person can act on, and asks before anything is done.
- **All of it runs on one Qualcomm QIDK board**: Snapdragon 8 Gen 3, Hexagon V75 NPU, Android 14. There is
  no cloud and no laptop.

**Show:** the app's live tab with the KH level-3 incident (fastcheck run, `proofs/2026-10-27_reasoner_fast/raw/fastcheck_*.json`).
**Say:** "Let's follow one alarm from the sensor to the person who fixes it."

---

## 2. Why it has to be on the edge

- **Privacy.** Room-by-room occupancy over time shows where people are. That data never leaves the board.
- **Seconds, not round trips.** A critical reading opens an incident in **5.6 s** on the board.
- **Works offline.** If the campus uplink fails, the monitor keeps watching and reporting.
- **Real causes cross domains.** A crowded room raises CO2, room power and cooling load together. Rules
  can see each line; they cannot connect them.

**Say:** "Cloud LLMs could write the report, but they can't see the data, can't promise seconds, and stop
when the network does."

---

## 3. The board today: what is live right now

| part | what runs | where |
|---|---|---|
| backend | Go `edge-agent` **b770aa57**: statistics, rules, data-quality gates, workflow, API, UI | CPU |
| domain agents | **B50**: our fine-tuned Llama-3.2-3B blend, one agent per abnormal sensor, all in one batch | NPU |
| reasoner | **rsn_v1**: our fine-tuned Qwen3.5-4B, writes the cross-domain report | NPU |
| NPU daemon | **htpd_v8x3**: our llama.cpp Hexagon server (batching, split decoding, safety guards) | NPU |
| retrieval | **254** reference reports plus every live AI report, used for the instant first report | CPU |
| app | Android foreground service, dashboard, checklist workflow | phone UI |

- Final app check after this morning's deploy: **2 of 2 chaos scenarios done and valid**. In fastcheck the
  fast path opened the incident in **5.6 s** and the AI report followed on the same incident at **42.2 s**
  (`proofs/2026-10-28_master/improve2/STATUS.md`).
- One model sits on the NPU at a time; htpd swaps agents ↔ reasoner in 4.6 s.

**Say:** "Everything on this slide is what is installed on the board in front of you, checked this morning."

---

## 4. Second 0 to 6: the alarm becomes an incident

- Every sensor sends a reading every 5 minutes. The CPU keeps statistics and rules for each one.
- **Critical fast path:** 2 fresh readings past the critical limit open the incident at once, **5.6 s** on
  the board, before any AI runs.
- Within the **same second** the operator sees a **first report**:
  - **retrieved**: built from the most similar past AI reports, using the live numbers. Shown as
    "Preliminary: based on N similar past incidents (best match X%, INC-…), full AI report coming";
  - **or rules**: "Preliminary from the rules, full AI report coming" when nothing similar exists.
- **The checklist is live immediately (new today):** the operator can say "I'm on it" and start ticking
  steps while the AI is still thinking.

**Show:** the preliminary banner and checklist on the incident sheet.
**Say:** "Nobody waits for the AI to know something is wrong. The AI makes the answer better; it does not
make the alarm slower."

---

## 5. RAG: the instant first report, and how good it is

- **Hybrid retrieval, no extra model** (`backend/retrieval.go`). It scores 70% on a structured match
  (same role and metric, pattern, status, values) and 30% on TF-IDF over the report text.
- **Safe by design:**
  - numbers always come from the live sensor, never from an old report;
  - severity = the higher of the rules and the retrieved report, so the preliminary never under-alerts.
- **The library grows by itself.** Every validated AI report is added, alongside 254 reference reports our
  reasoner wrote on the training split (320 written, 254 passed the gate). Seeds rank 3% below live reports.
- **Board check** (`RAG_STATUS.md`):
  - 4/4 incidents had the preliminary at 0 s, and the AI report replaced it on the same incident;
  - retrieval matched 2/4 and the rules covered the rest.
- **Consistency check:** after the AI report lands, the app compares it with similar past incidents and
  logs any disagreement, e.g. "AI severity sensor_fault differs from 1 of 3 similar past incidents".

**Say:** "This is RAG for speed and consistency. Past AI work answers the first second; the live AI
answers the next half-minute."

---

## 6. Second 6 to 12: the domain agents

- Each abnormal sensor gets a domain agent (air quality, water, power, HVAC, occupancy, weather). All of
  them run **in one NPU batch** inside htpd.
- One agent takes **5.9 s** (first token 0.7 s), and a 12-agent incident **20.7 s**. With Genie it took
  46-48 s (HANDBOOK 2.37).
- **B50** is a weight-space blend of our v2 fine-tune and a top-up, chosen by gate2, our paired acceptance
  test:
  - severity-weighted net **+61** against the previous live model;
  - E1 stories **+4**;
  - safety **16/16**;
  - no slice worse (`proofs/2026-10-25_domain_plan/B50_STAGED.json`).
- Post-rules and the policy gate check every answer: valid JSON, allowed values, real evidence ids, no
  actuation language.

**Say:** "Six specialists look at their own sensors at the same time, on the NPU, in one sweep over the
weights."

---

## 7. Second 12 to 42: the reasoner writes the report

- htpd swaps in the reasoner, **rsn_v1** (Qwen3.5-4B, our QLoRA). It reads every agent's finding plus the
  related sensors and writes:
  - the title, severity, label and root cause;
  - the causal chain;
  - observations with evidence ids;
  - claim checks on the agents;
  - a checklist.
- **Split decoding:** the head is written once, then 3 field groups are decoded as parallel streams.
  - Reasoner time is **21.6 s** (`x2x3_ab.result`), down from 27.8 s before OPPOLL and split decoding (RESULTS §2, §6).
- **Accuracy, rsn_v1** on 150 held-out incidents (host Q4_0, `summary_v3.json`):
  - severity **91.9%**, label 87.8%, valid JSON 98.7%;
  - **0%** ungrounded numbers, 0% unit errors, 0% actuation, 0% prompt injections followed.
  - On 6 real-world stories the label is right 6/6.
- **New today, report contract repairs:** two rules the training data always follows are now enforced in
  the gate.
  - "Normal + needs more data" gets the label `unknown`, and a title location must come from the input.
  - Replayed on **386 board answers**, label accuracy goes **83.2% → 87.6%** with 0 new errors.

**Show:** the incident sheet before/after the AI report (`proofs/2026-10-27_reasoner_fast/screens/`).
**Say:** "The first report is fast. This one is right, and it says why."

---

## 8. The handover to a person

- The AI report replaces the preliminary **on the same incident**. The checklist merges in, and nothing
  is lost:
  - steps the operator already ticked that the AI also recommends **stay done** and take the AI's reason;
  - preliminary steps the AI no longer suggests are withdrawn;
  - new AI steps are marked "New since you acknowledged".
- The person stays in charge: acknowledge, then "Done" / "Not needed" per step, then close with an
  outcome. Nothing switches on its own.
- At **1.5 h and 3 h** of sensor time the incident is re-checked. The severity can rise, fall, or the
  incident resolves.
- A critical incident nobody has acknowledged re-alerts after 15 min.

**Say:** "The AI recommends. People decide. The system remembers who did what."

---

## 9. How we know the numbers are real

- **Paired tests on the same rows**, with confidence intervals and sign tests (gate2). A new model ships
  only if it is not worse anywhere that matters.
- **Through the real app** on the board: chaos scenarios (crowded room, ventilation failure, off-hours
  presence, leak), stress and fault injection, with screenshots and raw JSON in `proofs/`.
- **Host proxy**: the same Q4_0 file on the laptop agrees with the board on 207/208 rows, so large test
  sets run on the host and the decisions are confirmed on the board.
- **Safety nets on every answer**:
  - the policy gate and post-rules;
  - the **severity guard** (the AI may not say "normal" when the rules say warning or critical);
  - a deterministic fallback report;
  - severity agrees 97% over 5 runs, and 100% with the guard.

**Say:** "Every number on these slides has a folder behind it."

---

## 10. This morning: three decisions made on evidence

- **rsn_v2 (our second reasoner round) was rejected.** On the same 106 held-out incidents:

  | | rsn_v1 (live) | rsn_v2 |
  |---|---|---|
  | severity right | **94.7%** | 87.6% |
  | label right | **88.4%** | 85.6% |
  | claim checks found | **90%** | 81% |

  On the board v2 was 10% faster but invented a building in one title and misread 324 > 300 ppm. Accuracy
  comes first, so v1 stays.
- **The GPU is not a latency path.** The reasoner on the Adreno 750 (upstream llama.cpp OpenCL) decodes at
  7-8 tokens/s, against about 20 on the NPU (`gpu_bench_out/out.md`).
- **One more split shape was tested and dropped.** Forking after the label gave 22.2 vs 22.2 s.

**Say:** "Saying no with data is part of the work. Each of these would have looked like progress and made
the system worse."

---

## 11. The latency story, end to end

| what | time on the board |
|---|---|
| critical breach → incident open | **5.6 s** |
| incident → first report on screen | **0 s** (same second) |
| one domain agent | **5.9 s** |
| reasoner report | **~22 s** |
| full AI report from the incident start | **42-47 s** |

- The ladder: Genie chaos (11-13 agents) 41-57 s → htpd batching 20.7 s for 12 agents. Reasoner: 27.8 s →
  OPPOLL 25.8 s → split decoding **21.6 s**.
- **Honest limit:** for non-critical events the AI waits for 8 readings × 5 min = **40-55 min of sensor
  time**, because young windows are hard to read reliably. Critical events skip the wait (fast path), and
  every incident shows a first report at once. For the prototype this is the right trade: accuracy first.

**Say:** "Compute is now seconds. What's left is how long the sensor needs to be sure, and we decided not
to guess early."

---

## 12. What we tried and threw away

| idea | result | why it's out |
|---|---|---|
| GPU for the models | agents 8.4 s each with no batch gain; reasoner 2.5× slower | the NPU wins at every size |
| two models resident on the NPU | rebooted the board | one model at a time, 4.6 s swap |
| speculative decoding (MTP, n-gram) for the reasoner | slower | the recurrent state can't roll back cheaply |
| split 4 / 6 / 3r | +1% / does not fit / 0% | the longest stream sets the time |
| T30 agents (best of a 30-blend search) | severity −13 vs B50 | gate2 FAIL |
| rsn_v2 reasoner | severity −7 pts on 106 incidents | accuracy first |

**Say:** "This is the part of the project nobody sees. Most of our time went into finding out what not to
ship."

---

## 13. Next: talk to the system (the conversational interface)

- The reasoner **already knows how to chat**. rsn_v1 was trained on about 2,000 chat traces with tools
  (count incidents, find incidents, action history).
  - On the 100-question chat test it answered **100%**, picked the right first tool **100%**, quoted exact
    numbers 90%, and made nothing up (0% ungrounded).
- **Path to ship it:**
  1. an `/api/chat` endpoint with the chat tools reading the incident store;
  2. a chat panel in the app that opens with the current incident as context;
  3. the same safety gate: answers must quote tool numbers, with no actuation;
  4. a board test of the latency per answer and the 100-question set on the NPU.
- Chat waits behind alerts on the NPU, just like the re-checks do today.

**Example:** "How many CO2 incidents in KH this week, and what fixed them?" The answer comes from the
store, with numbers.

---

## 14. Next: faster and earlier

- **Reasoner speed:** have htpd write the text that is fully determined by the input (for example the
  sensor id after "S1 (") instead of generating it token by token. Group rearranging is used up; this is
  the next lever.
- **Earlier AI:** young-window training is prepared (data and scripts ready). Early AI is built into the
  app and switched off until accuracy at 2-4 readings is proven.
- **GPU for bursts:** while the NPU writes one report, the GPU could run the next incident's agents. This
  needs the memory-safety check first.
- **rsn_v3:** keep v2's speed and wording, fix its severity regressions, then gate it against v1 again.

---

## 15. Close

- One board, two fine-tuned models, no cloud.
- A first report in the same second; a critical incident in 5.6 s; the full AI report in about 45 s.
- A reasoner that explains across domains: 91.9% severity, 0% ungrounded numbers.
- A person decides every action, and every number has its proof folder.

**Say:** "From a CO2 spike to a person with a checklist, all on the edge. Thank you."
