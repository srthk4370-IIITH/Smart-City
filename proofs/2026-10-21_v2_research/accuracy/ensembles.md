# Cheap post-hoc fixes simulated on device outputs (placement_v2)

## 1. What the app would actually show at 3 h (ladder + keep-early-spike/dip rule), baseline model
app-chain 3 h pattern accuracy: 157/183 = 0.858 CI (0.8, 0.901); ladder n used: Counter({144: 89, 48: 50, 96: 44})
  same chain, window fixed n=48: 0.842
  same chain, window fixed n=96: 0.852
  same chain, window fixed n=144: 0.814
plain d=36 (no keep rule): {48: 0.825136612021858, 96: 0.8360655737704918, 144: 0.8032786885245902}
n=48 at 3 h + keep-early rule only: 154/183 = 0.842
app-chain per pattern: dip 13/14, erratic 16/21, exponential_increase 16/21, flatline 21/21, gradual_decrease 11/14, gradual_increase 16/21, oscillation 13/15, spike 18/21, step_decrease 14/14, step_increase 19/21

## 2. Deterministic rule detector (v1 rule_pattern = app rules.go) accuracy
d=8 n=48: rules 46/183 = 0.251 | dip 11/14, erratic 1/21, exponential_increase 13/21, flatline 0/21, gradual_decrease 1/14, gradual_increase 0/21, oscillation 2/15, spike 14/21, step_decrease 3/14, step_increase 1/21
d=36 n=48: rules 94/183 = 0.514 | dip 11/14, erratic 4/21, exponential_increase 19/21, flatline 21/21, gradual_decrease 8/14, gradual_increase 12/21, oscillation 6/15, spike 11/21, step_decrease 1/14, step_increase 1/21
d=36 n=96: rules 86/183 = 0.470 | dip 9/14, erratic 0/21, exponential_increase 12/21, flatline 21/21, gradual_decrease 1/14, gradual_increase 0/21, oscillation 6/15, spike 11/21, step_decrease 10/14, step_increase 16/21
d=36 n=144: rules 62/183 = 0.339 | dip 9/14, erratic 0/21, exponential_increase 7/21, flatline 21/21, gradual_decrease 0/14, gradual_increase 0/21, oscillation 9/15, spike 7/21, step_decrease 5/14, step_increase 4/21
clean n=48: rules call [('stable', 59), ('dip', 17), ('spike', 13), ('oscillation', 8), ('erratic', 3)]
clean n=96: rules call [('stable', 35), ('spike', 24), ('dip', 18), ('flatline', 15), ('oscillation', 5), ('exponential_increase', 2), ('step_decrease', 1)]
clean n=144: rules call [('flatline', 27), ('stable', 27), ('spike', 22), ('dip', 16), ('oscillation', 7), ('erratic', 1)]

rule precision by called label (events d in {18,24,36}, all n; clean counted as wrong if not stable):
dip 86/216=0.40, erratic 8/35=0.23, exponential_increase 101/219=0.46, flatline 189/435=0.43, gradual_decrease 24/30=0.80, gradual_increase 16/18=0.89, oscillation 54/263=0.21, spike 94/233=0.40, stable 121/310=0.39, step_decrease 52/98=0.53, step_increase 58/90=0.64
model precision by called label (same rows): INVALID 0/23=0.00, dip 114/131=0.87, erratic 124/126=0.98, exponential_increase 117/141=0.83, flatline 183/206=0.89, gradual_decrease 104/110=0.95, gradual_increase 145/221=0.66, oscillation 104/175=0.59, spike 145/232=0.62, stable 149/231=0.65, step_decrease 121/148=0.82, step_increase 182/197=0.92

## 3. Model confidence vs correctness (events, d=36, all n)
conf 0.3: 22/34, conf 0.35: 12/15, conf 0.4: 11/15, conf 0.55: 9/10, conf 0.6: 2/20, conf 0.65: 26/26, conf 0.7: 69/82, conf 0.75: 35/60, conf 0.8: 9/13, conf 0.85: 56/59, conf 0.9: 1/1, conf 0.95: 199/211

## 4. Post-hoc override policies (no extra NPU calls)
| policy | 3h n=48 | 3h n=96 | 3h n=144 | app-chain 3h | 40min n=48 | 90min n=48 | clean flag n=48/96/144 (pattern!=stable) |
|---|---|---|---|---|---|---|---|
| baseline | 0.825 | 0.836 | 0.803 | 0.858 | 0.738 | 0.825 | [37, 57, 57] |
| invalid->rule | 0.836 | 0.847 | 0.803 | 0.858 | 0.743 | 0.831 | [37, 51, 57] |
| +flatline rule | 0.842 | 0.738 | 0.607 | 0.738 | 0.743 | 0.820 | [37, 51, 57] |
| +exp(rule, conf<=.5) | 0.863 | 0.743 | 0.607 | 0.738 | 0.672 | 0.760 | [37, 51, 57] |
| +exp(rule|tail, conf<=.5) | 0.869 | 0.749 | 0.607 | 0.743 | 0.661 | 0.765 | [37, 51, 57] |
| +lowconf<=.3 -> rule | 0.847 | 0.694 | 0.579 | 0.705 | 0.639 | 0.727 | [37, 51, 57] |
| +lowconf<=.5 -> rule | 0.831 | 0.699 | 0.579 | 0.699 | 0.639 | 0.727 | [37, 51, 57] |

## 5. Multi-window self-consistency at the 3 h refinement (extra NPU calls)
vote over (48, 96) (tie -> 48) [baseline]: 3h 0.825; clean flag 37/100
vote over (48, 96) (tie -> 48) [+exp/flat fixes]: 3h 0.869; clean flag 37/100
vote over (48, 96, 144) (tie -> 48) [baseline]: 3h 0.852; clean flag 44/100
vote over (48, 96, 144) (tie -> 48) [+exp/flat fixes]: 3h 0.749; clean flag 45/100
vote over (96, 48, 144) (tie -> 96) [baseline]: 3h 0.852; clean flag 49/100
vote over (96, 48, 144) (tie -> 96) [+exp/flat fixes]: 3h 0.754; clean flag 49/100
vote over (144, 96, 48) (tie -> 144) [baseline]: 3h 0.842; clean flag 49/100
vote over (144, 96, 48) (tie -> 144) [+exp/flat fixes]: 3h 0.738; clean flag 49/100
confidence-weighted vote 48/96/144 [baseline]: 3h 0.852; clean flag 47/100
confidence-weighted vote 48/96/144 [+exp/flat fixes]: 3h 0.749; clean flag 46/100
vote at 1.5 h (48/96/144): 0.809 vs n=48 alone 0.825
temporal vote d=18/24/36 at n=48 (no extra calls if the app kept 1.5 h + an added 2 h refinement): 0.852

bootstrap 95% CI of delta (vote48/96/144 + fixes) - (n=48 baseline) at 3 h: (-0.142, -0.016)
bootstrap 95% CI of delta (exp/flat/invalid fixes) - baseline at 3 h n=48: (0.005, 0.082)