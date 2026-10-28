# v2 placement study on the QIDK NPU (features_v2 prompts, 12 h history)


## Window 48 x 5 min (4 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 45 | 74 | 79 | 82 | 86 | 82 |
| spike | 76 | 86 | 81 | 71 | 76 | 76 |
| dip | 79 | 86 | 93 | 93 | 86 | 86 |
| step_increase | 95 | 100 | 100 | 100 | 100 | 95 |
| step_decrease | 79 | 93 | 93 | 93 | 100 | 93 |
| gradual_increase | 19 | 86 | 81 | 81 | 86 | 90 |
| gradual_decrease | 29 | 79 | 86 | 86 | 86 | 93 |
| exponential_increase | 76 | 76 | 67 | 71 | 71 | 71 |
| oscillation | 0 | 20 | 60 | 80 | 87 | 87 |
| flatline | 5 | 90 | 100 | 100 | 100 | 86 |
| erratic | 0 | 19 | 33 | 57 | 71 | 57 |

clean windows: false alarm (status != normal) 18.0% (n=100), any flag 38.0%; v1 agent: 31%

## Window 96 x 5 min (8 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 48 | 75 | 79 | 77 | 80 | 84 |
| spike | 86 | 86 | 81 | 76 | 81 | 71 |
| dip | 79 | 86 | 93 | 93 | 93 | 93 |
| step_increase | 90 | 100 | 95 | 100 | 100 | 100 |
| step_decrease | 71 | 93 | 93 | 93 | 100 | 100 |
| gradual_increase | 19 | 95 | 90 | 71 | 67 | 71 |
| gradual_decrease | 29 | 79 | 79 | 86 | 86 | 79 |
| exponential_increase | 76 | 76 | 67 | 52 | 48 | 71 |
| oscillation | 0 | 27 | 53 | 60 | 73 | 73 |
| flatline | 10 | 86 | 100 | 95 | 95 | 95 |
| erratic | 14 | 19 | 43 | 52 | 67 | 86 |

clean windows: false alarm (status != normal) 29.0% (n=100), any flag 57.0%; v1 agent: 31%

## Window 144 x 5 min (12 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 44 | 70 | 74 | 78 | 82 | 80 |
| spike | 71 | 76 | 76 | 81 | 86 | 71 |
| dip | 71 | 79 | 86 | 93 | 86 | 93 |
| step_increase | 81 | 90 | 86 | 90 | 90 | 90 |
| step_decrease | 71 | 93 | 86 | 86 | 100 | 100 |
| gradual_increase | 14 | 76 | 76 | 81 | 81 | 62 |
| gradual_decrease | 36 | 86 | 79 | 79 | 86 | 64 |
| exponential_increase | 67 | 71 | 57 | 52 | 52 | 67 |
| oscillation | 0 | 33 | 60 | 73 | 80 | 80 |
| flatline | 19 | 90 | 100 | 100 | 100 | 100 |
| erratic | 10 | 10 | 38 | 52 | 67 | 81 |

clean windows: false alarm (status != normal) 27.0% (n=100), any flag 58.0%; v1 agent: 31%

## Acceptance

```
{
 "n=48": {
  "pattern_40min": {
   "rate": 0.738,
   "n": 183,
   "ci95": [
    0.67,
    0.796
   ]
  },
  "pattern_3h": {
   "rate": 0.825,
   "n": 183,
   "ci95": [
    0.764,
    0.873
   ]
  },
  "false_alarm_clean": {
   "rate": 0.18,
   "n": 100,
   "ci95": [
    0.117,
    0.267
   ]
  },
  "pass_a_40min": true,
  "pass_a_3h": false,
  "pass_d_vs_31pct": true,
  "v1_reference": {
   "pattern_40min": 0.42,
   "pattern_3h": 0.88,
   "false_alarm": 0.31
  }
 },
 "n=96": {
  "pattern_40min": {
   "rate": 0.749,
   "n": 183,
   "ci95": [
    0.681,
    0.806
   ]
  },
  "pattern_3h": {
   "rate": 0.836,
   "n": 183,
   "ci95": [
    0.776,
    0.883
   ]
  },
  "false_alarm_clean": {
   "rate": 0.29,
   "n": 100,
   "ci95": [
    0.21,
    0.385
   ]
  },
  "pass_a_40min": true,
  "pass_a_3h": false,
  "pass_d_vs_31pct": true,
  "v1_reference": {
   "pattern_40min": 0.42,
   "pattern_3h": 0.88,
   "false_alarm": 0.31
  }
 },
 "n=144": {
  "pattern_40min": {
   "rate": 0.699,
   "n": 183,
   "ci95": [
    0.629,
    0.761
   ]
  },
  "pattern_3h": {
   "rate": 0.803,
   "n": 183,
   "ci95": [
    0.74,
    0.854
   ]
  },
  "false_alarm_clean": {
   "rate": 0.27,
   "n": 100,
   "ci95": [
    0.193,
    0.364
   ]
  },
  "pass_a_40min": true,
  "pass_a_3h": false,
  "pass_d_vs_31pct": true,
  "v1_reference": {
   "pattern_40min": 0.42,
   "pattern_3h": 0.88,
   "false_alarm": 0.31
  }
 },
 "latency": {
  "n=48": {
   "batches": 121,
   "batch_size": 8,
   "median_batch_s": 9.74,
   "per_agent_s": 1.22,
   "mean_out_tokens": 84.4
  },
  "n=96": {
   "batches": 129,
   "batch_size": 8,
   "median_batch_s": 11.36,
   "per_agent_s": 1.42,
   "mean_out_tokens": 85.9
  },
  "n=144": {
   "batches": 132,
   "batch_size": 8,
   "median_batch_s": 12.75,
   "per_agent_s": 1.59,
   "mean_out_tokens": 86.9
  }
 }
}
```

