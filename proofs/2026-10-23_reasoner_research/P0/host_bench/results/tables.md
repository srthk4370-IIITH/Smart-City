### Gates

| model | G1 groundedness & safety | ungrounded-number answers | invented ids | actuation | injection followed (of 3) | 'not available' correct | refusals correct | G2 deployability | est. NPU report p50 / p90 (s) |
|---|---|---|---|---|---|---|---|---|---|
| v2_3b_q4_0 | **FAIL** | 0.5% | 0.0% | 1 | 3 | 78% | 29% | **PASS** | 8.5 / 16.4 |
| llama32_3b_base_q4_0 | **FAIL** | 0.0% | 0.0% | 0 | 3 | 89% | 71% | **FAIL** | 24.6 / 32.5 |
| qwen35_4b_q4_0 | **FAIL** | 8.2% | 0.0% | 1 | 2 | 89% | 100% | **FAIL** | 41.5 / 47.4 |
| qwen35_2b_q4_0 | **FAIL** | 23.2% | 0.5% | 0 | 1 | 78% | 100% | **CONDITIONAL** | 14.2 / 16.7 |

### Weighted score (45 reasoning / 25 tools / 20 data / 10 secondary), 95% bootstrap CI

| model | 1. cross-domain reasoning (45%) | 2. tools (25%) | 3. understanding data (20%) | 4. secondary (10%) | **weighted total** |
|---|---|---|---|---|---|
| qwen35_4b_q4_0 | 0.80 [0.75, 0.84] | 0.78 [0.73, 0.84] | 0.81 [0.73, 0.87] | 0.79 [0.71, 0.87] | **0.79 [0.77, 0.82]** |
| qwen35_2b_q4_0 | 0.64 [0.59, 0.68] | 0.66 [0.59, 0.72] | 0.67 [0.59, 0.74] | 0.57 [0.47, 0.69] | **0.64 [0.61, 0.67]** |
| llama32_3b_base_q4_0 | 0.36 [0.31, 0.41] | 0.55 [0.49, 0.62] | 0.50 [0.40, 0.60] | 0.32 [0.28, 0.38] | **0.43 [0.40, 0.47]** |
| v2_3b_q4_0 | 0.22 [0.18, 0.26] | 0.65 [0.60, 0.70] | 0.43 [0.34, 0.53] | 0.25 [0.23, 0.28] | **0.37 [0.34, 0.40]** |

### 1. Cross-domain reasoning: components and families

| model | report parsed | label acc. | label | keywords | suspects | severity | checklist | evidence | checklist recall | forbidden-action reports |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v2_3b_q4_0 | 0.80 | 0.21 | 0.23 | 0.13 | 0.39 | 0.36 | 0.09 | 0.13 | 0.09 | 0.01 |
| llama32_3b_base_q4_0 | 0.93 | 0.28 | 0.31 | 0.37 | 0.48 | 0.34 | 0.28 | 0.50 | 0.35 | 0.06 |
| qwen35_4b_q4_0 | 1.00 | 0.67 | 0.74 | 0.92 | 0.71 | 0.79 | 0.78 | 0.98 | 0.92 | 0.17 |
| qwen35_2b_q4_0 | 0.96 | 0.45 | 0.53 | 0.80 | 0.35 | 0.63 | 0.74 | 0.96 | 0.85 | 0.17 |

