
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

## Mode 2 as built (item 3; agent model agt3_s0450 Q4_0 + singlePrompt port; Set B + D; mode2_asbuilt.py, results/extra34.json)

Severity = ruleSeverity of the flagged sensors (this mode's report has no severity key; the Go reasonerSeverity guard is not ported). Label gate: JSON parses and label in the 13 report labels, else rule-fallback template (as Go).

| set | n | arm | label % | severity % | both % [95% CI] | valid JSON+label % |
|---|---|---|---|---|---|---|
| B | 153 | Mode 2 as built (agent model, old prompt) | 22.9 [16.3, 29.4] | 89.5 [85.0, 94.1] | 20.9 [14.4, 27.5] | 79.7 |
| B | 153 | Mode 2-fair (reasoner, no agents) | 88.2 [82.4, 92.8] | 79.7 [73.2, 85.6] | 71.2 [64.1, 78.4] | - |
| B | 153 | Mode 3 full | 78.4 [71.9, 85.0] | 92.8 [88.9, 96.7] | 75.2 [68.6, 81.7] | - |
| B | 153 | cheap (Mode 3 template) | 27.5 [20.3, 34.6] | 82.4 [75.8, 88.2] | 25.5 [19.0, 32.7] | - |
| D | 65 | Mode 2 as built (agent model, old prompt) | 27.7 [16.9, 38.5] | 100.0 [100.0, 100.0] | 27.7 [16.9, 38.5] | 87.7 |
| D | 65 | Mode 2-fair (reasoner, no agents) | 33.8 [23.1, 46.2] | 43.1 [30.8, 53.8] | 33.8 [23.1, 46.2] | - |
| D | 65 | Mode 3 full | 44.6 [32.3, 56.9] | 53.8 [41.5, 66.2] | 43.1 [30.8, 55.4] | - |
| D | 65 | cheap (Mode 3 template) | 69.2 [56.9, 80.0] | 76.9 [66.2, 86.2] | 66.2 [53.8, 76.9] | - |
- Set B both-correct, Mode 3 full vs Mode 2 as built: b=92 (arm right, as-built wrong) c=9 p=0.0
- Set B both-correct, Mode 2-fair vs Mode 2 as built: b=84 (arm right, as-built wrong) c=7 p=0.0
- Mode 2 as built: mean host wall 2.05 s per case, mean prompt tokens 1206; label invalid -> fallback in 39 of 218 cases.
- Set D normal windows (n=50): as-built reports severity != normal (rule severity) in 0.0 % and a label != normal_operation in 88.0 %.
