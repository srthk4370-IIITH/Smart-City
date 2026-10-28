# Host Q4_0 GGUF eval: v2 vs 3d (laptop CPU llama.cpp), and v2 host vs device

Rows available: v2 16, 3d 0, device_v2 3976


## Placement seed 24, fixed window (pattern accuracy on events; clean d=0: false alarm = status != normal)

| d (min) | n | metric | v2 host | 3d host | McNemar (only v2 / only 3d, p) | v2 device |
|---|---|---|---|---|---|---|
| 18 (90) | 144 | pattern | 100.0 [68-100] (8/8) | - | - | 75.3 [68-81] (137/182) |
| 18 (90) | 144 | JSON valid | 100.0 [68-100] (8/8) | - | - | 98.4 [95-99] (179/182) |
| 36 (180) | 144 | pattern | 87.5 [53-98] (7/8) | - | - | 77.5 [71-83] (141/182) |
| 36 (180) | 144 | JSON valid | 100.0 [68-100] (8/8) | - | - | 98.9 [96-100] (180/182) |

## App chain per stage (early call d=8 at 4 h; refine d=18 / d=36 at the policy's window; spike/dip keep rule)

20min = the d=4 (n=48) call alone (no chain). A stage is reported only for cases whose needed rows exist.

| policy | stage | v2 host | 3d host | McNemar (only v2 / only 3d, p) | v2 device | v2 host vs device: same correctness |
|---|---|---|---|---|---|---|

Per-pattern 3 h (WindowN app chain):

| pattern | device_v2 |
|---|---|
| dip | 11/14 |
| erratic | 14/21 |
| exponential_increase | 15/21 |
| flatline | 21/21 |
| gradual_decrease | 14/14 |
| gradual_increase | 21/21 |
| oscillation | 11/14 |
| spike | 18/21 |
| step_decrease | 13/14 |
| step_increase | 19/21 |

## v2 host (laptop CPU ggml) vs v2 device (QIDK htpd), same rows (a = host, b = device)

```
{
 "placement_rows": {
  "n": 16,
  "same_pattern": {
   "rate": 1.0,
   "k": 16,
   "n": 16,
   "ci95": [
    0.806,
    1.0
   ]
  },
  "same_pattern_status": {
   "rate": 1.0,
   "k": 16,
   "n": 16,
   "ci95": [
    0.806,
    1.0
   ]
  },
  "same_pattern_correctness_events": {
   "rate": 1.0,
   "k": 16,
   "n": 16,
   "ci95": [
    0.806,
    1.0
   ]
  },
  "identical_answer_text": {
   "rate": 0.875,
   "k": 14,
   "n": 16,
   "ci95": [
    0.64,
    0.965
   ]
  },
  "pattern_acc_events_host_vs_device": {
   "n": 16,
   "a": {
    "rate": 0.938,
    "k": 15,
    "n": 16,
    "ci95": [
     0.717,
     0.989
    ]
   },
   "b": {
    "rate": 0.938,
    "k": 15,
    "n": 16,
    "ci95": [
     0.717,
     0.989
    ]
   },
   "only_a": 0,
   "only_b": 0,
   "p": 1.0
  }
 }
}
```

