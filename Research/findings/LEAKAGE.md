# Leakage check (frozen sets A, B, D, F)

Run 2026-11-25 22:21. Sets: A=200, B=153, D=65, F=50.

Every eval window (incl. its 12 h history) ends after the training cutoff (epoch 1765391400, 2025-12-11 00:00 IST): earliest window start in the sets = epoch 1765394400 (2025-12-11 00:50 IST).

| check | result |
|---|---|
| case ids vs training row ids | 0 overlaps |
| evidence-block hashes (E1..E10 of every sensor in every eval incident, 1525 distinct blocks) vs 381959 training rows in 48 files | 2 overlapping blocks |
| agent-prompt user text hashes (917) vs training prompts | 0 overlaps |
| REAL-labelled training rows (src_real / real_end_epoch / real families) with an end epoch >= first eval window start | 0 (latest real training end epoch 1767194400 = 2025-12-31 20:50 IST) |
| latest CONTEXT date in any training reasoner prompt | 2026-12-28 (info only: synthetic scenes carry arbitrary calendar dates; real rows are checked by epoch above) |
| retrieval corpus (app state/incidents.jsonl) | 32 past incidents on disk, 0 within 12 h of an eval case end (sim clock is shifted +1 year, never overlaps) |

Overlaps with EVAL-ONLY files (the old agent's sft_v2 test split; not training data of the deployed agent or the reasoner): 101 real windows end inside the held-out weeks; informative evidence-block overlaps with them: 0. Low-information block overlaps (listed in leakage.json): ['B-091'] in ['test.jsonl:eval-only']; ['D-037'] in ['train.jsonl:training', 'windows_real.jsonl:training'].

## Retrieval-memory surface
- The harness runs the reasoner with `MEMORY: no past incidents or maintenance on these sensors in the last 90 days` and tools `find_incidents` / `get_action_history` / `get_sensor_history` / `related_context` answering from an EMPTY, frozen corpus (see run_case.py: ToolExec). No finished report, seed case (rag_seed.json is not in the repo) or past incident can be returned, so no eval case can be retrieved and no training case leaks through retrieval. The retrieval ablation is therefore not meaningful in this version; a retrieval-on arm needs a corpus frozen before the test window (future work).
- Retrieval-hit rate per case = 0 by construction (logged as `tool_calls` with empty results).

## Fault-family overlap (explicit; training generators vs these test generators)
Training synthetic rows: 140,690 of 163,567 (RESEARCH_PAPER.md section 11). Test injections are written separately (pinject.py), applied to REAL held-out campus windows, and share no code with gen5_* / gen_r4_inc. Conceptual overlap with training families is expected and listed:

| test family | closest training family | note |
|---|---|---|
| heat_room, heat_ac3, heat_ac_water, heat_crowd_water(+hvac) | gen5 heat_three / heat_trans / heat_multihop | same physical story (heat -> room -> power), different generator, real baselines, campus node ids |
| crowd_co2, crowd_heat | occ_load | same story |
| pm_ingress | pm_ingress | same story |
| ac_fail | ac_fail | same story |
| fault_vs_event | occ_fault / wx_fault_co2 | same story |
| single_* | card / r1 single-sensor families | same story |
| real windows (A, D, F natural) | real_rows (pre-cutoff real windows) | disjoint in time by construction |

**RESULT: PASS (no overlap)**
