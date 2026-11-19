# rsn_v3 2B r1: why it failed (diagnosis, 2026-11-02, laptop only)

Inputs: gate `proofs/2026-10-29_rsn_v3/kaggle/gate/g2b_r1/` (GATE.md, chatdev3_v3.jsonl), gate outputs
`proofs/2026-10-25_reasoner_final/eval/results/rsn_v3_g2b_r1/{rwh,rwh2,dev}.jsonl` (ft612 = rsn_v1 alongside), board verdict
`proofs/2026-11-02_2b_board/VERDICT.md` (+ `app/rreq/q100-106` app prompts), the r1 training files (`kaggle/build/r1/data`,
`build/r1/mix_laptop`, `distill_laptop/chat3_distilled.jsonl`) and the app source (`app/backend/chat.go`, `chat_header.txt`,
`reasoner_v3.go`). Scripts: `tools/` (Go gate harness `r2_gate_test.go` + `go_gate.sh`); one-off analysis scripts were run
from the session scratchpad and their numbers are quoted here.

## 1. Chat: pass 0.183 vs rsn_v1 0.477

| finding | evidence | class |
|---|---|---|
| **Training bug: the "close the think block" decision was never trained.** `train_rsn3.py encode()` tokenized the whole conversation in one pass and labelled only tokens that start at or after the generation prompt `...<|im_start|>assistant\n<think>\n`. In the target `<think>\n\n</think>` the tokenizer merges the prompt's `\n` with the next `\n` into one `\n\n` token that straddles the boundary, so it was dropped from the labels. | 1,414 of 1,414 easy chat rows and 792 of 1,276 hard rows (first 1,500 rows of chat_mix3) have a straddling token and a token-prefix mismatch with the inference prompt; incident rows are clean (thinking off). After the fix the first labelled tokens of an easy row are `\n`, `</think>` and the inference prompt is an exact token prefix of the training row. | training code |
| Consequence: **the 2B thinks on 98 % of easy questions** (`easy_think_nonempty 0.98`, mean 96 think tokens) | `think_not_empty` is 194 of the 300 failures. With that reason ignored the 2B would pass **161/300 = 0.537**, above rsn_v1's 0.477. | adaptive thinking (consequence of the bug) |
| Long thinking costs answers: 15/300 `too_many_calls`, 11 `no_final`, 8 `think_too_long`; mean 232 generated tokens vs 99 | chatdev3_v3.jsonl | consequence |
| **Prompt mismatch on the board: the app exposes 9 tools, training used 15.** `chat_header.txt` (what `chatStaticPrefix` sends) has the 9 round-1 tools; r1 chat rows used `tools_v4.json` (15 tools: + rank_readings, current_levels, recent_incidents, open_incidents, faulty_sensors, what_if). The app's executor runs all 15 (`chat.go` -> `runV3`), but the model is never told about 6 of them. Everything else in the chat prompt is byte-identical to the training render (checked: template render with the 9 tools == chat_header + system; system text == training system text). | On the board the 2B had to answer "level in KH", "pm25 in water" etc. without `current_levels`/`rank_readings` and invented args for the 9-tool schema (`node: "KH level 3"`, domain `"all"`), then "I could not find an answer". The host gate used the 15-tool header, so it never saw this. | prompt format |
| Tool-call format/args on the gate are fine | 0 unknown tools, 0 bad enum values in 300 dev transcripts; 3 calls with an unknown arg (`faulty_sensors.include_faulty`). calls_ok 0.757 > rsn_v1 0.65. | not a cause |
| Device time is frozen in training: all 8,549 chat rows say `Device time: 2026-10-22 12:00 IST (Thursday)` | the tool store is built around that clock; the board runs other dates | coverage (limitation, see DATASET.md) |
| No Hinglish in training (0 rows match kya/hai/batao/kitne/mein); the board's leftover questions (router misses) are exactly the Hinglish / typo / multi-part ones | `chat_router_ops_test.go` has "KH building mein temperature kya hai?" | coverage |
| Remaining content fails (excluding think): missing_fact 124, missing_call 70, extra_calls 25, invented_num 20 — spread over levels_domain, whatif_*, trend, faults, rank_lowest, faulty_explain, multistep | per-kind table in the scratch analysis | knowledge (more varied verified rows) |

