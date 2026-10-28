# Track B (2026-10-24): fixing v2's weaknesses without retraining

- **Inputs:**
  - the v2 Q4_0 GGUF (`agents_v2/post/gguf/ft_v2_q4_0.gguf`);
  - its stored host outputs, tag `v2cuda`, on four sets:
    - test: 1,148 rows (3e set);
    - rw5test: 318 rows;
    - dev3f: 2,010 rows;
    - rw5dev: 313 rows.
- **Scorer:** `training/v2/post/common_v2.score_one`, the `host_eval3e` scorer.
- **Method:** rules and their thresholds were chosen on dev + rw5dev, then confirmed on test + rw5test.
- **Constraints:**
  - CPU only.
  - No prompt or model change.
  - Nothing touched the board, and nothing was committed.

## 0. Summary
- **Grammar (GBNF per role, host CPU llama-server 620d222, 89 rows; run stopped early for track A's RAM):**
  - JSON 100 → 100, policy 100 → 100.
  - The answer changed on 10 of 89 rows (79/89 identical): 0 wins, 1 loss on pattern, status and cause.
  - Decode cost −1.0 % per token (noise).
  - On host outputs the grammar adds nothing measurable: the host model is already on-label. Its value is the board's off-label case.
  - For that case, use the existing htpd label trie (no build) or the v9 patch.

- **Post-rules (Go, `postrules.go`, htpd_profile `post_rules=all`, default off)**, v2 → v2 + rules:

| set | pattern | status | cause | fault_kind | event_active | slices down > 1 pt |
|---|---|---|---|---|---|---|
| test (1,148) | 83.6 → 83.6 | **81.5 → 86.4** (57 W / 1 L) | 81.3 → 82.1 (9/0) | 71.5 → 71.5 | 91.6 → 91.6 | none |
| rw5test (318) | 72.6 → 80.2 (24/0) | **60.4 → 85.2** (79/0) | 57.9 → 72.0 (45/0) | 38.3 → 72.3 (16/0) | 77.7 → 85.5 (25/0) | none |
| dev (2,010) | = | 83.5 → 87.8 (91/6) | +16/0 | +1/0 | = | rw_real_routine −4.5 (1 row of 22) |
| rw5dev (313) | +18/0 | 62.0 → 89.5 (87/1) | +41/0 | +18/0 | +29/0 | calm_or_routine −1.2 (1 row of 80) |

- **The listed weaknesses, test unless marked rw5:**

| weakness | v2 | v2 + rules | rule(s) |
|---|---|---|---|
| power status | 66.3 | **79.9** | rel_power |
| unseen sensors, status | 70.8 | **80.7** | rel_power, rel_level |
| unseen Sep–Oct, status | 67.5 | 67.5 | none fire; this is a pattern weakness |
| erratic (pattern 27.8) | 27.8 | 27.8 | a pattern weakness, out of reach for rules |
| water status / cause | 74.9 / 69.9 | 78.8 / 73.4 | rel_level, water_cause |
| `water_cause` slice (21 rows), cause | 66.7 | 66.7 | none fire |
| 1.5 h stage, status | 77.5 | **82.7** | rel_power, rel_level |
| 3 h stage, status | 77.4 | **87.1** | rel_power, rel_level |
| early stage, status | 79.6 | **84.3** | rel_power, rel_level |
| off-label cause (`acidic_condition`) | rejected by the gate | mapped → `water_quality_issue`, valid | quality_cause, cause (+ the htpd trie, §1) |
| rw5 glitch, status | 28.1 | 59.4 | glitch |
| rw5 chatter, status (pair consistency) | 26.9 (6/26 pairs) | **92.3 (24/26)** | chatter |
| rw5 CO2 below floor, status | 46.7 | 86.7 | floor |
| rw5 acidic, status / cause | 0 / 0 | **100 / 100** | limit, quality_cause |
| rw5 gap recovery, status | 72.7 | 90.9 | rel_power |
| rw5 holiday, status | 86.7 | 86.7 | none fire; no regression |

## 1. Grammar-constrained decoding
- **Setup:**
  - Grammar: `grammar/agent_v2_<role>.gbnf`, built by `scripts/gbnf_v2.py`. It enforces the enums per role, `sensor_fault` ⇔ `fault_kind` ⇔ cause `sensor_fault`, the key order, and 1–2 observations each ending in `[E..]`.
  - Run: `scripts/grammar_eval.py`. Each row is decoded free, then with the grammar, on the same server (`-t 4`, greedy, stop at `"action"`).
  - Sample: 111 rows picked (power, unseen Sep–Oct, 1.5 h, water cause, erratic, calm, rw5 cases, plus the 3 host off-label dev rows). **89 were done** when the run was stopped twice: once by the session's memory reaper, once on the coordinator's request (track A needed the RAM). The 3 off-label dev rows were not reached.
- **Accuracy:** full table in `grammar_tables.md`.

| metric | free | grammar | W/L |
|---|---|---|---|
| json | 100.0 | 100.0 | 0/0 |
| policy | 100.0 | 100.0 | 0/0 |
| pattern | 75.3 | 74.2 | 0/1 |
| status | 58.4 | 57.3 | 0/1 |
| cause | 61.8 | 60.7 | 0/1 |
| fault_kind (n = 22) | 59.1 | 54.5 | 0/1 |
| event_active | 79.8 | 79.8 | 0/0 |

- **The single loss:**
  - Row: `t3e-rw-test-rw_fault_quantised_water-0000`. Free decoding gave a correct `flatline`/`sensor_fault`/quantised; the grammar gave `gradual_decrease`/warning.
  - The free answer is on-grammar: the vocab-only bench walks stored answers like this through the grammar token by token, and all of them stay on it.
  - So the divergence comes from llama-server's grammar sampling path, not from the grammar's language. It is not explained further; check it before any rollout.
- **Other changes:**
  - 1 cause change (rw5 glitch): free gave the inconsistent `critical` + cause `sensor_fault`; the grammar forced a non-fault cause. Both answers are wrong.
  - 8 rows changed only in free text or onset.
- **Fidelity:** the CPU free text equals the stored CUDA v2cuda text on 72/89 rows.
- **Latency (decode, same rows):**
  - free: 140.3 ms per token (7,265 tokens);
  - grammar: 138.9 ms per token (7,291 tokens);
  - overhead: −1.0 % (noise; the server checks the greedy token first).
- **Host micro-benchmark** (`htpd_grammar/bench_grammar.cpp`, `raw/bench_grammar_host.jsonl`, 12 real answers, all on-grammar):
  - accept path: 41–98 µs per token;
  - full-vocabulary mask: 23–38 ms mean, only when greedy is off-grammar.
- **htpd:**
  - It can already constrain enum values per stream with `HTPD_PATTERN_TRIE=2` + `HTPD_TRIE_KEYS=pattern,status,likely_cause` (profile `env=`, v7+ binary, no build).
  - For full GBNF per stream, `htpd_grammar/htpd_grammar_v9.patch` adds `llama_sampler_init_grammar` per stream:
    - lazy check, drafting-safe, `HTPD_GRAMMAR=1|2`, default off;
    - applies cleanly and is syntax-checked; not built.
  - Board cost estimate: ≈ 1–2 % decode wall time; ≈ 0.2–0.4 s per off-label answer instead of a 2.5–3.5 s solo re-run.
  - Details: `htpd_grammar/GRAMMAR_DESIGN.md`.
- **Verdict:**
  - Don't deploy the full grammar on accuracy grounds: no gain on the host, plus one unexplained loss.
  - Use the trie, or the `cause` post-rule, for the off-label case.
- **To finish later:** the remaining 22 rows. `grammar_eval.py run` resumes once Windows free RAM is ≥ 3 GB with training running, or after training ends.

## 2. Post-rules: what each one does, and the verdict

The rules run in `checkAgentWin` before the whitelist check and the action derivation. So a corrected status or cause is what the gate checks and what the action is derived from.

Each correction is logged in `call.Repairs` as `post-rule <rule>: <field> '<old>' -> '<new>'`.

Order: erratic, limit, quality_cause, rel_power, rel_level, water_cause, glitch, floor, chatter, cause, fkind.

| rule | what it does | gate (target up, no slice n ≥ 10 down > 1 pt) | teacher copy? |
|---|---|---|---|
| **erratic** | The model's own pattern implies a fault: `erratic` outside power → `sensor_fault`/noise; non-zero `flatline` → `sensor_fault`/stuck. | **kept**. dev 3 rows, status 2/0, policy 3/0. This fixes the 3 host off-label answers (`noisy_flow`, `noise`). | yes (v1 rule); it makes the answer self-consistent |
| **limit** | For limit-defined metrics (AQ, weather, pf, pH, TDS): status from the value against the warning/critical limits (`StatusOf`, limit branch), using the model's pattern. | **kept**. rw5 acidic 0 → 100 (12/0) on both rw5 sets. Alone, chatter −1 row (cancelled by the chatter rule). | the limits are the operator's (LIMITS line); rule = label spec |
| **quality_cause** | Water pH/TDS beyond a limit → `water_quality_issue`. | **kept**. rw5 acidic cause 0 → 100 (test), 0 → 83 (dev). No other row changes. | yes (`cause_of`) |
| **rel_power** | Power kW (no fixed limits): status from range / first-hour mean (`StatusOf` relative branch), then the v2 power routines (startup, shutdown, cyclic, solar). | **kept**. test power 66.3 → 79.9 (47/1); dev 70/4; rw5 power +12.7 / +20.3. Dev: rw_real_routine −1 row (95.5 → 90.9, n = 22), within paired noise. | **yes**: the teacher's own relative rule (a hidden `base_mean`, approximated by the first-hour mean, exactly as `RuleFinding` does) |
| **rel_level** | The same for the water tank level, with the TANK routines (overflow, filling, valve, leak, pump cycling). | **kept**. test water status +3.9 (10/0); dev +3.2 (16/2). | yes |
| rel_water (flow too) | The same, for flow. | **rejected**: dev calm −2.3, Sep–Oct −2.2, 24/12. Recurring flow spikes are labelled normal by a generator-family flag the backend cannot see. | — |
| **water_cause** | Water level/flow: the cause the v2 routine gives for the model's pattern. | **kept**. Cause test 9/0, dev 13/0. | yes |
| **glitch** | One isolated reading ≥ 8 robust σ from both neighbours (`glitchFree`) that IS the spike/dip the model reports, in an otherwise normal window. A 0 or range-rail value → `sensor_fault`/dropout. Any other value (CO2, temp, RH, TDS, pH) → normal, `event_active` false. | **kept**. rw5 glitch status 40 → 83 (dev), 28 → 59 (test), 0 losses. | REALWORLD §5.2 label |
| glitch_v1 (all metrics, always reset cause and `event_active`) | — | **rejected**: v2 dropout rows have `event_active` = true (−11 to −18 pts); tank level and RH-100 spikes are v2 events. | — |
| **floor** (250 ppm) | Indoor CO2 whose last reading is below 250 ppm (below the sensor's valid range) → `sensor_fault`, bias (stuck if flatline). | **kept**. rw5 co2_floor 40 → 83 (dev), 47 → 87 (test). 0 losses on v2 sets. | REALWORLD §5.6 |
| floor 300 / 280 | The same at 300 / 280 ppm. | **rejected**: the v2 test/dev labels call 250–300 ppm windows normal (real KH95-00 history, and the generator's clamp at 250). rw5 holiday rows at 277–290 ppm are labelled normal. | **label conflict, documented**: REALWORLD says < 300 is implausible, but the teacher labels disagree |
| **chatter** | Every reading within the 5 % deadband of the warning limit and ≥ 3 crossings → warning, event active. A `flatline`/`sensor_fault` answer is overridden only when the data crosses the limit and no flat run covers half the window (a stuck sensor at the limit is never overridden). | **kept**. rw5 chatter 27 → 92 (test), 29 → 90 (dev); pair consistency 6/26 → 24/26. | REALWORLD §5.11 label |
| **cause** | An off-label cause → synonym / keyword map per role (e.g. `acidic_condition` → `water_quality_issue`), else `sensor_fault` (with that status) or the role's normal cause (with normal), else unchanged. | **kept** (a safety net). The host never produced off-label causes after `erratic`, so 0 rows change. Go test: the board case becomes valid. | — |
| **fkind** | `sensor_fault` with a missing or invalid `fault_kind` → derive it from the pattern. | **kept** (safety net, 0 rows on host). | — |

- **Teacher-copy caveat.** v2's labels are deterministic functions of the window (teacher_v2):
  - limit, rel_power, rel_level, water_cause, erratic and quality_cause re-apply those functions to the **model's own pattern**;
  - so their gains measure consistency with the teacher. They are not new knowledge.
  - In deployment this is what we want: status follows the operator's limits and the documented relative rule, and the pattern stays the model's judgement.
  - The one hidden input is `base_mean`, the pre-event level of the synthetic base. The rules approximate it by the first-hour mean, which is also what `RuleFinding` uses.
- **Status losses (all sets): 8 rows.**
  - Where the model's pattern is wrong, the status computed from it can also be wrong (e.g. gold `erratic` critical, model `spike`).
  - Pattern accuracy is untouched, except chatter, where `flatline` → `stable` is a pattern fix.
- **Robustness:** the same rules on the stored outputs of the best 3f candidate (mixA50) give the same gains.
  - test status 82.1 → 86.9 (57/1);
  - 1.5 h 75.7 → 82.7, which turns its failing gate slice (75.7 < v2's 77.5) into a pass vs plain v2;
  - rw5test 59.1 → 84.9.
  - See `rules_tables.md`.

## 3. Go implementation
- **New files:**
  - `app/backend/postrules.go`: the rules, `routineV2` (port of `teacher_v2.routine_rule`, water and power branches), and the profile switch.
  - `app/backend/postrules_test.go`: off by default; the acidic board case; each rule; parity.
- **Changes to existing files:**
  - `policy.go`: `checkAgentWin(s, res, prompt, win)`. `checkAgent` = `checkAgentWin(…, nil)`, unchanged.
  - `reason.go`: the agent call passes `ai.Xs`.
  - `features.go`: `AgentInput.Xs`.
  - `features_v2.go`: `BuildAgentPromptV2` sets `Xs` to the prompt's window.
- **Switch:** `<workDir>/htpd_profile` line `post_rules=all`, or a subset such as `post_rules=limit,rel_power,chatter`.
  - Default: off.
  - v2 agent only. HVAC and occupancy are never touched.
  - Not part of the htpd args key, so turning it on does not restart htpd.
- **Parity:** `TestPostRulesParity` replays `raw/postrules_parity.jsonl`. That file holds every stored v2 answer of the 4 sets (3,229 non-HVAC/occupancy rows), its window, and the Python result.
  - Result: Go = Python on all 3,229 rows; 366 rows changed; 0 mismatches.
  - The test skips if the fixture is absent (local data).
- **Tests:** `GOMAXPROCS=2 go test` in WSL.
  - Full suite: green (`go_test_full.log`, 67 s).
  - Post-rules alone: `go_test_postrules.log`.
  - `go vet` is clean.

## 4. Deploy (main)
1. Rebuild the backend/APK with the Go changes. Behaviour is unchanged until the profile key is set.
2. Turn it on: add `post_rules=all` to the board's `htpd_profile`. No htpd restart is needed.
3. Optional, no htpd build: add `env=HTPD_PATTERN_TRIE=2 HTPD_TRIE_KEYS=pattern,status,likely_cause` to the same profile.
   - This needs an htpd v7+ binary (`bin=` per HANDBOOK 2.42).
   - htpd restarts, so stop the app and wait for the old process to exit (one NPU client at a time).
4. Verify through the app:
   - random inputs plus the chaos and fault runs;
   - `Repairs` shows `post-rule …` lines;
   - no `cause … not allowed` rejections;
   - the rw5-like cases (chatter at the limit, a CO2 sensor at 200 ppm, one glitch, low pH) give warning / `sensor_fault` / normal / `water_quality_issue`.
5. Optional, with a build: `htpd_grammar/htpd_grammar_v9.patch` (full GBNF per stream; see `htpd_grammar/GRAMMAR_DESIGN.md`).

## 5. Expected combined effect
- **Post-rules on, measured offline on v2's stored outputs:**
  - test status 81.5 → 86.4 (+4.9: power +13.6, unseen +9.9, 1.5 h +5.2, 3 h +9.7, early +4.7), cause +0.8;
  - rw5test status 60.4 → 85.2, cause +14.1, fault_kind +34.0, pattern +7.6 (chatter);
  - no slice down on the test sets;
  - 2 single-row dips on dev, within paired noise.
- **With the trie as well:** no off-label rejections and no solo re-runs. This is the `acidic_condition` case, seen in 2 of 3 chaos runs. On the board the cause rule alone also maps it, after the answer is generated.
- **Not reached by any rule (pattern-limited, needs training):**
  - erratic (27.8);
  - unseen Sep–Oct (67.5);
  - the `water_cause` slice;
  - CO2 floor windows at 250–300 ppm;
  - level glitches.
- **With mixA50 instead of v2:** the rules lift it the same way (test 1.5 h status 75.7 → 82.7), so its 1.5 h gate failure disappears once rules are on.

## Files
- **Tables:**
  - `rules_tables.md`: per slice, before/after, all 4 sets; each rule alone; mixA50.
  - `grammar_tables.md`.
- **Scripts (`scripts/`):**
  - `trackb_lib.py`: rules and rescoring;
  - `eval_rules.py`, `make_rule_tables.py`, `inspect_losses.py`, `export_parity.py`;
  - `gbnf_v2.py`, `grammar_eval.py`.
- **Raw data (`raw/`):**
  - `<set>_v2cuda_kept_changes.jsonl`: every changed row with its changes and gold;
  - `postrules_parity.jsonl`;
  - `grammar_sample.json`, `grammar_runs.jsonl` (texts, timings, scores), `grammar_server.log`;
  - `bench_grammar_host.jsonl`.
- **Grammar files:** `grammar/agent_v2_<role>.gbnf`.
- **htpd:** `htpd_grammar/` holds the patch, the design and `bench_grammar.cpp`.
- **Manifest:** `MANIFEST.json` (md5 of every file).
