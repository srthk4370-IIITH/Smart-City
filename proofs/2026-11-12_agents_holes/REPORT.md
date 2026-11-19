# Domain-agent holes study (B50), 2026-11-12

**Question.** Do the live domain agents (B50 = mixA50 + 0.5 (v21 - v2), Llama-3.2-3B, `Code/models_stage/ft_B50_q4_0.gguf`,
md5 bfdca67b...) have enough holes to justify a retrain?

**Answer.** Yes, but a targeted retrain only. Sensor names do not matter: renaming changes nothing beyond run-to-run noise.
The holes are in **power and water severity**, in **critical recall**, and in **false alarms on calm windows**. The holes
that do the most damage are the ones the 4B reasoner cannot repair. When a real agent run calls a faulty air-quality sensor
"normal", the 4B r3 never catches it (0 of 13 cases).

Rules followed: no board, no training, no uploads, no commits. GPU work ran under `GPU_LOCK` as "agents_holes studyA":
about 46 min in two parts (a transient WSL CUDA "unknown error" at row 1,744, then a resume). The lock was released at
12:43:56 UTC, before topup_r4 took it. Heat and RAM guards (92/88 C, Windows free RAM < 500 MB) were active; neither
triggered. Study B used the CPU only.

## Study A: sensor-name independence and absolute accuracy

**Set.** 1,000 stratified held-out dev3f windows (`C.select_rows(seed 2026)` over
`~/smartcity_runs/agents_v2_topup3f/eval_dev/eval3e.jsonl`, 2,010 windows). After de-duplicating ids, 992 are unique.
Each window ran three times:
- **orig**: the unchanged window.
- **ren**: the same window with the `NODE:` line renamed. Building codes come from a novel pool (BX, DQ, JR, MZ, FT, WC,
  GY, LU, OE, ZA). Levels, sensor numbers and gateway ids are new random numbers. The type prefix (WM-WF, SR-AC ...) and
  every value and evidence line are kept. The mapping is in `raw/rename_map.json`.
- **rep**: 150 exact repeats of orig windows, to measure the run-to-run noise floor.

Backend: llama-server CUDA b11815, `-ngl 99`, 4 slots, greedy decoding. Prompt, prefill and stop rule are the device
ones, through `host_eval_v2.gen_gguf`; host Q4_0 matches the board on 207 of 208 rows (HB 2.45). Scoring is
`common_v2.score_one`, which scores the raw model output with no app post-rules.

### A1. Rename agreement (orig vs ren)
| domain | n | pattern | status | cause | all 3 | noise floor (orig vs repeat, all 3) |
|---|---|---|---|---|---|---|
| ALL | 992 | 99.6 | 99.5 | 99.3 | **99.2** | 98.0 (147/150) |
| air_quality | 167 | 100 | 100 | 100 | 100 | 100 |
| hvac | 167 | 100 | 100 | 100 | 100 | 100 |
| occupancy | 159 | 100 | 100 | 100 | 100 | 100 |
| power | 167 | 98.8 | 98.8 | 98.8 | 98.8 | 100 (26) |
| water | 166 | 99.4 | 98.8 | 98.2 | 97.6 | 91.3 (23) |
| weather | 166 | 99.4 | 99.4 | 98.8 | 98.8 | 95.7 (23) |

Accuracy against gold is unchanged by renaming in every domain and in every gold-status slice.
- Overall: pattern 89.0 -> 89.0, status 87.2 -> 87.1, cause 87.3 -> 87.3.
- Every McNemar p is >= 0.5.
- False alarms went from 28 to 30.
- There were 5 status flips in total (power 2, water 2, weather 1). They are the same size as the batching noise seen on
  the repeats.

**Conclusion: B50 reads type and values, not names. This is not a hole.** The deferred "sensor-name independence" item
can be closed for the agents. Full tables, including per gold pattern and per family, are in `raw/A_tables.md`.

