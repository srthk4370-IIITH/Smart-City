# Stage-aware post-hoc fixes (simulated on device outputs)

| fixes | 40 min (early, n=48) | 1.5 h chain | 3 h chain (app ladder) | 3 h plain n=48 | 3 h plain n=96 | 3 h plain n=144 | clean: refine-stage pattern != stable n=48/96/144 |
|---|---|---|---|---|---|---|---|
| none | 0.738 | 0.792 | 0.858 | 0.825 | 0.836 | 0.803 | [37, 57, 57] |
| invalid | 0.743 | 0.792 | 0.858 | 0.836 | 0.847 | 0.803 | [37, 50, 57] |
| invalid+flat | 0.743 | 0.787 | 0.847 | 0.842 | 0.836 | 0.792 | [37, 50, 57] |
| invalid+flat+exp | 0.743 | 0.776 | 0.858 | 0.863 | 0.847 | 0.803 | [37, 50, 57] |

3 h chain per pattern, baseline -> invalid+flat+exp: dip 13->13/14, erratic 16->16/21, exponential_increase 16->18/21, flatline 21->21/21, gradual_decrease 11->11/14, gradual_increase 16->16/21, oscillation 13->13/15, spike 18->18/21, step_decrease 14->12/14, step_increase 19->19/21

changed labels (stage, truth, before, after): ('1.5h', 'gradual_increase', 'gradual_increase', 'exponential_increase'): 9; ('1.5h', 'exponential_increase', 'gradual_increase', 'exponential_increase'): 7; ('3h', 'step_decrease', 'step_decrease', 'flatline'): 2; ('3h', 'exponential_increase', 'gradual_increase', 'exponential_increase'): 2; ('1.5h', 'step_decrease', 'step_decrease', 'flatline'): 1; ('1.5h', 'step_decrease', 'INVALID', 'flatline'): 1; ('40m', 'exponential_increase', 'INVALID', 'exponential_increase'): 1; ('40m', 'gradual_increase', 'INVALID', 'oscillation'): 1; ('1.5h', 'gradual_increase', 'INVALID', 'exponential_increase'): 1

bootstrap 95% CI of the 3 h chain gain: [-0.022, +0.022]  (in-sample: thresholds chosen on this set; confirm on a fresh seed)