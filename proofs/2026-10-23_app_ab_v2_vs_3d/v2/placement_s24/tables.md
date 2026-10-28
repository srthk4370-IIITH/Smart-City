# v2 placement study on the QIDK NPU (features_v2 prompts, 12 h history)


## Window 48 x 5 min (4 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 50 | 79 | 78 | 82 | 84 | 82 |
| spike | 81 | 81 | 81 | 81 | 86 | 76 |
| dip | 86 | 86 | 86 | 86 | 93 | 79 |
| step_increase | 81 | 81 | 90 | 90 | 90 | 90 |
| step_decrease | 86 | 93 | 93 | 100 | 100 | 93 |
| gradual_increase | 5 | 90 | 81 | 86 | 86 | 90 |
| gradual_decrease | 43 | 100 | 100 | 100 | 100 | 100 |
| exponential_increase | 95 | 95 | 81 | 71 | 67 | 67 |
| oscillation | 0 | 29 | 29 | 64 | 79 | 79 |
| flatline | 19 | 86 | 95 | 95 | 95 | 95 |
| erratic | 5 | 43 | 43 | 52 | 57 | 57 |

clean windows: false alarm (status != normal) 18.0% (n=100), any flag 29.0%; v1 agent: 31%

## Window 96 x 5 min (8 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 48 | 74 | 78 | 79 | 84 | 80 |
| spike | 86 | 81 | 81 | 86 | 95 | 71 |
| dip | 79 | 79 | 79 | 71 | 79 | 86 |
| step_increase | 76 | 86 | 90 | 86 | 95 | 90 |
| step_decrease | 86 | 86 | 93 | 93 | 93 | 93 |
| gradual_increase | 5 | 81 | 76 | 67 | 71 | 67 |
| gradual_decrease | 36 | 100 | 100 | 100 | 100 | 86 |
| exponential_increase | 81 | 90 | 76 | 71 | 71 | 71 |
| oscillation | 0 | 21 | 29 | 79 | 79 | 86 |
| flatline | 24 | 81 | 90 | 90 | 95 | 95 |
| erratic | 14 | 33 | 57 | 52 | 67 | 67 |

clean windows: false alarm (status != normal) 28.0% (n=100), any flag 42.0%; v1 agent: 31%

## Window 144 x 5 min (12 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 41 | 72 | 74 | 75 | 78 | 78 |
| spike | 52 | 57 | 67 | 67 | 86 | 67 |
| dip | 64 | 71 | 64 | 64 | 64 | 64 |
| step_increase | 67 | 81 | 86 | 90 | 90 | 90 |
| step_decrease | 79 | 86 | 93 | 86 | 86 | 79 |
| gradual_increase | 10 | 76 | 67 | 67 | 71 | 71 |
| gradual_decrease | 43 | 100 | 100 | 100 | 100 | 93 |
| exponential_increase | 71 | 81 | 67 | 52 | 52 | 62 |
| oscillation | 0 | 14 | 50 | 79 | 71 | 79 |
| flatline | 19 | 100 | 100 | 100 | 95 | 100 |
| erratic | 10 | 48 | 52 | 57 | 62 | 71 |

clean windows: false alarm (status != normal) 27.0% (n=100), any flag 51.0%; v1 agent: 31%

## Acceptance

```
{
 "n=48": {
  "pattern_40min": {
   "rate": 0.786,
   "n": 182,
   "ci95": [
    0.721,
    0.839
   ]
  },
  "pattern_3h": {
   "rate": 0.819,
   "n": 182,
   "ci95": [
    0.756,
    0.868
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
   "rate": 0.742,
   "n": 182,
   "ci95": [
    0.674,
    0.8
   ]
  },
  "pattern_3h": {
   "rate": 0.802,
   "n": 182,
   "ci95": [
    0.738,
    0.854
   ]
  },
  "false_alarm_clean": {
   "rate": 0.28,
   "n": 100,
   "ci95": [
    0.201,
    0.375
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
   "rate": 0.72,
   "n": 182,
   "ci95": [
    0.651,
    0.78
   ]
  },
  "pattern_3h": {
   "rate": 0.775,
   "n": 182,
   "ci95": [
    0.709,
    0.829
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
   "batches": 118,
   "batch_size": 8,
   "median_batch_s": 10.12,
   "per_agent_s": 1.26,
   "mean_out_tokens": 81.8
  },
  "n=96": {
   "batches": 123,
   "batch_size": 8,
   "median_batch_s": 11.71,
   "per_agent_s": 1.46,
   "mean_out_tokens": 82.7
  },
  "n=144": {
   "batches": 129,
   "batch_size": 8,
   "median_batch_s": 13.21,
   "per_agent_s": 1.65,
   "mean_out_tokens": 84.6
  }
 }
}
```