### A2. Absolute B50 accuracy (the table ROADMAP §1 said was missing)
Live merged GGUF, 992 windows, Wilson 95% CI. JSON validity was 100% in every domain.

| domain | n | pattern | status | cause | false alarms |
|---|---|---|---|---|---|
| ALL | 992 | 89.0 [87-91] | 87.2 [85-89] | 87.3 [85-89] | 28 |
| occupancy | 159 | 100 [98-100] | 100 [98-100] | 100 [98-100] | 0 |
| hvac | 167 | 97.0 [93-99] | 93.4 [89-96] | 98.2 [95-99] | 1 |
| weather | 166 | 87.3 [81-92] | 94.6 [90-97] | 86.1 [80-91] | 4 |
| air_quality | 167 | 88.0 [82-92] | 90.4 [85-94] | 88.0 [82-92] | 3 |
| water | 166 | 80.7 [74-86] | **74.7** [68-81] | **74.7** [68-81] | 7 |
| power | 167 | 81.4 [75-87] | **70.7** [63-77] | 77.2 [70-83] | 13 |

Status accuracy by gold status:

| gold status | n | status accuracy |
|---|---|---|
| normal | 497 | 91.5 |
| sensor_fault | 179 | 91.1 |
| critical | 89 | **79.8** |
| warning | 227 | **77.5** |

On calm and routine windows, 28 of 229 (12%) raise a false alarm.

The full dev3f set (2,010 windows) was also scored from the stored runtime-LoRA B50 run (`eval_dev/eval/B50`). It gives
pattern 84.7, status 83.4 and cause 84.4. Power status is 67.6 there and water status 78.7. That run and the live merged
GGUF agree on all three fields for 98.7% of the shared windows, which settles the parity check that `B50_STAGED.json`
lists as "not run".

### A3. What the errors are (`raw/A_holes.json`)
- **Power (status 71%).** The errors are severity calibration, in both directions:
  - warning -> normal: 15
  - warning -> critical: 12
  - normal -> critical: 12 (false alarms)
  - critical -> normal: 4

  The pattern errors are events read as `stable` (oscillation, spike, exponential increase). The cause errors are
  load_surge, outage or cyclic load read as `normal_load`, and the reverse. Most errors are on the event family (36 of 78).
- **Water (status 75%).** Missed leaks: possible_leak -> normal_usage (8), -> high_demand (4), -> tank_draining (3).
  Critical windows came out as normal (4), warning (4) or sensor_fault (4). Flatline windows were read as
  gradual_decrease (4). There were also 9 normal -> warning false alarms.
- **Air quality.** sensor_fault -> normal (5) and normal -> sensor_fault (4).
- **Weather.** normal_weather -> diurnal_cycle (6). This affects the cause only; status is good (94.6%).

## Study B: does a wrong agent claim survive into the final report?

### B1. Report suites with gold agent_checks, 4B r3 outputs (the gate_r3 runs), CPU
Sources: rwh 150, rwh2 150, dev 120 and test_r2 1,080 incident rows, scored with the `score_v3` hit rule. They contain
480 gold wrong, stale or unsupported agent claims. A claim **survived** if the 4B did not list it in `agent_checks`. A
surviving claim did **damage** if the report's label or severity is also wrong.

| set | wrong claims | caught | survived | survived and report wrong | severity copied from the wrong agent |
|---|---|---|---|---|---|
| ALL | 480 | 435 (90.6%) | 45 (9.4%) | **21 (4.4%)** | 17 |
| synthetic agent errors (templated) | 461 | 433 (93.9%) | 28 | 4 (0.9%) | - |
| **real agent runs** (`real_agent:*` families: v2_board, m50rw50, mixA50 ...) | **19** | **2 (10.5%)** | 17 | **17 (89%)** | - |
| real, air_quality, gold = sensor_fault | 13 | **0** | 13 | **13** | agent and report both "normal" |
| real, power / water | 4 | 1 | 3 | 3 | - |
| synthetic weather "outdoor ..." claims | 9 | **0** | 9 | 0 (the severity was right anyway) | - |
| synthetic power, gold = sensor_fault | 14 | 10 | 4 | 4 | - |

