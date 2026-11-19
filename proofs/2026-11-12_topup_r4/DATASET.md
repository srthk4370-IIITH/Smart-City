# Dataset r4: cross-domain reasoning top-up of rsn_v3 4B r3 (built 2026-11-12, laptop CPU only, nothing uploaded)

Base model: rsn_v3 r3 4B at step 2800 (`~/smartcity_runs/KEEP_rsn3_4b_r3_s2800`, GGUF `Code/models_stage/rsn_v3_4b_r3_q4_0.gguf`).
Goal (owner): make cross-domain reasoning and inference better without hurting anything else. All data is synthetic: template
generators with a known causal graph per scenario, plus a stratified r3 replay. No board data.

## 1. Why: weaknesses seen in the r3 gate (`../2026-11-06_4b_local/post/gate_r3/`, per-item files; `tools/diag_r3*.py`)
| finding | evidence | r4 answer |
|---|---|---|
| Easy fog answers get **copied into the think block** | `think_not_empty` 73 in chat_test_r3. In fog_find_old, fog_text, fog_old_detail, inject_fog and fog_status the reasoning_content is the final answer | 2,087 easy rows with an empty think, mostly fog offline/timeout |
| **Facts dropped** in fog fallbacks | listings miss the total (recent_vs_fog), fog_status misses the pending count, fog_drop misses the coverage date, fog_resolve "by type" is answered with the overall mean | more rows of these kinds; the gold always states the total, the link, the last sync, pending, and the coverage |
| Misrouting | "how many incidents about X" goes to count_incidents(pattern) instead of fog_search_history(text). fog_drop goes to count_incidents | fog_text 254, fog_drop 207 and old_count 156 rows (contrast) |
| **Gold artefact in chat_test_r3** | cooccur / fu_cooccur / recurring gold calls carry a `window_min` / `min_count` the question never states (e.g. "anything co-occurring with INC-1014?" requires window 90). Most of cooccur 22/35, fu_cooccur 4/35 and part of recurring are this | r4 policy: a parameter appears in the gold only if the question states it (contrastive with/without). **These r3 test items stay unfair; read those kinds with care** |
| Heat slice severity 0.873 | 32 of the misses are a weather-sensor fault (jump/drift) called critical heat while the building shows no heat | `wx_fault` 367 + `wx_fault_co2` 285 rows: weather jump/drift with indoor temp, AC and feeder flat, so sensor_fault |

## 2. Files (`data/final/`, MD5SUMS there; the r4 top-up training already runs on them, so do not touch)
| file | rows | what |
|---|---|---|
| `train_new.jsonl` | 15,588 | 9,300 incident + 6,288 chat, all new and verified; every row has `reasoning_type` + `hops` |
| `replay.jsonl` | 15,020 | stratified r3 training rows: 7,501 incident (623 given the r4 multi-domain think), 7,304 chat, 215 general (no tools) |
| `test_inc_r4.jsonl` | 720 | **held-out** cross-domain incidents (never trained on); `reasoning_type`, `hops`, `think_expected`, `novel_names`, `gold_text` |
| `test_chat_r4.jsonl` | 925 | **held-out** chat records (gen_chat_r3 format); `reasoning_type`, `hops`, `answer_key`, `fog`, `hinglish`, `gold_text` |
| `dev_gen_inc.jsonl` / `dev_gen_chat.jsonl` | 60 / 55 | trainer generation-eval slices, separate from test and train |
| `tools_r3.json` | - | unchanged tool headers (`incident` 4, `chat` 21) |
| `build_manifest.json`, `tokens_r4.json` | - | counts and stats, tokens per epoch |

Build: `tools/run_r4.sh` runs these steps. `make_store_r4.py` → `gen_r4_inc.py` (9,300 / 720 / 60, seed 41112) → app Go gate
(`../2026-11-02_2b_r2/tools/go_gate.sh`) → `gen_chat_r4.py` (seed 41114) → `build_r4.py` → `tok_r4.py` → MD5SUMS. Run time is about 35 min on CPU.

