# v2 placement study on the QIDK NPU (features_v2 prompts, 12 h history)


## Window 48 x 5 min (4 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 50 | 79 | 83 | 84 | 85 | 84 |
| spike | 76 | 81 | 81 | 76 | 76 | 76 |
| dip | 79 | 93 | 86 | 86 | 93 | 71 |
| step_increase | 86 | 90 | 95 | 90 | 90 | 90 |
| step_decrease | 86 | 93 | 100 | 100 | 100 | 93 |
| gradual_increase | 10 | 76 | 86 | 90 | 86 | 90 |
| gradual_decrease | 43 | 100 | 100 | 93 | 93 | 93 |
| exponential_increase | 90 | 95 | 86 | 86 | 81 | 86 |
| oscillation | 0 | 21 | 36 | 71 | 86 | 86 |
| flatline | 19 | 86 | 100 | 100 | 95 | 95 |
| erratic | 14 | 52 | 57 | 52 | 62 | 57 |

clean windows: false alarm (status != normal) 19.0% (n=100), any flag 29.0%; v1 agent: 31%

## Window 96 x 5 min (8 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 46 | 78 | 80 | 82 | 85 | 81 |
| spike | 86 | 81 | 81 | 86 | 90 | 71 |
| dip | 71 | 86 | 86 | 86 | 86 | 86 |
| step_increase | 76 | 86 | 86 | 86 | 90 | 90 |
| step_decrease | 86 | 93 | 93 | 93 | 100 | 93 |
| gradual_increase | 0 | 76 | 76 | 62 | 67 | 67 |
| gradual_decrease | 21 | 100 | 100 | 100 | 100 | 86 |
| exponential_increase | 81 | 90 | 90 | 76 | 90 | 86 |
| oscillation | 0 | 21 | 36 | 71 | 64 | 71 |
| flatline | 19 | 90 | 100 | 100 | 100 | 100 |
| erratic | 19 | 52 | 52 | 71 | 67 | 62 |

clean windows: false alarm (status != normal) 18.0% (n=100), any flag 28.0%; v1 agent: 31%

## Window 144 x 5 min (12 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 41 | 73 | 73 | 76 | 80 | 76 |
| spike | 52 | 52 | 62 | 67 | 71 | 57 |
| dip | 57 | 71 | 64 | 64 | 64 | 64 |
| step_increase | 67 | 86 | 86 | 86 | 86 | 86 |
| step_decrease | 79 | 86 | 86 | 93 | 100 | 93 |
| gradual_increase | 0 | 71 | 57 | 62 | 62 | 62 |
| gradual_decrease | 36 | 100 | 100 | 100 | 100 | 86 |
| exponential_increase | 76 | 86 | 76 | 62 | 76 | 76 |
| oscillation | 0 | 14 | 43 | 71 | 71 | 71 |
| flatline | 33 | 100 | 100 | 100 | 100 | 100 |
| erratic | 14 | 57 | 57 | 62 | 71 | 71 |

clean windows: false alarm (status != normal) 21.0% (n=100), any flag 38.0%; v1 agent: 31%

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
   "rate": 0.835,
   "n": 182,
   "ci95": [
    0.774,
    0.882
   ]
  },
  "false_alarm_clean": {
   "rate": 0.19,
   "n": 100,
   "ci95": [
    0.125,
    0.278
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
   "rate": 0.808,
   "n": 182,
   "ci95": [
    0.744,
    0.858
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
 "n=144": {
  "pattern_40min": {
   "rate": 0.731,
   "n": 182,
   "ci95": [
    0.662,
    0.79
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
   "rate": 0.21,
   "n": 100,
   "ci95": [
    0.142,
    0.3
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
   "batches": 122,
   "batch_size": 8,
   "median_batch_s": 9.41,
   "per_agent_s": 1.18,
   "mean_out_tokens": 80.9
  },
  "n=96": {
   "batches": 121,
   "batch_size": 8,
   "median_batch_s": 10.91,
   "per_agent_s": 1.36,
   "mean_out_tokens": 81.9
  },
  "n=144": {
   "batches": 129,
   "batch_size": 8,
   "median_batch_s": 12.3,
   "per_agent_s": 1.54,
   "mean_out_tokens": 83.3
  }
 }
}
```