Real-agent incident rows overall (315): the 4B report has the right severity on 297 (94%). Every wrong severity on a row
where the agent was wrong came from an agent error that survived. Where the real agent was right, the report was almost
always right. Data: `raw/B_real_agent_rows.json`, `raw/B_claims.jsonl`, `raw/B_summary.json`.

**Reading.** The 4B is very good at catching the kind of agent errors it was trained on (templated contradictions). It is
almost blind to the errors real agents make, above all a confident `status=normal` on a faulty air-quality sensor. So agent
errors in this class reach the operator about 9 times in 10, and the agent model is where they have to be fixed.

### B2. The 2,978-incident r3 training store (`data/store/fog_store_r3.sqlite`)
The store is synthetic: its S1 agent fields are generated from the incident label, not from B50. In it, agent status equals
the report severity on 2,976 of 2,978 incidents. On the 279 incidents the operator closed as `false_alarm`, the agent alarm
went straight into the report every time (132 of 132 alarm cases).

This cannot measure B50's propagation. It shows only that the store teaches "the report severity follows the agent", which
is the opposite of what B1 needs. That is worth fixing in the 4B data, which is outside this study.

The board dumps (`2026-10-27_reasoner_fast/raw/board_incidents*.jsonl`) date from Oct 13-14, before B50, and were not used.

## Holes ranked by impact on final reports
Impact = how often the agent error happens x how often it survives into the report x how much damage it does.

1. **A missed sensor fault reported as "normal" (air quality first).** B50 does this on 5 of 167 AQ windows. Real-agent
   history shows it survives the 4B 13 of 13 times, and the report then shows a healthy reading for a broken sensor.
2. **Power severity calibration.** Status is 70.7% (67.6% on the full dev). There are 12 normal -> critical false alarms and
   19 missed or under-graded events. Power is the largest incident domain (533 of 2,978 store S1 incidents; 547 of 2,010
   dev windows). The 4B catches synthetic power errors 89% of the time, but real ones only 1 time in 3.
3. **Water: missed leaks and critical events.** possible_leak becomes normal_usage or high_demand 12 times; critical
   becomes normal or warning 8 times; status is 74.7%.
4. **Critical recall is 79.8%, warning 77.5%** across domains. These under-graded alerts are the most costly for an alert
   product.
5. **False alarms on calm windows: 12%** (28 of 229). This is B50's known weakness against mixA50 (calm 10 wins / 27
   losses).
6. Minor: the weather cause (diurnal vs normal) has no severity impact. The 4B never checks weather "outdoor" claims (0 of
   9), but the severity stayed right.

Not a hole: sensor names (99.2% agreement against a 98.0% noise floor), occupancy (100%) and HVAC (93-98%).

## Retrain recommendation: YES, targeted top-up from B50 (not from scratch)
The holes are not "very few". Two domains have status at 71-75%, critical recall is 80%, and one error class goes through
the reasoner unchecked. History shows broad retrains regress (3e, T30, P3b), so this retrain should be narrow.

**Spec (b50_r1)**
- **Base.** Re-merge B50 in bf16 with `proofs/2026-10-25_domain_plan/scripts/b50_build.sh` (merge_mix: mixA50 +
  0.5 (v21 - v2)). The merged bf16 has been deleted; only `choice.json` remains in `post/B50`. Upload the merged model to
  Kaggle as a private dataset, after the owner says yes.
