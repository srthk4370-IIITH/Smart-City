# v2 placement study on the QIDK NPU (features_v2 prompts, 12 h history)


## Window 48 x 5 min (4 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 48 | 82 | 84 | 85 | 89 | 89 |
| spike | 75 | 81 | 80 | 73 | 81 | 81 |
| dip | 75 | 100 | 75 | 75 | 88 | 62 |
| step_increase | 77 | 92 | 94 | 94 | 100 | 93 |
| step_decrease | 100 | 100 | 100 | 100 | 100 | 100 |
| gradual_increase | 6 | 88 | 94 | 89 | 89 | 100 |
| gradual_decrease | 36 | 100 | 100 | 100 | 100 | 100 |
| exponential_increase | 90 | 95 | 85 | 85 | 79 | 84 |
| oscillation | 0 | 18 | 33 | 75 | 82 | 91 |
| flatline | 22 | 83 | 100 | 100 | 100 | 100 |
| erratic | 15 | 54 | 62 | 54 | 73 | 64 |

clean windows: false alarm (status != normal) 17.1% (n=76), any flag 28.9%; v1 agent: 31%

## Window 96 x 5 min (8 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 43 | 78 | 84 | 85 | 85 | 85 |
| spike | 83 | 83 | 75 | 83 | 93 | 79 |
| dip | 78 | 89 | 91 | 91 | 78 | 89 |
| step_increase | 62 | 92 | 100 | 92 | 93 | 86 |
| step_decrease | 85 | 92 | 91 | 91 | 92 | 100 |
| gradual_increase | 0 | 73 | 73 | 60 | 62 | 69 |
| gradual_decrease | 15 | 100 | 100 | 100 | 100 | 92 |
| exponential_increase | 92 | 92 | 87 | 93 | 93 | 87 |
| oscillation | 0 | 25 | 33 | 67 | 62 | 88 |
| flatline | 19 | 88 | 100 | 100 | 100 | 100 |
| erratic | 17 | 44 | 60 | 67 | 69 | 69 |

clean windows: false alarm (status != normal) 15.3% (n=72), any flag 33.3%; v1 agent: 31%

## Window 144 x 5 min (12 h): pattern accuracy by readings since onset

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 44 | 74 | 76 | 79 | 77 | 75 |
| spike | 47 | 59 | 68 | 68 | 78 | 67 |
| dip | 70 | 80 | 80 | 90 | 70 | 70 |
| step_increase | 71 | 88 | 78 | 83 | 88 | 88 |
| step_decrease | 90 | 100 | 90 | 90 | 91 | 91 |
| gradual_increase | 0 | 62 | 46 | 46 | 31 | 31 |
| gradual_decrease | 40 | 100 | 100 | 100 | 100 | 90 |
| exponential_increase | 72 | 83 | 94 | 82 | 76 | 71 |
| oscillation | 0 | 20 | 25 | 62 | 64 | 73 |
| flatline | 29 | 93 | 100 | 100 | 100 | 100 |
| erratic | 19 | 56 | 67 | 73 | 71 | 71 |

clean windows: false alarm (status != normal) 22.5% (n=40), any flag 57.5%; v1 agent: 31%

## Acceptance

```
{
 "n=48": {
  "pattern_40min": {
   "rate": 0.815,
   "n": 135,
   "ci95": [
    0.741,
    0.871
   ]
  },
  "pattern_3h": {
   "rate": 0.886,
   "n": 132,
   "ci95": [
    0.821,
    0.93
   ]
  },
  "false_alarm_clean": {
   "rate": 0.171,
   "n": 76,
   "ci95": [
    0.103,
    0.271
   ]
  },
  "pass_a_40min": true,
  "pass_a_3h": true,
  "pass_d_vs_31pct": true,
  "v1_reference": {
   "pattern_40min": 0.42,
   "pattern_3h": 0.88,
   "false_alarm": 0.31
  }
 },
 "n=96": {
  "pattern_40min": {
   "rate": 0.783,
   "n": 129,
   "ci95": [
    0.704,
    0.845
   ]
  },
  "pattern_3h": {
   "rate": 0.847,
   "n": 131,
   "ci95": [
    0.776,
    0.899
   ]
  },
  "false_alarm_clean": {
   "rate": 0.153,
   "n": 72,
   "ci95": [
    0.088,
    0.253
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
   "rate": 0.741,
   "n": 135,
   "ci95": [
    0.661,
    0.807
   ]
  },
  "pattern_3h": {
   "rate": 0.752,
   "n": 137,
   "ci95": [
    0.673,
    0.817
   ]
  },
  "false_alarm_clean": {
   "rate": 0.225,
   "n": 40,
   "ci95": [
    0.123,
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
 "latency": {
  "n=48": {
   "batches": 97,
   "batch_size": 8,
   "median_batch_s": 9.49,
   "per_agent_s": 1.19,
   "mean_out_tokens": 83.1
  },
  "n=96": {
   "batches": 93,
   "batch_size": 8,
   "median_batch_s": 11.12,
   "per_agent_s": 1.39,
   "mean_out_tokens": 85.3
  },
  "n=144": {
   "batches": 92,
   "batch_size": 8,
   "median_batch_s": 12.57,
   "per_agent_s": 1.57,
   "mean_out_tokens": 86.3
  }
 }
}
```

