# RESULTS (host phase 2, tag `full`)

Generated 2026-11-26 01:00 by analyze.py. All accuracy numbers are on INJECTED cases (B, F-injected) or D controls; real windows (A, F-natural) are unscored. 'both' = label AND severity match the injection gold. 95% CIs are bootstrap (2000 resamples) in brackets; McNemar exact two-sided.

## RQ2: what escalation buys (Set B, injected, n=153)

| N domains | n | arm | label acc % | severity acc % | both % | missed critical |
|---|---|---|---|---|---|---|
| 2 | 63 | cheap (isolatedReport) | 46.0 [33.3, 58.7] | 79.4 [68.3, 88.9] | 42.9 [31.7, 55.6] | 1/33 |
| 2 | 63 | cheap_x (fallbackReport) | 38.1 [27.0, 49.2] | 82.5 [73.0, 92.1] | 38.1 [27.0, 50.8] | 1/33 |
| 2 | 63 | full (agents+reasoner) | 81.0 [71.4, 90.5] | 93.7 [87.3, 98.4] | 79.4 [68.3, 88.9] | 1/33 |
| 2 | 63 | Mode 2-fair (reasoner, no agents) | 85.7 [76.2, 93.7] | 88.9 [81.0, 96.8] | 81.0 [71.4, 90.5] | 3/33 |
| 3-4 | 60 | cheap (isolatedReport) | 11.7 [3.3, 20.0] | 83.3 [73.3, 91.7] | 10.0 [3.3, 18.3] | 2/33 |
| 3-4 | 60 | cheap_x (fallbackReport) | 18.3 [10.0, 28.3] | 86.7 [78.3, 95.0] | 18.3 [8.3, 28.3] | 1/33 |
| 3-4 | 60 | full (agents+reasoner) | 73.3 [61.7, 83.3] | 93.3 [86.7, 98.3] | 70.0 [58.3, 81.7] | 3/33 |
| 3-4 | 60 | Mode 2-fair (reasoner, no agents) | 86.7 [76.7, 95.0] | 63.3 [50.0, 75.0] | 51.7 [38.3, 65.0] | 17/33 |
| 5+ | 30 | cheap (isolatedReport) | 20.0 [6.7, 33.3] | 86.7 [73.3, 96.7] | 20.0 [6.7, 33.3] | 1/22 |
| 5+ | 30 | cheap_x (fallbackReport) | 30.0 [16.7, 46.7] | 86.7 [73.3, 96.7] | 30.0 [13.3, 46.7] | 0/22 |
| 5+ | 30 | full (agents+reasoner) | 83.3 [70.0, 96.7] | 90.0 [80.0, 100.0] | 76.7 [60.0, 90.0] | 2/22 |
| 5+ | 30 | Mode 2-fair (reasoner, no agents) | 96.7 [90.0, 100.0] | 93.3 [83.3, 100.0] | 90.0 [80.0, 100.0] | 2/22 |
| all | 153 | cheap (isolatedReport) | 27.5 [20.3, 34.6] | 82.4 [76.5, 88.2] | 25.5 [19.0, 32.7] | 4/88 |
| all | 153 | cheap_x (fallbackReport) | 28.8 [21.6, 35.9] | 85.0 [79.1, 90.2] | 28.8 [21.6, 36.6] | 2/88 |
| all | 153 | full (agents+reasoner) | 78.4 [71.9, 85.0] | 92.8 [88.2, 96.7] | 75.2 [68.6, 81.7] | 6/88 |
| all | 153 | Mode 2-fair (reasoner, no agents) | 88.2 [82.4, 93.5] | 79.7 [73.2, 85.6] | 71.2 [64.1, 78.4] | 22/88 |

Paired tests (full vs cheap, both-correct; b = full right & cheap wrong, c = reverse):

- N=2, full vs cheap: b=27 c=4 p=0.0
- N=2, full vs cheap_x: b=29 c=3 p=0.0
- N=2, full vs m2: b=10 c=11 p=1.0
- N=3-4, full vs cheap: b=36 c=0 p=0.0
- N=3-4, full vs cheap_x: b=31 c=0 p=0.0
- N=3-4, full vs m2: b=19 c=8 p=0.0522
- N=5+, full vs cheap: b=19 c=2 p=0.0002
- N=5+, full vs cheap_x: b=16 c=2 p=0.0013
- N=5+, full vs m2: b=2 c=6 p=0.2891
- N=all, full vs cheap: b=82 c=6 p=0.0
- N=all, full vs cheap_x: b=76 c=5 p=0.0
- N=all, full vs m2: b=31 c=25 p=0.5044

Mapping-corrected cheap label accuracy (Set B): the cheap template reports only the LEAD sensor's cause->label. Counting a label as right when the gold label is the label of ANY flagged agent's cause (an upper bound for a fair cause->label map): 69.3 [61.4, 76.5] % (strict cheap: 27.5 [20.3, 34.6] %).

Per family (both-correct %, full / cheap / Mode 2-fair):

- ac_fail (n=14): 71 / 86 / 93
- crowd_co2 (n=20): 70 / 0 / 75
- crowd_heat (n=20): 50 / 0 / 45
- fault_vs_event (n=10): 90 / 10 / 80
- heat_ac3 (n=20): 75 / 5 / 60
- heat_ac_water (n=20): 85 / 25 / 50
- heat_crowd_water (n=15): 87 / 33 / 100
- heat_crowd_water_hvac (n=15): 67 / 7 / 80
- heat_room (n=9): 89 / 44 / 89
- pm_ingress (n=10): 90 / 100 / 70

## Set D: negative controls (50 normal windows, 15 real sensor-fault windows)