## 3. Reasoning taxonomy (owner addition). Every row and test item is tagged
Types: `pair_relation` (cause / effect / same cause / independent / sensor fault), `pair_who` (which one is the root), `pairwise`
(compare two incidents on a property), `transitive` (A→B→C, so what is A's effect on C), `three_way` (three domains interacting),
`multihop` (chains of 2-4 hops), `chain_direct` (the nearest cause), `chain_max` (the root that explains the most symptoms).
`hops` = edges in the gold causal chain. Non-reasoning chat rows (fog and fix kinds) are tagged `none` / 0.

| type | train incidents | train chat | test incidents | test chat |
|---|---|---|---|---|
| pair_relation | 1,542 | 437 | 136 | 140 |
| pair_who | 1,094 | 323 | 95 | 70 |
| pairwise | 1,049 | 316 | 77 | 140 |
| transitive | 1,050 | 307 | 80 | 70 |
| three_way | 1,406 | 315 | 95 | 70 |
| multihop | 1,058 | 287 | 80 | 70 |
| chain_direct | 1,051 | 292 | 79 | 70 |
| chain_max | 1,050 | 323 | 78 | 70 |
| none | - | 3,688 | - | 225 |

Hops: train incidents 0/1/2/3 = 1,049 / 4,978 / 2,215 / 1,058; test incidents = 77 / 387 / 176 / 80.

## 4. Incidents (`tools/gen_r4_inc.py`)
Concurrent events in 2-3 domains, with onsets 0-60 min apart. Each family has a known causal graph. The prompt is rendered by
round-1 `lib.render`, which equals the app's RenderV3User: LIMITS and TANK head lines, outdoor CONTEXT, related sensors,
RE-CHECK (refine-1.5h / 3h, 2,820 rows, where the earlier revision is often wrong) and MEMORY. In about 35-50 % of rows a
domain agent is wrong or two agents contradict each other, and the gold corrects them in `agent_checks`.

| family | train | what |
|---|---|---|
| occ_load | 2,133 | occupancy → CO2 + room power (+ room temp: three_way). The power agent calls an "anomaly"; the gold says shared cause |
| heat_trans / heat_multihop / heat_three | 1,050 / 587 / 323 | outdoor heat → room temp → AC units → room power (+ arrivals) |
| worse / indep | 1,049 / 253 | two real unrelated events (CO2, pH held, PF dip) in different buildings: which is worse / no link |
| dry_run / pump_trip / leak / level_fault | 534 / 293 / 252 / 297 | tank ↔ pump: dry run is the direct cause, pump trip is the root, a leak's pump load is a symptom, a level offset starts the pump |
| ac_fail | 517 | AC units stop: the room heats and room power falls, weather steady (chain_direct) |
| pf_chain | 471 | heat → AC → feeder load → PF dip (multihop, 3 hops) |
| wx_fault / wx_fault_co2 | 367 / 285 | weather sensor jump/drift with the building flat; with a real CO2 event in parallel (real event + fault) |
| occ_fault | 347 | real CO2 with people + room power meter dropout/stuck |
| pm_ingress / pm_fault | 252 / 127 | outdoor PM → lagged indoor PM; indoor one-sample step with clean outdoor air |
| rain_level | 163 | rain (outdoor RH) → tank level rising with the pump idle |

Severity: critical 3,778, warning 4,076, normal 569, sensor_fault 877.
Test set: 35 % of items use building codes never seen in training (QX, ZR, EL, WD, FY, UV).

**New behaviour: think before the report when the FLAGGED sensors span 2+ domains.**
- The reasoning is in the assistant `reasoning_content` and the row has `"think": true`. It is at most 80 think tokens (verify_chat
  count), uses numbers and times only from the prompt, has no braces or quotes, and covers which domains are flagged, how they link
  (order, shared cause, fault) and the root and severity.
- Single-domain rows keep the empty think exactly as today: `think` is absent, so the trainer renders enable_thinking=False.
- Train: 8,554 with think, 746 without. Test: 653 / 67. Replay: 6,878 single-domain incident rows keep the empty think.
- Replay incidents whose flagged sensors span 2+ domains (623) get a short templated think ("Flagged in X and Y: … Verdict: label,
  severity"), so the rule has no exceptions in training.
- Rule used by both training and the app: count the distinct `(role)` values of `S# [FLAGGED]` header lines.
- Note: outdoor and indoor PM are both `air_quality`, so pm_ingress and pm_fault are single-domain rows (empty think) even though they cross sensors.

## 5. Chat (`tools/gen_chat_r4.py`, r4 store)
**r4 store** (`tools/make_store_r4.py`, `build/store_r4/`):
- It is the r3 device and fog stores plus 280 cross-domain clusters (heat 106, occupancy 99, leak 39, pump 36): 909 incidents, plus
  decoys (a sensor fault, a water-quality or PM event in another building).
- 3,887 incidents in total. Ids are renumbered by time in every table.
- Causal rule (same code for gold and scorer):
  - edges between labels: weather→hvac, hvac→power, occupancy→power, occupancy→hvac, power→PF, leak→pump power, pump power→supply;
  - a link needs the time order with at most 90 min between the two incidents;
  - links are campus-wide or same-building depending on the edge.

Cross-domain kinds (calls: `get_incident(anchor)` + `co_occurring_incidents(anchor[, window stated in the question])`):
- `x_relation` 285 and `x_fu_links` 152 (multi-turn) → pair_relation
- `x_who` 323 → pair_who
- `x_first` 160 (easy, empty think) and `x_severe` 156 → pairwise
- `x_direct` 292 → chain_direct
- `x_trans` 307 → transitive
- `x_three` 315 → three_way
- `x_chain` 287 → multihop
- `x_max` 323 → chain_max

Anchors are split by id (`id % 5 == 0` → test/dev only), so test questions are about incidents never seen in training.

Fix and fog kinds (3,688 rows):
- the r3 fog kinds, weighted to offline/timeout;
- cooccur / fu_cooccur / recurring with the stated-parameter policy;
- fog_status with the full state;
- r3 weak device kinds: explain_*, rank_clean, trend, recent_filtered, what-if, open_domain, unanswerable, recommend, compare.

Fog state of the new chat rows: offline 3,788, online 1,964, timeout 536. Easy 2,087 (empty think), hard 4,201 (short numberless
plan think, ≤ 80 tokens). Hinglish/code-switched rewrites: 746 (train, re-verified), about 25 % in test.

## 6. Verification (pass rates)
- **Incidents:**
  - round-1 `verify.py check_incident` + think checks: 9,300 / 9,300 train, 720 / 720 test, 60 / 60 dev kept;
  - generator rejections (no row emitted, not verify failures): 985 `worse` draws with equal severities, 4 others;
  - **app Go gate** `checkReportV3For` (+ weatherOnlyIncident): 9,300 / 9,300, 720 / 720, 60 / 60.
- **Chat:**
  - every record's gold calls are re-executed on the r4 store in its fog state and pass `verify_chat.verify` (grounded numbers,
    ids, dates and units; gold facts; refusals; think rules): train 6,288 / 6,288 (0 fails);
  - `check_schema_r3.row_ok`: 0 invalid calls;
  - test references: 925 kept after dropping 75 that overlap gate/test questions (0 reference fails); dev 55 (5 dropped).
- **Prompts:**
  - incident system == app `reasoner_v3_system.txt` byte for byte (`tools/check_prompt_r4.py`);
  - headers are unchanged from r3 (tools_r3.json; the app parity was proved in r2/r3);
  - chat system = `gen_chat_r3.system_r3` (the r3 app prompt).
- **Dedup:**
  - new train vs RWH (150), RWH-2 (150), round-1 dev (299), incidents_test_r2 (1,368), incidents_dev60 (60), chat dev v3 (300),
    chat_test_r2 (581), chat_test_r3 (983) and the new test/dev: exact incident user prompt, and chat session/last question,
    normalised;
  - drops: 0 incident, 12 chat train, 75 test, 5 dev.

## 7. Tokens per epoch (Qwen3.5-4B tokenizer, 800-row samples, `tokens_r4.json`)
| part | rows | mean | epoch |
|---|---|---|---|
| new incidents | 9,300 | 3,035 | 28.2 M |
| new chat | 6,288 | 5,741 | 36.1 M |
| replay incidents | 7,501 | 2,453 | 18.4 M |
| replay chat | 7,519 | 5,466 | 41.1 M |
| **total** | 30,608 | | **123.8 M** (r3: 267.9 M) |

## 8. Scoring the new test (`tools/`)
- `run_r4_inc.py`: llama-server raw /completion with the APP prompt.
  - `--think app` opens `<think>` only for 2+ flagged domains; `adaptive` always opens it; `off` never does.
- `eval_chat_r4.py`: post/chat_r3_eval.py loop with the tools on the r4 store.
- `score_r4.py inc|chat`: per reasoning_type, hops, family, mode, novel names and fog. Metrics:
  - severity, label, check_recall/prec, req, schema_err, ungrounded;
  - `root_domain_ok`: domain of the first sensor ref in causal_chain, gold vs prediction;
  - `think_ok_multi`, `think_present_multi`, `think_empty_single`;
  - chat: pass and `key_ok`/`reasoning_ok` (relation phrase, first-named id, mediator id, ids in order).
- `selftest_r4.py` (gold vs corrupted outputs; writes `build/selftest/scorer_selftest.json`) results:
  - incident gold scores 1.0 on severity, label, check_recall, req, root_domain, think_ok_multi and think_empty_single;
  - corrupted outputs: severity 0.0, root_domain 0.054, think rules 0.0;
  - chat answer key: gold 630/630, corrupted 70/630 (swaps that cannot change the key).
- **Ambiguous r3 test items (owner decision 2026-11-12):** `data/chat_test_r3_ambiguous.jsonl` (`tools/ambig_r3.py`).
  - 50 items whose gold has a co_occurring `window_min` or a recurring `min_count` the question does not state:
    online 17, offline 33, timeout 0 (cooccur 13, fu_cooccur 25, recurring 12). r3-2800 passed 1 of them.
  - `train/post/gate_score_r4.py` rule (c) now gates on chat_test_r3 minus this list for both models, and prints the full slices for information.
  - r3-2800 filtered baselines: online 354/404 = 0.876, offline 340/460 = 0.739, timeout 36/69 = 0.522.
  - Self-check of r3 against itself (`build/gate_selfcheck/`): all 22 checks ok; it reads INCOMPLETE only because the r4-test part (a) has no inputs there.

## 9. App change needed (reference)
The app pre-fills an empty think (`v3AssistantOpen = "<|im_start|>assistant\n<think>\n\n</think>\n\n"`) and parses the first
`{…}` with `extractJSON`. For r4 the app must:
1. open `<|im_start|>assistant\n<think>\n` when the incident's flagged roles span 2+ domains (keep the pre-fill otherwise);
2. strip everything up to `</think>` before `extractJSON`, `v3StreamTitle` / `v3StreamSeverity` and `checkReportV3For` (the think
   has no braces, but keep it out of the known text and the stream);
3. raise `maxNew` by about 100 tokens for those incidents;
4. keep the force-prefix path (`v3AnswerPrefix`) after `</think>`.

**The trainer agent has already implemented this in `reasoner_v3.go` behind the profile key `reasoner_think=adaptive`**; this
dataset matches it (rule: distinct roles of flagged sensors ≥ 2).

## 10. Known limits / risks
- The causal graph is our rule set (label pairs, time order, locality). It is plausible campus physics, but not learned from real
  data. Natural r3-store incidents are linked by the same rule, so some "links" are coincidences that the rule accepts.
- In chat the anchor's label comes from get_incident, so cross-domain questions use two calls.
- The chat world is now the r4 store (3,887 incidents). The fix kinds' counts differ from the r3 world, which is fine because the
  model never memorises the store.
- Think text is template-generated: 3-4 phrasings per family. The model may learn the templates rather than free reasoning.
  `pm_*` and `wx_fault` are single-domain by the role rule.
- chat_test_r3 still contains the unstated-parameter gold items (§1). r4 trains the opposite policy (default when unstated), so
  r3-test cooccur/recurring scores may move down while the behaviour gets better.
- Test fog mix is light on timeout (21 items). Fix-kind test slices are small (about 3-10 per kind); read them in aggregate.
- Device time is still frozen at 2026-10-22 12:00 (as r3). Hinglish is the r2 rule-based code-switch.