| family | v2_3b_q4_0 | llama32_3b_base_q4_0 | qwen35_4b_q4_0 | qwen35_2b_q4_0 |
|---|---|---|---|---|
| agent_missed_event | 0.17 | 0.49 | 0.67 | 0.63 |
| coincidence | 0.52 | 0.59 | 0.88 | 0.64 |
| contradictory_agents | 0.00 | 0.00 | 1.00 | 0.53 |
| daytime_demand | 0.33 | 0.79 | 0.85 | 0.85 |
| heatwave_cooling_load | 0.15 | 0.37 | 0.94 | 0.70 |
| impossible_reading | 0.10 | 0.30 | 0.70 | 0.46 |
| irrelevant_data | 0.30 | 0.80 | 0.93 | 0.74 |
| lone_alarm_contradicted | 0.08 | 0.36 | 0.67 | 0.65 |
| memory_fault_held | 0.12 | 0.00 | 1.00 | 0.32 |
| memory_recurring_fault | 0.30 | 0.22 | 0.87 | 0.71 |
| memory_recurring_leak | 0.40 | 0.53 | 0.78 | 0.60 |
| memory_weekly_pattern | 0.61 | 0.65 | 0.93 | 0.76 |
| missing_stale_sensor | 0.00 | 0.15 | 0.75 | 0.69 |
| needs_fetch | 0.02 | 0.09 | 0.84 | 0.76 |
| night_leak | 0.35 | 0.46 | 0.85 | 0.84 |
| normal_operation | 0.11 | 0.08 | 0.67 | 0.29 |
| occupancy_load | 0.66 | 0.53 | 0.90 | 0.77 |
| pollution_ingress | 0.21 | 0.48 | 0.96 | 0.85 |
| power_quality | 0.00 | 0.40 | 0.85 | 0.57 |
| prompt_injection | 0.00 | 0.00 | 0.33 | 0.52 |
| realworld_slice | 0.21 | 0.26 | 0.65 | 0.51 |
| recheck_drift | 0.00 | 0.47 | 1.00 | 0.65 |
| recheck_escalating | 0.23 | 0.48 | 0.85 | 0.65 |
| recheck_resolved | 0.68 | 0.41 | 1.00 | 0.74 |
| stuck_sensor | 0.17 | 0.31 | 0.95 | 0.69 |
| ventilation_failure | 0.17 | 0.48 | 0.88 | 0.50 |
| water_quality | 0.55 | 0.44 | 0.60 | 0.83 |
| water_supply | 0.34 | 0.22 | 0.82 | 0.68 |

### 2. Tools

| model | first-call selection | argument exec-match | fetched when needed (9 cases) | no call when not needed (118) | tool-error rate | mean calls / report |
|---|---|---|---|---|---|---|
| v2_3b_q4_0 | 0.88 | 0.19 | 0.50 | 1.00 | 0.49 | 0.2 |
| llama32_3b_base_q4_0 | 0.72 | 0.23 | 0.08 | 0.38 | 0.56 | 2.8 |
| qwen35_4b_q4_0 | 0.95 | 0.57 | 1.00 | 0.00 | 0.11 | 6.2 |
| qwen35_2b_q4_0 | 0.83 | 0.27 | 0.00 | 1.00 | 0.17 | 0.0 |

| argument exec-match by category | v2_3b_q4_0 | llama32_3b_base_q4_0 | qwen35_4b_q4_0 | qwen35_2b_q4_0 |
|---|---|---|---|---|
| action_history | 0.00 | 0.00 | 0.25 | 0.00 |
| count | 0.00 | 0.13 | 0.67 | 0.27 |
| faults | 0.00 | 0.00 | 0.50 | 0.38 |
| find | 0.20 | 0.20 | 0.20 | 0.00 |
| history | 0.17 | 0.17 | 0.83 | 0.00 |
| lookup | 1.00 | 1.00 | 1.00 | 1.00 |
| multistep | 0.00 | 0.00 | 0.19 | 0.06 |
| offline | 1.00 | 1.00 | 1.00 | 1.00 |
| unanswerable | 0.33 | 0.33 | 0.67 | 0.00 |

### 3. Understanding the data

| model | chat final answer exact | data-reading exact (15) | ungrounded-number answers |
|---|---|---|---|
| v2_3b_q4_0 | 0.16 | 0.47 | 0.01 |
| llama32_3b_base_q4_0 | 0.21 | 0.60 | 0.00 |
| qwen35_4b_q4_0 | 0.64 | 0.93 | 0.04 |
| qwen35_2b_q4_0 | 0.34 | 0.93 | 0.06 |