| arm | false-alarm rate (normal reported as warning/critical/fault) | false sensor_fault rate (normal) | fault detected as sensor_fault (n=15) | fault called an event (warning/critical) |
|---|---|---|---|---|
| cheap (isolatedReport) | 10.0 [2.0, 20.0] | 4.0 [0.0, 10.0] | 33.3 [13.3, 60.0] | 13.3 [0.0, 33.3] |
| cheap_x (fallbackReport) | 44.0 [30.0, 58.0] | 8.0 [2.0, 16.0] | 33.3 [13.3, 60.0] | 46.7 [20.0, 73.3] |
| full (agents+reasoner) | 42.0 [28.0, 56.0] | 14.0 [6.0, 24.0] | 46.7 [20.0, 73.3] | 13.3 [0.0, 33.3] |
| Mode 2-fair (reasoner, no agents) | 54.0 [40.0, 68.0] | 16.0 [6.0, 26.0] | 33.3 [13.3, 60.0] | 33.3 [13.3, 60.0] |

Event called a sensor fault (injected events in B and F whose gold is not sensor_fault, n=165), per arm: cheap 0.6 [0.0, 1.8]; cheap_x 0.0 [0.0, 0.0]; full 2.4 [0.6, 4.8]; m2 0.7 [0.0, 2.1]

## Set F: forced single-domain cases (n=50: 30 injected with gold, 20 natural unscored)

- The app's rule (>= 2 domains) escalates 3 of 50 of these; so every case where the reasoner would have fixed the cheap report is a MISSED escalation: 1 of 30 (3.3 %). Escalations that would have hurt (cheap right, full wrong): 0.
- cheap (isolatedReport) both-correct on F-injected: 96.7 [90.0, 100.0]
- full (agents+reasoner) both-correct on F-injected: 100.0 [100.0, 100.0]
- Missed escalations by family: single_power_surge 1
- Natural single-domain (unscored, n=20): cheap vs full discordance (label or severity) 65.0 %; any-critical in 60.0 %.

## RQ1 host proxy: cost per case (laptop GPU Q4_0; sequential-equivalent agent time; swap cost is a board-only quantity and is NOT included)

| N domains | n | cheap s (agents) | full s (agents+reasoner) | Mode 2-fair s | full/cheap | reasoner prefill tok | reasoner decode tok | Mode 2 prefill tok | agent calls |
|---|---|---|---|---|---|---|---|---|---|
| 1 (F,D 1-dom) | 85 | 3.56 | 13.1 | 9.14 | 3.68x | 895 | 448 | 818 | 1.0 |
| 2 | 63 | 7.37 | 19.37 | 11.0 | 2.63x | 1613 | 550 | 1289 | 2.0 |
| 3-4 | 60 | 12.15 | 24.79 | 11.16 | 2.04x | 1993 | 572 | 1585 | 3.33 |
| 5+ | 30 | 21.44 | 34.63 | 12.21 | 1.62x | 3295 | 566 | 2599 | 6.0 |

## RQ3: offline trigger study (universe: B + D + F-injected = 248 gold-labelled cases; policy = escalate to the full path when the trigger fires, else keep the cheap report)

