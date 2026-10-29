# teachWeb: the evaluation website, page by page, and how to present it

**URL:** https://qidk-nasa.pages.dev
**Password:** ask the team, or see the private notes. Never say it on screen and never put it in a slide or a chat.

Last updated: 29 Oct 2026, morning of the final evaluation (12:00 IST). Every number below comes from
`proofs/2026-10-28_master/FACTS_2026-10-29.md`. If a number is not in that file, do not say it.

---

## 0. What the website is (say this in one breath)

"This is our evidence site. It is a static, password-protected site, built from our proof files at build time.
Every number on it links back to a file in `proofs/`. Nothing is typed in by hand without a source, and no raw sensor
readings or model prompts are published, only aggregates."

How it is built (for the person driving the laptop, if someone asks):
- Collectors in `Website/build/collect/*.py` read the proof files and write `Website/data/*.json`.
  - `today.py` builds the Today page. It now also reads this morning's files: `improve/STATUS.md`,
    `improve2/STATUS.md`, `split3r/result.txt` and `gpu_bench_out/out.md`.
  - `overlay.py` brings the Q&A answers up to date (current build, rsn_v2 decision, GPU result, chat path).
  - `status.py` builds the status strip.
- `Website/build/build.py` encrypts everything with the site password into `dist/`, and wrangler deploys it to
  Cloudflare Pages (`qidk-nasa`).
- The data is decrypted in the viewer's browser after the password is typed. The lock button in the top bar locks it again.

---

## 1. Page by page

The top bar has: **Deck · Today · Journey · Route · Decisions · Proofs · Raw data · Q&A**.

### 1.1 Deck (home)
- **What it shows:** a one-line summary ("An AI agent that reads building sensors and reports faults, on the phone
  chip, offline"), two headline before/after numbers, a status strip (agents, reasoner, event-to-report time,
  live build), and a "Start here" path. The slide deck viewer sits below.
- **Where the numbers come from:** the headline numbers are read from the datasets (12-agent report Genie → htpd;
  agent accuracy at 40 min → 3 h). The status strip reads `data/today.json`.
- **Key takeaway:** this is a working edge system on a Snapdragon 8 Gen 3 board, and every claim has a proof.

### 1.2 Today (the most important page for the evaluation)
Sections from top to bottom:

1. **Banner: "Live now: edge-agent b770aa57"** (APK c62b6014). Domain agents B50, reasoner rsn_v1, htpd_v8x3,
   split 3, retrieval library of 254 reference reports. Checked through the app after the deploy: chaos scenarios
   passed, critical breach opened by the fast path in **5.6 s**, AI report on the same incident at **42.2 s**.
   Source: `improve2/STATUS.md`.
2. **On the board:** a table of every part that runs (agents, reasoner, NPU daemon, split decoding, contract repairs,
   app, preliminary report, critical fast path, early AI) with md5 values and a "why" column.
3. **How an incident flows today:** sensor readings → critical fast path → event gate (8 readings) → preliminary report
   in the same second (rules + retrieval, checklist usable at once) → reasoner report (merges the checklist) →
   re-checks at 1.5 h and 3 h, operator approves every action.
4. **Latency:** big numbers: preliminary report at 0 s, reasoner title and severity 8 to 15 s, full report
   25.2 to 38.6 s (overnight final deploy, 6 scenarios), fast path 5.6 s with AI update 42.2 s. Two tables:
   where the NPU time goes (including the ladder **27.8 → 25.8 → 21.6 s**: base → polling → split decoding,
   and 22.2 s on this morning's 10-incident A/B), and latency levers kept and dropped (GPU and split 3r now listed as
   dropped, with measurements).
5. **Accuracy:** reasoner card (rsn_v1: severity 91.9%, label 87.8%, valid output 98.7% on 150 held-out incidents;
   board 30-prompt check; 97% severity consistency, 100% with the guard; contract repairs 83.2% → 87.6%;
   rsn_v1 vs rsn_v2 94.7% vs 87.6%; chat dev set) and domain agents card (B50).
