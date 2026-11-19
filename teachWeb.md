# teachWeb: the evaluation website, page by page, and how to present it

**URL:** https://qidk-nasa.pages.dev
**Password:** ask the team. Never say it aloud on stream, never show it on screen, never put it in a slide, a chat or a
file. Log in **before** you share the screen.

Last updated: 4 Nov 2026, the morning of the final evaluation (12:00 IST). The site was rebuilt and deployed at about
09:40 IST (`proofs/2026-11-04_split/website_1104.log`: "verify ok"). Every number below comes from the site's source
files or the proof files named next to it. The full project guide is `teach.md`; the deck is `ppt.md`.

---

## 0. What the website is (say this in one breath)

"This is our evidence site. It is a static, password-protected site, built from our proof files at build time. Every
number links back to a file in `proofs/`. No raw sensor readings, prompts or room-level occupancy are published, only
aggregates."

How it is built (if someone asks):
- Collectors in `Website/build/collect/*.py` read the proof files and write `Website/data/*.json`.
  - **New for 4 Nov:** `recent.py` adds six datasets: `lat_app_ai_update` (AI update per deploy, 55.2 s on 28 Oct ->
    21.7-28.0 s on deploy20-27), `lat_reasoner_spec` (reasoner 23.3 -> 9.1 s), `ux_chat_sweeps` (27 -> 39/40,
    25 -> 39/40, blind 20/40), `ux_chat_timing` (160 questions: 142 < 1 s, median 0.2 s, 0 errors),
    `acc_reasoner_split` (4B vs 2B on the same gate), `acc_rsn_v1_v2` (rsn_v1 vs rsn_v2 on the same 106 incidents).
  - `decisions.py` (now D001-D134) and `decision_groups.py` (now G01-G36).
  - `overlay.py` keeps the Q&A current (105 questions, new categories `chat` and `safety`).
- `Website/build/build.py` encrypts everything with the site password into `dist/`; wrangler deploys to Cloudflare Pages
  (`qidk-nasa`). The viewer's browser decrypts after the password is typed; the lock button locks it again.
- Source of these changes: `Website/HAANDBOOK.md`, entry "2026-11-04 evaluation-day update".

---

## 1. The eval-day story in one paragraph (memorise)

"Today the board runs three models. The domain agents (our fine-tuned Llama 3.2 3B, ft_B50) and the incident-report
reasoner (our fine-tuned Qwen3.5-4B, rsn_v1) run on the Hexagon NPU. For this evaluation only, the Campus Assistant's
model is our fine-tuned Qwen3.5-2B (rsn_v3 r2) on 5 CPU cores, because on the same gate it chats better (0.737 vs 0.477)
but writes worse reports (severity 0.793 vs 0.919). The 4B is being trained further to be the one model for both. We first
tried the 2B on the GPU and measured 9-10 tokens/s; on the CPU it does about 25 with identical text, because the model's
recurrent layers run on the CPU anyway. If the chat server fails, chat falls back to the 4B on the NPU."

Sources: `proofs/2026-10-29_rsn_v3/kaggle/gate/g2b_r2/GATE.md`, `proofs/2026-11-04_split/README.md`,
`proofs/2026-11-04_split/gpu/tune/TUNE.md`.

**How to present the split honestly:**
- Say "for the evaluation only" and "each model where it scores best". Do not call the 2B "our reasoner".
- Say the 2B **failed** the report gate; that is why it does not write reports.
- The 160-question comparison was read side by side, **not graded** against ground truth (`CMP_d27_d30.md`).
- Each chat answer shows its engine ("· qwen3.5-2b rsn_v3 (cpu)"); a router answer shows no badge.

---

## 2. Page by page

The top bar: **Deck · Today · Journey · Route · Decisions · Proofs · Raw data · Q&A**. The nav subtitle and deck link now
say "sixteen steps".

### 2.1 Deck (home)
- **Shows:** one-line summary, headline before/after numbers, a status strip and a "Start here" path; the slide viewer.
- **Status strip (new):** agents (B50, NPU) / reports (rsn_v1 4B, NPU) / chat (eval day: 2B on the CPU) / critical breach
  -> AI report. A third headline anchor comes from `lat_app_ai_update` (AI report on the incident 55.2 s -> ~22-28 s).