Cost = host seconds per case (agents always; reasoner only when escalated). Oracle escalates exactly when full is right and cheap is wrong (91 of 248 cases = 36.7 %, not implementable). Precision/recall are against that oracle. Domain count here = flagged domains (the app's own rule also counts informative context domains).

| policy | escalation rate % | both-correct % [95% CI] | label % | severity % | host s/case | precision vs oracle | recall vs oracle |
|---|---|---|---|---|---|---|---|
| domains>=2 | 73.8 | 70.2 [64.5, 75.8] | 72.2 | 84.3 | 18.19 | 0.459 | 0.923 |
| any critical | 48.4 | 62.5 [56.5, 68.5] | 66.5 | 85.5 | 14.88 | 0.4 | 0.527 |
| rules-vs-agent disagree | 39.5 | 63.3 [57.7, 69.0] | 64.9 | 89.5 | 14.03 | 0.51 | 0.549 |
| agent uncertain | 20.2 | 44.0 [38.3, 50.4] | 46.8 | 79.8 | 11.40 | 0.18 | 0.099 |
| site-tree links | 73.8 | 70.2 [64.5, 75.8] | 72.2 | 84.3 | 18.19 | 0.459 | 0.923 |
| domains>=2 OR critical | 80.2 | 70.2 [64.5, 75.8] | 72.2 | 84.3 | 18.75 | 0.422 | 0.923 |
| domains>=2 OR disagree | 79.8 | 71.4 [65.7, 77.0] | 73.8 | 85.5 | 18.80 | 0.439 | 0.956 |
| critical OR disagree | 63.7 | 69.8 [64.5, 75.4] | 72.2 | 89.9 | 16.73 | 0.43 | 0.747 |
| disagree OR uncertain | 52.0 | 61.7 [55.6, 67.7] | 63.7 | 87.1 | 15.35 | 0.419 | 0.593 |
| domains>=2 OR crit OR disagree OR uncertain | 91.1 | 70.6 [64.9, 76.2] | 73.0 | 84.7 | 19.81 | 0.385 | 0.956 |
| never (cheap) | 0.0 | 44.8 [38.7, 51.2] | 46.8 | 82.7 | 9.14 | None | 0.0 |
| always (full) | 100.0 | 69.8 [63.7, 75.8] | 72.2 | 83.5 | 20.59 | 0.367 | 1.0 |
| oracle | 36.7 | 81.5 [76.6, 86.3] | 83.1 | 91.9 | 13.65 | 1.0 | 1.0 |

Escalation rate per trigger by stratum (percent of cases the trigger fires):

| trigger | B N=2 | B N=3-4 | B N=5+ | D | F-injected | A (natural, unscored) |
|---|---|---|---|---|---|---|
| domains>=2 | 100.0 | 100.0 | 100.0 | 46.2 | 0.0 | 14.0 |
| any critical | 57.1 | 70.0 | 86.7 | 0.0 | 53.3 | 73.5 |
| rules-vs-agent disagree | 31.7 | 48.3 | 93.3 | 26.2 | 13.3 | 67.0 |
| agent uncertain | 15.9 | 8.3 | 16.7 | 33.8 | 26.7 | 16.0 |
| site-tree links | 100.0 | 100.0 | 100.0 | 46.2 | 0.0 | 14.0 |

## Set A: natural replay (n=200, unscored): routing and short-circuit

- App routing rule (>= 2 domains incl. informative context) would escalate 15.5 % (short-circuit rate 84.5 %); flagged domains >= 2 in 14.0 %; the set was sampled 86/14 single/multi (no natural 5+ windows exist). Any-critical 73.5 %, rules-vs-agent disagreement 67.0 %. Cheap vs full discordance 53.5 % (unscored). Host cost: cheap 4.67 s, full 15.52 s per case.
- Real-data note: natural windows are dominated by feeder power-factor dips and PM/CO2 sensor quirks (see Caveats), so rates here describe this campus in this period, not a general workload.

## Run health

- Reasoner valid 97.0 % over 468 cases; fallback template fired 14; think on 83.1 %; tool calls 6; Mode 2-fair valid 100.0 % (n=218).

## Appendix: BLEU / ROUGE / chrF

Not computed: the frozen sets carry gold label, severity and affected domains by construction but no gold report text (RESEARCH_PAPER.md section 7 demotes these metrics because part of any gold text is self-distilled). Reasoner texts are in records.jsonl for a later judge-based or text-metric pass.

## Caveats

- **Thin post-cutoff data.** Real baselines come only from the 20 days after the 2025-12-11 cutoff. Weather exists for about 3.8 days, outdoor PM for 6.7, occupancy and water level essentially never; weather families therefore cluster in a few days and N=5+ cases reuse the same windows with different injections. Effective independent baselines are far fewer than 153.
- **CO2 re-base.** The campus CO2 sensor reads physically implausibly low (median 364 ppm, 44 % of windows rule-flagged as sensor_fault), so injections level-shift the pre-event CO2 to 430-520 ppm; occupancy baseline is held vacant and the event injected.
- **Cheap label mapping artefact.** The Go template maps the LEAD sensor's agent cause through causeToLabel and reports one domain (and `normal_operation` for causes it does not map). At N >= 2 this makes low cheap label / domain scores partly structural. Mapping-corrected (any flagged agent's label) accuracy is given in RQ2; cheap_x is the cross-domain template. Cheap severity is derived from the lead finding's status (Go's isolatedReport has no severity field).
- **Python rule mirror.** Rule status / patterns come from the training-time rules (generate_dataset.py + features.py), not rules.go with per-node card thresholds; disagreement, critical and domain-count trigger inputs are approximate. 'Flagged' sensors are the injected ones (occupancy and hvac forced into the incident in the 5+ family), not what the live alert path would have promoted.
- **Gold by construction.** Injected gold labels encode one root-cause story per family; reasonable alternative labels (e.g. hvac_or_thermal_issue for a heat chain) count as wrong. Injection generators are separate from training generators but share the stories (LEAKAGE.md).
- **Mode 2-fair** = reasoner model + reasoner prompt with every agent line removed (raw evidence only, context sensors kept), no tools.
- **Host proxy only.** Costs are laptop-GPU Q4_0 seconds; swap, streams and thermal pacing exist only on the board (Set C). Agent time is the sequential sum of per-call times (the run used np=4).
- Retrieval off (empty frozen corpus); no retrieval ablation.

## Extra metrics from existing records (item 1; extra1.py, results/extra1.json)

Universe: gold-labelled B + D + F-injected (n=248; Mode 2-fair only on B+D, n=218). Bootstrap 1000 resamples.

### Severity macro-F1 (classes normal / warning / critical / sensor_fault)

| arm | n | macro-F1 [95% CI] | F1 normal | F1 warning | F1 critical | F1 sensor_fault |
|---|---|---|---|---|---|---|
| cheap | 248 | 0.766 [0.701, 0.823] | 0.763 | 0.807 | 0.935 | 0.560 |
| cheap_x | 248 | 0.705 [0.629, 0.768] | 0.644 | 0.711 | 0.915 | 0.549 |
| full | 248 | 0.789 [0.727, 0.841] | 0.659 | 0.830 | 0.947 | 0.719 |
| Mode 2-fair | 218 | 0.647 [0.572, 0.710] | 0.554 | 0.667 | 0.815 | 0.553 |

Confusion matrices (rows = gold, columns = predicted; order normal, warning, critical, sensor_fault):

- cheap: [45,3,0,2]; [6,46,8,0]; [1,3,100,1]; [16,2,1,14]
- cheap_x: [28,16,2,4]; [1,48,11,0]; [1,2,102,0]; [7,9,3,14]
- full: [29,13,1,7]; [1,56,3,0]; [0,5,99,1]; [8,1,1,23]
- Mode 2-fair: [23,17,2,8]; [3,48,3,1]; [2,20,66,0]; [5,4,3,13]

### Affected-domain set F1 (B + F-injected, D excluded; gold = injected domain set incl. context domains)

| arm | n | mean per-case F1 | micro F1 | micro P | micro R |
|---|---|---|---|---|---|
| cheap | 183 | 0.561 | 0.474 | 0.995 | 0.311 |
| cheap_x | 183 | 0.911 | 0.918 | 0.849 | 1.000 |
| full | 183 | 0.852 | 0.830 | 0.903 | 0.768 |
| Mode 2-fair | 153 | 0.856 | 0.847 | 0.916 | 0.787 |

### Grounding (all non-A cases that have a prompt; validity checked against the FULL reasoner prompt, the Mode 2-fair prompt text was not logged)

