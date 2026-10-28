# v2 placement study on the QIDK NPU (features_v2 prompts, 12 h history)


## Window 48 x 5 min (4 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 50 | 80 | 81 | 83 | 87 | 85 |
| spike | 81 | 81 | 81 | 81 | 86 | 76 |
| dip | 79 | 93 | 86 | 86 | 93 | 79 |
| step_increase | 86 | 86 | 95 | 90 | 90 | 90 |
| step_decrease | 86 | 93 | 93 | 100 | 100 | 93 |
| gradual_increase | 10 | 86 | 86 | 90 | 90 | 95 |
| gradual_decrease | 43 | 100 | 100 | 100 | 100 | 100 |
| exponential_increase | 90 | 95 | 81 | 71 | 81 | 86 |
| oscillation | 0 | 21 | 36 | 71 | 86 | 86 |
| flatline | 19 | 86 | 95 | 95 | 95 | 95 |
| erratic | 10 | 52 | 52 | 52 | 62 | 52 |

clean windows: false alarm (status != normal) 18.0% (n=100), any flag 30.0%; v1 agent: 31%

## Window 96 x 5 min (8 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 47 | 78 | 80 | 82 | 86 | 81 |
| spike | 86 | 81 | 81 | 86 | 95 | 71 |
| dip | 71 | 86 | 79 | 79 | 86 | 86 |
| step_increase | 76 | 81 | 90 | 86 | 95 | 90 |
| step_decrease | 79 | 86 | 93 | 93 | 93 | 86 |
| gradual_increase | 5 | 81 | 81 | 67 | 71 | 76 |
| gradual_decrease | 21 | 100 | 100 | 100 | 100 | 86 |
| exponential_increase | 81 | 90 | 76 | 76 | 76 | 71 |
| oscillation | 0 | 29 | 36 | 71 | 71 | 79 |
| flatline | 24 | 86 | 100 | 100 | 100 | 100 |
| erratic | 19 | 57 | 57 | 71 | 76 | 71 |

clean windows: false alarm (status != normal) 29.0% (n=100), any flag 43.0%; v1 agent: 31%

## Window 144 x 5 min (12 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 40 | 74 | 75 | 78 | 80 | 76 |
| spike | 52 | 48 | 62 | 67 | 81 | 62 |
| dip | 57 | 71 | 64 | 64 | 71 | 64 |
| step_increase | 67 | 86 | 86 | 90 | 81 | 90 |
| step_decrease | 79 | 86 | 93 | 93 | 93 | 86 |
| gradual_increase | 10 | 71 | 67 | 67 | 67 | 62 |
| gradual_decrease | 36 | 100 | 100 | 100 | 100 | 93 |
| exponential_increase | 71 | 81 | 71 | 52 | 67 | 62 |
| oscillation | 0 | 29 | 43 | 79 | 71 | 71 |
| flatline | 24 | 100 | 100 | 100 | 100 | 100 |
| erratic | 10 | 62 | 62 | 71 | 76 | 76 |

clean windows: false alarm (status != normal) 24.0% (n=100), any flag 50.0%; v1 agent: 31%

## Acceptance

```
{
 "n=48": {
  "pattern_40min": {
   "rate": 0.797,
   "n": 182,
   "ci95": [
    0.732,
    0.849
   ]
  },
  "pattern_3h": {
   "rate": 0.846,
   "n": 182,
   "ci95": [
    0.787,
    0.891
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
   "rate": 0.78,
   "n": 182,
   "ci95": [
    0.715,
    0.834
   ]
  },
  "pattern_3h": {
   "rate": 0.813,
   "n": 182,
   "ci95": [
    0.75,
    0.863
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
   "rate": 0.736,
   "n": 182,
   "ci95": [
    0.668,
    0.795
   ]
  },
  "pattern_3h": {
   "rate": 0.764,
   "n": 182,
   "ci95": [
    0.697,
    0.82
   ]
  },
  "false_alarm_clean": {
   "rate": 0.24,
   "n": 100,
   "ci95": [
    0.167,
    0.332
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
   "median_batch_s": 9.19,
   "per_agent_s": 1.15,
   "mean_out_tokens": 82.8
  },
  "n=96": {
   "batches": 119,
   "batch_size": 8,
   "median_batch_s": 10.8,
   "per_agent_s": 1.35,
   "mean_out_tokens": 83.9
  },
  "n=144": {
   "batches": 126,
   "batch_size": 8,
   "median_batch_s": 12.15,
   "per_agent_s": 1.52,
   "mean_out_tokens": 85.8
  }
 }
}
```