- **Say:** "A working edge system on one Snapdragon 8 Gen 3 board, and every claim has a proof."

### 2.2 Today (the most important page)
Top half is new for 4 Nov; the 29 Oct material is kept below as "History".

1. **Evaluation-day split (deploy32 live) banner.** Says chat runs on the CPU (2B), reports and agents on the NPU; GPU
   measured ~9-10 tok/s vs ~25 on the CPU; live as **deploy32**; fastcheck 5.6 s alert / 27.9 s AI report with chat
   running; a chat question during the incident answered in 6 s; model chat answers 7-14 s fresh (~28 s for a long
   list) vs 10-42 s on the GPU.
2. **On the board today:** table of parts: backend (CPU), domain agents ft_B50 (NPU, resident; gate2 +61, safety 16/16),
   reasoner rsn_v1 (NPU, swapped in, load 2.8 s; severity 91.9%, label 87.8%), htpd_v9f (draft corpora, 150 s guard),
   chat model eval only (rsn_v3 r2 2B, CPU 5 threads, GPU measured 2.7x slower; chat dev pass 0.737 vs 0.477; killed first
   under memory pressure), apps (two icons, one backend).
3. **How an incident flows today:** readings every 5 min (demo replay every 2 s) -> critical fast path (~5.6 s; 2.6 s
   after a silent gap) -> preliminary report in the same second (live checklist) -> event gate (8 readings, 4 h window,
   one agent per sensor in one NPU batch) -> reasoner report ~28 s after the fast incident, "AI so far" while it writes,
   validator -> re-checks at 1.5 h and 3 h, 12 h drift/level-shift checks; operator approves every action.
4. **Latency today:** "Compute is seconds; sensor time is minutes." Table: 40-55 min gate; 5.6 s fast path; same-second
   preliminary; agent 2.06 s; swap 2.80 s (was 3.67); reasoner 8.9-9.1 s (was 23.3); fast incident -> AI 28.0 / 32.7 s;
   router chat median 0.2 s (142/160 < 1 s); 4B chat 8.8-17.2 s (~5 s warm); 2B CPU chat 7.0 / 11.6 / 13.8 s (~28 s long
   list; GPU 10-42 s). Then the "why": memory-bandwidth roof (~52 GB/s over 2.6 GB for the 4B), one NPU model at a time.
5. **Models today:** "The 2B chats better; the 4B writes better reports" (chart from `acc_reasoner_split`), plus rsn_v1 vs
   rsn_v2 (`acc_rsn_v1_v2`: severity 94.7% vs 87.6%).
6. **Campus Assistant:** router first, model for the rest (up to 5 read-only tool calls, "How I found this"), Hinglish and
   typos, refusals, and the eval-day sweep (deploy30: 160/160, 0 errors, router 143/160, model mean 8.4-13.4 s per set vs
   9.2-12.4 s on the 4B, one 63 s loop fixed in deploy31; 2B better on ~6 of 17, worse on 1-2). Charts `ux_chat_sweeps`,
   `ux_chat_timing`.
7. **Decisions since 29 October:** verified drafts (23.3 -> 9.1 s; app AI 52.6 -> 21.7-28 s), silent-sensor fast path
   (2.6 s vs 44-46 s), weather-aware validator floor, chat router from graded sweeps, rsn_v3 2B rolled back for reports and
   r2 kept for chat, the split, fix-forward deploys. Links to Decisions G31-G36.
8. **History · the 29 October evaluation build**, **Morning of 29 October**, **Overnight run (28 to 29 October)**: the old
   material. Do not present it as "now". (If asked: the 29 Oct build had AI reports at 42-55 s; today ~28 s.)
9. **Known limits** (rewritten) and **What's next** (four items, see section 5).

### 2.3 Journey (16 steps)
Steps 1-11 as before (Genie, htpd, window study, v2 retrain, post-rules and blends, reasoner, faster reports, B50 and
gate2, sensor time, deploy with rollback, small measured fixes of 29 Oct). **New:**
- **12. Verified drafts inside split decoding, a faster swap, and drafts that learn from the app** (htpd v9-v9f;
  23.3 -> 9.1 s; load 3.67 -> 2.80 s; agents -21%).