| arm | cases | evidence ids | id validity | flagged-sensor coverage | numbers in text | ungrounded-number rate |
|---|---|---|---|---|---|---|
| full | 268 | 1138 | 99.91 % | 88.5 % | 2473 | 1.90 % |
| Mode 2-fair | 218 | 868 | 99.65 % | 85.0 % | 1854 | 1.78 % |
| cheap | 268 | 1290 | 100.00 % | 99.4 % | 1345 | 0.00 % |
| cheap_x | 268 | 2295 | 100.00 % | 97.5 % | 677 | 5.61 % |

id validity = cited evidence id (Sx.Ey) occurs in the prompt. Coverage = share of [FLAGGED] sensors with at least one cited evidence id. Ungrounded number = a number in title/root_cause/causal_chain/explanation/observation text that appears nowhere in the prompt (heuristic string match; derived values such as a sum or a rounding count as ungrounded, so it is an upper bound). cheap/cheap_x numbers come from templates.

### Latency, paired Wilcoxon signed-rank (B+D, n=218; per-case host seconds, cheap = agents only, full = agents + reasoner, Mode 2-fair = reasoner only)

| pair | median A s | median B s | median diff s | W | p |
|---|---|---|---|---|---|
| full vs cheap | 19.77 | 7.64 | 11.96 | 0 | 1.6e-37 |
| full vs Mode 2-fair | 19.77 | 10.86 | 9.39 | 0 | 1.6e-37 |
| Mode 2-fair vs cheap | 10.86 | 7.64 | 2.54 | 8472 | 0.00029 |

### Retrieval-hit rate

Logged per case (`retrieval_hits`) but the paper runs used an EMPTY frozen corpus (see LEAKAGE.md): hits > 0 in 0 of 468 cases; the reasoner made a tool call in 5 cases. Retrieval therefore had no chance to help or hurt in the main arms; the retrieval ablation (item 4) is correspondingly a no-op unless a populated corpus is used.

## Prefill-token table, N = 1/2/4/8/12 flagged sensors (item 2; prefill_table.py, results/prefill_table.json)