6. **This morning (29 Oct)** (new section):
   - two deploys this morning, both checked through the app (fast path 5.6 s both times; AI report 47.2 s then 42.2 s);
   - contract repairs: label 83.2% → 87.6% on 386 board answers, 0 new errors;
   - checklist from the preliminary report with the smart merge;
   - rsn_v2 rejected: the 106-case table (severity 94.7 vs 87.6, label 88.4 vs 85.6, check recall 0.90 vs 0.81,
     score 0.938 vs 0.913) plus its two board errors;
   - GPU measured: 7.35 / 8.44 / 8.35 tokens/s (pp1 / pp3 / tg), about 2.5x slower than the NPU;
   - split 3r: 22.2 vs 22.2 s, no gain;
   - two-stage report with retrieval: how it works and its deploy check (4/4 at 0 s, 2/4 retrieved);
   - conversational interface: what is ready, what is missing, the 4-step plan.
7. **Overnight run (28 to 29 Oct):** the final overnight deploy steps, 6 scenarios through the app, split 4/6 A/B,
   retrieval deploy, rsn_v2 retry, overnight job table.
8. **Known limits** and **What's next** (five items, see section 4 below).

- **Key takeaway:** what runs right now, how fast, how accurate, and what we honestly have not solved.

### 1.3 Journey
- **What it shows:** eleven steps from 6 to 29 Oct, oldest first. Each step: what we did, why, what we measured,
  and what we dropped. Step 11 (new) is this morning: contract repairs, preliminary checklist, seed library kept;
  rsn_v2, GPU and split 3r rejected.
- **Where the numbers come from:** each step has a proof chip that links to its folder.
- **Key takeaway:** we measured every idea and dropped the ones that did not help. That is the story of the project.

### 1.4 Route
- **What it shows:** the full route from spec to standalone board (22 steps), the latency route (each kept step with
  its measured saving), the training v2 status, and 13 speed ideas we measured and dropped.
- **Key takeaway:** latency came down step by step, and each step is measured.

### 1.5 Decisions
- **What it shows:** the design decisions, grouped, each with evidence and the alternatives we rejected, plus
  "in practice" situations on the board.
- **Key takeaway:** every choice (NPU over GPU, accuracy first, human approval, policy gate) has a reason and evidence.

### 1.6 Proofs
- **What it shows:** every measured result as a chart or table, each linked to its source file. Filter by proof folder.
  App screens before/after. "Download the numbers": aggregates and per-sample scores, no raw sensor values.
- **Key takeaway:** "Evidence, on request". If an evaluator doubts a number, open it here.

### 1.7 Raw data
- **What it shows:** the cleaned campus sensor data (2025): pick a sensor, see its analysis, and see how raw windows
  become training examples.
- **Key takeaway:** the models were trained and tested on real campus data, with test months and some sensors held out.

### 1.8 Q&A
- **What it shows:** "What happens when...?" situations, the use case, and a searchable list of about 100 questions,
  each with a short answer and a chart. Answers updated today: what runs now, why not the GPU (measured), why rsn_v2
  was rejected, contract repairs, what the operator sees first, whether the 40-55 min wait is solved (no), chat status,
  split 3r.
- **Key takeaway:** use it live when an evaluator asks something: type a keyword, show the answer.

---

## 2. A 10 to 12 minute walk-through

Before you start: log in, open the **Today** page in one tab and **Deck** in another. Zoom the browser to about 110%.
Have the app on the board running in parallel if someone else is demoing it.