- **13. A weather-aware validator rule, and critical readings after a silence** (deploy22; 2.6 s fast incident).
- **14. Graded chat sweeps on the board, and a router in front of the model** (27 -> 39/40, 25 -> 39/40, blind 20/40,
  question-type layer).
- **15. A fine-tuned 2B for chat and reports: better chat, worse reports** (2B r1 rolled back; r2 gate).
- **16. Each model where it scores best: 2B chat on the CPU, 4B reports on the NPU.**
- **Papers we built on** (end of page): GPTQ, LoRA/QLoRA, speculative decoding, prompt lookup / suffix drafts, ReAct,
  Toolformer, LLMCompiler, RAG, DPO, STaR, WiSE-FT / model soups / task arithmetic, prompt injection, Lost in the Middle,
  Qwen3 and Llama 3 reports, HAX guidelines, HeteroInfer, each with the repo file that cites it. Lookahead Decoding is
  listed separately as "well known, not cited in the repo" (same list as ppt.md slide 28).
- **Say:** "We measured every idea and dropped the ones that did not help."

### 2.4 Route
Unchanged: route from spec to standalone board (22 steps), latency route (ends at 19 Oct), training v2 status, dropped
speed ideas. **Say:** "For the newer latency steps, see Journey 12-16 and Today."

### 2.5 Decisions
- Groups **G01-G36**, 134 decisions. New groups:
  - **G31** A cross-domain reasoner on the same NPU, accuracy first (D126 P0 choice; D127 reject rsn_v2).
  - **G32** Make the reports fast without changing their answers (D128 split, D129 verified drafts, D131 reasoner stays on
    the NPU): reasoner 23.3 -> 9.1 s; AI report 55 s -> 22-28 s.
  - **G33** Critical fast path; honest about sensor time (D130).
  - **G34** Campus Assistant: router first, model for the rest, read-only (D132): 39/40 on two sweeps; 142/160 < 1 s.
  - **G35** Evaluation day: each model where it scores best (D133): chat 0.737 vs 0.477; reports 0.919 vs 0.793.
  - **G36** Fix forward with automatic rollback (D134).
- **Say:** "Every choice has a reason, evidence and the alternatives we rejected."

### 2.6 Proofs
Every measured result as a chart or table with its source file; the six new datasets appear here too. "Download the
numbers" gives aggregates only. **Say:** "Any number you doubt, we open here."

### 2.7 Raw data
Cleaned 2025 campus sensor data: pick a sensor, see its analysis and how windows become training examples. 20,538
threshold breaches in the cleaned data (ppt slide 2).

### 2.8 Q&A
- **105 questions**, searchable, new categories **chat** and **safety**.
- Rewritten answers: explanation time, incident speed, honest limits, what is unsolved, next steps, NPU vs GPU, what runs
  today, training status, the chat answer; "Do you use speculative decoding?" (yes, inside split decoding).
- New questions: chat model today, Hinglish, can the assistant change anything, validator, why not two models on the NPU,
  papers.
- **Say:** "The questions you are likely to ask are here", then type "GPU", "2B" or "Hinglish".

---

## 3. A 10-12 minute walk-through

Before: warm the board (one incident, then open the chat once; `proofs/2026-11-04_split/DEMO.md`). Log in to the site
before sharing the screen. Open **Today** and **Deck** in two tabs; zoom about 110%.

