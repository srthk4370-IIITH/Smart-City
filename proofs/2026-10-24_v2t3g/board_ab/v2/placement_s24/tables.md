# v2 placement study on the QIDK NPU (features_v2 prompts, 12 h history)


## Window 48 x 5 min (4 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 50 | 79 | 79 | 81 | 84 | 83 |
| spike | 76 | 76 | 76 | 71 | 76 | 71 |
| dip | 86 | 86 | 93 | 86 | 93 | 79 |
| step_increase | 90 | 86 | 95 | 90 | 90 | 90 |
| step_decrease | 86 | 93 | 93 | 100 | 100 | 93 |
| gradual_increase | 10 | 95 | 86 | 90 | 90 | 95 |
| gradual_decrease | 43 | 100 | 100 | 100 | 93 | 100 |
| exponential_increase | 95 | 95 | 71 | 67 | 67 | 71 |
| oscillation | 0 | 29 | 36 | 71 | 86 | 86 |
| flatline | 19 | 86 | 95 | 95 | 95 | 95 |
| erratic | 5 | 43 | 43 | 48 | 62 | 57 |

clean windows: false alarm (status != normal) 22.0% (n=100), any flag 29.0%; v1 agent: 31%

## Window 96 x 5 min (8 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 48 | 76 | 79 | 80 | 85 | 81 |
| spike | 86 | 81 | 81 | 86 | 95 | 71 |
| dip | 79 | 86 | 79 | 79 | 86 | 86 |
| step_increase | 76 | 86 | 90 | 86 | 95 | 90 |
| step_decrease | 86 | 86 | 93 | 93 | 86 | 86 |
| gradual_increase | 5 | 86 | 81 | 67 | 76 | 76 |
| gradual_decrease | 36 | 100 | 100 | 100 | 100 | 86 |
| exponential_increase | 81 | 90 | 76 | 71 | 71 | 71 |
| oscillation | 0 | 29 | 36 | 79 | 79 | 86 |
| flatline | 24 | 86 | 100 | 100 | 100 | 100 |
| erratic | 14 | 33 | 52 | 52 | 67 | 67 |

clean windows: false alarm (status != normal) 27.0% (n=100), any flag 42.0%; v1 agent: 31%

## Window 144 x 5 min (12 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 41 | 70 | 75 | 76 | 78 | 78 |
| spike | 52 | 57 | 67 | 67 | 86 | 67 |
| dip | 64 | 64 | 64 | 64 | 71 | 64 |
| step_increase | 67 | 81 | 86 | 86 | 86 | 86 |
| step_decrease | 79 | 86 | 93 | 93 | 93 | 86 |
| gradual_increase | 10 | 67 | 62 | 67 | 67 | 71 |
| gradual_decrease | 43 | 93 | 100 | 100 | 100 | 93 |
| exponential_increase | 71 | 81 | 67 | 52 | 57 | 62 |
| oscillation | 0 | 21 | 50 | 79 | 71 | 79 |
| flatline | 19 | 100 | 100 | 100 | 95 | 100 |
| erratic | 10 | 48 | 62 | 62 | 62 | 71 |

clean windows: false alarm (status != normal) 26.0% (n=100), any flag 50.0%; v1 agent: 31%

## Acceptance

```
{
 "n=48": {
  "pattern_40min": {
   "rate": 0.791,
   "n": 182,
   "ci95": [
    0.726,
    0.844
   ]
  },
  "pattern_3h": {
   "rate": 0.83,
   "n": 182,
   "ci95": [
    0.768,
    0.877
   ]
  },
  "false_alarm_clean": {
   "rate": 0.22,
   "n": 100,
   "ci95": [
    0.15,
    0.311
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
   "rate": 0.764,
   "n": 182,
   "ci95": [
    0.697,
    0.82
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
 "n=144": {
  "pattern_40min": {
   "rate": 0.703,
   "n": 182,
   "ci95": [
    0.633,
    0.765
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
   "rate": 0.26,
   "n": 100,
   "ci95": [
    0.184,
    0.354
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
   "batches": 120,
   "batch_size": 8,
   "median_batch_s": 9.44,
   "per_agent_s": 1.18,
   "mean_out_tokens": 81.7
  },
  "n=96": {
   "batches": 117,
   "batch_size": 8,
   "median_batch_s": 11.01,
   "per_agent_s": 1.38,
   "mean_out_tokens": 83.2
  },
  "n=144": {
   "batches": 123,
   "batch_size": 8,
   "median_batch_s": 12.39,
   "per_agent_s": 1.55,
   "mean_out_tokens": 84.8
  }
 }
}
```