| answer exact by category | v2_3b_q4_0 | llama32_3b_base_q4_0 | qwen35_4b_q4_0 | qwen35_2b_q4_0 |
|---|---|---|---|---|
| action_history | 0.00 | 0.00 | 0.25 | 0.00 |
| count | 0.07 | 0.13 | 0.73 | 0.33 |
| faults | 0.00 | 0.00 | 0.75 | 0.50 |
| find | 0.00 | 0.40 | 0.40 | 0.20 |
| history | 0.17 | 0.00 | 1.00 | 0.17 |
| lookup | 0.20 | 0.20 | 0.60 | 0.60 |
| multistep | 0.00 | 0.00 | 0.12 | 0.12 |
| offline | 1.00 | 1.00 | 1.00 | 1.00 |
| refusal | 0.29 | 0.71 | 1.00 | 1.00 |
| unanswerable | 0.75 | 1.00 | 1.00 | 0.50 |

### 4. Secondary

| model | 1 - Brier | ECE | mean confidence | consistent (3 reruns + 2 paraphrases) | reruns only | paraphrases only | communication rubric |
|---|---|---|---|---|---|---|---|
| v2_3b_q4_0 | 0.31 | 0.47 | 0.78 | 0.00 | 0.73 | 0.07 | 0.45 |
| llama32_3b_base_q4_0 | 0.30 | 0.41 | 0.60 | 0.07 | 0.33 | 0.13 | 0.61 |
| qwen35_4b_q4_0 | 0.72 | 0.24 | 0.90 | 0.67 | 1.00 | 0.67 | 0.99 |
| qwen35_2b_q4_0 | 0.60 | 0.36 | 0.82 | 0.38 | 1.00 | 0.38 | 0.73 |

### Latency and tokens (host RTX 4050, llama.cpp b11815 CUDA; NPU = estimate)

| model | Q4 file GB | host report p50 (s) | prefill tokens / report (after prefix cache) | decode tokens / report | est. NPU report p50 (s) | chat host p50 (s) | chat decode tokens |
|---|---|---|---|---|---|---|---|
| v2_3b_q4_0 | 2.80 | 5.0 | 77 | 198 | 8.5 | 4.8 | 256 |
| llama32_3b_base_q4_0 | 1.92 | 11.9 | 1165 | 643 | 24.6 | 3.0 | 186 |
| qwen35_4b_q4_0 | 2.61 | 18.3 | 2373 | 806 | 41.5 | 2.3 | 148 |
| qwen35_2b_q4_0 | 1.24 | 6.4 | 688 | 605 | 14.2 | 1.4 | 156 |

### Paired differences (same items resampled; 1000 bootstraps)

| A - B | reasoning diff [95% CI] | P(diff <= 0) | weighted total diff [95% CI] | P(diff <= 0) |
|---|---|---|---|---|
| v2_3b_q4_0 - llama32_3b_base_q4_0 | -0.140 [-0.196, -0.085] | 1.000 | -0.061 [-0.095, -0.025] | 1.000 |
| v2_3b_q4_0 - qwen35_4b_q4_0 | -0.581 [-0.634, -0.527] | 1.000 | -0.424 [-0.461, -0.389] | 1.000 |
| v2_3b_q4_0 - qwen35_2b_q4_0 | -0.422 [-0.471, -0.371] | 1.000 | -0.271 [-0.309, -0.233] | 1.000 |
| llama32_3b_base_q4_0 - qwen35_4b_q4_0 | -0.441 [-0.507, -0.379] | 1.000 | -0.363 [-0.403, -0.325] | 1.000 |
| llama32_3b_base_q4_0 - qwen35_2b_q4_0 | -0.282 [-0.333, -0.231] | 1.000 | -0.212 [-0.249, -0.175] | 1.000 |
| qwen35_4b_q4_0 - qwen35_2b_q4_0 | 0.160 [0.107, 0.216] | 0.000 | 0.155 [0.117, 0.192] | 0.000 |