| # | time | click | what to say |
|---|---|---|---|
| 1 | 0:00-1:00 | Deck | "Agentic edge AI for a campus: domain agents per sensor, a reasoner for one cross-domain report, a chat assistant, all on the QIDK, offline. Every number links to a proof." Point at the status strip (agents / reports / chat / breach -> AI). |
| 2 | 1:00-2:30 | Today, split banner + On the board | The eval-day paragraph (section 1). "deploy32 is live; reports unchanged with chat running: 5.6 s alert, 27.9 s AI report." |
| 3 | 2:30-3:30 | Today, How an incident flows | Fast path, same-second preliminary with live checklist, AI report merges, human approves. |
| 4 | 3:30-5:00 | Today, Latency | "Compute is seconds, sensor time is minutes: 40-55 min for normal events, 5.6 s for criticals. Reasoner 23.3 -> 9.1 s with verified drafts; decode is at the bandwidth roof." |
| 5 | 5:00-6:30 | Today, Models + Campus Assistant | "2B chats better, 4B reports better: that is the split. Router answers in 0.2 s median; model answers 7-14 s." |
| 6 | 6:30-8:00 | Journey, steps 12-16 | "Each step measured; the 2B was rolled back for reports and kept for chat." Scroll to Papers. |
| 7 | 8:00-9:00 | Decisions, G35 and G32 | "Each model where it scores best; faster without changing answers." |
| 8 | 9:00-10:00 | Proofs, one chart | Open `lat_app_ai_update` or `acc_reasoner_split`, show the source. |
| 9 | 10:00-11:30 | Board: Campus Assistant (live, not on the site) | Ask "Which incident needs my attention first?", then "explain why"; "Kitne incidents aaj hue?"; "Show me critical alerts" (model, badge "qwen3.5-2b rsn_v3 (cpu)"); "Turn off all the AC units in KH building" (refused). Tap "How I found this". |
| 10 | 11:30-12:00 | Q&A | Type "2B" or "GPU". |

If only 5 minutes: steps 2, 4, 5, 9.

---

## 4. Likely evaluator questions (website angle)

**Why does chat use a different model from reports?** Same gate: 2B chat 0.737 vs 0.477; 4B report severity 0.919 vs
0.793, check recall 0.848 vs 0.405. Evaluation only; the 4B is being trained to do both (G35, D133).

**Why the CPU, not the GPU, for the 2B?** Measured 9-10 vs ~25 tokens/s, identical text; the hybrid model's recurrent
layers run on the CPU, so the GPU path syncs every layer (`TUNE.md`).

**Does the chat slow down incident reports?** No: fastcheck with the 2B resident 5.6 s / 27.7-27.9 s, same as without
(`deploy30-32/STATUS.md`). Chat no longer waits for the NPU.

**What if the chat server fails?** That call falls back to the 4B on the NPU and the 2B is skipped for 60 s;
`split_off.sh` turns the split off in ~4 s without an app restart (rehearsed: 3.8 s, the 4B answered in 6.1 s).

**How fast is the system?** Critical breach -> incident 5.6 s; AI report ~28 s later (78 s for the first incident after
4 h idle, so we warm up); preliminary at once; non-critical events wait 40-55 min of sensor time.

**How accurate?** rsn_v1: severity 91.9%, label 87.8% on 150 held-out; agents (htpd) 90.7% pattern on the board.

**Why not rsn_v2?** Severity 87.6% vs 94.7% on the same 106 incidents (G31, D127).

**Why not two models on the NPU?** It rebooted the board; we swap in 2.8 s.

**Can the AI or the chat act?** No. Read-only tools, refusals, validator, severity guard, human approval.

**What did you try that did not work?** rsn_v2; GPU for the reasoner and for the 2B; LADE; grammar decoding; continuous
batching; row padding; split 4/6/3r; MTP and n-gram speculation outside split; T30; 2B r1 for reports.

---

## 5. Next steps (in this order, as on Today)
1. One general model: rsn_v3 4B must beat rsn_v1 on reports and the 2B on chat; then the split goes away.
2. Younger events: young-window training; the early provisional AI is built and off until proven.
3. Chat: a fresh blind set after every fix, streaming answers, chat about the open incident.
4. Fog layer: derived data to a free Supabase project, board as the only writer.

---

## 6. Pitfalls: do not say these

- Do not say the password, show it, or type it while sharing the screen.
- Do not present the 29 Oct "History" section as the current build (its 42-55 s AI times are old; today ~28 s).
- Do not say the 2B is our report model or "better overall". It failed the report gate.
- Do not say the 160-question comparison was graded; it was read side by side.
- Do not claim the 40-55 min gate is solved; only criticals have the fast path; power, tank level and flow have none.
- Do not say the GPU helped. It was measured slower for the reasoner (~2.5x) and the 2B (9-10 vs 25 tok/s).
- Do not call the preliminary report "the AI"; it is rules plus wording from a similar past report.
- Do not mix demo time (one reading every 2 s) with real time (one every 5 min).
- Heat: heavy NPU work reaches 84-97 C; if it throttles, say so plainly.
- If the first incident is slow, say: "cold start after idle; measured 78 s once, 28 s warm" (`FINAL_CHECK.md`).