| # | Time | Click | What to say (short) |
|---|---|---|---|
| 1 | 0:00-1:00 | **Deck** | "Agentic edge AI for a smart campus. Domain agents read each sensor, a reasoner writes one cross-domain report, all on the QIDK, offline, no cloud. Every number here links to a proof file." Point at the status strip: live build, agents B50, reasoner rsn_v1. |
| 2 | 1:00-2:30 | **Today**, banner + On the board | "This is what runs right now: build b770aa57. Llama 3.2 3B agents (B50) and Qwen3.5-4B reasoner (rsn_v1), both Q4_0 on the Hexagon NPU, one model at a time, through our htpd daemon. We deployed it this morning and checked it through the app: critical breach to incident in 5.6 s, AI report on the same incident in 42.2 s." |
| 3 | 2:30-3:30 | Today, **How an incident flows** | Walk the 6 steps. Stress: the preliminary report appears in the same second, and the operator can start ticking the checklist at once; the AI report merges in. The operator approves every action; the AI never switches anything. |
| 4 | 3:30-5:00 | Today, **Latency** | "On the NPU: preliminary at 0 s, title and severity 8-15 s, full report 25-39 s. The reasoner went 27.8 → 25.8 → 21.6 s with polling and split decoding. In the real world the bigger delay is sensor time: 8 readings at 5 min each is 40-55 min. Critical cases skip it through the fast path." |
| 5 | 5:00-6:30 | Today, **Accuracy** | "Reasoner on 150 held-out incidents: severity 91.9%, label 87.8%, 0% ungrounded. This morning's contract repairs moved the label from 83.2% to 87.6% on 386 real board answers, with 0 new errors." |
| 6 | 6:30-8:30 | Today, **This morning** | "We also say no on evidence. rsn_v2 lost on the same 106 incidents, severity 87.6% vs 94.7%, so rsn_v1 stays. We measured the GPU: about 2.5x slower than the NPU. Split 3r: no gain. Retrieval: the preliminary uses the most similar past report from a library of 254 seeds plus every live report, but the numbers always come from the live values, and severity never goes below the rules." |
| 7 | 8:30-9:30 | **Journey** (scroll to step 9-11) | "The real delay is sensor time, not NPU time. The last step is this morning: small measured fixes, bigger ideas rejected on evidence." |
| 8 | 9:30-10:30 | **Proofs** (open one chart) | "Any number you doubt, we open here, with its file." Pick one (e.g. a latency chart) and show the source chip. |
| 9 | 10:30-11:30 | Today, **Known limits + What's next** | Read the limits honestly. Next: conversational interface, reasoner speed via forced text, young-window training, GPU for bursts, rsn_v3. |
| 10 | 11:30-12:00 | **Q&A** | "And the questions you are likely to ask are here." Type "GPU" or "rsn_v2" to show it works. |

If you have only 5 minutes: steps 2, 4, 5, 6, 9.

---

## 3. Likely evaluator questions, with crisp answers

**Does it really run on the board alone?**
Yes. Both models run on the Hexagon NPU of the QIDK, offline, no cloud. One model on the NPU at a time; htpd swaps them.

**How fast is it?**
Preliminary report in the same second as the incident. One domain agent 5.9 s (first token 0.7 s). 12 agents 20.7 s.
Reasoner report 21.6 s mean on the bench, 22.2 s in this morning's A/B. Full AI report from incident start 42-47 s
in the fast-path check. Critical breach to incident: 5.6 s.

**Then why do you say 40 to 55 minutes?**
Real sensors give one reading every 5 min, and the AI waits for 8 abnormal readings. That is sensor time, not compute.
We accept it for the prototype; critical cases use the fast path (2 readings). Young-window training is the next step.

**How accurate is the reasoner?**
rsn_v1 on 150 held-out incidents (host copy, which agrees with the board 207/208): severity 91.9%, label 87.8%,
parsed 98.7%, ungrounded 0%, unit errors 0%, actuation 0%, injection followed 0%. Board 30-prompt check: parse 30/30,
severity 27/30, label 25/30.

**Why didn't you deploy the newer reasoner rsn_v2?**
On the same 106 held-out incidents it was worse: severity 87.6% vs 94.7%, label 85.6% vs 88.4%, checklist recall
0.81 vs 0.90. On the board it also invented a title location and misread 324 > 300 ppm. Accuracy first, so rsn_v1 stays.

