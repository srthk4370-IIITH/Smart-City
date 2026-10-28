# v2 placement study on the QIDK NPU (features_v2 prompts, 12 h history)


## Window 48 x 5 min (4 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 50 | 80 | 79 | 82 | 85 | 83 |
| spike | 81 | 81 | 76 | 81 | 86 | 76 |
| dip | 86 | 86 | 86 | 86 | 93 | 79 |
| step_increase | 86 | 86 | 95 | 90 | 90 | 90 |
| step_decrease | 86 | 93 | 93 | 93 | 93 | 86 |
| gradual_increase | 10 | 95 | 86 | 90 | 90 | 95 |
| gradual_decrease | 43 | 100 | 100 | 100 | 100 | 100 |
| exponential_increase | 95 | 95 | 76 | 67 | 67 | 71 |
| oscillation | 0 | 29 | 36 | 71 | 86 | 86 |
| flatline | 19 | 86 | 95 | 100 | 95 | 95 |
| erratic | 5 | 43 | 43 | 52 | 57 | 57 |

clean windows: false alarm (status != normal) 20.0% (n=100), any flag 32.0%; v1 agent: 31%

## Window 96 x 5 min (8 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 48 | 76 | 78 | 79 | 85 | 81 |
| spike | 86 | 81 | 81 | 86 | 90 | 71 |
| dip | 79 | 86 | 79 | 79 | 86 | 86 |
| step_increase | 76 | 81 | 86 | 81 | 90 | 86 |
| step_decrease | 86 | 86 | 93 | 93 | 93 | 93 |
| gradual_increase | 5 | 86 | 76 | 57 | 76 | 76 |
| gradual_decrease | 29 | 93 | 93 | 93 | 93 | 79 |
| exponential_increase | 81 | 90 | 76 | 71 | 71 | 71 |
| oscillation | 0 | 29 | 36 | 79 | 79 | 86 |
| flatline | 24 | 86 | 100 | 100 | 100 | 95 |
| erratic | 14 | 38 | 57 | 62 | 71 | 71 |

clean windows: false alarm (status != normal) 28.0% (n=100), any flag 42.0%; v1 agent: 31%

## Window 144 x 5 min (12 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 41 | 72 | 74 | 75 | 78 | 78 |
| spike | 52 | 57 | 67 | 62 | 86 | 62 |
| dip | 64 | 71 | 64 | 64 | 71 | 64 |
| step_increase | 67 | 76 | 81 | 86 | 86 | 86 |
| step_decrease | 79 | 86 | 93 | 86 | 93 | 86 |
| gradual_increase | 10 | 76 | 67 | 67 | 67 | 71 |
| gradual_decrease | 43 | 93 | 93 | 100 | 100 | 93 |
| exponential_increase | 71 | 81 | 67 | 52 | 52 | 62 |
| oscillation | 0 | 21 | 50 | 79 | 71 | 79 |
| flatline | 24 | 100 | 100 | 100 | 95 | 100 |
| erratic | 10 | 52 | 62 | 62 | 62 | 76 |

clean windows: false alarm (status != normal) 26.0% (n=100), any flag 50.0%; v1 agent: 31%

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
   "rate": 0.83,
   "n": 182,
   "ci95": [
    0.768,
    0.877
   ]
  },
  "false_alarm_clean": {
   "rate": 0.2,
   "n": 100,
   "ci95": [
    0.133,
    0.289
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
   "rate": 0.758,
   "n": 182,
   "ci95": [
    0.691,
    0.815
   ]
  },
  "pattern_3h": {
   "rate": 0.808,
   "n": 182,
   "ci95": [
    0.744,
    0.858
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
   "batches": 132,
   "batch_size": 8,
   "median_batch_s": 10.26,
   "per_agent_s": 1.28,
   "mean_out_tokens": 82.2
  },
  "n=96": {
   "batches": 124,
   "batch_size": 8,
   "median_batch_s": 11.8,
   "per_agent_s": 1.48,
   "mean_out_tokens": 82.8
  },
  "n=144": {
   "batches": 123,
   "batch_size": 8,
   "median_batch_s": 13.26,
   "per_agent_s": 1.66,
   "mean_out_tokens": 84.7
  }
 }
}
```