Grader mismatch: none found. `think_not_empty` is the intended rule (easy questions must not think, the app's latency budget);
the grader and `chat3_eval.py` use the same `<think>\n` opening as the app's adaptive mode (`chatAssistantOpenAdaptive`).

## 2. Reports: schema_err 0.095-0.103 vs 0.038-0.081

| finding | evidence |
|---|---|
| **All of the 2B's extra schema errors are one thing: it drops the last key `explanation`** (`key:explanation` 8-9 items per suite; rsn_v1's schema errors are `checks` / `evidence_count` instead). The object always ends right after `"needs_deeper": false}`. | rwh 8, dev 9, rwh2 9 items. Concentrated in drift_low / replaced_shift / single_glitch (sensor_fault rows). All 20,000 r1 training rows have the 16 keys with `explanation` last, so it is a 2B capacity / Q4_0 effect on long sensor-fault reports, not bad data. |
| evidence_count 3-6 per suite (both models) | same rate as rsn_v1 |
| unparsed 2-3 per suite (rsn_v1 15-25 on the same suites) | the 2B is the better JSON writer apart from the dropped key |
| The training data is consistent with the app gate | all 20,000 r1 incident rows pass the app's own Go validator `checkReportV3For` (with tool turns in the known text): 20000/20000. So the board's "critical + check_sensor first" pH report was the model, not the data. |

## 3. Severity / sensor_fault vs critical

| finding | evidence |
|---|---|
| RWH severity misses: sensor_fault -> normal 5, sensor_fault -> critical 2, critical -> warning 3 (rsn_v1: sensor_fault -> normal 3, sensor_fault -> critical 2) | `rsn_v3_g2b_r1/rwh.jsonl` |
| RWH-2: critical -> warning 4 (rsn_v1 5); check_prec 0.738: 16 extra `corrected` agent_checks on refs with no gold check (over-correcting agents that were right) | rwh2 |
| Board: room-temperature sensor fault (one-sample +18.8 C jump, AC room sensor 24 C, room empty) -> critical "outdoor heat" | q104. In r1 there are 3,413 hvac rows but no pair that contrasts an indoor temperature jump against the AC's own room sensor. |
| Board: pH 7.2 -> 9.6 held for 40 min -> text "single bad reading" but severity critical + check_sensor first (rejected by the app gate) | q103. r1 has no contrast between ONE bad sample (sensor_fault) and a held excursion (critical, inspect_water_system first). |
| Board: real CO2 rise with people (agent said step/sensor_fault) copied as sensor_fault; drift below the limit reported as warning | q100/q101/q102 |
| **Refinement prompts are almost untrained**: the app sends `(mode refine-1.5h)` and `(mode refine-3h)` with RE-CHECK lines `HH:MM <severity>: <earlier title>`. r1: refine-1.5h 431 rows (2 %), **refine-3h 0 rows**, and the RE-CHECK lines were "CO2 was N ppm (acknowledged by op_x)", not earlier titles. On the board the false critical stayed critical through 1.5 h and 3 h. | `grep` over incidents3_train |
| Real-agent rows (28 % of r1, `real_agent`) are the largest single miss family in every suite (rwh 7/15, dev 5/11, rwh2 4/12) | these rows are synthetic sensor inputs (sft_v2 simulator) with recorded agent outputs; kept in r2 |

## 4. What r2 changes (details in DATASET.md)
1. Trainer: segment tokenization at every prompt/target boundary (`train_rsn3.py`, env `RSN3_SEG_TOKENIZE`, default on;
   incident rows tokenize identically, 50/50 checked). This alone should fix most of the chat gate.
2. Chat rows in both headers: the 15-tool header (gate, and what the app should send to rsn_v3) and the app's current 9-tool
   header for every question the 9 tools can answer. Recommended app change (not made here): send the 15-tool header when
   `chat_think=adaptive` (the executor already runs all 15).
3. Hinglish / code-switched and typo questions; more and new-seed chat rows; dedup against chat dev v3.
4. Targeted contrastive report pairs with verified gold: room-temperature fault vs real AC failure, pH single bad reading vs held
   excursion, CO2 real occupancy rise vs bias step vs normal drift; refine-1.5h/3h with app-style earlier-revision lines (some
   wrong, re-judged); varied building codes.
5. More heatwave pairs (new seed) on top of the 192 r1 add-on rows.
6. Bigger incident base (30,000 rows, new seed 47) through the unchanged round-1 generator + verify.py; every incident row also
   through the app's Go gate.

## 5. Init from r1 best (step 1200)?
Not recommended. r1 spent ~1,200 optimizer steps learning "after `<think>\n` write reasoning" on every chat row (the closing
decision was unlabelled), and its 4-bit LoRA also carries the `explanation` drop. Starting from the base 2B with the fixed
tokenization costs the same epoch time as r1 but removes the learned habit cleanly; the incident side of r1 (label/check
recall above rsn_v1) is reproducible from the same data. If wall time matters more, a short r1-init run (LR 5e-5, chat rows
x2) is the fallback; it is not the default. Training is on hold until the owner confirms the dataset.