**Why not the GPU?**
We measured it this morning: Adreno 750, upstream llama.cpp OpenCL, 7.35 / 8.44 / 8.35 tokens/s, about 2.5x slower than
the NPU split. It may help bursts later (a second incident's agents while the NPU reasoner runs), after a memory-safety check.

**Why not two models on the NPU at once?**
We tried: two resident models rebooted the board. So one model at a time, with a 4.6 s swap.

**What is the preliminary report? Is it the AI?**
No, it is the rules computed from the live values, worded like the most similar past report (hybrid retrieval:
structured vector 0.7 + TF-IDF 0.3, same role and metric). Severity is the higher of rules and retrieval, so it never
under-alerts. It is labelled "Preliminary" with the best match percentage and incident id, and the AI report replaces it.

**Could retrieval copy wrong numbers from an old incident?**
No. Numbers always come from the live values; only the wording comes from the old report.

**What are "contract repairs"?**
Rule-based checks after the reasoner: severity normal with needs_more_data gets the label unknown, and a title location
that is not in the input is replaced by one from the input. Replayed on 386 board answers: label 83.2% → 87.6%, 0 new errors.

**Can the AI switch something off by itself?**
No. Policy gate (valid JSON, allowed labels, real evidence ids, numbers must exist in the input, no actuation language),
severity guard (AI may not say normal when rules say warning or critical), and human approval for every action.
If the AI fails the gate, a deterministic report is used.

**Is the NPU output repeatable?**
Not bit for bit. Same prompt 5 times: severity agrees 97%, 100% with the severity guard.

**Can I chat with it?**
Not in the app yet. The reasoner was trained with about 2,000 chat tool traces and scores 100% answered, 100% first tool
right, 90% numbers exact, 0% ungrounded on 100 dev questions. Missing: the endpoint, the chat tools over the incident
store, a chat panel and NPU scheduling. It is the first item after the evaluation.

**What if the board hangs?**
htpd_v8x3 has a 150 s wall-clock guard per report, bounded token picking, and a heartbeat stall log; the overnight
watchdog saw 0 stalls. Every deploy has a rollback script and a known-good snapshot.

**What did you try that did not work?**
rsn_v2, the GPU, split 4 (+1%), split 6 (does not fit), split 3r (22.2 vs 22.2 s), MTP and n-gram speculation (slower),
two resident models (reboot). All on the Today and Journey pages.

---

## 4. Next steps (say them in this order)
1. Conversational interface: endpoint + chat tools over the incident store, chat panel, guard (answers quote tool numbers,
   no actuation), board test (latency per answer, the 100-question set on the board).
2. Reasoner speed: force fully determined text (for example the sensor id after "S1 (") in the htpd forcer;
   group rebalancing is exhausted.
3. Young-window training (data ready, paused) to shorten the 8-reading gate; early AI is built but off.
4. GPU for bursts: a second incident's agents while the NPU reasoner runs (needs the memory-safety check).
5. rsn_v3: fix rsn_v2's severity regressions before another round.

---

## 5. Pitfalls: do not say these

- **Do not claim the 40-55 min real-world gate is solved.** It is accepted for the prototype; only critical breaches
  use the fast path. Power, tank level and flow have no fixed critical limits, so they have no fast path.
- **Do not say rsn_v2 is deployed or "almost as good".** It was rejected on evidence (severity 87.6% vs 94.7%).
- **Do not say the GPU is faster or "the next speed-up".** It was measured about 2.5x slower than the NPU.
- **Do not say split 3r, split 4 or split 6 helped.** They did not.
- **Do not call the preliminary report "the AI"** or say it reasons. It is rules plus wording from a similar past report.
- **Do not say the chat interface exists in the app.** It is trained and scored on the laptop, not built into the app.
- **Do not quote numbers that are not on the site or in the fact sheet.** If unsure, open Proofs or Q&A and read it.
- **Do not mix demo time and real time.** The demo replays one reading every 2 s; in the field it is one every 5 min.
- **Do not show the password** on the projector; log in before you share the screen.
- **Heat:** back-to-back heavy incidents push the board to 90-94 °C; if it throttles, say so plainly, it is a known limit
  (needs a heatsink or fan in the field).