- **Data, about 8k rows, prompts of about 700 tokens.**
  - **Replay, 60%: about 4.8k rows.** These are B50's own correct outputs on train-split windows, so they are B50
    replay targets, not raw v2 gold (the P3b lesson). Stratify them by domain and family, with at least 25% calm and
    routine windows.
  - **Targeted, 40%: about 3.2k rows.** Generate them with `generate_v2` / `teacher_v2` from train months only, then pass
    them through the validator:

    | target | rows | content |
    |---|---|---|
    | power severity | 1,000 | warning vs critical vs normal boundaries; outages, surges and cyclic load around the limits; hard negatives for normal -> critical |
    | water | 800 | slow and night leaks vs usage; critical tank and supply events; flatline vs gradual decrease |
    | sensor faults that look calm | 700 | AQ first, then all domains: stuck, bias, drift and dropout faults whose values look plausible (the real-agent miss pattern) |
    | critical and warning recall | 400 | all domains |
    | calm and routine negatives | 300 | against false alarms |
  - **Names.** Randomise node, building, level and number in 30% of rows. The model is already name-independent; this
    keeps it that way.
- **Recipe.** QLoRA r 16, alpha 32, on all linear layers. LR 5e-5 cosine, 1 epoch, NLL on the completion only, max length
  1,024, effective batch 32. On a Kaggle T4 (fp16, gradient checkpointing) this takes about 2-3 h for 8k rows. Then merge,
  convert to Q4_0 with the v2 imatrix (`imatrix_v2.gguf`), and check that the tensor types match B50.
- **Gate (host GPU after r4, or Kaggle).** All of these must hold:
  1. gate2 against B50 on dev3f: net > 0, severity-weighted net >= 0, no Holm-worse slice, and calm/routine not worse.
  2. E1 net >= 0 and safety 16/16.
  3. Absolute status accuracy: power >= 78 and water >= 80, with no domain dropping more than 2 points.
  4. Critical status recall >= 85.
  5. Rename agreement >= the noise floor (rerun `scripts/run_A.py` with the new GGUF).
  6. Final check on the untouched `eval_test` (1,148 windows).
  7. Feed the 315 real-agent incidents through the 4B with the new agent outputs: the number of wrong reports must not
     rise.
- **Reasoner side (note for r5, not part of this retrain).** Add real-agent missed-fault incidents to the 4B data, and
  drop the "severity = agent status" coupling from the synthetic store.

## Files
- `scripts/`:
  - `build_rename.py`, `run_A.py`, `run_A.sh` (the GPU_LOCK wrapper), `analyse_A.py`, `holes_A.py`
  - `study_B.py`, `study_B_real.py`
- `raw/`:
  - Study A rows and outputs: `rows_A.jsonl`, `samples_A.jsonl` (2,134 generations), `rename_map.json`
  - Study A results: `A_tables.md`, `A_summary.json`, `A_holes.json`
  - Study B results: `B_claims.jsonl`, `B_summary.json`, `B_real_agent_rows.json`
  - Logs: `server.log`, `tokenize_check.json` (1 BOS, tokens identical to htpd), `run_A_part1.log`

## Addendum 2026-11-13: label audit corrects Study B (history above left unchanged)
Source: `proofs/2026-11-13_label_audit/AUDIT.md` (every real-agent row checked: is the gold visible in the prompt's E-lines?).
- Of the 19 real-agent wrong claims in B1, **9 have a gold the evidence does not support**: all 9 are ONE PM10 window
  (`test-air_quality-00176`, AQ-AN00-00: last 64.6 ug/m3, noise 3.54, flat run 2, E9 none, E10 none), gold `sensor_fault` from a
  weak injected `noise_increase`. The agent's and r3's "normal" is correct there.
- Corrected B1 real-agent line: **10 evidence-supported real agent errors, r3 caught 2 (20 %), 8 survived with a wrong report**
  (not 19 / 2 / 17).
- Corrected "AQ faulty sensor called normal": **4 rows (2 windows: a drop-to-0 dropout, a 9.9x-excursion noise burst), caught 0**
  (not 0 of 13). Still a real hole, but 4 rows, not 13.
- Real-agent report severity on the 315 rows: 297/315 on the original gold; on the cleaned gold (11 dropped as undecidable)
  295/304 (97.0 %).
- Holes ranking: item 1 stays (missed visible faults survive the 4B) but its size is 4 rows, not 13; items 2-6 unchanged.