Real prompt builders (pcase.assemble / render_reasoner, agent prompts of pcore, the Mode 2-fair line filter of run_case.py), real tokenizer (the Q4_0 GGUF's own vocab through llama-server /tokenize, chat template via /apply-template; agent GGUF for agent prompts, reasoner GGUF for reasoner prompts). N flagged sensors are drawn round-robin over roles from the 18-sensor campus network on real windows (6 windows for N<=4, 4 for N=8, 3 for N=12; windows with missing sensor data are skipped). Rule findings stand in for agent findings (same line shape). Context sensors are added by the real picker (up to 4), so the sensors-in-prompt column is larger than N.

| N flagged | windows | sensors in prompt | agent calls | agent tok / call | agent tok total (all calls) | reasoner prompt tok (Mode 3 full) mean [max] | Mode 2-fair prompt tok mean [max] | > 4096 ? |
|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 2.2 | 1 | 815 | 815 | 1455 [1650] | 1303 [1426] | no |
| 2 | 6 | 4.7 | 2 | 796 | 1592 | 2282 [2557] | 1939 [2134] | no |
| 4 | 6 | 6.7 | 4 | 809 | 3237 | 3186 [3570] | 2662 [2989] | no |
| 8 | 4 | 11.2 | 8 | 813 | 6505 | 5030 [5279] | 4162 [4413] | YES (full), borderline (Mode 2-fair mean 4162 > 4096) |
| 12 | 3 | 14 | 12 | 810 | 9726 | 6366 [6403] | 5267 [5371] | YES (both) |

Cross-check against the measured full run (records.jsonl, `prefill_tokens` as reported by llama-server, may exclude cached prefix): real N=1 cases averaged 1041, N=2 1587 (table 1455 / 2282: the table draws mixed-role flagged sets with more context sensors), real 5+ cases 3283 mean, max 3916 (33 cases), so every real run stayed under 4096; the table shows the knee: the reasoner prompt crosses 4096 at about N = 5-6 flagged mixed-role sensors and 12 sensors need about 6.4k tokens (agent side: 1 call per flagged sensor, ~810 tokens each, under the 1024 agent ctx).

Overflow behaviour (C6), MEASURED on the board (Set C, setc_board.sh, results/setc_board.json): the live htpd runs the reasoner with `--reason-ctx 8192`, not 4096, so the 4096 column above is the old limit; at 8192 even the N=12 Set C prompts fit (median prefill 13.8 s, no ctx stop). Probe `ovf_x0` (the N=12 user text doubled, 31.9k chars, > 8192 tokens): htpd prefilled for 23.7 s, then returned 0 tokens with `stop = "ctx"` (htpd logged `reason prefill failed (rc 1)`; no crash, no silent truncation, process stayed up until the harness stopped it). In the app this is an invalid report, so the Go fallback template takes over. The earlier source-only reading (prefill false / ctx stop) is confirmed, with the threshold at 8192.

Mode 2 as-built token counts (agent model + old singlePrompt) are not in the table: the Go singlePrompt builder has no Python port on the host (see item 3).

## Classical baselines on Set B + D (item 5; baselines.py, results/baselines.json, baselines_rows.json)

Task: anomaly vs normal per case (gold anomaly = gold severity != normal: 153 injected B cases + 15 real sensor-fault D windows = 168; 50 normal D windows). Case score = max over its flagged sensors. Mode 1 = the python rule mirror (generate_dataset.py + features.py rules), Isolation Forest = per sensor key, 200 trees on 10 window features, fitted on 500 real PRE-cutoff windows (400 fit / 100 held out; alarm threshold = 90th percentile of held-out normal scores; 2 water-quality keys have no data and are skipped, n_if = 218); STL = robust STL (period 288) on 7 days of real history + the case window, alarm when max |residual| > K x robust sigma of the history residual (K=4; n_stl = 206, others had < 80 % history coverage). F1 CI = bootstrap 1000.

| method | recall B (injected events) | false-alarm rate on 50 normal | recall on 15 real sensor faults | F1 [95% CI] | balanced acc | AUROC |
|---|---|---|---|---|---|---|
| Mode 1 rules-only (any flagged sensor non-normal) | 1.000 | 0.000 | 1.000 | 1.000 [1.000, 1.000] | 1.000 | - |
| Isolation Forest (score>1) | 0.987 | 0.360 | 0.133 | 0.903 [0.869, 0.933] | 0.813 | 0.907 |
| STL + threshold (K=4) | 0.948 | 0.440 | 0.333 | 0.882 [0.842, 0.917] | 0.754 | 0.902 |
| cheap (agents + template) | 0.908 | 0.100 | 0.467 | 0.915 [0.882, 0.945] | 0.904 | - |
| cheap_x | 0.967 | 0.440 | 0.800 | 0.914 [0.882, 0.943] | 0.764 | - |
| full (agents + reasoner) | 0.987 | 0.420 | 0.533 | 0.914 [0.883, 0.943] | 0.783 | - |
| Mode 2-fair | 0.967 | 0.540 | 0.667 | 0.895 [0.861, 0.929] | 0.714 | - |

Threshold sweeps (no tuning on the test set was used for the headline rows): STL K=3/4/6/8/12/20 gives F1 0.882 / 0.882 / 0.893 / 0.898 / 0.894 / 0.907 and false alarm 0.44 / 0.44 / 0.36 / 0.32 / 0.30 / 0.18; IF threshold 0.8/1.0/1.2/1.5 gives F1 0.876 / 0.903 / 0.879 / 0.000 and false alarm 0.90 / 0.36 / 0.06 / 0.00.

Mode 1 rules-only on the full task (lead sensor's rule status as severity, causeToLabel of its rule cause as label), B+D n=218: severity acc 94.0 %, label acc 38.1 %, both 38.1 %; on Set B only: severity 91.5 %, label 17.0 %, both 17.0 % (full LLM path on B: severity 92.8, both 75.2; Mode 2-fair severity 79.7, both 71.2).

Reading: (1) the rules score a perfect anomaly F1 by construction, not by merit: gold severity and the injected windows are generated with the same rule logic (Python mirror of the training-time rules), so this is a circular upper bound for detection, not evidence that rules beat the LLM; the honest information is that the LLM arms ADD label / cross-domain cause (Mode 1 label 17.0 % on B vs 78 % full) while detection itself is cheap and rule-solvable. (2) The statistical baselines (IF, STL) detect injected events (recall 0.95-0.99) but cannot tell a real sensor fault from an event (recall 0.13-0.33 as 'anomalous' only; they have no cause or severity output) and false-alarm on 36-44 % of normal windows at the stated thresholds (STL K=20 / IF 1.2 trade recall for 6-18 %). (3) Normal-window false alarms of the LLM arms (cheap 10 %, full 42 %) come from D windows where the rules say normal but the model reads a mild pattern as warning; see Set D above.


## Mode 3 ablations (item 4; extra34.py, results/extra34.json)

Guards = the validity gate (JSON + label + severity enums) with the cross-domain template as fallback; 'no guards' scores the same raw reasoner output but an invalid report counts as wrong. The Go severity guard (rule anchor) is not part of the python pipeline and is not ablated.

### Set B, all 153 cases: no tools / no retrieval, retrieval ON, no guards

| arm | label % | severity % | both % [95% CI] | both, paired diff vs full (pp) [95% CI] | McNemar b / c / p (b = arm right & full wrong) |
|---|---|---|---|---|---|
| full (main, guards on) | 78.4 [71.9, 84.3] | 92.8 [88.2, 96.7] | 75.2 [68.6, 81.7] | - | - |
| no tools (no retrieval, no more-data) | 88.2 [83.0, 92.8] | 85.0 [79.1, 90.2] | 74.5 [67.3, 81.1] | -0.7 [-9.8, +8.5] | 27 / 28 / 1.0 |
| retrieval ON (populated past-incident store: MEMORY + incident tools) | 79.1 [72.5, 85.6] | 87.6 [82.4, 92.2] | 74.5 [67.3, 81.0] | -0.7 [-9.8, +7.8] | 25 / 26 / 1.0 |
| no guards (invalid output counts as wrong) | 76.5 [69.9, 83.0] | 90.2 [85.0, 94.8] | 73.2 [66.0, 80.4] | -2.0 [-3.9, +0.0] | 0 / 3 / 0.25 |
- `nt`: mean reasoner wall 12.73 s (main run, same cases 12.48 s), mean prefill tokens 2095 (main 2092)
- `rt`: mean reasoner wall 12.81 s (main run, same cases 12.48 s), mean prefill tokens 2262 (main 2092)
- `rt` store: 468 past incidents (248 closed with an outcome: sensor_fault gold -> sensor_repaired, normal -> no_action_needed, other -> fixed_by_action; outcomes simulated from gold of OTHER, earlier cases, >= 12 h before the case window). MEMORY lines reached 152 of 153 prompts (mean 2.97 lines, max 3). Tool calls: 0 of 153 cases.

### Fixed stratified 60 of Set B (20 per N stratum, host speed): no context agents

| arm | label % | severity % | both % [95% CI] | both, paired diff vs full (pp) [95% CI] | McNemar b / c / p (b = arm right & full wrong) |
|---|---|---|---|---|---|
| full (main, guards on) | 78.3 [68.3, 88.3] | 90.0 [83.3, 96.7] | 73.3 [61.7, 83.3] | - | - |
| no tools (no retrieval, no more-data) | 90.0 [81.7, 96.7] | 85.0 [75.0, 93.3] | 75.0 [63.3, 85.0] | +1.7 [-13.3, +16.7] | 11 / 10 / 1.0 |
| no context agents | 83.3 [73.3, 91.7] | 80.0 [68.3, 90.0] | 70.0 [58.3, 81.7] | -3.3 [-18.3, +10.0] | 9 / 11 / 0.8238 |
| no guards (invalid output counts as wrong) | 76.7 [66.7, 86.7] | 86.7 [78.3, 95.0] | 71.7 [60.0, 81.7] | -1.7 [-5.0, +0.0] | 0 / 1 / 1.0 |
- `nc`: mean reasoner wall 12.27 s (main run, same cases 12.55 s), mean prefill tokens 1948 (main 2298)

Retrieval note: the paper runs used an empty frozen corpus; the reasoner called a tool in only 0 of 153 Set-B cases and every call returned an empty result, so 'no retrieval' and 'no tools / no more-data' are the same ablation here (the `rt` arm above repeats Set B with a populated store).

Retrieval ON result: a populated store changed nothing measurable. MEMORY (3 past incidents with outcomes on the same sensors) reached 152 of 153 prompts, but the reasoner never called find_incidents / get_action_history, and both-correct moved 75.2 -> 74.5 (-0.7 pp, McNemar 25 / 26, p = 1.0) for +170 prefill tokens per case (2262 vs 2092). Caveat: outcomes are simulated from gold of earlier cases, not real operator closures.

## Mode 2 as built (item 3; agent model agt3_s0450 Q4_0 + singlePrompt port; Set B + D; mode2_asbuilt.py, results/extra34.json)

Severity = ruleSeverity of the flagged sensors (this mode's report has no severity key; the Go reasonerSeverity guard is not ported). Label gate: JSON parses and label in the 13 report labels, else rule-fallback template (as Go).

| set | n | arm | label % | severity % | both % [95% CI] | valid JSON+label % |
|---|---|---|---|---|---|---|
| B | 153 | Mode 2 as built (agent model, old prompt) | 22.9 [16.3, 29.4] | 89.5 [84.3, 94.1] | 20.9 [14.4, 27.5] | 79.7 |
| B | 153 | Mode 2-fair (reasoner, no agents) | 88.2 [83.0, 92.8] | 79.7 [73.2, 85.6] | 71.2 [64.1, 78.4] | - |
| B | 153 | Mode 3 full | 78.4 [71.9, 85.0] | 92.8 [88.9, 96.7] | 75.2 [68.0, 82.4] | - |
| B | 153 | cheap (Mode 3 template) | 27.5 [20.3, 34.6] | 82.4 [76.5, 88.2] | 25.5 [19.0, 32.7] | - |
| D | 65 | Mode 2 as built (agent model, old prompt) | 27.7 [16.9, 38.5] | 100.0 [100.0, 100.0] | 27.7 [16.9, 38.5] | 87.7 |
| D | 65 | Mode 2-fair (reasoner, no agents) | 33.8 [21.5, 46.2] | 43.1 [30.8, 55.4] | 33.8 [23.1, 46.2] | - |
| D | 65 | Mode 3 full | 44.6 [32.3, 55.4] | 53.8 [41.5, 66.2] | 43.1 [30.8, 55.4] | - |
| D | 65 | cheap (Mode 3 template) | 69.2 [58.5, 80.0] | 76.9 [66.2, 86.2] | 66.2 [53.8, 76.9] | - |
- Set B both-correct, Mode 3 full vs Mode 2 as built: b=92 (arm right, as-built wrong) c=9 p=0.0
- Set B both-correct, Mode 2-fair vs Mode 2 as built: b=84 (arm right, as-built wrong) c=7 p=0.0
- Mode 2 as built: mean host wall 2.05 s per case, mean prompt tokens 1206; label invalid -> fallback in 39 of 218 cases.
- Set D normal windows (n=50): as-built reports severity != normal (rule severity) in 0.0 % and a label != normal_operation in 88.0 %.

## Root-cause text judge (item 6; judge.py, results/judge.json, runs/full/judge_out.jsonl)

Judge = the UNTUNED Qwen3.5-4B (q8_0, ~/models/qwen3.5-4b-gguf; not the reasoner under test, but the same base family the reasoner was fine-tuned from), thinking off, greedy, temperature 0, one candidate per call, anonymised (arm names, mode and label/severity fields stripped; only root_cause + causal_chain + explanation), calls in shuffled order. The judge is told the true cause, domains and severity of the injected scenario and rates 0 / 1 / 2. Set B n=153, plus a mismatched DECOY per case (another case's full report with a different gold label) as a validity check.

| candidate | n | mean score (0-2) [95% CI] | % scored 2 | % scored 0 |
|---|---|---|---|---|
| Mode 3 full | 153 | 1.869 [1.778, 1.948] | 93.5 | 6.5 |
| Mode 2-fair | 153 | 1.843 [1.752, 1.922] | 92.2 | 7.8 |
| cheap template | 153 | 1.399 [1.242, 1.542] | 69.9 | 30.1 |
| DECOY (wrong case) | 153 | 1.301 [1.137, 1.451] | 64.7 | 34.6 |

Paired Wilcoxon: full vs Mode 2-fair diff +0.026 p=0.64; full vs cheap +0.471 p=4e-07; Mode 2-fair vs cheap +0.444 p=2e-06. Label-correct full reports mean 1.95 (n=120) vs label-wrong 1.58 (n=33).

**Validity verdict: weak judge.** The decoy (a wrong-case report) still gets 1.30 on average and 64.7 % top scores, barely below the cheap template (1.40), so the 4B judge cannot separate right from wrong cause reliably; it is lenient and anchored on the supplied scenario words. Only the coarse ordering (LLM reports > template/decoy, p<1e-6) is usable, and full vs Mode 2-fair is a tie (p=0.64), consistent with the label-accuracy result. Do not report this as an accuracy measure in the paper; a stronger judge (human or larger model) is needed. Caveats: 4B model, shared base family with the reasoner, gold = injection story, not free text.

## BLEU / ROUGE-L / chrF (item 7, supersedes the appendix note above)

Computed on the frozen gate set gold free text, the held-out r4 cross-domain subset and the domain agent: see METRICS_MODELS.md (textmetrics.py, metrics_models.py, results/textmetrics.json). v5 (deployed) report text vs gold JSON: BLEU 43.1 / ROUGE-L 52.1 / chrF 52.9 (p2 33.2 / 42.2 / 45.0). The paper sets A/B/D/F still have no gold text, so no text metric is reported for the main arms.

## RQ1 on the board (measured, 2026-11-26)

Details: `BOARD_RQ1.md`, raw data `results/board_incidents.json`. The source is the 14 incidents the board ran on the v5 reasoner. Set C (N = 1/2/4/8/12) was measured on a stopped-app harness: see "Set C on the board" below.

| Flagged sensors | n | Total (s) | Agents (s) | Reasoner (s) | Reasoner TTFT (s) |
|---|---|---|---|---|---|
| 1 | 7 | 18.2 | 3.1 | 12.0 | 1.6 |
| 2 | 5 | 19.2 | 5.4 | 21.3 | 2.4 |
| 3 | 2 | 36.8 | 12.3 | 25.7 | 3.6 |

- **Swap and prefill** (medians over 24 swaps): reasoner swap in 2.83 s, agent model back in 2.30 s, prefill 1.45 s.
- **Board cost ratio:** escalation costs about 5–6× the cheap path, against a host proxy of 1.6–3.7×.
- **N ≥ 4:** measured in Set C on the board (below).

**Finding: the deployed app always escalates.** `reason.go:1004` sends single-domain incidents to reasoner v3 too (owner decision, 2026-10-27), and all 7 N=1 board incidents have a reasoner report. The deployed policy is therefore the "always" baseline of RQ3. "Domains ≥ 2" (the Set A 15.5% routing rate) is the pre-v3 policy and a candidate trigger, not the deployed one.

## BERTScore (plan section 7 appendix; bertscore_run.py, results/bertscore.json)

- **Setup:** roberta-large, layer 17 (the bert-score default for English), F1 x 100, on the same pairs as BLEU / ROUGE-L / chrF.
- **Report pairs:** root_cause + causal_chain + explanation, joined.
- **Domain agent pairs:** severity_reason.
- **Rescaled:** baseline-rescaled F1 (raw BERTScore crowds near 90). Bootstrap 95% CI over rows.
- **Caveat:** demoted like BLEU, because part of the gold text is self-distilled.

| model | report F1 (rescaled) | chat_en F1 (rescaled) | tool_chain F1 (rescaled) |
|---|---|---|---|
| v5 (deployed) | 92.3 (54.5 [50.1, 58.6]) | 94.3 (66.5 [55.5, 76.7]) | 90.5 (43.7 [31.9, 56.5]) |
| fix60 | 91.9 (51.8 [47.4, 56.5]) | 94.1 (65.0 [55.1, 75.5]) | 90.2 (41.9 [28.4, 55.0]) |
| p2 | 90.9 (46.1 [42.0, 50.3]) | 92.3 (54.6 [42.9, 66.9]) | 89.3 (36.3 [26.5, 45.9]) |
| r3c1 | 90.2 (42.2 [38.6, 46.5]) | 87.2 (24.0 [16.4, 31.9]) | 88.7 (33.1 [23.9, 43.3]) |

Domain agent agt3_s0450, severity_reason (n=160): F1 97.8 (87.0 [83.0, 90.8]).

v5 is highest on every slice. The ranking v5 > fix60 > p2 > r3c1 matches BLEU / chrF.

## Fix 1: all-normal skip rule (owner 2026-11-26; skip_rule.py, results/skip_rule.json; offline from the full run, no reruns)

When every flagged sensor's agent AND rule say normal, the reasoner is not called and the report is a deterministic normal; otherwise the full path is unchanged (all sensors sent). Cause it targets: in 15 of the 21 Set D false alarms every agent and rule said normal and the reasoner still raised the severity (11 warning, 3 sensor_fault, 1 critical). `skip+ctx` also requires every context sensor's rule to be normal.

| arm | Set B both % | Set B severity % | Set B missed critical | D false alarm % (n=50) | D fault -> sensor_fault % (n=15) | F-injected both % (n=30) | reasoner calls skipped (B / D / F / A) | host s per case (B+D+F) |
|---|---|---|---|---|---|---|---|---|
| full | 75.2 [68.6, 81.7] | 92.8 [88.2, 96.7] | 6/88 | 42.0 [28.0, 56.0] | 40.0 [13.3, 66.7] | 100.0 [100.0, 100.0] | 0 / 0 / 0 / 0 | 20.69 |
| skip | 75.2 [68.0, 82.4] | 92.8 [88.2, 96.7] | 6/88 | 12.0 [4.0, 22.0] | 40.0 [13.3, 66.7] | 96.7 [90.0, 100.0] | 0 / 43 / 1 / 0 | 18.92 |
| skip+ctx | 75.2 [68.0, 81.7] | 92.8 [88.2, 96.7] | 6/88 | 24.0 [12.0, 36.0] | 40.0 [20.0, 66.7] | 96.7 [90.0, 100.0] | 0 / 28 / 1 / 0 | 19.62 |

- Skipped F-injected cases with a non-normal gold (the skip hides a real event): F-024. Set A (natural, unscored): the skip fires on 0 of 200 windows.
- F-024 (injected critical power surge): the python rule mirror and the power agent both read it as stable 12.88 kW, yet the reasoner reported critical from the raw window. The skip trusts agents + rules, so when both miss an event the reasoner's second look is lost. Live incidents start only from a rule flag, so a window where every rule says normal is rare in the app (Set A: 0 of 200 natural windows would skip).
- Chosen: `skip` (agents + rules), all sensors still sent when anything is not normal (dropping context cut Set B severity 90 -> 80 % on the fixed 60, for ~0.3 s). Not deployed: the owner reviews all fixes after the board sets finish.

## Set C on the board: forced schema vs adaptive thinking (2026-11-26; setc_board.sh + board_drive.py, setc_analyze.py, results/setc_board.json)

Same 50 cases (N = 1/2/4/8/12 flagged sensors x 10 real windows), the deployed models (agt3_s0450 + rsn_v3_4b_v5, Q4_0, htpd_v9h, reason ctx 8192, 3 streams), v4 prompt, standalone htpd with the app stopped, each case started at <= 55 C. Forced = what the live app runs today (think off, schema + split 3). Adaptive = profile reasoner_think=adaptive (think open, no schema, the Go runV3Loop replayed by board_drive.py). Medians per N; valid = the final text parses as JSON with a severity and label.

| N | agents s | forced: reasoner s | forced: prefill/TTFT s | forced: tokens | forced: valid | adaptive: reasoner s | adaptive: TTFT s | adaptive: tokens | adaptive: valid |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 10.2 | 24.9 | 1.7 | 680 | 5/10 | 30.1 | 1.7 | 512 | 9/10 |
| 2 | 24.2 | 40.5 | 3.7 | 872 | 3/10 | 36.9 | 3.9 | 532 | 10/10 |
| 4 | 44.2 | 44.1 | 6.5 | 907 | 1/10 | 45.2 | 6.9 | 560 | 10/10 |
| 8 | 78.6 | 43.6 | 10.5 | 844 | 4/10 | 46.5 | 11.2 | 534 | 10/10 |
| 12 | 123.1 | 47.2 | 13.7 | 540 | 7/10 | 52.8 | 14.6 | 542 | 9/10 |

- **Forced decoding loops on the board.** 30 of 50 forced reports were invalid: most ran to the token limit repeating a sentence (stop `max`, ~700+ tokens), so the JSON never closed and the app would show the template fallback. The host runs (adaptive) repeated in 3 of 468.
- **Adaptive fixes it at about the same cost.** 48 of 50 valid; every case closed its thinking and answered in ONE call (no second forced call, no tool call), ~510-560 tokens. Reasoner time is +5 s at N=1 (30.1 vs 24.9 s), -4 to +6 s at N=2-12. The 2 invalid adaptive reports are small JSON syntax slips (a trailing comma, one extra brace) that the Go parser does not repair.
- **Agents dominate at large N.** Agent time grows ~linearly (10 s at N=1 to 123 s at N=12, one call per flagged sensor + context); the reasoner grows only from 30 to 53 s (prefill/TTFT 1.7 to 14.6 s). Swap-in ~3.1-3.3 s per case throughout.
- **Overflow (> 8192 tokens, ovf_x0):** forced: 23.7 s prefill then 0 tokens, stop `ctx`; adaptive: the same twice (the loop's second call also overflows), 54.6 s, empty report. Both end in the template fallback, no crash.
- Caveat: every case starts at <= 55 C and the board heats to 79-85 C per case, so decode is slower than live (186-222 ms/step vs 83-152 ms live); these are upper-bound costs.

## Sets B + D reasoner on the board (2026-11-26; board_drive.py bd, bd_score.py, results/bd_board.json)

Same user prompts as the host full arm (host agent findings; agents are 207/208 host = board), deployed v5 reasoner, v4 prompt, adaptive thinking, standalone htpd with the app stopped, each case started at <= 55 C. Guards as in the paper (invalid -> template fallback); skip = Fix 1.

| measure | board | host |
|---|---|---|
| valid reports, B+D | 208/218 (95.4 %) | 212/218 (97.2 %) |
| Set B both correct, raw (invalid = wrong) | 112/153 (73.2 %) | 112/153 (73.2 %) |
| Set B both correct, guards on | 113/153 (73.9 %) | 115/153 (75.2 %) |
| Set B label / severity, guards on | 126/153 (82.4 %) / 135/153 (88.2 %) | 120/153 (78.4 %) / 142/153 (92.8 %) |
| D false alarm (normal windows) | 25/50 (50.0 %) | 21/50 (42.0 %) |
| D false alarm with skip rule | 5/50 (10.0 %) | 6/50 (12.0 %) |
| D real faults called sensor_fault | 4/15 (26.7 %) | 6/15 (40.0 %) |
| board = host (label and severity) | 129/218 (59.2 %) | - |
| reasoner wall s, median (B / D) | 34.2 / 29.6 | 12.4 / 10.5 |

- Set B board vs host, both-correct McNemar: board-only right 21, host-only right 23, p = 0.88.

- **Board accuracy = host accuracy.** Set B both-correct is identical raw (73.2 %) and within noise with guards (73.9 vs 75.2 %, McNemar p = 0.88), so the host-run paper results carry to the board. Individual answers differ (59 % of cases identical): Q4_0 on the NPU and the GPU are not bit-identical, so greedy decoding drifts; the errors move between cases, not in number.
- **Severity is a little lower on the board** (88.2 vs 92.8 %) and label a little higher (82.4 vs 78.4 %); the same trade-off seen in the no-tools ablation.
- **False alarms reproduce on the board** (50 % of normal windows) and the skip rule removes them there too (10 %).
- **Board reasoner time** is ~2.8x the host (34 s vs 12 s median on B), including swap-in (~3 s) and thermal pacing (upper bound, see Set C caveat).
